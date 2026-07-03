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
explicit --resolution only to override the planner. The plan (grid, file size,
slice count) prints before anything is fetched.
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

def plan_build(bbox_4326, dst_crs, resolution_m=None):
    """Everything main() needs to know before fetching: the DEM resolution (auto =
    finest of DEM_RES_CHOICES whose grid fits GRID_BUDGET_MPX; explicit overrides
    but is flagged when over budget), the slice count that keeps peak memory
    bounded, the landcover resolution, and honest size estimates."""
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
    n_slices = max(1, int(np.ceil(mpx / SLICE_BUDGET_MPX)))
    return {"resolution_m": resolution_m, "auto": auto,
            "grid": (w, h), "transform": transform, "grid_mpx": mpx,
            "over_budget": mpx > GRID_BUDGET_MPX,
            "n_slices": n_slices,
            "landcover_resolution_m": lc_res,
            "est_dem_mb": mpx * 4,           # float32; terrain barely deflates
            "est_peak_gb": mpx / n_slices * 4 * 10 / 1024}

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

def build_dem_cog(bbox_4326, dst_crs, out_path, plan):
    """Fetch 3DEP and write the region COG onto ONE shared grid, in longitude slices
    (plan['n_slices']) so peak memory stays bounded no matter the bbox size: each
    slice is fetched, warped into its window of the target grid, merged prefer-finite
    with the 0.03 deg overlap, and released before the next begins. Replaces the old
    whole-bbox to_cog, which held source + destination + reprojection scratch for the
    entire region simultaneously and OOM'd at corridor scale. py3dep returns CONUS
    Albers (EPSG:5070); each slice is warped straight onto the region grid, and the
    GRID_INSET_M inset (see projected_grid) replaces the old NaN-edge trimming."""
    from pyproj import Transformer
    from rasterio.warp import reproject
    from rasterio.windows import from_bounds as win_from_bounds
    w_px, h_px = plan["grid"]
    T = plan["transform"]
    res = plan["resolution_m"]
    n = plan["n_slices"]
    fwd = Transformer.from_crs("EPSG:4326", dst_crs, always_xy=True)
    profile = dict(driver="GTiff", dtype="float32", count=1,
                   height=h_px, width=w_px, crs=dst_crs, transform=T,
                   nodata=np.nan, tiled=True, blockxsize=512, blockysize=512,
                   compress="deflate", BIGTIFF="IF_SAFER")
    edges = np.linspace(bbox_4326[0], bbox_4326[2], n + 1)
    minx, maxy = T.c, T.f
    # create the nodata-filled target, then reopen r+ ("w" datasets are write-only
    # in rasterio, and the slice-overlap merge must read back what's written)
    with rasterio.open(out_path, "w", **profile):
        pass
    with rasterio.open(out_path, "r+") as dst:
        for i in range(n):
            sb = (float(edges[i]) - 0.03, bbox_4326[1],
                  float(edges[i + 1]) + 0.03, bbox_4326[3])
            if n > 1:
                print(f"  slice {i + 1}/{n}: fetching 3DEP "
                      f"lon [{sb[0]:.3f}, {sb[2]:.3f}]", flush=True)
            da = fetch_dem(sb, res)
            src = np.asarray(da.values, dtype="float32")
            if src.ndim == 3:
                src = src[0]
            # destination window on the shared grid = this slice's projected extent
            sxs, sys_ = fwd.transform(*_densified_edge(sb, n=21))
            wminx = max(minx, float(np.min(sxs)))
            wmaxx = min(minx + w_px * res, float(np.max(sxs)))
            wminy = max(maxy - h_px * res, float(np.min(sys_)))
            wmaxy = min(maxy, float(np.max(sys_)))
            win = win_from_bounds(wminx, wminy, wmaxx, wmaxy,
                                  transform=T).round_offsets().round_lengths()
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
    ap.add_argument("--resolution", default="auto", choices=("auto", "10", "30", "60"),
                    help="DEM grid in metres; 'auto' (default) picks the finest that "
                         "fits the grid budget, so a huge bbox can't OOM the build")
    args = ap.parse_args()

    out_dir = os.path.join("regions", args.id)
    os.makedirs(out_dir, exist_ok=True)
    dst_crs = f"EPSG:{args.epsg}"

    # Plan first, fetch second: the operator sees the full cost of this bbox --
    # resolution, grid, disk, slices, peak memory -- before a byte is downloaded.
    plan = plan_build(tuple(args.bbox), dst_crs,
                      None if args.resolution == "auto" else int(args.resolution))
    gw, gh = plan["grid"]
    print(f"Build plan: {plan['resolution_m']} m"
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
