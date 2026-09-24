# region_prep.py
"""
One-time, offline. Fetch 3DEP elevation for a bbox, write a COG with overviews,
build the aim-view overview PNG, and write region.json.

Usage:
    python region_prep.py --id lassen_ca \
        --name "Lassen County, California" \
        --bbox -120.90 40.33 -120.50 40.78 \
        --epsg 32610

Resolution is picked automatically from the bbox (finest of 10/30/60 m whose grid
fits the budget) and the DEM is always fetched in memory-bounded slices; pass an
explicit --resolution only to override the planner. An order plate passes
--resolution and --out-root together (app/orderprep.py); a resolution off 10/30/60
is fetched from the 3DEP dynamic service at that cell size. The plan (grid, file
size, slice count) prints before anything is fetched.
"""
import os
import certifi
# Point OpenSSL at certifi BEFORE importing anything that pulls aiohttp (py3dep,
# pynhd). python.org Python on macOS ships no system CA bundle, so the USGS NHD
# service fails SSL verification otherwise -- and aiohttp captures its SSL config
# at import, so setting this after those imports is too late (concurrent requests
# race onto the empty default store).
os.environ.setdefault("SSL_CERT_FILE", certifi.where())
os.environ.setdefault("SSL_CERT_DIR", "")

import argparse, importlib, json, math, time
import numpy as np
import rasterio
from rasterio.enums import Resampling
from PIL import Image
# pandas / py3dep / pynhd are imported lazily inside the functions that fetch or
# bake: importing THIS module then only needs the core stack, so the pure-logic
# tests (plan_build, bake_hydro) run in CI without the ~200 MB fetch stack.

# ---- build planning: decide resolution, grid, and slicing BEFORE any fetch ------
# The 15.8 GB lesson (elko_bonneville): a corridor-scale bbox built one-shot holds
# the whole source + reprojection scratch + the NLCD tile merge in RAM at once and
# OOMs. The planner makes the cost visible up front; the slicer bounds the peak.
DEM_RES_CHOICES = (10, 30, 60)
GRID_BUDGET_MPX = 200      # auto-resolution ceiling for the projected DEM grid
SLICE_BUDGET_MPX = 40      # max Mpx fetched + warped at once (bounds peak RSS)
LANDCOVER_BUDGET_MPX = 60  # ceiling for the (uint8) landcover grid
GRID_INSET_M = 500.0       # grid sits inside fetched data: no reproject NaN fringe
# Probed 2026-09-24 against py3dep's dynamic 3DEP service: 4 m requested -> actual
# 3.25 x 3.47 m cells; 25 m -> 20.3 x 21.6 m. Off a static layer (DEM_RES_CHOICES)
# the service resamples from whatever it holds and returns cells ~15-20% finer than
# asked, and not square, so the requested resolution understates both the pixel
# count and the real fetch size.
DYNAMIC_OVERSAMPLE = 1.5
# The finest cell size a build accepts. The finest 3DEP layer is 1 m and orders
# never ask below it; 0.5 m leaves headroom and refuses a typo like 0.05.
MIN_RESOLUTION_M = 0.5


def _is_static(res):
    """True when py3dep serves `res` from its static 10/30/60 m tiles. This is
    py3dep.get_dem's own test, np.isclose(res, (10, 30, 60)) at numpy's default
    tolerances, so the plan's dynamic flag and the sources.json label never
    disagree with what was actually fetched."""
    return any(abs(res - r) <= 1e-8 + 1e-5 * r for r in DEM_RES_CHOICES)

def _densified_edge(bbox_4326, n=41):
    """Lon/lat points along all four bbox edges. Meridians and parallels curve in a
    projected CRS, so 4 corners under-bound a wide box; the densified ring doesn't."""
    w, s, e, n_ = bbox_4326
    t = np.linspace(0.0, 1.0, n)
    lons = np.concatenate([w + t*(e-w), w + t*(e-w), np.full(n, w), np.full(n, e)])
    lats = np.concatenate([np.full(n, s), np.full(n, n_), s + t*(n_-s), s + t*(n_-s)])
    return lons, lats

def projected_grid(bbox_4326, dst_crs, resolution_m):
    """The target grid for a bbox at a resolution: (width_px, height_px, transform),
    inset GRID_INSET_M so the grid sits strictly inside what a fetch returns, and
    snapped to the resolution."""
    from pyproj import Transformer
    from rasterio.transform import from_origin
    fwd = Transformer.from_crs("EPSG:4326", dst_crs, always_xy=True)
    xs, ys = fwd.transform(*_densified_edge(bbox_4326))
    minx, maxx = float(np.min(xs)) + GRID_INSET_M, float(np.max(xs)) - GRID_INSET_M
    miny, maxy = float(np.min(ys)) + GRID_INSET_M, float(np.max(ys)) - GRID_INSET_M
    minx = resolution_m * round(minx / resolution_m)
    miny = resolution_m * round(miny / resolution_m)
    w = int((maxx - minx) // resolution_m)
    h = int((maxy - miny) // resolution_m)
    return w, h, from_origin(minx, miny + h * resolution_m, resolution_m, resolution_m)

def slice_overlap_deg(resolution_m):
    """Longitude buffer added on each side of a slice's fetch bbox, in degrees. The
    original fixed 0.03 deg (~2.7 km) for 10 m and coarser; below 10 m it scales to
    ~300 cells, so a fine order plate a few km wide doesn't fetch mostly buffer."""
    if resolution_m >= 10:
        return 0.03
    return min(0.03, max(0.002, 300 * resolution_m / 111_320.0))

def plan_build(bbox_4326, dst_crs, resolution_m=None):
    """Everything main() needs to know before fetching: the DEM resolution (auto =
    finest of DEM_RES_CHOICES whose grid fits GRID_BUDGET_MPX; explicit overrides
    but is flagged when over budget), the slice count that keeps peak memory
    bounded, the landcover resolution, and honest size estimates. A resolution off
    DEM_RES_CHOICES is fetched from the dynamic service, which returns more cells
    than asked (DYNAMIC_OVERSAMPLE), so its slices and peak are sized for that."""
    auto = resolution_m is None
    if auto:
        resolution_m = DEM_RES_CHOICES[-1]
        for res in DEM_RES_CHOICES:
            w, h, _ = projected_grid(bbox_4326, dst_crs, res)
            if w * h <= GRID_BUDGET_MPX * 1e6:
                resolution_m = res
                break
    w, h, transform = projected_grid(bbox_4326, dst_crs, resolution_m)
    mpx = w * h / 1e6
    lc_res = 60
    for res in (30, 60):
        wl, hl, _ = projected_grid(bbox_4326, dst_crs, res)
        if wl * hl <= LANDCOVER_BUDGET_MPX * 1e6:
            lc_res = res
            break
    dynamic = not _is_static(resolution_m)
    fetch_mpx = mpx * DYNAMIC_OVERSAMPLE if dynamic else mpx
    n_slices = max(1, int(np.ceil(fetch_mpx / SLICE_BUDGET_MPX)))
    return {"resolution_m": resolution_m, "auto": auto, "dynamic": dynamic,
            "grid": (w, h), "transform": transform, "grid_mpx": mpx,
            "over_budget": mpx > GRID_BUDGET_MPX,
            "n_slices": n_slices,
            "landcover_resolution_m": lc_res,
            "est_dem_mb": mpx * 4,           # float32; terrain barely deflates
            "est_peak_gb": fetch_mpx / n_slices * 4 * 10 / 1024}

def _resolution_arg(value):
    """--resolution: 'auto' (None) or a finite number of metres, at least
    MIN_RESOLUTION_M. A static layer (10/30/60) comes back as the int it always
    was, so an explicit static build writes the same region.json and sources.json
    as before."""
    if value == "auto":
        return None
    try:
        res = float(value)
    except ValueError as ex:
        raise argparse.ArgumentTypeError(f"not a number: {value!r}") from ex
    if not math.isfinite(res) or not res >= MIN_RESOLUTION_M:
        raise argparse.ArgumentTypeError("resolution must be 'auto' or a number of "
                                         f"at least {MIN_RESOLUTION_M:g} m")
    return int(res) if res in DEM_RES_CHOICES else res

def _exterior_rings(geom):
    if geom.geom_type == "Polygon":
        return [list(geom.exterior.coords)]
    if geom.geom_type == "MultiPolygon":
        return [list(p.exterior.coords) for p in geom.geoms]
    return []

def _lines(geom):
    if geom.geom_type == "LineString":
        return [list(geom.coords)]
    if geom.geom_type == "MultiLineString":
        return [list(l.coords) for l in geom.geoms]
    return []

# NHD waterbody ftypes that are honestly "blue water" on a poster. Playa (361) is a
# dry alkali flat most of the year (red-team's top beauty finding: a basin plate came
# back carrying hundreds of km2 of fictional water), and SwampMarsh (466) / Ice (378)
# mislead the same way. LakePond (390) + Reservoir (436) stay.
#
# The finding named Honey Lake, which turns out to be the wrong example: NHD files it
# as LakePond, so it is drawn blue today and nothing here changes that. The ftype that
# actually costs is 361, and elko_bonneville is where it shows -- 139 pans, 874 km2 in
# total, the largest a single 491 km2 sheet of Bonneville salt.
WATER_FTYPES = {390, 436}
# Playa (NHD ftype 361): a dry alkali flat, which is exactly why it is NOT in
# WATER_FTYPES -- filling it blue paints a basin's salt as open water. It is still
# real ground worth naming and drawing, just not as water, so it bakes to its OWN
# sidecar (playa.json) rather than into hydro.json. Two reasons, and the second is the
# one that decides it: a dry lake is a different cartographic object with a different
# treatment (stipple, not fill), and hydro.json is hashed into the plate's identity, so
# appending to it would make every poster ever printed report a plate mismatch on
# reprint. A separate file that `region_pack_block` skips unless the sheet actually
# draws it keeps existing plates byte-identical (the labels.json / landcover.tif
# precedent).
PLAYA_FTYPES = {361}

def _is_playa_ftype(row):
    v = row.get("ftype", row.get("FTYPE"))
    if v is None:
        return False
    try:
        return int(v) in PLAYA_FTYPES
    except (TypeError, ValueError):
        return str(v).strip().lower() == "playa"

def bake_playa(waterbodies, dst_crs, simplify_m=30.0):
    """Reproject/simplify the PLAYA waterbodies into a serializable dict in dst_crs
    metres. Same shape as bake_hydro's lakes, so the renderer reads one geometry
    format; `None`/empty in gives an empty (but valid) sidecar."""
    out = []
    if waterbodies is not None and len(waterbodies):
        for _, row in waterbodies.to_crs(dst_crs).iterrows():
            if not _is_playa_ftype(row):
                continue
            g = row.geometry.simplify(simplify_m)
            for ring in _exterior_rings(g):
                out.append({"coords": [[float(x), float(y)] for x, y, *_ in ring],
                            "name": str(row.get("gnis_name") or "")})
    return {"crs": dst_crs, "playas": out}

def _is_water_ftype(row):
    v = row.get("ftype", row.get("FTYPE"))
    if v is None:
        return True                       # no ftype column -> keep (old behavior)
    try:
        return int(v) in WATER_FTYPES
    except (TypeError, ValueError):
        return str(v).strip().lower() in {"lakepond", "reservoir"}

def bake_hydro(waterbodies, flowlines, dst_crs, simplify_m=30.0, min_order=3):
    """Reproject/simplify/filter NHD geometry into a serializable hydro dict in
    dst_crs metres. waterbodies/flowlines are GeoDataFrames (EPSG:4326) or None."""
    import pandas as pd
    lakes, rivers = [], []
    if waterbodies is not None and len(waterbodies):
        for _, row in waterbodies.to_crs(dst_crs).iterrows():
            if not _is_water_ftype(row):
                continue
            g = row.geometry.simplify(simplify_m)
            for ring in _exterior_rings(g):
                lakes.append({"coords": [[float(x), float(y)] for x, y, *_ in ring],
                              "name": str(row.get("gnis_name") or "")})
    if flowlines is not None and len(flowlines):
        fl = flowlines.to_crs(dst_crs)
        col = "streamorde" if "streamorde" in fl.columns else (
            "StreamOrde" if "StreamOrde" in fl.columns else None)
        for _, row in fl.iterrows():
            v = row[col] if col else None
            # NHD non-network records carry NaN/NA streamorde; pd.isna catches both
            # (neither is `is None`), else int(NaN) would crash the whole bake.
            order = int(v) if v is not None and not pd.isna(v) else 0
            if order < min_order:
                continue
            g = row.geometry.simplify(simplify_m)
            for line in _lines(g):
                rivers.append({"coords": [[float(x), float(y)] for x, y, *_ in line],
                               "order": order, "name": str(row.get("gnis_name") or "")})
    return {"crs": dst_crs, "lakes": lakes, "rivers": rivers}

# A 3DEP or NLCD service can be down for a minute (acceptance: the WMS answered
# "Service is currently not available" and the same request worked minutes later).
# A transient failure is retried after each of these waits, in seconds.
_RETRY_WAITS = (20, 60)
_sleep = time.sleep                  # tests swap it out
# Errors that say "the file is not there", not "the network hiccuped".
_LASTING_OS_ERRORS = (FileNotFoundError, PermissionError, IsADirectoryError,
                      NotADirectoryError)


def _transient_errors() -> tuple:
    """The exception types worth retrying, resolved at call time. async_retriever
    wraps only a non-200 answer (as ServiceError, not retried: a 4xx is lasting);
    a dropped connection escapes as aiohttp's ClientError, and py3dep raises its
    own ServiceUnavailableError (a pygeoogc subclass) for an unreadable answer."""
    kinds = [TimeoutError, ConnectionError, OSError]
    for mod, name in (("aiohttp", "ClientError"),
                      ("pygeoogc.exceptions", "ServiceUnavailableError"),
                      ("py3dep.exceptions", "ServiceUnavailableError")):
        try:
            kinds.append(getattr(importlib.import_module(mod), name))
        except (ImportError, AttributeError):
            pass
    return tuple(kinds)


def with_retries(fetch, service):
    """fetch(), retried after each _RETRY_WAITS wait on a transient failure. Each
    retry is announced on stdout, so it streams into the build's progress log. A
    lasting error, or the last transient one, raises."""
    transient = _transient_errors()
    for wait in (*_RETRY_WAITS, None):
        try:
            return fetch()
        except transient as ex:
            if wait is None or isinstance(ex, _LASTING_OS_ERRORS):
                raise
            print(f"{service} busy, retrying in {wait:g} s "
                  f"({type(ex).__name__}: {ex})", flush=True)
            _sleep(wait)


def fetch_dem(bbox, resolution_m=10):
    # bbox is (west, south, east, north) in lon/lat. 10 m = 3DEP standard; 30 m
    # for corridor-scale regions where 10 m would be a multi-GB build. py3dep serves
    # 10/30/60 from static tiles and any other cell size from the dynamic service.
    import py3dep
    # xarray DataArray, EPSG:4326
    return with_retries(lambda: py3dep.get_dem(bbox, resolution=resolution_m), "3DEP")

# The 3DEP layers an order can draw from, in metres. 3 m (1/9 arc-second) is being
# retired and is missing in many places (Tecopa has none), so coverage is measured,
# never assumed.
COVERAGE_LAYERS_M = (1, 3, 10, 30, 60)


def coverage_fraction(footprints, bbox_4326):
    """Share of the bbox (EPSG:4326) inside the union of the 3DEP source footprints
    (shapely geometries, EPSG:4326). Measured in degrees: only the ratio matters, and
    on a plate-sized box the distortion is well under 1%."""
    from shapely.geometry import box
    from shapely.ops import unary_union
    target = box(*bbox_4326)
    geoms = list(footprints)
    if not geoms:
        return 0.0
    return float(unary_union(geoms).intersection(target).area / target.area)


# The 3DEP elevation index, queried directly. py3dep.query_3dep_sources asks for each
# footprint's full outline, and the server answers a large lidar footprint (the 1 m
# one at Tecopa, OBJECTID 537) with "Error performing query operation", which py3dep
# swallows as "no footprints" -- coverage 0.0 over real lidar. maxAllowableOffset
# generalises the outlines (~50 m), and the server answers.
INDEX_QUERY_URL = ("https://index.nationalmap.gov/arcgis/rest/services/"
                   "3DEPElevationIndex/MapServer/{layer}/query")
INDEX_LAYERS = {1: 18, 3: 19, 5: 20, 10: 21, 30: 22, 60: 23}   # py3dep's own table
INDEX_SIMPLIFY_DEG = 0.0005
INDEX_TIMEOUT_S = 60        # 30 s timed out on a corridor-sized box


def _signed_area(ring):
    """Shoelace area of a ring as given: negative when clockwise. Defined for any
    ring, even a self-intersecting one (the net of its lobes), unlike an
    orientation test on the repaired shape: make_valid re-orients what it rebuilds."""
    xs = np.asarray([p[0] for p in ring], dtype=float)
    ys = np.asarray([p[1] for p in ring], dtype=float)
    return 0.5 * float(np.sum(xs[:-1] * ys[1:] - xs[1:] * ys[:-1]))


def _polygonal(geom):
    """The polygonal part of a make_valid result (which can carry stray lines)."""
    from shapely.geometry import MultiPolygon
    if geom.geom_type in ("Polygon", "MultiPolygon"):
        return geom
    parts = [g for g in getattr(geom, "geoms", [])
             if g.geom_type in ("Polygon", "MultiPolygon")]
    return MultiPolygon([p for g in parts for p in getattr(g, "geoms", [g])])


def esri_rings_to_geom(rings):
    """One Esri polygon (its `rings`, EPSG:4326) as a shapely geometry. Esri marks an
    outer ring clockwise and a hole counter-clockwise, and one polygon may carry
    several of each, nested: an island can sit inside a lake inside land. Each hole
    belongs to the smallest outer larger than it that holds most of it; each outer
    minus its own holes is one polygon, and the result is their union. Orientation
    is read from the ring as given (_signed_area), then the ring is repaired, since
    a generalised outline can self-intersect. A polygon with no clockwise ring at
    all is read as all outers: some servers flip orientation."""
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
    from shapely.validation import make_valid
    parsed = []
    for ring in rings:
        if len(ring) < 4:
            continue                      # generalised away to a sliver
        poly = _polygonal(make_valid(Polygon(ring)))
        if not poly.is_empty:
            parsed.append((_signed_area(ring) > 0, poly))   # (is_hole, shape)
    if not any(not is_hole for is_hole, _ in parsed):
        parsed = [(False, poly) for _, poly in parsed]
    outers = sorted((p for is_hole, p in parsed if not is_hole), key=lambda p: p.area)
    own = [[] for _ in outers]
    for is_hole, hole in parsed:
        if not is_hole:
            continue
        for i, outer in enumerate(outers):         # smallest first
            # an outer no larger than the hole is an island inside it, not its land
            if (outer.area > hole.area
                    and outer.intersection(hole).area >= 0.5 * hole.area):
                own[i].append(hole)
                break                               # a hole in no outer cuts nothing
    return unary_union([outer.difference(unary_union(h)) if h else outer
                        for outer, h in zip(outers, own)])


def _index_features(layer_m, bbox_4326):
    """The index features for one layer that intersect the bbox, with simplified
    outlines. Retries once on a 5xx, a timeout or a dropped connection; a 4xx is
    not retried. Any failure raises RuntimeError naming the layer: a failed query
    must never read as 'no data here'."""
    import http.client
    import ssl
    import urllib.error
    import urllib.parse
    import urllib.request
    query = urllib.parse.urlencode({
        "geometry": ",".join(str(v) for v in bbox_4326),
        "geometryType": "esriGeometryEnvelope", "inSR": 4326,
        "spatialRel": "esriSpatialRelIntersects", "returnGeometry": "true",
        "outSR": 4326, "maxAllowableOffset": INDEX_SIMPLIFY_DEG,
        "outFields": "OBJECTID", "f": "json"})
    url = INDEX_QUERY_URL.format(layer=INDEX_LAYERS[layer_m]) + "?" + query
    ctx = ssl.create_default_context(cafile=certifi.where())
    name = f"3DEP index layer {layer_m} m"
    for attempt in (1, 2):
        retry = attempt == 1
        try:
            with urllib.request.urlopen(url, context=ctx, timeout=INDEX_TIMEOUT_S) as r:
                body = json.load(r)
        except urllib.error.HTTPError as ex:
            if retry and ex.code >= 500:
                continue
            raise RuntimeError(f"{name}: HTTP {ex.code}") from ex
        except (OSError, http.client.HTTPException) as ex:
            # a timeout, a reset or dropped connection (often raised from
            # getresponse, not urlopen's own URLError), a truncated body
            if retry:
                continue
            raise RuntimeError(f"{name}: {type(ex).__name__}: {ex}") from ex
        except ValueError as ex:          # a body that isn't JSON
            raise RuntimeError(f"{name}: unreadable response ({ex})") from ex
        if "error" in body:
            code = body["error"].get("code") if isinstance(body["error"], dict) else None
            if retry and isinstance(code, int) and code >= 500:
                continue
            raise RuntimeError(f"{name}: server error {body['error']}")
        if body.get("exceededTransferLimit"):
            raise RuntimeError(f"{name}: more footprints than one query returns")
        features = body.get("features")
        if features is None:
            raise RuntimeError(f"{name}: response has no features list")
        return features
    raise AssertionError("unreachable")


def layer_coverage(bbox_4326, layers=COVERAGE_LAYERS_M):
    """{layer metres: covered share} for each of `layers` (a subset of
    COVERAGE_LAYERS_M), from the 3DEP index over the network. A layer with no
    footprints is 0.0; a failed query raises RuntimeError, never 0.0. Asking for
    fewer layers matters on a big box: the 1 m footprint query over a corridor
    times out, and a print that coarse cannot use lidar anyway."""
    unknown = [r for r in layers if r not in COVERAGE_LAYERS_M]
    if unknown:
        raise ValueError(f"not a 3DEP coverage layer: {unknown}; "
                         f"choose from {list(COVERAGE_LAYERS_M)}")
    out = {}
    for r in layers:
        geoms = []
        for f in _index_features(r, bbox_4326):
            rings = (f.get("geometry") or {}).get("rings")
            if rings is None:
                raise RuntimeError(f"3DEP index layer {r} m: a footprint has no outline")
            geoms.append(esri_rings_to_geom(rings))
        out[r] = coverage_fraction(geoms, bbox_4326)
    return out

def fetch_hydro(bbox):
    """Fetch NHD waterbodies + network flowlines for the bbox (EPSG:4326).
    Returns (waterbodies_gdf_or_None, flowlines_gdf_or_None); tolerant of gaps."""
    import pynhd
    wb = fl = None
    try:
        wb = pynhd.WaterData("nhdwaterbody").bybox(bbox)
    except Exception as ex:
        print(f"  no waterbodies: {ex}")
    try:
        fl = pynhd.WaterData("nhdflowline_network").bybox(bbox)
    except Exception as ex:
        print(f"  no flowlines: {ex}")
    return wb, fl

def _fetch_nlcd(bbox, resolution_m, year):
    """The NLCD request, retried through a brief outage like the DEM fetch
    (acceptance: "Server disconnected"). Still a failure after the retries: the
    caller decides whether land cover is optional."""
    import geopandas as gpd
    import pygeohydro
    from shapely.geometry import box
    geom = gpd.GeoSeries([box(*bbox)], crs=4326)
    return with_retries(lambda: pygeohydro.nlcd_bygeom(
        geom, resolution=resolution_m, years={"cover": [year]}), "NLCD")


def bake_landcover(bbox, dst_crs, out_path, resolution_m=30, year=2021):
    """Fetch NLCD land cover for the bbox and write it as a compact uint8 GeoTIFF in
    the region CRS (~0.5 MB per county-scale region -- committed, unlike the DEM).
    Drives the optional biome tint: hue from land cover, lightness from elevation.
    NLCD is US-only, public domain (USGS/MRLC)."""
    ds = _fetch_nlcd(bbox, resolution_m, year)
    da = (list(ds.values())[0] if isinstance(ds, dict) else ds)[f"cover_{year}"]
    da = da.rio.reproject(dst_crs, resolution=resolution_m,
                          resampling=Resampling.nearest, nodata=0)
    arr = np.asarray(da.values).astype("uint8")
    profile = dict(driver="GTiff", dtype="uint8", count=1,
                   height=arr.shape[0], width=arr.shape[1], crs=dst_crs,
                   transform=da.rio.transform(), nodata=0,
                   tiled=True, compress="deflate")
    with rasterio.open(out_path, "w", **profile) as f:
        f.write(arr, 1)
    return out_path

def _slice_extents(bbox_4326, dst_crs, plan):
    """Each longitude slice build_dem_cog fetches, as (fetch bbox in lon/lat with the
    slice_overlap_deg buffer, projected extent clipped to the grid as
    (wminx, wminy, wmaxx, wmaxy)). Pure: no fetch."""
    from pyproj import Transformer
    w_px, h_px = plan["grid"]
    T = plan["transform"]
    n = plan["n_slices"]
    overlap = slice_overlap_deg(plan["resolution_m"])
    fwd = Transformer.from_crs("EPSG:4326", dst_crs, always_xy=True)
    edges = np.linspace(bbox_4326[0], bbox_4326[2], n + 1)
    minx, maxy = T.c, T.f
    out = []
    for i in range(n):
        sb = (float(edges[i]) - overlap, bbox_4326[1],
              float(edges[i + 1]) + overlap, bbox_4326[3])
        sxs, sys_ = fwd.transform(*_densified_edge(sb, n=21))
        out.append((sb, (max(minx, float(np.min(sxs))),
                         max(maxy - h_px * T.a, float(np.min(sys_))),
                         min(minx + w_px * T.a, float(np.max(sxs))),
                         min(maxy, float(np.max(sys_))))))
    return out


# Float noise on an extent that sits exactly on a cell edge must not add a column.
_WINDOW_EPS_PX = 1e-6


def _slice_window(wminx, wminy, wmaxx, wmaxy, T, w_px, h_px):
    """The integer window of the grid (transform T, w_px x h_px) that a slice's
    projected extent covers: start floored, end ceiled, clipped to the grid.
    Rounding the offset and the length apart (rasterio's round_offsets then
    round_lengths) could end a window one column short, and the last slice then
    left the grid's east column NaN."""
    from rasterio.windows import Window, from_bounds
    f = from_bounds(wminx, wminy, wmaxx, wmaxy, transform=T)
    c0 = max(0, math.floor(f.col_off + _WINDOW_EPS_PX))
    c1 = min(w_px, math.ceil(f.col_off + f.width - _WINDOW_EPS_PX))
    r0 = max(0, math.floor(f.row_off + _WINDOW_EPS_PX))
    r1 = min(h_px, math.ceil(f.row_off + f.height - _WINDOW_EPS_PX))
    return Window(c0, r0, c1 - c0, r1 - r0)


def build_dem_cog(bbox_4326, dst_crs, out_path, plan):
    """Fetch 3DEP and write the region COG onto ONE shared grid, in longitude slices
    (plan['n_slices']) so peak memory stays bounded no matter the bbox size: each
    slice is fetched, warped into its window of the target grid, merged prefer-finite
    with the slice_overlap_deg buffer, and released before the next. Replaces the old
    whole-bbox to_cog, which held source + destination + reprojection scratch for the
    entire region simultaneously and OOM'd at corridor scale. py3dep returns CONUS
    Albers (EPSG:5070); each slice is warped straight onto the region grid, and the
    GRID_INSET_M inset (see projected_grid) replaces the old NaN-edge trimming."""
    from rasterio.warp import reproject
    w_px, h_px = plan["grid"]
    T = plan["transform"]
    res = plan["resolution_m"]
    n = plan["n_slices"]
    profile = dict(driver="GTiff", dtype="float32", count=1,
                   height=h_px, width=w_px, crs=dst_crs, transform=T,
                   nodata=np.nan, tiled=True, blockxsize=512, blockysize=512,
                   compress="deflate", BIGTIFF="IF_SAFER")
    # create the nodata-filled target, then reopen r+ ("w" datasets are write-only
    # in rasterio, and the slice-overlap merge must read back what's written)
    with rasterio.open(out_path, "w", **profile):
        pass
    with rasterio.open(out_path, "r+") as dst:
        for i, (sb, extent) in enumerate(_slice_extents(bbox_4326, dst_crs, plan)):
            if n > 1:
                print(f"  slice {i + 1}/{n}: fetching 3DEP "
                      f"lon [{sb[0]:.3f}, {sb[2]:.3f}]", flush=True)
            da = fetch_dem(sb, res)
            src = np.asarray(da.values, dtype="float32")
            if src.ndim == 3:
                src = src[0]
            # destination window on the shared grid = this slice's projected extent
            win = _slice_window(*extent, T, w_px, h_px)
            dst_arr = np.full((int(win.height), int(win.width)), np.nan, "float32")
            reproject(source=src, destination=dst_arr,
                      src_transform=da.rio.transform(), src_crs=da.rio.crs,
                      src_nodata=np.nan,
                      dst_transform=rasterio.windows.transform(win, T),
                      dst_crs=dst_crs, dst_nodata=np.nan,
                      resampling=Resampling.bilinear)
            existing = dst.read(1, window=win)
            dst.write(np.where(np.isnan(dst_arr), existing, dst_arr), 1, window=win)
            del da, src, dst_arr, existing
        # Overviews are the image pyramid: coarse copies for zoomed-out reads.
        dst.build_overviews([2, 4, 8, 16, 32], Resampling.average)
        dst.update_tags(ns="rio_overview", resampling="average")
    return out_path

def overview_png(cog_path, out_png, long_edge=1400):
    with rasterio.open(cog_path) as ds:
        scale = long_edge / max(ds.width, ds.height)
        ow, oh = int(ds.width * scale), int(ds.height * scale)
        elev = ds.read(1, out_shape=(oh, ow), resampling=Resampling.average)
        bounds = ds.bounds; crs = ds.crs.to_string()
    # A neutral grayscale relief just for aiming; the pretty version is rendered later.
    valid = np.isfinite(elev)
    lo, hi = np.nanpercentile(elev[valid], [1, 99])
    norm = np.clip((elev - lo) / (hi - lo + 1e-9), 0, 1)
    # Reprojecting Albers -> UTM leaves NaN corners; render those as clean black
    # (casting NaN -> uint8 is otherwise undefined) so the aim view has no garbage.
    img = np.nan_to_num(norm * 255.0, nan=0.0).astype("uint8")
    Image.fromarray(img, "L").convert("RGB").save(out_png)
    return (ow, oh), (bounds.left, bounds.bottom, bounds.right, bounds.top), crs

def write_sources_manifest(out_dir, region_id, bbox_4326, dst_crs, built=None,
                           resolution_m=10):
    """Record what this region was built FROM (V1-12 continuity): source datasets,
    licenses, the exact fetch bbox, and sha256 of the produced assets. The DEM itself
    is gitignored; the committed manifest lets a rebuild be verified against what was
    validated (a hash mismatch = upstream 3DEP/NHD drift, not a local mistake) and
    tells an archival job exactly which artifacts to preserve."""
    import datetime
    import hashlib

    def _sha256(path):
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()

    manifest = {
        "id": region_id,
        "built": built or datetime.date.today().isoformat(),
        "fetch_bbox_4326": list(bbox_4326),
        "crs": dst_crs,
        "rebuild": (f"python region_prep.py --id {region_id} --name <name> "
                    f"--bbox {' '.join(str(v) for v in bbox_4326)} "
                    f"--epsg {dst_crs.split(':')[1]} --resolution {resolution_m}"),
        "assets": {},
        "sources": [
            {"dataset": (f"USGS 3DEP {resolution_m:g} m DEM"
                         if _is_static(resolution_m)
                         else f"USGS 3DEP dynamic service, {resolution_m:g} m"),
             "via": "py3dep.get_dem", "license": "Public domain (USGS)"},
            {"dataset": "USGS NHD waterbodies + network flowlines",
             "via": "pynhd.WaterData nhdwaterbody/nhdflowline_network",
             "license": "Public domain (USGS)"},
            {"dataset": "NLCD 2021 land cover (30 m)",
             "via": "pygeohydro.nlcd_bygeom",
             "license": "Public domain (USGS/MRLC)"},
        ],
    }
    # labels.json is baked later (scripts/build_labels.py) and usually absent here;
    # hashed only if present, and the labels bake syncs it into this manifest itself.
    for name in ("dem.tif", "hydro.json", "region.json", "overview.png", "landcover.tif",
                 "labels.json"):
        p = os.path.join(out_dir, name)
        if os.path.exists(p):
            manifest["assets"][name] = {"sha256": _sha256(p), "bytes": os.path.getsize(p)}
    with open(os.path.join(out_dir, "sources.json"), "w") as f:
        json.dump(manifest, f, indent=2)
    return manifest

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--bbox", nargs=4, type=float, required=True,
                    help="west south east north (lon/lat)")
    ap.add_argument("--epsg", type=int, required=True,
                    help="projected CRS for the region, e.g. a local UTM zone")
    ap.add_argument("--resolution", default=None, type=_resolution_arg,
                    help="DEM grid in metres, or 'auto' (default): the finest of "
                         "10/30/60 that fits the grid budget, so a huge bbox can't "
                         "OOM the build. Any other cell size is fetched from the "
                         "3DEP dynamic service")
    ap.add_argument("--out-root", default="regions",
                    help="directory the region folder is written under")
    args = ap.parse_args()

    out_dir = os.path.join(args.out_root, args.id)
    os.makedirs(out_dir, exist_ok=True)
    dst_crs = f"EPSG:{args.epsg}"

    # Plan first, fetch second: the operator sees the full cost of this bbox --
    # resolution, grid, disk, slices, peak memory -- before a byte is downloaded.
    plan = plan_build(tuple(args.bbox), dst_crs, args.resolution)
    gw, gh = plan["grid"]
    print(f"Build plan: {plan['resolution_m']:g} m"
          f"{' (auto)' if plan['auto'] else ''} -> grid {gw}x{gh} "
          f"({plan['grid_mpx']:.0f} Mpx), dem.tif ~{plan['est_dem_mb']:.0f} MB, "
          f"{plan['n_slices']} slice(s), peak ~{plan['est_peak_gb']:.1f} GB RAM, "
          f"landcover @ {plan['landcover_resolution_m']} m")
    if plan["over_budget"]:
        print(f"  WARNING: grid exceeds the {GRID_BUDGET_MPX} Mpx budget. The slice "
              f"builder keeps memory bounded, but the DEM will be "
              f"~{plan['est_dem_mb'] / 1024:.1f} GB on disk and renders will be "
              f"slow. Consider a coarser --resolution.")

    # Fetch hydrography first, while aiohttp's SSL context is fresh (a prior large
    # DEM fetch can leave it in a state where concurrent NHD requests fail SSL).
    print("Fetching NHD hydrography...")
    try:
        wb, fl = fetch_hydro(tuple(args.bbox))   # import + fetch + ...
        hydro = bake_hydro(wb, fl, dst_crs)       # ...processing all guarded
    except Exception as ex:
        print(f"  hydro failed, continuing without water: {ex}")
        hydro = {"crs": dst_crs, "lakes": [], "rivers": []}
    with open(os.path.join(out_dir, "hydro.json"), "w") as f:
        json.dump(hydro, f)
    print(f"  lakes: {len(hydro['lakes'])}  rivers: {len(hydro['rivers'])}")

    print("Fetching NLCD land cover...")
    try:
        bake_landcover(tuple(args.bbox), dst_crs, os.path.join(out_dir, "landcover.tif"),
                       resolution_m=plan["landcover_resolution_m"])
    except Exception as ex:
        # biome tint is optional; the render falls back to pure elevation tint
        print(f"  land cover failed, continuing without biome tint: {ex}")

    print("Fetching 3DEP DEM...")
    cog = build_dem_cog(tuple(args.bbox), dst_crs,
                        os.path.join(out_dir, "dem.tif"), plan)

    print("Building aim-view overview...")
    size, bounds, crs = overview_png(cog, os.path.join(out_dir, "overview.png"))

    with rasterio.open(cog) as ds:
        # decimated read: percentile color anchors don't need every pixel, and a
        # corridor-scale DEM read whole would defeat the slice builder's memory cap
        elev = ds.read(1, out_shape=(max(1, ds.height // 4), max(1, ds.width // 4)),
                       resampling=Resampling.average)
        finite = elev[np.isfinite(elev)]
        emin, emax = float(np.percentile(finite, 0.5)), float(np.percentile(finite, 99.5))

    region = {
        "id": args.id, "name": args.name, "crs": crs,
        "bounds": list(bounds), "overview_size": list(size),
        "dem_path": "dem.tif", "overview_path": "overview.png",
        "hydro_path": "hydro.json",
        "native_resolution_m": plan["resolution_m"],
        # absolute color scale + fixed light keep every crop consistent (invariant 4):
        "elevation_min": emin, "elevation_max": emax,
        "light_azimuth": 315, "light_altitude": 45, "z_factor": 1.0,
    }
    with open(os.path.join(out_dir, "region.json"), "w") as f:
        json.dump(region, f, indent=2)
    write_sources_manifest(out_dir, args.id, tuple(args.bbox), dst_crs,
                           resolution_m=plan["resolution_m"])
    print(f"Region ready: {out_dir}")

if __name__ == "__main__":
    main()
