# scripts/measure_final.py
"""Render one large final and print its peak memory: the gate for panel sets.

A set is painted as one sheet and then cut, so its largest sheet (59 x 22 in at
300 dpi, 116.8 megapixels) must fit in memory. This renders that sheet on a real
plate and prints one JSON line. Exit 0 when the peak is under the limit.

The line's `peak_gb` is the peak RESIDENT memory, in units of 2**30 bytes. On macOS
it reads too low when the system compresses memory: on 2026-10-11 it said 14.07 for
a render whose footprint was 22.8 GB. So run this under `/usr/bin/time -l` and judge
the line "peak memory footprint" (bytes), not this script's own `pass`."""
import argparse
import json
import os
import resource
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import numpy as np  # noqa: E402

from app.spec import FINAL_DPI, MAX_UPSAMPLE, CompositionSpec  # noqa: E402


def centred_crop(bounds, aspect, min_w):
    """The largest crop of `aspect` (width / height) centred in `bounds`."""
    bw, bh = bounds[2] - bounds[0], bounds[3] - bounds[1]
    w = min(bw, bh * aspect)
    if w < min_w:
        raise SystemExit(f"region too small: the sheet needs {min_w / 1000:.1f} km "
                         f"across and the region holds {w / 1000:.1f} km")
    h = w / aspect
    cx, cy = (bounds[0] + bounds[2]) / 2, (bounds[1] + bounds[3]) / 2
    return (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)


def peak_gb(ru_maxrss, platform=sys.platform):
    """ru_maxrss is bytes on macOS and KiB on Linux."""
    return round(ru_maxrss / (1024 ** 3 if platform == "darwin" else 1024 ** 2), 2)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--region", default="rifle_aspen")
    ap.add_argument("--w", type=float, default=59.0, help="sheet width, inches")
    ap.add_argument("--h", type=float, default=22.0, help="sheet height, inches")
    ap.add_argument("--limit-gb", type=float, default=16.0)
    a = ap.parse_args(argv)
    from app import render
    region_dir = os.path.join(ROOT, "regions", a.region)
    with open(os.path.join(region_dir, "region.json")) as f:
        cfg = json.load(f)
    floor_w = cfg["native_resolution_m"] / MAX_UPSAMPLE * round(a.w * FINAL_DPI) * 1.001
    crop = centred_crop(cfg["bounds"], a.w / a.h, floor_w)
    track = np.array([[crop[0] + 2000.0, crop[1] + 2000.0],
                      [crop[2] - 2000.0, crop[3] - 2000.0]])
    spec = CompositionSpec(
        region_id=cfg["id"], crs=cfg["crs"], crop=crop, print_w_in=a.w, print_h_in=a.h,
        native_resolution_m=cfg["native_resolution_m"], tracks=[track], hotspots=[],
        seed=7, title_text="Memory gate", contours=True,
        labels=os.path.isfile(os.path.join(region_dir, "labels.json")),
        biome=os.path.isfile(os.path.join(region_dir, "landcover.tif")))
    started = time.monotonic()
    img = render.rasterize(spec, dpi=FINAL_DPI, region_dir=region_dir,
                           watermark=False, cfg=cfg)
    peak = peak_gb(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    ok = peak < a.limit_gb
    print(json.dumps({"region": a.region, "sheet_in": [a.w, a.h],
                      "pixels_mp": round(img.size[0] * img.size[1] / 1e6, 1),
                      "seconds": round(time.monotonic() - started, 1),
                      "peak_gb": peak, "limit_gb": a.limit_gb, "pass": ok}))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
