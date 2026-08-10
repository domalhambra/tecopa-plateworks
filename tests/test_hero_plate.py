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


# ---- the scene, as pure math (no Blender anywhere in this file) --------------------

def test_scene_params_are_derived_from_the_window_not_the_crop():
    """Registration lives or dies here: Cycles must render the PADDED window, at that
    window's pixel count, over that window's ground extent -- deriving any of it from
    spec.crop / spec.pixel_size would drop the render margin and shift the sheet."""
    from scripts.hero_plate import scene_params
    cfg = _cfg()
    spec = _spec_for()
    elev, res_m, shape = render.terrain_window(spec, 96, REGION_DIR, cfg)
    p = scene_params(shape, res_m, 315.0, 45.0, samples=256)
    assert p["resolution"] == [shape[1], shape[0]]        # w, h -- and it IS the window
    assert p["plane_size"] == [pytest.approx(shape[1] * res_m),
                               pytest.approx(shape[0] * res_m)]
    # portrait sheet -> Blender's ortho_scale is the frame's LARGER dimension, so the
    # ground HEIGHT. (The crop width would have been wrong by the full aspect ratio.)
    assert shape[0] > shape[1]
    assert p["ortho_scale"] == pytest.approx(shape[0] * res_m)
    assert p["samples"] == 256


def test_scene_params_take_the_ground_width_on_a_landscape_sheet():
    from scripts.hero_plate import scene_params
    p = scene_params((600, 900), 10.0, 315.0, 45.0, samples=16)
    assert p["ortho_scale"] == pytest.approx(9000.0)      # width, this time


@pytest.mark.parametrize("az,alt", [(315.0, 45.0), (0.0, 30.0), (90.0, 20.0),
                                    (180.0, 60.0), (140.0, 22.0)])
def test_sun_euler_points_at_the_sun(az, alt):
    """The euler handed to Blender must rotate a SUN lamp's +Z onto the vector toward
    the sun. Asserting the physics rather than the formula is what catches the
    east-west mirror that the intuitive `-azimuth` produces."""
    import math
    from scripts.hero_plate import sun_rotation_euler, sun_vector
    rx, ry, rz = sun_rotation_euler(az, alt)
    # Blender XYZ euler: R = Rz . Ry . Rx
    def _rot(a, axis):
        c, s = math.cos(a), math.sin(a)
        if axis == "x":
            return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])
        if axis == "y":
            return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])
        return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])
    got = (_rot(rz, "z") @ _rot(ry, "y") @ _rot(rx, "x")) @ np.array([0.0, 0.0, 1.0])
    np.testing.assert_allclose(got, np.array(sun_vector(az, alt)), atol=1e-12)


def test_sun_angles_follow_the_light_the_poster_was_painted_with():
    from scripts.hero_plate import sun_angles
    cfg = _cfg()
    assert sun_angles(_spec_for(), cfg) == (cfg["light_azimuth"], cfg["light_altitude"])
    j = _spec_for(light_mode="journey", sun_azimuth_deg=140.0, sun_altitude_deg=22.0)
    assert sun_angles(j, cfg) == (140.0, 22.0)


# ---- the textures Blender reads ----------------------------------------------------

def test_heightmap_round_trips_the_elevation(tmp_path):
    from scripts.hero_plate import write_heightmap
    from PIL import Image
    cfg = _cfg()
    spec = _spec_for()
    elev, res_m, shape = render.terrain_window(spec, 96, REGION_DIR, cfg)
    p = str(tmp_path / "h.png")
    lo, hi = write_heightmap(p, elev)
    q = np.asarray(Image.open(p))
    assert q.dtype == np.uint16 and q.shape == shape
    back = lo + q.astype("float64") / 65535.0 * (hi - lo)
    # 16 bits over the window's range: the error must be under half a quantum
    assert np.abs(back - elev).max() <= (hi - lo) / 65535.0
    assert lo == pytest.approx(float(elev.min())) and hi == pytest.approx(float(elev.max()))


def test_colour_texture_is_the_engines_own_unlit_palette(tmp_path):
    """The hero sheet must wear the archival sheet's colours -- Cycles supplies only
    the light. So the texture is relief.base_colour, the very expression the "color"
    stage of shaded_relief uses, and nothing that shades."""
    from scripts.hero_plate import write_color_texture
    from PIL import Image
    from app import relief
    cfg = _cfg()
    spec = _spec_for()
    elev, res_m, shape = render.terrain_window(spec, 96, REGION_DIR, cfg)
    p = str(tmp_path / "c.png")
    write_color_texture(p, spec, 96, REGION_DIR, cfg, shape)
    got = np.asarray(Image.open(p).convert("RGB"))
    want = relief.base_colour(elev, cfg["elevation_min"], cfg["elevation_max"])
    assert got.shape == shape + (3,)
    assert np.array_equal(got, np.clip(want * 255.0, 0, 255).astype("uint8"))


def test_base_colour_is_the_shaded_relief_colour_stage():
    """The hoist that makes the above true: base_colour must be what shaded_relief
    starts from, or the hero plate wears a palette no poster has."""
    from app import relief
    v, u = np.mgrid[0:40, 0:50].astype("float64")
    elev = (1200.0 + 700.0 * (u / 49.0 + v / 39.0) / 2.0).astype("float32")
    norm = np.clip((elev - 1200.0) / 900.0, 0, 1)
    assert np.array_equal(relief.base_colour(elev, 1200.0, 2100.0),
                          relief.hypsometric(elev, 1200.0, 2100.0, norm=norm))


# ---- the CLI's refusals ------------------------------------------------------------

def test_cli_refuses_what_v1_does_not_do():
    from scripts.hero_plate import check_supported, HeroError
    for bad in (_spec_for(output_kind="wallpaper", screen_ppi=254.0),
                _spec_for(bleed_in=0.125),
                _spec_for(oblique=0.5)):
        with pytest.raises(HeroError):
            check_supported(bad)
    check_supported(_spec_for())            # a plain print sails through


def test_find_blender_reports_the_install_path_honestly(monkeypatch, tmp_path):
    from scripts.hero_plate import find_blender, HeroError
    monkeypatch.delenv("TECOPA_BLENDER", raising=False)
    monkeypatch.setenv("PATH", str(tmp_path))       # nothing on it
    with pytest.raises(HeroError) as e:
        find_blender(None)
    assert "blender.org/download" in str(e.value)


def test_a_png_without_a_manifest_is_refused_by_name(tmp_path):
    """A hero plate is rendered FROM a poster. Anything else gets a sentence, not a
    traceback -- and never reaches the untrusted-manifest door with None."""
    from scripts.hero_plate import read_poster, HeroError
    from PIL import Image
    p = str(tmp_path / "not-a-poster.png")
    Image.new("RGB", (8, 8), (255, 255, 255)).save(p)
    with pytest.raises(HeroError) as e:
        read_poster(p)
    assert "manifest" in str(e.value)


def test_scene_script_parses_and_imports_nothing_from_the_app():
    """hero_scene.py runs inside Blender's Python, which has neither the venv nor the
    engine on its path -- so it must parse standalone and import only bpy + stdlib."""
    import ast
    src = open("scripts/hero_scene.py").read()
    tree = ast.parse(src)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert "app" not in imported and not any(m.startswith("app") for m in imported)
    assert imported <= {"bpy", "json", "sys", "math", "os"}, imported
