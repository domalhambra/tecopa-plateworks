#!/usr/bin/env python3
"""Build a candidate DEM for a curated plate on its committed grid, outside regions/, and
compare it with the plate's current DEM. Nothing in the plate changes.

    .venv-prep/bin/python scripts/dem_candidate.py <id> --out cache/dem_candidates

region_prep.plan_build can give a different grid today than the plate was built on, so
the grid comes from region.json and the fetch bbox from sources.json. The script does
not write sources.json (invariant 12). The swap is a separate step: see
docs/changing-things.md, Repair an orphaned DEM.
"""
import argparse
import json
import os
import sys

import numpy as np
import rasterio
from rasterio.transform import from_origin
from rasterio.windows import Window

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import region_prep as rp  # noqa: E402
from scripts.stripe_check import scan  # noqa: E402

COMPARE_ROWS = 1024       # rows read at a time, so a corridor plate fits in memory


def committed_plan(region_dir):
    """(bbox_4326, crs, plan) for the plate's committed grid."""
    with open(os.path.join(region_dir, "region.json")) as f:
        cfg = json.load(f)
    with open(os.path.join(region_dir, "sources.json")) as f:
        bbox = tuple(json.load(f)["fetch_bbox_4326"])
    res = cfg["native_resolution_m"]
    left, bottom, right, top = cfg["bounds"]
    plan = dict(rp.plan_build(bbox, cfg["crs"], res))
    plan["grid"] = (int(round((right - left) / res)), int(round((top - bottom) / res)))
    plan["transform"] = from_origin(left, top, res, res)
    return bbox, cfg["crs"], plan


def compare(old_path, new_path, cfg):
    """How the candidate differs from the current DEM: stripe scans of both, RMS and mean
    of new minus old in metres, the candidate's range, and its share of finite cells
    above cfg['elevation_max'], which region.json keeps."""
    n = sq = mean = over = finite = 0
    lo, hi = np.inf, -np.inf
    with rasterio.open(old_path) as a, rasterio.open(new_path) as b:
        if a.shape != b.shape:
            raise ValueError(f"grids differ: {a.shape} and {b.shape}")
        for row in range(0, a.height, COMPARE_ROWS):
            win = Window(0, row, a.width, min(COMPARE_ROWS, a.height - row))
            old, new = a.read(1, window=win), b.read(1, window=win)
            both = np.isfinite(old) & np.isfinite(new)
            d = new[both].astype("float64") - old[both]
            n += d.size
            sq += float((d * d).sum())
            mean += float(d.sum())
            ok = new[np.isfinite(new)]
            if ok.size:
                lo, hi = min(lo, float(ok.min())), max(hi, float(ok.max()))
                finite += ok.size
                over += int((ok > cfg["elevation_max"]).sum())
    return {"old_scan": scan(old_path), "new_scan": scan(new_path),
            "rms_m": (sq / n) ** 0.5 if n else 0.0, "mean_m": mean / n if n else 0.0,
            "new_min": lo, "new_max": hi, "over_max_share": over / finite if finite else 0.0}


def _inside(path, root):
    path, root = os.path.realpath(path), os.path.realpath(root)
    return path == root or path.startswith(root + os.sep)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Build a candidate DEM outside regions/.")
    ap.add_argument("region_id")
    ap.add_argument("--out", required=True)
    ap.add_argument("--regions-root", default="regions")
    args = ap.parse_args(argv)
    if _inside(args.out, args.regions_root):
        print("--out must be outside regions/: a candidate is not a plate yet.", file=sys.stderr)
        return 2
    region_dir = os.path.join(args.regions_root, args.region_id)
    bbox, crs, plan = committed_plan(region_dir)
    out_dir = os.path.join(args.out, args.region_id)
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, "dem.tif")
    rp.build_dem_cog(bbox, crs, out, plan)
    with open(os.path.join(region_dir, "region.json")) as f:
        result = compare(os.path.join(region_dir, "dem.tif"), out, json.load(f))
    with open(os.path.join(out_dir, "compare.json"), "w") as f:
        json.dump(result, f, indent=1)
    print(json.dumps(result, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
