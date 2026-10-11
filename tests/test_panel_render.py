# tests/test_panel_render.py
import json
import os

import numpy as np

from app import panels, render
from app.spec import CompositionSpec
from tests.conftest import synthetic_region

REGION_DIR = synthetic_region("lassen_ca")
DPI = 40


def _cfg():
    return json.load(open(os.path.join(REGION_DIR, "region.json")))


def _spec(n=2, gap=2.0, **kw):
    """Two panels 17 in across on the middle of the plate: 36 x 22 in at gap 2."""
    cfg = _cfg(); bx = cfg["bounds"]
    w, h = panels.sheet_sizes(2, gap)[1]
    cx = (bx[0] + bx[2]) / 2; cy = (bx[1] + bx[3]) / 2
    half = 27000.0
    crop = (cx - half, cy - half * h / w, cx + half, cy + half * h / w)
    base = dict(region_id="lassen_ca", crs=cfg["crs"], crop=crop, print_w_in=w,
                print_h_in=h, native_resolution_m=10,
                tracks=[np.array([[crop[0] + 3000, crop[1] + 3000],
                                  [crop[2] - 3000, crop[3] - 3000]])],
                hotspots=[], seed=7, title_text="-", compass=False, keyline=False,
                panels=n, panel_gap_in=gap if n > 1 else 0.0)
    base.update(kw)
    return CompositionSpec(**base)


def _render(spec, labels=None):
    return np.asarray(render.rasterize(spec, dpi=DPI, region_dir=REGION_DIR, cfg=_cfg(),
                                       hydro={"lakes": [], "rivers": []}, labels=labels))


def _seam_labels(spec):
    """One summit on the middle of the gap, and one range that crosses it."""
    cx = (spec.crop[0] + spec.crop[2]) / 2; cy = (spec.crop[1] + spec.crop[3]) / 2
    return {"crs": _cfg()["crs"], "features": [
        {"name": "Seam Peak", "kind": "summit", "rank": 100, "coords": [[cx, cy + 6000]]},
        {"name": "Seam Range", "kind": "range", "rank": 100,
         "coords": [[cx - 5000, cy - 6000], [cx, cy - 6000], [cx + 5000, cy - 6000]]},
    ]}


def test_each_panel_is_the_matching_window_of_the_unbroken_sheet():
    as_set = _spec(2, 2.0)
    unbroken = _spec(1, 2.0)
    a, b = _render(as_set), _render(unbroken)
    assert a.shape == b.shape
    for x0, y0, x1, y1 in panels.panel_rects_px(as_set, DPI):
        assert np.array_equal(a[y0:y1, x0:x1], b[y0:y1, x0:x1])


def test_no_place_name_is_drawn_in_a_seam_band():
    for gap in (2.0, 0.0):
        as_set = _spec(2, gap, labels=True)
        unbroken = _spec(1, gap, labels=True)
        names = _seam_labels(as_set)
        edge = round(render.GEO_EDGE_IN * DPI)
        band = panels.seam_bands_px(as_set, DPI, edge // 2)[0]
        x0, x1 = band[0], band[2]
        # the control: with one panel the two names do paint in the band
        plain = _render(_spec(1, gap))
        assert (_render(unbroken, names)[:, x0:x1] != plain[:, x0:x1]).any()
        # the set: nothing of a name is in the band
        bare = _render(_spec(2, gap))
        assert np.array_equal(_render(as_set, names)[:, x0:x1], bare[:, x0:x1]), gap
