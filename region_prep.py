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
import argparse, json, os
import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.warp import calculate_default_transform, reproject
import py3dep
from PIL import Image

def fetch_dem(bbox):
    # bbox is (west, south, east, north) in lon/lat. 10 m = 3DEP standard.
    return py3dep.get_dem(bbox, resolution=10)  # xarray DataArray, EPSG:4326

def to_cog(dem_da, dst_crs, out_path, resolution_m=10):
    # py3dep returns a rioxarray DataArray that already carries its own CRS
    # (3DEP serves CONUS Albers, EPSG:5070, with coords in metres). Trust that
    # CRS and reproject straight to the region CRS at a fixed metre grid, rather
    # than assuming EPSG:4326 and rebuilding the transform from lon/lat bounds.
    if dem_da.rio.crs is None:
        dem_da = dem_da.rio.write_crs("EPSG:4326")
    dem_da = dem_da.rio.reproject(dst_crs, resolution=resolution_m,
                                  resampling=Resampling.bilinear, nodata=np.nan)
    dst = np.asarray(dem_da.values, dtype="float32")
    dh, dw = dst.shape
    dst_transform = dem_da.rio.transform()

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

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--bbox", nargs=4, type=float, required=True,
                    help="west south east north (lon/lat)")
    ap.add_argument("--epsg", type=int, required=True,
                    help="projected CRS for the region, e.g. a local UTM zone")
    args = ap.parse_args()

    out_dir = os.path.join("regions", args.id)
    os.makedirs(out_dir, exist_ok=True)
    dst_crs = f"EPSG:{args.epsg}"

    print("Fetching 3DEP DEM...")
    dem = fetch_dem(tuple(args.bbox))
    cog = to_cog(dem, dst_crs, os.path.join(out_dir, "dem.tif"))

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
        "native_resolution_m": 10,
        # absolute color scale + fixed light keep every crop consistent (invariant 4):
        "elevation_min": emin, "elevation_max": emax,
        "light_azimuth": 315, "light_altitude": 45, "z_factor": 1.0,
    }
    with open(os.path.join(out_dir, "region.json"), "w") as f:
        json.dump(region, f, indent=2)
    print(f"Region ready: {out_dir}")

if __name__ == "__main__":
    main()
