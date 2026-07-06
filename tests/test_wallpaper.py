# tests/test_wallpaper.py
"""Wallpaper output (v1.5): a screen is a sheet with a known ppi. The spec gains
output_kind/screen_ppi/keyline/top_clear_frac; presets re-target a composed spec at
a device's exact native pixels; wallpapers render clean (no sheet furniture) and keep
auto-placed geography out of the phone clock band. The print path stays byte-identical
(output_kind defaults to "print" and every new field defaults to the old behavior)."""
import json
import os
import numpy as np
import pytest

from app import render, wallpaper
from app.geo import refit_crop_aspect
from app.serialize import spec_from_json, spec_to_json
from app.spec import CompositionSpec, SpecError, ZoomTooTightError, FINAL_DPI

REGION_DIR = "regions/lassen_ca"

# A big synthetic region so every preset's zoom-cap floor box fits comfortably.
BOUNDS = (0.0, 0.0, 300000.0, 400000.0)


def _base(**over):
    kw = dict(
        region_id="r", crs="EPSG:32610",
        crop=(100000.0, 100000.0, 154000.0, 172000.0),   # 54 x 72 km, 3:4 (clears the
                                                         # 18x24 @ 300 dpi zoom cap)
        print_w_in=18.0, print_h_in=24.0,
        native_resolution_m=10.0,
        tracks=[np.array([[101000.0, 101000.0], [129000.0, 139000.0]])],
        hotspots=[{"x": 115000.0, "y": 120000.0, "weight": 5}],
        seed=7,
    )
    kw.update(over)
    return CompositionSpec(**kw)


# ---- the spec: final_dpi() + validation of the new fields ----

def test_final_dpi_is_print_resolution_for_prints_and_ppi_for_wallpapers():
    assert _base().final_dpi() == float(FINAL_DPI)
    w = _base(output_kind="wallpaper", screen_ppi=163.0)
    assert w.final_dpi() == 163.0


def test_unknown_output_kind_rejected():
    with pytest.raises(SpecError):
        _base(output_kind="poster").validate(dpi=300)


def test_wallpaper_requires_a_plausible_screen_ppi():
    for bad in (0.0, 50.0, 1000.0, float("nan")):
        with pytest.raises(SpecError):
            _base(output_kind="wallpaper", screen_ppi=bad).validate(dpi=96)


def test_top_clear_frac_bounds_rejected():
    for bad in (-0.1, 0.5, float("nan")):
        with pytest.raises(SpecError):
            _base(top_clear_frac=bad).validate(dpi=300)


def test_new_fields_default_to_print_behavior():
    s = _base()
    assert (s.output_kind, s.screen_ppi, s.keyline, s.top_clear_frac) == \
        ("print", 0.0, True, 0.0)
    assert s.validate(dpi=300) is s


def test_wallpaper_spec_roundtrips_serialization():
    s = wallpaper.spec_for_preset(_base(), wallpaper.PRESETS["iphone"], BOUNDS)
    r = spec_from_json(spec_to_json(s))
    assert (r.output_kind, r.screen_ppi, r.keyline, r.top_clear_frac) == \
        ("wallpaper", 460.0, False, wallpaper.PHONE_TOP_CLEAR)
    assert r.crop == s.crop and r.print_w_in == s.print_w_in


# ---- refit_crop_aspect: center-preserving, aspect-exact, floored, region-clamped ----

def test_refit_preserves_center_and_hits_the_aspect():
    crop = (100000.0, 100000.0, 130000.0, 140000.0)
    out = refit_crop_aspect(crop, 16 / 9, BOUNDS)
    assert abs((out[0] + out[2]) / 2 - 115000.0) < 1e-6
    assert abs((out[1] + out[3]) / 2 - 120000.0) < 1e-6
    ar = (out[2] - out[0]) / (out[3] - out[1])
    assert abs(ar - 16 / 9) < 1e-9
    # area-preserving reshape: same terrain budget, new shape
    assert abs((out[2] - out[0]) * (out[3] - out[1]) - 30000.0 * 40000.0) < 1.0


def test_refit_grows_to_the_zoom_cap_floor():
    crop = (114000.0, 119000.0, 116000.0, 121000.0)        # tiny 2 x 2 km
    out = refit_crop_aspect(crop, 16 / 9, BOUNDS, floor_w=38400.0)  # 4K floor at 10 m
    assert (out[2] - out[0]) >= 38400.0 - 1e-6


def test_refit_stays_inside_the_region():
    crop = (1000.0, 1000.0, 31000.0, 41000.0)              # hugs the SW corner
    out = refit_crop_aspect(crop, 9 / 19.5, BOUNDS, floor_w=12000.0)
    assert out[0] >= BOUNDS[0] and out[1] >= BOUNDS[1]
    assert out[2] <= BOUNDS[2] and out[3] <= BOUNDS[3]


# ---- spec_for_preset: exact native pixels, clean furniture, style preserved ----

def test_every_preset_renders_exact_native_pixels():
    base = _base()
    for p in wallpaper.PRESETS.values():
        s = wallpaper.spec_for_preset(base, p, BOUNDS)
        assert s.pixel_size(s.final_dpi()) == (p.px_w, p.px_h), p.id
        ar = (s.crop[2] - s.crop[0]) / (s.crop[3] - s.crop[1])
        assert abs(ar - p.aspect) / p.aspect < 0.02, p.id


def test_preset_spec_goes_clean_but_keeps_the_picture():
    base = _base(track_width_pt=3.4, labels=True, title_text="Eagle Lake")
    s = wallpaper.spec_for_preset(base, wallpaper.PRESETS["iphone"], BOUNDS)
    assert (s.output_kind, s.screen_ppi) == ("wallpaper", 460.0)
    assert s.keyline is False and s.compass is False and s.title_text == ""
    assert s.top_clear_frac == wallpaper.PHONE_TOP_CLEAR
    # the picture decisions survive the re-target
    assert s.track_width_pt == 3.4 and s.labels is True and s.seed == base.seed
    assert len(s.tracks) == len(base.tracks) and s.hotspots == base.hotspots


def test_infeasible_preset_raises_the_usual_spec_error():
    # a region too small to hold the phone's zoom-cap floor box: honest 422 material,
    # never a silent clamp (same contract as a too-tight print crop)
    tiny = (0.0, 0.0, 5000.0, 5000.0)
    base = _base(crop=(1000.0, 1000.0, 3250.0, 4000.0))
    with pytest.raises(ZoomTooTightError):
        wallpaper.spec_for_preset(base, wallpaper.PRESETS["iphone"], tiny)


def test_presets_meta_is_json_ready():
    m = wallpaper.PRESETS["desktop_4k"].meta()
    assert m["px"] == [3840, 2160] and m["ppi"] == 163.0
    assert m["device_class"] == "desktop"
    json.dumps([p.meta() for p in wallpaper.PRESETS.values()])   # serializable


# ---- render: keyline toggle + the clock keep-out band (synthetic DEM via conftest) ----

def _region_spec(**kw):
    cfg = json.load(open(os.path.join(REGION_DIR, "region.json")))
    bx = cfg["bounds"]
    cx, cy = (bx[0] + bx[2]) / 2, (bx[1] + bx[3]) / 2
    base = dict(region_id="lassen_ca", crs=cfg["crs"],
                crop=(cx - 13500, cy - 18000, cx + 13500, cy + 18000),  # 27x36 km, 3:4
                print_w_in=9, print_h_in=12, native_resolution_m=10,
                tracks=[], hotspots=[], seed=7, title_text="-", compass=False)
    base.update(kw)
    return CompositionSpec(**base)


def test_keyline_off_leaves_the_sheet_unframed():
    nw = {"lakes": [], "rivers": []}
    on = np.asarray(render.rasterize(_region_spec(keyline=True), dpi=96,
                                     region_dir=REGION_DIR, hydro=nw), int)
    off = np.asarray(render.rasterize(_region_spec(keyline=False), dpi=96,
                                      region_dir=REGION_DIR, hydro=nw), int)
    inset = round(render.KEYLINE_INSET_IN * 96)
    w, h = on.shape[1], on.shape[0]
    # the two renders differ, and ONLY on the keyline ring (the frame is the sole
    # element the toggle controls) -- terrain brightness plays no part in the check
    diff = (on != off).any(axis=2)
    assert diff.any(), "keyline=True drew no frame"
    ys, xs = np.where(diff)
    on_ring = ((np.abs(ys - inset) <= 2) | (np.abs(ys - (h - 1 - inset)) <= 2) |
               (np.abs(xs - inset) <= 2) | (np.abs(xs - (w - 1 - inset)) <= 2))
    assert on_ring.all(), "keyline toggle changed pixels away from the frame"


def test_top_clear_band_keeps_auto_labels_out_of_the_clock_zone():
    cfg = json.load(open(os.path.join(REGION_DIR, "region.json")))
    nw = {"lakes": [], "rivers": []}
    spec = _region_spec(labels=True, top_clear_frac=0.0)
    banded = _region_spec(labels=True, top_clear_frac=0.30)
    # one label anchored ~15% down the sheet: inside the 30% band, clear of the edge
    ax = (spec.crop[0] + spec.crop[2]) / 2
    ay = spec.crop[3] - 0.15 * (spec.crop[3] - spec.crop[1])
    labels = {"crs": cfg["crs"], "features": [
        {"name": "Clocktop Peak", "kind": "summit", "rank": 85, "coords": [[ax, ay]]}]}
    base = np.asarray(render.rasterize(_region_spec(labels=False), dpi=96,
                                       region_dir=REGION_DIR, hydro=nw))
    with_label = np.asarray(render.rasterize(spec, dpi=96, region_dir=REGION_DIR,
                                             hydro=nw, labels=labels))
    with_band = np.asarray(render.rasterize(banded, dpi=96, region_dir=REGION_DIR,
                                            hydro=nw, labels=labels))
    assert not np.array_equal(base, with_label), "label never drew at all"
    assert np.array_equal(base, with_band), \
        "top_clear_frac must drop an auto label anchored in the clock band"
