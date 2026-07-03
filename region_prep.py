# region_prep.py
"""
One-time, offline. Fetch 3DEP elevation for a bbox, write a COG with overviews,
build the aim-view overview PNG, and write region.json.

Usage:
    python region_prep.py --id lassen_ca \
        --name "Lassen County, California" \
        --bbox -120.90 40.33 -120.50 40.78 \
        --epsg 32610
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

import argparse, json
import numpy as np
import rasterio
from rasterio.enums import Resampling
from affine import Affine
from PIL import Image
# pandas / py3dep / pynhd are imported lazily inside the functions that fetch or
# bake: importing THIS module then only needs the core stack, so the pure-logic
# tests (_trim_nan_edges, bake_hydro) run in CI without the ~200 MB fetch stack.

def _trim_nan_edges(dst, max_edge_nan=0.005):
    """Return (r0, r1, c0, c1) bounding a NaN-clean rectangle. Greedily peel whichever
    single edge (top/bottom/left/right) is currently the most NaN, and stop once the
    worst remaining edge is under max_edge_nan. Peeling the worst edge each step removes
    the reproject's NaN frame and triangular corners without over-trimming a clean side
    (a naive per-edge pass over-trims, since a perpendicular NaN band makes every row or
    column look bad). The small tolerance avoids peeling a whole row/col for one stray
    pixel; sparse interior NaN is left for relief._fill_nan."""
    finite = np.isfinite(dst)
    r0, r1, c0, c1 = 0, dst.shape[0], 0, dst.shape[1]
    while r1 - r0 > 1 and c1 - c0 > 1:
        fr = [1.0 - finite[r0, c0:c1].mean(),       # top
              1.0 - finite[r1-1, c0:c1].mean(),     # bottom
              1.0 - finite[r0:r1, c0].mean(),       # left
              1.0 - finite[r0:r1, c1-1].mean()]     # right
        k = int(np.argmax(fr))
        if fr[k] <= max_edge_nan:
            break
        if k == 0: r0 += 1
        elif k == 1: r1 -= 1
        elif k == 2: c0 += 1
        else: c1 -= 1
    return r0, r1, c0, c1

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
# dry alkali flat most of the year (Honey Lake rendered as a ~234 km2 solid slab --
# red-team's top beauty finding), and SwampMarsh (466) / Ice (378) mislead the same
# way. LakePond (390) + Reservoir (436) stay.
WATER_FTYPES = {390, 436}

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

def fetch_dem(bbox, resolution_m=10):
    # bbox is (west, south, east, north) in lon/lat. 10 m = 3DEP standard; 30 m
    # for corridor-scale regions where 10 m would be a multi-GB build.
    import py3dep
    return py3dep.get_dem(bbox, resolution=resolution_m)  # xarray DataArray, EPSG:4326

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

def bake_landcover(bbox, dst_crs, out_path, resolution_m=30, year=2021):
    """Fetch NLCD land cover for the bbox and write it as a compact uint8 GeoTIFF in
    the region CRS (~0.5 MB per county-scale region -- committed, unlike the DEM).
    Drives the optional biome tint: hue from land cover, lightness from elevation.
    NLCD is US-only, public domain (USGS/MRLC)."""
    import geopandas as gpd
    import pygeohydro
    from shapely.geometry import box
    geom = gpd.GeoSeries([box(*bbox)], crs=4326)
    ds = pygeohydro.nlcd_bygeom(geom, resolution=resolution_m,
                                years={"cover": [year]})
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

def to_cog(dem_da, dst_crs, out_path, bbox_4326, resolution_m=10):
    # py3dep returns a rioxarray DataArray that already carries its own CRS
    # (3DEP serves CONUS Albers, EPSG:5070, with coords in metres). Trust that
    # CRS and reproject straight to the region CRS at a fixed metre grid, rather
    # than assuming EPSG:4326 and rebuilding the transform from lon/lat bounds.
    if dem_da.rio.crs is None:
        dem_da = dem_da.rio.write_crs("EPSG:4326")
    dem_da = dem_da.rio.reproject(dst_crs, resolution=resolution_m,
                                  resampling=Resampling.bilinear, nodata=np.nan)
    # Clip to the UTM box of the requested geographic bbox. py3dep over-returns and
    # the Albers->UTM reprojection leaves NaN corners; the bbox sits strictly inside
    # the data, so this trims to a clean, fully-valid rectangle (honest bounds).
    from pyproj import Transformer
    fwd = Transformer.from_crs("EPSG:4326", dst_crs, always_xy=True)
    w, s, e, n = bbox_4326
    # Densify the bbox edges before projecting: meridians/parallels curve in UTM, so
    # 4 corners can mis-bound a wide/high-latitude box. (NaN-freeness then relies on
    # py3dep over-returning past the bbox, which it reliably does.)
    t = np.linspace(0.0, 1.0, 25)
    lons = np.concatenate([w + t*(e-w), w + t*(e-w), np.full(25, w), np.full(25, e)])
    lats = np.concatenate([np.full(25, s), np.full(25, n), s + t*(n-s), s + t*(n-s)])
    xs, ys = fwd.transform(lons, lats)
    dem_da = dem_da.rio.clip_box(float(np.min(xs)), float(np.min(ys)),
                                 float(np.max(xs)), float(np.max(ys)))
    dst = np.asarray(dem_da.values, dtype="float32")
    dst_transform = dem_da.rio.transform()
    # The Albers->UTM reproject can still leave NaN at the corners when py3dep didn't
    # over-return far enough past the bbox on a side (worse for wide/zone-straddling
    # boxes). Trim whole edge rows/cols while they are mostly NaN so the COG is an
    # honest, fully-valid rectangle (no dark wedges in the poster or aim view), and
    # shift the transform origin to match.
    r0, r1, c0, c1 = _trim_nan_edges(dst)
    dst = dst[r0:r1, c0:c1]
    dst_transform = dst_transform * Affine.translation(c0, r0)
    dh, dw = dst.shape

    profile = dict(driver="GTiff", dtype="float32", count=1,
                   height=dh, width=dw, crs=dst_crs, transform=dst_transform,
                   nodata=np.nan, tiled=True, blockxsize=512, blockysize=512,
                   compress="deflate")
    with rasterio.open(out_path, "w", **profile) as ds:
        ds.write(dst, 1)
        # Overviews are the image pyramid: coarse copies for zoomed-out reads.
        ds.build_overviews([2, 4, 8, 16, 32], Resampling.average)
        ds.update_tags(ns="rio_overview", resampling="average")
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
            {"dataset": f"USGS 3DEP {resolution_m} m DEM", "via": "py3dep.get_dem",
             "license": "Public domain (USGS)"},
            {"dataset": "USGS NHD waterbodies + network flowlines",
             "via": "pynhd.WaterData nhdwaterbody/nhdflowline_network",
             "license": "Public domain (USGS)"},
            {"dataset": "NLCD 2021 land cover (30 m)",
             "via": "pygeohydro.nlcd_bygeom",
             "license": "Public domain (USGS/MRLC)"},
        ],
    }
    for name in ("dem.tif", "hydro.json", "region.json", "overview.png", "landcover.tif"):
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
    ap.add_argument("--resolution", type=int, default=10, choices=(10, 30, 60),
                    help="DEM grid in metres (10 m default; 30 m for huge regions)")
    args = ap.parse_args()

    out_dir = os.path.join("regions", args.id)
    os.makedirs(out_dir, exist_ok=True)
    dst_crs = f"EPSG:{args.epsg}"

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
        bake_landcover(tuple(args.bbox), dst_crs, os.path.join(out_dir, "landcover.tif"))
    except Exception as ex:
        # biome tint is optional; the render falls back to pure elevation tint
        print(f"  land cover failed, continuing without biome tint: {ex}")

    print("Fetching 3DEP DEM...")
    dem = fetch_dem(tuple(args.bbox), args.resolution)
    cog = to_cog(dem, dst_crs, os.path.join(out_dir, "dem.tif"), tuple(args.bbox),
                 resolution_m=args.resolution)

    print("Building aim-view overview...")
    size, bounds, crs = overview_png(cog, os.path.join(out_dir, "overview.png"))

    with rasterio.open(cog) as ds:
        elev = ds.read(1)
        valid = np.isfinite(elev)
        emin, emax = float(np.nanpercentile(elev[valid], 0.5)), float(np.nanpercentile(elev[valid], 99.5))

    region = {
        "id": args.id, "name": args.name, "crs": crs,
        "bounds": list(bounds), "overview_size": list(size),
        "dem_path": "dem.tif", "overview_path": "overview.png",
        "hydro_path": "hydro.json",
        "native_resolution_m": args.resolution,
        # absolute color scale + fixed light keep every crop consistent (invariant 4):
        "elevation_min": emin, "elevation_max": emax,
        "light_azimuth": 315, "light_altitude": 45, "z_factor": 1.0,
    }
    with open(os.path.join(out_dir, "region.json"), "w") as f:
        json.dump(region, f, indent=2)
    write_sources_manifest(out_dir, args.id, tuple(args.bbox), dst_crs,
                           resolution_m=args.resolution)
    print(f"Region ready: {out_dir}")

if __name__ == "__main__":
    main()
