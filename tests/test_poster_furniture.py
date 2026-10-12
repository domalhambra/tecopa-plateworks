# tests/test_poster_furniture.py
# Finished-sheet furniture (V1-10 print-correctness): the keyline frame, the title
# block with its deterministic stats caption. Blank canvases -- no DEM needed.
import numpy as np
import pytest
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


def test_contours_blend_the_same_at_any_band_size_and_leave_the_sheet_alone(monkeypatch):
    # The contour blend runs in bands of rows in its own float buffer (the memory
    # trim). One band is the whole-array blend; short bands must give the same bytes,
    # and the sheet handed in is read, never written.
    from app import relief
    h, w = 300, 120
    yy, xx = np.mgrid[0:h, 0:w].astype("float32")
    elev = 1000.0 + 3.0 * xx + 40.0 * np.sin(yy / 20.0)
    rng = np.random.default_rng(5)
    sheet = rng.integers(0, 256, (h, w, 3), dtype=np.uint8)
    kept = sheet.copy()
    monkeypatch.setattr(relief, "BAND_ROWS", 10 ** 9)
    whole = render._draw_contours(sheet, elev, dpi=96, ground_m_per_in=200.0)
    assert (whole != sheet).any(), "no contour ink to blend"
    for rows in (1, 7, 256):
        monkeypatch.setattr(relief, "BAND_ROWS", rows)
        assert np.array_equal(whole, render._draw_contours(sheet, elev, dpi=96,
                                                           ground_m_per_in=200.0))
    assert np.array_equal(sheet, kept)


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

def _scale(w, h, **kw):
    return render._furniture_scale(_spec(print_w_in=w, print_h_in=h, **kw))


def test_furniture_scale_tracks_sheet_size():
    # literal values, so a changed base, floor or ceiling fails here by number:
    # sqrt(sheet area / 374 in2), held between 0.80 and 2.0
    assert _scale(17, 22) == 1.0                                 # the design sheet
    assert _scale(18, 24) == pytest.approx(1.0747466, abs=1e-6)  # sqrt(432 / 374)
    assert _scale(24, 36) == pytest.approx(1.5199212, abs=1e-6)  # sqrt(864 / 374)
    assert _scale(9, 12) == pytest.approx(0.80)                  # the floor, not tiny
    assert _scale(36, 48) == 2.0                                 # the ceiling: raw 2.149
    assert _scale(60, 90) == 2.0


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
    assert _scale(17, 22) == 1.0                                 # 1.0 is a no-op
    assert _scale(17, 22, furniture_scale=1.4) == 1.4            # the slider alone
    assert _scale(24, 36, furniture_scale=0.75) == pytest.approx(1.1399409, abs=1e-6)
    assert _scale(11, 17, furniture_scale=1.5) == pytest.approx(1.2)   # the floor, times 1.5


def test_scale_bar_stays_truthful_when_furniture_scales():
    # 32 km crop over 18 in at 96 dpi -> gpp is fixed by the picture, not the furniture:
    # a scaled bar may pick a LONGER nice mileage, but its px length must equal
    # miles * 1609.344 / gpp exactly, or the printed bar lies.
    s = _spec(print_w_in=18, print_h_in=24)
    gpp = (s.crop[2] - s.crop[0]) / (s.print_w_in * 96)
    for fs in (1.0, 1.41, 2.0):
        miles, px = render._scale_bar_miles(s, 96, fs)
        assert abs(px - miles * 1609.344 / gpp) < 1e-6


# ---- the label keep-out covers the furniture as drawn (sample-kit finding #5) ----

def _painted(spec, w, h, dpi):
    """Boolean mask of every pixel the cartouche and compass paint on a clear sheet."""
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    img = render._draw_title_block(img, spec, w, h, dpi)
    img = render._draw_compass(img, spec, w, h, dpi)
    return np.asarray(img)[..., 3] > 0


def _kept_out(spec, w, h, dpi):
    from PIL import ImageDraw
    d = ImageDraw.Draw(Image.new("RGBA", (w, h)))
    mask = np.zeros((h, w), bool)
    for x0, y0, x1, y1 in render._label_keepout(spec, d, w, h, dpi):
        mask[max(0, y0):max(0, y1), max(0, x0):max(0, x1)] = True
    return mask


def test_label_keepout_covers_the_drawn_title_block_and_compass():
    # The keep-out was a fixed 3.4 x 2.5 in guess; the Tecopa cartouche is about
    # 5.9 in wide, so "...G HILLS" ran under it. Every painted pixel of the stack
    # must sit inside the keep-out, for a long title and for the compass alone.
    dpi = 40
    for kw in ({"title_text": "Tecopa and the Amargosa Country, California"},
               {"title_text": "Tecopa", "credit_text": "Terrain USGS 3DEP - "
                "Water USGS NHD - Land cover NLCD 2021 - Names USGS GNIS"},
               {"title_text": "", "compass": True}):
        spec = _spec(print_w_in=18, print_h_in=24, **kw)
        w, h = spec.pixel_size(dpi)
        painted = _painted(spec, w, h, dpi)
        assert painted.any()
        uncovered = painted & ~_kept_out(spec, w, h, dpi)
        assert not uncovered.any(), (kw, int(uncovered.sum()))


def test_label_keepout_does_not_blot_the_sheet_beyond_the_stack():
    # measured, not padded: the keep-out is no larger than the drawn stack's own
    # boxes, so a short title frees the ground beside it for names
    dpi = 40
    spec = _spec(print_w_in=18, print_h_in=24, title_text="Tecopa")
    w, h = spec.pixel_size(dpi)
    ys, xs = np.nonzero(_painted(spec, w, h, dpi))
    ky, kx = np.nonzero(_kept_out(spec, w, h, dpi))
    assert kx.max() <= xs.max() + 1 and ky.min() >= ys.min() - 1


def test_the_two_sheets_on_the_menu_set_the_furniture_scale():
    """The menu is 17 x 22 and 11 x 17 (decisions, 2026-10-10). The large sheet is
    the design size. The small sheet stops at the floor."""
    assert render.FURNITURE_BASE_IN2 == 17.0 * 22.0
    assert render._furniture_scale(_spec(print_w_in=17, print_h_in=22)) == 1.0
    assert render._furniture_scale(_spec(print_w_in=22, print_h_in=17)) == 1.0
    assert render._furniture_scale(_spec(print_w_in=11, print_h_in=17)) == pytest.approx(0.80)
    assert render.FURNITURE_SCALE_MIN == 0.80 and render.FURNITURE_SCALE_MAX == 2.0


def test_the_smallest_furniture_text_on_the_smallest_sheet_is_six_points():
    """The credit line is the smallest furniture text: label_pt x 0.62. At the floor
    it must still be legible on paper."""
    spec = _spec(print_w_in=11, print_h_in=17)
    assert spec.label_pt * 0.62 * render._furniture_scale(spec) >= 6.0
