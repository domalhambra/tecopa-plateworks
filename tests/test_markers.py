# tests/test_markers.py
# Rich-marker drawing (labels, vector icons, pinned photos) exercised directly on
# blank canvases -- no DEM needed, so these run on a fresh clone.
import numpy as np
from PIL import Image
from app.spec import CompositionSpec
from app import render

def _spec(hotspots, **kw):
    return CompositionSpec(
        region_id="t", crs="EPSG:32610", crop=(0, 0, 1000, 1000),
        print_w_in=10, print_h_in=10, native_resolution_m=10,
        tracks=[], hotspots=hotspots, seed=7, **kw)

def _blank(w, h):
    return Image.new("RGBA", (w, h), (128, 128, 128, 255))

def test_each_icon_draws_ink():
    w = h = 400
    lum = np.ones((h, w), np.float32)                  # light bg -> dark ring + ink
    for icon in ("peak", "camp", "water", "flag", "camera", "star"):
        spec = _spec([{"x": 500, "y": 500, "weight": 3, "icon": icon}],
                     marker_diameter_in=0.8)
        out = np.asarray(render._draw_markers(_blank(w, h), spec, lum, w, h, dpi=96).convert("RGB"))
        # gold disc present, and dark glyph ink somewhere inside it
        gold = (np.abs(out[..., 0].astype(int) - 190) < 40) & (out[..., 2] < 130)
        dark = (out.sum(axis=2) < 200)
        assert gold.sum() > 50, icon
        assert dark.sum() > 5, icon

def test_label_renders_plate_and_text():
    w = h = 400
    lum = np.ones((h, w), np.float32)
    spec = _spec([{"x": 200, "y": 500, "weight": 3, "label": "Eagle Lake"}],
                 marker_diameter_in=0.4, label_pt=24)
    base = np.asarray(_blank(w, h).convert("RGB"))
    out = np.asarray(render._draw_markers(_blank(w, h), spec, lum, w, h, dpi=96).convert("RGB"))
    assert not np.array_equal(base, out)               # something was drawn
    cream = (out[..., 0] > 225) & (out[..., 1] > 220) & (out[..., 2] > 200)
    assert cream.sum() > 100                            # the cream label plate

def test_photo_pin_composites_and_tolerates_missing(tmp_path):
    w = h = 600
    p = tmp_path / "pic.png"
    Image.new("RGB", (80, 80), (255, 0, 255)).save(p)   # vivid magenta, not in any palette
    spec = _spec([{"x": 500, "y": 500, "weight": 3, "photo": str(p)}], photo_box_in=2.0)
    out = np.asarray(render._draw_photos(_blank(w, h), spec, w, h, dpi=96).convert("RGB"))
    magenta = (out[..., 0] > 200) & (out[..., 1] < 80) & (out[..., 2] > 200)
    assert magenta.sum() > 200                          # the photo thumbnail landed

    # a missing file must not crash the render -- it is simply skipped
    spec2 = _spec([{"x": 500, "y": 500, "weight": 3, "photo": str(tmp_path / "nope.png")}])
    render._draw_photos(_blank(w, h), spec2, w, h, dpi=96)
