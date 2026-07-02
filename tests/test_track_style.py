# tests/test_track_style.py
# V1-10 track cartography, exercised directly on flat canvases -- no DEM needed.
# Guards the approved hybrid styling: frequency -> WIDTH (worn paths widen), the
# paper halo, and the journey terminus pins.
import numpy as np
from PIL import Image
from app.spec import CompositionSpec
from app import render


def _spec(tracks, **kw):
    return CompositionSpec(
        region_id="t", crs="EPSG:32610", crop=(0, 0, 1000, 1000),
        print_w_in=10, print_h_in=10, native_resolution_m=10,
        tracks=tracks, hotspots=[], seed=7, **kw)


LINE = np.array([[100.0, 500.0], [900.0, 500.0]])   # horizontal, mid-canvas


def _gold_band_height(out, col, ink=render.TRACK_INK, tol=70.0):
    """Count pixels in one column whose color is near the track ink."""
    d = np.linalg.norm(out[:, col, :].astype(float) - np.array(ink, float), axis=1)
    return int((d < tol).sum())


def _ink(tracks, dpi=300, w=400, h=400):
    flat = np.full((h, w, 3), 128, np.uint8)
    return render._ink_tracks(flat, _spec(tracks), w, h, dpi)


def test_single_pass_track_is_near_solid_gold():
    out = _ink([LINE])
    # 2.6 pt at 300 dpi ~ 11 px; the line must read as a solid gold band, not a wash
    band = _gold_band_height(out, 200)
    assert band >= 7, f"gold band only {band}px tall"


def test_repeated_days_widen_the_track():
    # the "lived in" rule: 3 distinct passes over the same segment widen the line
    # toward WORN_WIDTH_FACTOR x, instead of only darkening (V1-10).
    single = _gold_band_height(_ink([LINE]), 200)
    worn = _gold_band_height(_ink([LINE, LINE.copy(), LINE.copy()]), 200)
    assert worn >= single + 4, f"worn {worn}px vs single {single}px -- no widening"


def test_casing_is_light_paper_halo():
    # the halo flanking the gold must be LIGHTER than the background (paper, not umber)
    out = _ink([LINE])
    col = out[:, 200, :].astype(int)
    rows = np.where(np.linalg.norm(col - np.array(render.TRACK_INK), axis=1) < 70)[0]
    above = col[rows.min() - 3]                  # sample just outside the gold edge
    assert above.sum() > 3 * 128, f"halo {above} is darker than the background"


def test_terminus_pins_drawn_at_track_ends():
    w = h = 400
    img = Image.new("RGBA", (w, h), (128, 128, 128, 255))
    img = render._draw_termini(img, _spec([LINE]), w, h, dpi=300)
    out = np.asarray(img.convert("RGB")).astype(int)
    # endpoints (100,500) and (900,500) in the (0,0,1000,1000) crop -> px (40,200),(360,200)
    for cx in (40, 360):
        patch = out[190:210, cx - 10:cx + 10]
        dark = (patch.sum(axis=2) < 200).sum()               # umber pin fill
        bright = (patch.sum(axis=2) > 640).sum()             # paper ring
        assert dark > 10, f"no pin fill near x={cx}"
        assert bright > 5, f"no paper ring near x={cx}"


def test_out_of_frame_terminus_skipped_not_crash():
    w = h = 400
    off = np.array([[-500.0, 500.0], [2000.0, 500.0]])       # both ends outside the crop
    img = Image.new("RGBA", (w, h), (128, 128, 128, 255))
    render._draw_termini(img, _spec([off]), w, h, dpi=300)   # must not raise
