#!/usr/bin/env python3
"""Score a real 5 m dynamic-service grid after the plate warp. Run by hand in .venv-prep:
    .venv-prep/bin/python scripts/stripe_probe_dynamic.py
The bilinear warp this replaced scored 57.4 here. Under STRIPE_RED_SCORE passes."""
import os
import sys

import numpy as np
from rasterio.transform import from_origin
from rasterio.warp import reproject

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import region_prep as rp  # noqa: E402  (sets the certificate path before py3dep loads)
from scripts.stripe_check import STRIPE_RED_SCORE, peaks  # noqa: E402

BBOX = (-106.8634, 39.0953, -106.7693, 39.1598)
GRID_CRS = "EPSG:32613"
GRID = from_origin(341000, 4333500, 5, 5)
GRID_W, GRID_H = 600, 500


def main():
    da = rp.fetch_dem(BBOX, 5)
    src = np.asarray(da.values, dtype="float32")
    src = src[0] if src.ndim == 3 else src
    out = np.full((GRID_H, GRID_W), np.nan, "float32")
    reproject(source=src, destination=out, src_transform=da.rio.transform(),
              src_crs=da.rio.crs, src_nodata=np.nan, dst_transform=GRID, dst_crs=GRID_CRS,
              dst_nodata=np.nan, resampling=rp.DEM_WARP_RESAMPLING)
    p = peaks(out, 5, 5)
    print(f"source {da.rio.crs} {da.rio.resolution()}; warped: {p}")
    return 1 if p[0]["score"] >= STRIPE_RED_SCORE else 0


if __name__ == "__main__":
    sys.exit(main())
