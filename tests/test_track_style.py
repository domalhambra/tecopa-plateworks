# tests/test_track_style.py
# V1-10 track cartography, exercised directly on flat canvases -- no DEM needed.
# Guards the approved hybrid styling: frequency -> WIDTH counted per JOURNEY (a day's
# pause-split segments are one journey), the paper halo, and the terminus pins.
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


def _gold_band_height(out, col, tol):
    """Count pixels in one column whose color is within tol of the track ink."""
    d = np.linalg.norm(out[:, col, :].astype(float) - np.array(render.TRACK_INK, float), axis=1)
    return int((d < tol).sum())


def _ink(tracks, dpi=300, w=400, h=400, **kw):
    flat = np.full((h, w, 3), 128, np.uint8)
    return render._ink_tracks(flat, _spec(tracks, **kw), w, h, dpi)


def test_single_pass_track_is_near_solid_gold():
    out = _ink([LINE])
    # 2.6 pt at 300 dpi ~ 11 px of solid gold band...
    assert _gold_band_height(out, 200, tol=70) >= 7
    # ...and NEAR-SOLID, not a wash: the core must sit close to the ink color.
    # (The old K=1.15 single-pass opacity ~0.65 measures ~42 here; near-solid ~16.)
    core = np.linalg.norm(out[200, 200].astype(float) - np.array(render.TRACK_INK, float))
    assert core < 30, f"line core {core:.0f} from ink -- a wash, not near-solid"


def test_repeated_days_widen_the_track():
    # the "lived in" rule: 3 DISTINCT-DAY passes over the same segment widen the line
    # toward WORN_WIDTH_FACTOR x. Measured at a tight (core-only) tolerance so the
    # feathered opacity skirt of a darkening-only implementation cannot fake the
    # widening: with near-solid single-pass ink, darkening-only measures +0 here,
    # true widening measures +4 (11 -> 15 px at 300 dpi; the worn stroke's own
    # anti-aliased edge falls off the core threshold, so not the full 7 px).
    days = ["2024-06-01", "2024-06-02", "2024-06-03"]
    single = _gold_band_height(_ink([LINE]), 200, tol=30)
    worn = _gold_band_height(_ink([LINE, LINE.copy(), LINE.copy()], track_days=days),
                             200, tol=30)
    assert worn >= single + 3, f"worn {worn}px vs single {single}px -- no true widening"


def test_same_day_segments_do_not_widen():
    # a device splits one outing at auto-pause: same-day segments are ONE journey and
    # must stay base width -- coincident same-day coverage counts once, not thrice.
    days = ["2024-06-01"] * 3
    single = _gold_band_height(_ink([LINE]), 200, tol=30)
    same_day = _gold_band_height(_ink([LINE, LINE.copy(), LINE.copy()], track_days=days),
                                 200, tol=30)
    assert same_day <= single + 1, f"same-day segments widened: {same_day} vs {single}px"


def test_casing_is_light_paper_halo():
    # the halo flanking the gold must be CLEARLY lighter than the background
    out = _ink([LINE])
    col = out[:, 200, :].astype(int)
    rows = np.where(np.linalg.norm(col - np.array(render.TRACK_INK), axis=1) < 70)[0]
    above = col[rows.min() - 3]                  # sample just outside the gold edge
    assert above.sum() > 3 * 140, f"halo {above} is not a light paper halo"


def test_terminus_pins_drawn_at_track_ends():
    w = h = 400
    img = Image.new("RGBA", (w, h), (128, 128, 128, 255))
    img = render._draw_termini(img, _spec([LINE]), w, h, dpi=300)
    out = np.asarray(img.convert("RGB")).astype(int)
    # endpoints (100,500) and (900,500) in the (0,0,1000,1000) crop -> px (40,200),(360,200)
    for cx in (40, 360):
        patch = out[190:210, cx - 10:cx + 10]
        assert (patch.sum(axis=2) < 200).sum() > 10, f"no pin fill near x={cx}"
        assert (patch.sum(axis=2) > 640).sum() > 5, f"no paper ring near x={cx}"


def test_termini_are_per_journey_not_per_segment():
    # one day recorded as three sequential pause-split segments: pins belong ONLY at
    # the journey's start (100,500) and end (900,500) -- never at the mid-route
    # pause points (400,500) and (700,500).
    segs = [np.array([[100.0, 500.0], [400.0, 500.0]]),
            np.array([[400.0, 500.0], [700.0, 500.0]]),
            np.array([[700.0, 500.0], [900.0, 500.0]])]
    w = h = 400
    img = Image.new("RGBA", (w, h), (128, 128, 128, 255))
    img = render._draw_termini(img, _spec(segs, track_days=["2024-06-01"] * 3), w, h, dpi=300)
    out = np.asarray(img.convert("RGB")).astype(int)
    for cx, expect in ((40, True), (360, True), (160, False), (280, False)):
        patch = out[190:210, cx - 10:cx + 10]
        dark = (patch.sum(axis=2) < 200).sum()
        if expect:
            assert dark > 10, f"missing journey terminus near x={cx}"
        else:
            assert dark == 0, f"stray mid-route pin near x={cx} (pause point)"


def test_out_of_frame_terminus_skipped_not_crash():
    w = h = 400
    off = np.array([[-500.0, 500.0], [2000.0, 500.0]])       # both ends outside the crop
    img = Image.new("RGBA", (w, h), (128, 128, 128, 255))
    render._draw_termini(img, _spec([off]), w, h, dpi=300)   # must not raise
