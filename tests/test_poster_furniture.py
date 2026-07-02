# tests/test_poster_furniture.py
# Finished-sheet furniture (V1-10 print-correctness): the keyline frame, the title
# block with its deterministic stats caption. Blank canvases -- no DEM needed.
import numpy as np
from PIL import Image
from app.spec import CompositionSpec
from app import render


def _spec(**kw):
    base = dict(region_id="t", crs="EPSG:32610", crop=(0.0, 0.0, 32000.0, 32000.0),
                print_w_in=10, print_h_in=10, native_resolution_m=10,
                tracks=[], hotspots=[], seed=7)
    base.update(kw)
    return CompositionSpec(**base)


def _blank(w=500, h=500):
    return Image.new("RGBA", (w, h), (128, 128, 128, 255))


def test_stats_line_is_deterministic_and_complete():
    # 32 km over 10 in -> ratio 32000/0.254 = 125,984 -> nice-rounded 130,000
    line = np.array([[0.0, 0.0], [16093.44, 0.0]])           # exactly 10 miles
    s = _spec(tracks=[line, line.copy()],
              track_days=["2024-06-01", "2024-06-02"])
    out = render._stats_line(s, dpi=96)
    assert out == "~1:130,000 · 2 DAYS · 20 MI", out


def test_stats_line_omits_missing_parts():
    s = _spec()                                              # no tracks, no days
    out = render._stats_line(s, dpi=96)
    assert out.startswith("~1:") and "DAY" not in out and "MI" not in out


def test_title_block_draws_plate_and_caption():
    w = h = 500
    img = render._draw_title_block(_blank(w, h), _spec(title_text="Eagle Lake"), w, h, dpi=96)
    out = np.asarray(img.convert("RGB"))
    # bottom-left corner region holds the cream plate with dark text on it
    corner = out[h - 120:h - 20, 20:260]
    cream = (corner[..., 0] > 225) & (corner[..., 1] > 220) & (corner[..., 2] > 200)
    dark = corner.sum(axis=2) < 260
    assert cream.sum() > 400, "no title plate"
    assert dark.sum() > 40, "no title ink"


def test_empty_title_draws_nothing():
    w = h = 500
    base = np.asarray(_blank(w, h).convert("RGB")).copy()
    img = render._draw_title_block(_blank(w, h), _spec(title_text=""), w, h, dpi=96)
    assert np.array_equal(base, np.asarray(img.convert("RGB")))


def test_keyline_frames_the_sheet():
    w = h = 500
    img = render._draw_keyline(_blank(w, h), w, h, dpi=96)
    out = np.asarray(img.convert("RGB")).astype(int)
    inset = round(render.KEYLINE_INSET_IN * 96)              # 24 px
    # dark frame pixels along all four edges at the inset; interior untouched
    assert (out[inset, inset:w - inset].sum(axis=1) < 300).mean() > 0.9
    assert (out[h - 1 - inset, inset:w - inset].sum(axis=1) < 300).mean() > 0.9
    assert (out[inset:h - inset, inset].sum(axis=1) < 300).mean() > 0.9
    assert (out[inset:h - inset, w - 1 - inset].sum(axis=1) < 300).mean() > 0.9
    assert (out[h // 2, w // 2] == [128, 128, 128]).all()
