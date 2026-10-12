# tests/test_render_memory.py
"""The live memory of a final, in bytes for each output pixel.

A final holds its whole padded window in memory, and the largest sheet a set renders
is 116.8 megapixels, so the bytes a render holds for each pixel decide whether that
sheet fits in the 16 GB agreed for it. On 2026-10-11 the relief was trimmed from 115
to 140 live bytes a pixel to 75 to 81 (docs/relief-passes.md, "Memory"). Nothing else
would notice if that were lost: an array kept alive one stage too long, or a banded
block written back as a whole-sheet expression, moves no pixel and fails no other
test. These tests render a small sheet and hold the number.

Why tracemalloc, and not the footprint of the process. tracemalloc counts the Python
and NumPy allocations that are live, which is exactly what the trim changes, and with
one relief worker the count is the same on every run. The footprint is not: the macOS
allocator keeps freed large blocks counted against the process, so it reads about
60 bytes a pixel above the live figure and moves from run to run, and on Linux the
number means something else again. tracemalloc does not see memory that a C library
takes for itself (Pillow's images, scipy's line buffers, GDAL's block cache), so the
bounds below are for the engine's own arrays and are not a size for the process.

Each bound is about 15 % above the value measured on the day of the trim, and far
below the value before it. A change that raises a number on purpose (a new full-sheet
plane that a pass really needs) updates the bound in the same commit and says why. One
relief worker, so the peak does not depend on which passes happen to overlap."""
import json
import os
import tracemalloc

import numpy as np
import pytest

from app import relief, render
from app.spec import CompositionSpec
from tests.conftest import synthetic_region

REGION_DIR = synthetic_region("lassen_ca")
DPI = 300
SHEET_IN = (9.0, 12.0)              # 2700 x 3600 px: 9.7 megapixels


def _cfg():
    with open(os.path.join(REGION_DIR, "region.json")) as f:
        return json.load(f)


def _spec(width_m, **kw):
    """A 9 x 12 in sheet centred on the plate, `width_m` of ground across. Place names
    are off and every look is at its spec default unless `kw` says otherwise."""
    cfg = _cfg()
    b = cfg["bounds"]
    cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
    w, h = width_m, width_m * SHEET_IN[1] / SHEET_IN[0]
    crop = (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)
    d = dict(region_id=cfg["id"], crs=cfg["crs"], crop=crop,
             print_w_in=SHEET_IN[0], print_h_in=SHEET_IN[1],
             native_resolution_m=cfg["native_resolution_m"],
             tracks=[np.array([[crop[0] + 2000, crop[1] + 2000],
                               [crop[2] - 2000, crop[3] - 2000]])],
             hotspots=[], seed=7, title_text="Memory")
    d.update(kw)
    return CompositionSpec(**d)


def traced_peak_per_pixel(spec, dpi=DPI):
    """Peak live bytes of one `rasterize`, for each pixel of the sheet it returns."""
    cfg = _cfg()
    already = tracemalloc.is_tracing()          # e.g. python -X tracemalloc
    if not already:
        tracemalloc.start()
    try:
        tracemalloc.reset_peak()
        start = tracemalloc.get_traced_memory()[0]
        img = render.rasterize(spec, dpi=dpi, region_dir=REGION_DIR, cfg=cfg)
        peak = tracemalloc.get_traced_memory()[1] - start
    finally:
        if not already:
            tracemalloc.stop()
    return peak / (img.size[0] * img.size[1])


# case -> (ground width in metres, spec fields, bound in bytes a pixel).
# Measured 2026-10-11 on this synthetic plate with one relief worker, at the commit
# before the trim (4a28e58) and after it; the same to 0.01 on a second run:
#   the default look            115.41 ->  75.27
#   land cover and contours     135.48 ->  75.26
#   the golden grade            140.49 ->  80.52
#   terrain depth               115.41 ->  75.26
CASES = {
    "the default look": (27_000.0, {}, 87.0),
    "land cover and contours": (27_000.0, dict(biome=True, contours=True), 87.0),
    "the golden grade": (27_000.0, dict(light_mode="journey", sun_azimuth_deg=250.0,
                                        sun_altitude_deg=18.0, golden_strength=0.7), 93.0),
    # 57 km on 9 in is 1:249,000, where the scale-keyed depth pass is on
    "terrain depth": (57_000.0, {}, 87.0),
}


@pytest.mark.parametrize("case", list(CASES))
def test_a_final_holds_few_live_bytes_for_each_pixel(case, monkeypatch):
    width_m, fields, bound = CASES[case]
    monkeypatch.setattr(relief, "RELIEF_WORKERS", 1)     # a stable peak (see above)
    spec = _spec(width_m, **fields)
    if case == "terrain depth":
        assert render._terrain_depth(spec) > 0.2, "this crop must switch the depth pass on"
    got = traced_peak_per_pixel(spec)
    assert got < bound, (
        f"{case}: a 9 x 12 in final held {got:.1f} live bytes for each output pixel at "
        f"its peak, and the bound is {bound:.0f}. A full-sheet array is alive longer "
        f"than it is read, or a per-pixel block builds sheet-sized temporaries again "
        f"(docs/relief-passes.md, Memory).")


def test_the_measure_sees_a_full_sheet_array(monkeypatch):
    """The gauge itself: one more RGB float plane kept alive through the relief must
    show as about 15 bytes a pixel (12, times the 1.25 of the padded window), and that
    is enough to break the bound. If the number did not move, the test above could
    not fail either."""
    monkeypatch.setattr(relief, "RELIEF_WORKERS", 1)
    spec = _spec(27_000.0)
    lean = traced_peak_per_pixel(spec)
    real = relief.base_colour
    held = []

    def hoarding(*a, **kw):
        base = real(*a, **kw)
        held.append(base.copy())                # a plane nothing reads, never freed
        return base

    monkeypatch.setattr(relief, "base_colour", hoarding)
    wasteful = traced_peak_per_pixel(spec)
    held.clear()
    assert wasteful > lean + 10
    assert wasteful > CASES["the default look"][2]
