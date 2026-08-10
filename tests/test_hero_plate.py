# tests/test_hero_plate.py
"""The hero-plate seams that run WITHOUT Blender: the terrain window export, the
terrain override (Cycles pixels under Tecopa ink), and the CLI's honest refusals.
The Cycles render itself is a documented manual smoke on the operator's Mac."""
import json
import os

import numpy as np
import pytest

from app import render
from app.spec import CompositionSpec

REGION_DIR = "regions/lassen_ca"


def _cfg(region_dir=REGION_DIR):
    with open(os.path.join(region_dir, "region.json")) as f:
        return json.load(f)


def _spec_for(region_dir=REGION_DIR, **kw):
    cfg = _cfg(region_dir)
    w, s, e, n = cfg["bounds"]
    cx, cy = (w + e) / 2, (s + n) / 2
    # 18 x 24 km on an 18 x 24 in sheet: 10.4 m/px at 96 dpi, just clear of the plate's
    # 10 m data floor, so the zoom cap (invariant 6) does not refuse the fixture.
    half_w, half_h = 9000.0, 12000.0
    base = dict(region_id=cfg["id"], crs=cfg["crs"],
                crop=(cx - half_w, cy - half_h, cx + half_w, cy + half_h),
                print_w_in=18.0, print_h_in=24.0,
                native_resolution_m=cfg["native_resolution_m"],
                tracks=[np.array([[cx - 4000, cy - 4000], [cx + 4000, cy + 4000]])],
                hotspots=[])
    base.update(kw)
    return CompositionSpec(**base)


def test_terrain_window_is_registration_true():
    cfg = _cfg()
    spec = _spec_for()
    elev, res_m, shape = render.terrain_window(spec, 96, REGION_DIR, cfg)
    assert elev.shape == shape and elev.dtype == np.float32
    assert not np.isnan(elev).any()
    # the window covers the crop at the render's own ground resolution
    assert res_m == pytest.approx(spec.ground_per_pixel(96), rel=1e-6)
    # and it is the PADDED window the relief renders from, not the trimmed sheet:
    # bigger than the sheet on both axes, by the render's own margin
    out_w, out_h = spec.pixel_size(96)
    assert shape[0] > out_h and shape[1] > out_w


def test_terrain_window_is_the_window_the_relief_actually_paints():
    """The whole registration argument rests on one window serving both sides, so it
    must be the same expressions _paint_terrain uses -- not a parallel derivation."""
    cfg = _cfg()
    spec = _spec_for()
    elev, res_m, shape = render.terrain_window(spec, 96, REGION_DIR, cfg)
    direct, pad_x, pad_top, pad_bot, gpp = render._read_window(
        REGION_DIR, cfg, spec.crop, *spec.pixel_size(96))
    assert res_m == gpp and shape == direct.shape
    # terrain_window repairs nodata the way shaded_relief does; compare where finite
    finite = ~np.isnan(direct)
    assert np.array_equal(elev[finite], direct.astype("float32")[finite])


def test_terrain_override_slots_under_ink_and_labels():
    cfg = _cfg()
    spec = _spec_for()
    normal = render.rasterize(spec, 96, REGION_DIR, cfg=cfg)
    elev, res_m, shape = render.terrain_window(spec, 96, REGION_DIR, cfg)
    fake = np.zeros(shape + (3,), dtype=np.uint8)
    fake[..., 0] = 200                      # unmistakable red terrain
    hero = render.rasterize(spec, 96, REGION_DIR, cfg=cfg, terrain_override=fake)
    a = np.asarray(normal).astype(int)
    b = np.asarray(hero).astype(int)
    assert a.shape == b.shape
    assert not np.array_equal(a, b)         # the terrain really was replaced
    # the route ink survives identically: the gold pixels' positions match
    gold = np.array(spec.track_rgb)
    mask_a = (np.abs(a[..., :3] - gold).sum(axis=2) < 60)
    mask_b = (np.abs(b[..., :3] - gold).sum(axis=2) < 60)
    assert mask_a.sum() > 0                 # the fixture really does ink a route
    overlap = (mask_a & mask_b).sum() / max(1, mask_a.sum())
    assert overlap > 0.85                   # registration held under the swap


def test_override_default_changes_nothing():
    cfg = _cfg()
    spec = _spec_for()
    assert np.array_equal(
        np.asarray(render.rasterize(spec, 96, REGION_DIR, cfg=cfg)),
        np.asarray(render.rasterize(spec, 96, REGION_DIR, cfg=cfg,
                                    terrain_override=None)))


def test_override_shape_and_dtype_are_checked():
    """A mis-sized override would silently mis-register the whole sheet -- refuse it."""
    cfg = _cfg()
    spec = _spec_for()
    _, _, shape = render.terrain_window(spec, 96, REGION_DIR, cfg)
    for bad in (np.zeros((shape[0] - 3, shape[1], 3), dtype=np.uint8),
                np.zeros(shape + (3,), dtype=np.float32)):
        with pytest.raises(ValueError):
            render.rasterize(spec, 96, REGION_DIR, cfg=cfg, terrain_override=bad)


def test_override_render_never_touches_the_base_cache():
    """Caller-supplied pixels are not in the cache key and never can be, so an
    override render must neither be served from the cache nor written to it (the
    caller-supplied-plate-data precedent in _base_layer)."""
    from app import basecache
    cfg = _cfg()
    spec = _spec_for()
    cache = basecache.BaseCache(max_bytes=256 * 1024 * 1024)
    elev, res_m, shape = render.terrain_window(spec, 96, REGION_DIR, cfg)
    fake = np.zeros(shape + (3,), dtype=np.uint8)
    fake[..., 1] = 220
    render.rasterize(spec, 96, REGION_DIR, cfg=cfg, base_cache=cache,
                     terrain_override=fake)
    assert cache.stats()["entries"] == 0, "an override render was cached"
    # and a normal cached render is unaffected by the override render before it
    plain = render.rasterize(spec, 96, REGION_DIR, cfg=cfg, base_cache=cache)
    assert cache.stats()["entries"] == 1
    served = render.rasterize(spec, 96, REGION_DIR, cfg=cfg, base_cache=cache)
    assert np.array_equal(np.asarray(plain), np.asarray(served))
