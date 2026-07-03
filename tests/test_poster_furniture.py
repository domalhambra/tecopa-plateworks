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


# ---- v1.2 furniture: contours + compass ----

def test_contour_interval_picks_conventional_steps():
    # ground_m_per_in ~ 0 isolates the local-relief cap: the range alone picks the step.
    assert render._contour_interval(90, 0.0) == 5        # 18 lines
    assert render._contour_interval(985, 0.0) == 50      # ~20 lines
    assert render._contour_interval(3000, 0.0) == 200
    assert render._contour_interval(60000, 0.0) == 2000  # beyond the table


def test_contour_interval_tracks_map_scale():
    # Dom: the interval must follow the zoom -- fine when zoomed into one valley, coarse
    # across a whole corridor -- so lines stay legible up close and don't mat when far.
    # Same terrain range (500 m), three zooms: the interval grows as the sheet zooms out.
    zoomed_in = render._contour_interval(500, 200)     # ~0.2 km/in -> a single valley
    mid = render._contour_interval(500, 800)           # ~0.8 km/in
    zoomed_out = render._contour_interval(500, 4000)   # ~4 km/in -> a whole corridor
    assert zoomed_in < mid < zoomed_out, (zoomed_in, mid, zoomed_out)
    assert (zoomed_in, mid, zoomed_out) == (20, 50, 200)


def test_contours_draw_on_slope_not_on_flat():
    # a uniform slope gets evenly spaced ink lines; dead-flat ground gets none --
    # even when the flat sits EXACTLY on a contour level (the flood case).
    h = w = 200
    slope = np.tile(np.linspace(1000, 1500, w, dtype="float32"), (h, 1))
    flat = np.full((h, w), 1200.0, dtype="float32")     # exactly on a 50 m level
    base = np.full((h, w, 3), 180, np.uint8)
    out_slope = render._draw_contours(base.copy(), slope, dpi=96, ground_m_per_in=200.0)
    out_flat = render._draw_contours(base.copy(), flat, dpi=96, ground_m_per_in=200.0)
    assert (out_slope != base).any(), "no contour ink on a slope"
    changed_cols = np.unique(np.where((out_slope != base).any(axis=2))[1])
    assert len(changed_cols) < w * 0.5, "contours shade the slope instead of lining it"
    assert np.array_equal(out_flat, base), "flat ground flooded with contour ink"


def test_contours_off_by_default_in_spec():
    from app.spec import CompositionSpec
    s = _spec()
    assert s.contours is False and s.compass is True


def test_compass_draws_above_title_block_and_toggles_off():
    w, h = 500, 600
    spec = _spec(title_text="Eagle Lake", print_w_in=10, print_h_in=12)
    img = render._draw_compass(_blank(w, h), spec, w, h, dpi=96)
    out = np.asarray(img.convert("RGB")).astype(int)
    fdpi = 96 * render._furniture_scale(spec)      # furniture scales with the sheet
    inset = round(render.TITLE_INSET_IN * fdpi)
    R = render.COMPASS_DIAMETER_IN * fdpi / 2
    cx = int(inset + R)
    band = out[h - inset - 260:h - inset - 20, max(0, cx - 60):cx + 60]
    dark = (band.sum(axis=2) < 260).sum()                # umber half-points / ring
    paper = ((band[..., 0] > 230) & (band[..., 1] > 225) & (band[..., 2] > 210)).sum()
    assert dark > 30, "no compass ink at bottom-left"
    assert paper > 100, "no paper ground/halves at bottom-left"
    # toggled off -> untouched sheet
    base = np.asarray(_blank(w, h).convert("RGB"))
    off = render._draw_compass(_blank(w, h), _spec(compass=False), w, h, dpi=96)
    assert np.array_equal(base, np.asarray(off.convert("RGB")))


# ---- furniture scales with the sheet (Dom): same crop, bigger print -> bigger
# compass/cartouche, but the scale bar keeps telling the truth ----

def test_furniture_scale_tracks_sheet_size():
    assert render._furniture_scale(_spec(print_w_in=18, print_h_in=24)) == 1.0
    big = render._furniture_scale(_spec(print_w_in=24, print_h_in=36))
    assert abs(big - (864 / 432) ** 0.5) < 1e-9                  # sqrt(area ratio)
    assert render._furniture_scale(_spec(print_w_in=9, print_h_in=12)) == \
        render.FURNITURE_SCALE_MIN                               # clamped, not tiny
    assert render._furniture_scale(_spec(print_w_in=60, print_h_in=90)) == \
        render.FURNITURE_SCALE_MAX


def test_cartouche_and_compass_grow_with_print_size():
    from PIL import ImageDraw
    d = ImageDraw.Draw(_blank(100, 100), "RGBA")
    small = _spec(title_text="Eagle Lake", print_w_in=18, print_h_in=24)
    large = _spec(title_text="Eagle Lake", print_w_in=24, print_h_in=36)
    ms = render._title_block_metrics(small, d, dpi=96)
    ml = render._title_block_metrics(large, d, dpi=96)
    assert ml["bh"] > ms["bh"] * 1.2 and ml["tw"] > ms["tw"] * 1.2


def test_furniture_slider_multiplies_the_auto_scale():
    # the Style panel's "Legend & compass size" knob rides the spec and multiplies
    # the sheet-appropriate automatic scale -- proof == final, and 1.0 is a no-op
    base = _spec(print_w_in=18, print_h_in=24)
    assert render._furniture_scale(base) == 1.0
    assert render._furniture_scale(_spec(print_w_in=18, print_h_in=24,
                                         furniture_scale=1.4)) == 1.4
    big = _spec(print_w_in=24, print_h_in=36, furniture_scale=0.75)
    assert abs(render._furniture_scale(big) - (864 / 432) ** 0.5 * 0.75) < 1e-9


def test_scale_bar_stays_truthful_when_furniture_scales():
    # 32 km crop over 18 in at 96 dpi -> gpp is fixed by the picture, not the furniture:
    # a scaled bar may pick a LONGER nice mileage, but its px length must equal
    # miles * 1609.344 / gpp exactly, or the printed bar lies.
    s = _spec(print_w_in=18, print_h_in=24)
    gpp = (s.crop[2] - s.crop[0]) / (s.print_w_in * 96)
    for fs in (1.0, 1.41, 2.0):
        miles, px = render._scale_bar_miles(s, 96, fs)
        assert abs(px - miles * 1609.344 / gpp) < 1e-6
