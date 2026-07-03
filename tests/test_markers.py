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

def test_marker_ring_slider_and_size():
    # ring=0 -> no outline ring pixels; a bigger marker_diameter_in -> more disc pixels
    w = h = 400
    lum = np.zeros((h, w), np.float32)               # dark bg -> would get a PAPER ring
    base_kw = dict(marker_diameter_in=0.5)
    ringed = np.asarray(render._draw_markers(
        _blank(w, h), _spec([{"x": 500, "y": 500, "weight": 3}], **base_kw),
        lum, w, h, dpi=96).convert("RGB"))
    ringless = np.asarray(render._draw_markers(
        _blank(w, h), _spec([{"x": 500, "y": 500, "weight": 3}], marker_ring=0.0, **base_kw),
        lum, w, h, dpi=96).convert("RGB"))
    paper = lambda a: ((a[..., 0] > 230) & (a[..., 1] > 225) & (a[..., 2] > 210)).sum()
    assert paper(ringed) > 50, "no ring drawn at default"
    assert paper(ringless) < paper(ringed) / 4, "ring=0 still draws a ring"
    small = np.asarray(render._draw_markers(
        _blank(w, h), _spec([{"x": 500, "y": 500, "weight": 3}], marker_diameter_in=0.14),
        lum, w, h, dpi=96).convert("RGB"))
    gold = lambda a: ((np.abs(a[..., 0].astype(int) - 190) < 40) & (a[..., 2] < 130)).sum()
    assert gold(ringless) > gold(small) * 3, "marker size slider has no effect"

def test_photo_frame_styles(tmp_path):
    from PIL import Image as _Im
    w = h = 600
    p = tmp_path / "pic.png"
    _Im.new("RGB", (80, 80), (255, 0, 255)).save(p)
    def frame_pixels(style):
        spec = _spec([{"x": 500, "y": 500, "weight": 3, "photo": str(p)}],
                     photo_box_in=2.0, photo_frame_style=style)
        out = np.asarray(render._draw_photos(_blank(w, h), spec, w, h, dpi=96).convert("RGB"))
        cream = ((out[..., 0] > 230) & (out[..., 1] > 225) & (out[..., 2] > 200)).sum()
        magenta = ((out[..., 0] > 200) & (out[..., 1] < 80) & (out[..., 2] > 200)).sum()
        return cream, magenta
    mat_cream, mat_mag = frame_pixels("mat")
    pol_cream, pol_mag = frame_pixels("polaroid")
    bare_cream, bare_mag = frame_pixels("borderless")
    key_cream, key_mag = frame_pixels("keyline")
    assert all(m > 200 for m in (mat_mag, pol_mag, bare_mag, key_mag))  # photo lands in all
    assert pol_cream > mat_cream, "polaroid bottom mat missing"
    assert bare_cream < mat_cream / 10, "borderless still draws a mat"
    assert key_cream < mat_cream / 2, "keyline mat too heavy"
