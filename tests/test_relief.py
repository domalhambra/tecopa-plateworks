# tests/test_relief.py
import numpy as np
from scipy.ndimage import distance_transform_edt
from app import relief
from app.relief import (shaded_relief, hillshade, _fill_nan,
                        multidirectional_hillshade, cast_shadow_mask,
                        sky_occlusion, _shadow_terms)

def synthetic_terrain(h=256, w=320):
    yy, xx = np.mgrid[0:h, 0:w]
    return (np.sin(xx/25.0) * np.cos(yy/30.0) * 300 + 1500).astype("float32")

def test_relief_shape_and_range():
    elev = synthetic_terrain()
    rgb = shaded_relief(elev, res_m=30.0, elev_min=1000, elev_max=2000,
                        azimuth=315, altitude=45, z_factor=1.0, seed=7)
    assert rgb.shape == (256, 320, 3)
    assert rgb.dtype == np.uint8

def test_relief_is_deterministic():
    elev = synthetic_terrain()
    a = shaded_relief(elev, 30.0, 1000, 2000, 315, 45, 1.0, seed=7)
    b = shaded_relief(elev, 30.0, 1000, 2000, 315, 45, 1.0, seed=7)
    assert np.array_equal(a, b)   # invariant 3

def _planar(facing, h=16, w=16):
    # A plane that faces a given compass direction (downhill toward 'facing').
    # row grows south (down), col grows east (right).
    col = np.mgrid[0:h, 0:w][1].astype("float32")
    if facing == "E":
        return (w - col)   # high west, low east -> faces east
    if facing == "W":
        return col         # faces west

def test_fill_nan_uses_nearest_neighbour_not_crop_mean():
    # red-team V1-1: a stray hole must be repaired from its nearest finite neighbour,
    # not filled with the crop mean (which would invent a plateau at the average).
    a = np.full((5, 5), 90.0, dtype="float32")
    a[0, :] = 10.0            # only the top row is low; the hole sits among 90s
    a[2, 2] = np.nan
    out = _fill_nan(a.copy())
    assert np.isfinite(out).all()
    assert out[2, 2] == 90.0  # nearest neighbour (90), not the ~73 crop mean

def test_fill_nan_all_nodata_is_flat_not_crash():
    a = np.full((4, 4), np.nan, dtype="float32")
    out = _fill_nan(a.copy())
    assert np.isfinite(out).all() and np.all(out == 0.0)

def test_terrain_depth_zero_is_a_strict_noop():
    # invariant: depth=0 (county scale, every existing test) must be byte-identical to
    # the single-light relief -- the depth blocks are skipped, nothing perturbs it.
    elev = synthetic_terrain()
    base = shaded_relief(elev, 30.0, 1000, 2000, 315, 45, 1.0, seed=7)
    depth0 = shaded_relief(elev, 30.0, 1000, 2000, 315, 45, 1.0, seed=7, depth=0.0)
    assert np.array_equal(base, depth0)

def test_terrain_depth_changes_the_render_and_stays_deterministic():
    elev = synthetic_terrain()
    flat = shaded_relief(elev, 30.0, 1000, 2000, 315, 45, 1.0, seed=7, depth=0.0)
    deep_a = shaded_relief(elev, 30.0, 1000, 2000, 315, 45, 1.0, seed=7, depth=1.0)
    deep_b = shaded_relief(elev, 30.0, 1000, 2000, 315, 45, 1.0, seed=7, depth=1.0)
    assert not np.array_equal(flat, deep_a), "depth=1 changed nothing"
    assert np.array_equal(deep_a, deep_b), "depth pass is not deterministic (invariant 3)"

def test_multidirectional_recovers_a_range_parallel_to_the_sun():
    # a N-S ridge lit from the north (azimuth 0) sits in its own shadow under one
    # light; the flanking lights of the multidirectional blend model it, so its mean
    # brightness rises relative to the single light.
    h, w = 64, 64
    col = np.abs(np.arange(w) - w / 2)              # a ridge running north-south
    elev = (200.0 - 8.0 * col).astype("float32")    # crest down the middle column
    elev = np.tile(elev, (h, 1))
    one = hillshade(elev, 30.0, azimuth=0, altitude=45)
    multi = multidirectional_hillshade(elev, 30.0, azimuth=0, altitude=45)
    assert multi.std() > one.std(), "multidirectional did not add cross-light modelling"

def test_salt_pan_lifts_flat_low_ground():
    # a dead-flat basin at the very bottom of the elevation range should read brighter
    # under the depth pass (the salt-pan luminous lift), while a high flat should not.
    low = np.full((64, 64), 1010.0, dtype="float32")     # norm ~ 0.01, flat
    high = np.full((64, 64), 1990.0, dtype="float32")    # norm ~ 0.99, flat
    low0 = shaded_relief(low, 30.0, 1000, 2000, seed=7, depth=0.0).mean()
    low1 = shaded_relief(low, 30.0, 1000, 2000, seed=7, depth=1.0).mean()
    high0 = shaded_relief(high, 30.0, 1000, 2000, seed=7, depth=0.0).mean()
    high1 = shaded_relief(high, 30.0, 1000, 2000, seed=7, depth=1.0).mean()
    assert low1 > low0 + 4, "salt pan did not brighten the low flat"
    assert abs(high1 - high0) < abs(low1 - low0), "depth hit the high flat like the salt pan"

# ---- cast shadows + sky occlusion (the "Blender relief" pass) ----

def _ridge(h=101, w=101, height=500.0, axis="ns"):
    """A tall wall across the middle of a flat plain: 'ns' = a north-south wall
    (casts under an E/W sun), 'ew' = an east-west wall (casts under a N/S sun) --
    a wall parallel to the light correctly casts nothing."""
    elev = np.zeros((h, w), dtype="float32")
    if axis == "ns":
        elev[:, w // 2] = height
    else:
        elev[h // 2, :] = height
    return elev

def _shadow_side(mask, margin=8):
    """Mean mask west/east/north/south of the centre, outside the ridge itself."""
    h, w = mask.shape
    return {"W": mask[:, :w//2 - margin].mean(), "E": mask[:, w//2 + margin:].mean(),
            "N": mask[:h//2 - margin, :].mean(), "S": mask[h//2 + margin:, :].mean()}

def test_cast_shadow_falls_on_the_far_side():
    # The rotation sign is THE bug this pins: a mirrored theta puts shadows on the
    # sun side. Four cardinal azimuths (no rotation-interp ambiguity) plus the
    # region default 315 (NW sun -> shadow to the SE).
    for az, dark, lit, axis in ((270, "E", "W", "ns"), (90, "W", "E", "ns"),
                                (0, "S", "N", "ew"), (180, "N", "S", "ew")):
        s = _shadow_side(cast_shadow_mask(_ridge(axis=axis), 30.0, azimuth=az, altitude=45))
        assert s[dark] > 10 * max(s[lit], 1e-6), f"az={az}: shadow not {dark}-side"
    # a small butte under a NW sun: shadow centroid sits to the SE
    butte = np.zeros((101, 101), dtype="float32"); butte[47:54, 47:54] = 500.0
    m = cast_shadow_mask(butte, 30.0, azimuth=315, altitude=45)
    m[44:57, 44:57] = 0.0                      # ignore the butte neighbourhood
    ys, xs = np.nonzero(m > 0.2)
    assert len(ys) and ys.mean() > 50 and xs.mean() > 50, "NW sun must cast SE"

def test_cast_shadow_length_scales_with_altitude():
    elev = _ridge()
    low = cast_shadow_mask(elev, 30.0, azimuth=270, altitude=25)
    high = cast_shadow_mask(elev, 30.0, azimuth=270, altitude=60)
    assert (low > 0.5).sum() > (high > 0.5).sum(), "a lower sun must cast longer shadows"

def test_shadow_zero_is_a_strict_noop():
    # invariant: shadow=0 (the parameter default) must be byte-identical to the
    # pre-shadow relief -- the shadow blocks are skipped, nothing perturbs it.
    elev = synthetic_terrain()
    base = shaded_relief(elev, 30.0, 1000, 2000, 315, 45, 1.0, seed=7)
    off = shaded_relief(elev, 30.0, 1000, 2000, 315, 45, 1.0, seed=7, shadow=0.0)
    assert np.array_equal(base, off)

def test_shadow_changes_the_render_and_stays_deterministic():
    elev = synthetic_terrain()
    off = shaded_relief(elev, 30.0, 1000, 2000, 315, 45, 1.0, seed=7, shadow=0.0)
    on_a = shaded_relief(elev, 30.0, 1000, 2000, 315, 45, 1.0, seed=7, shadow=1.0)
    on_b = shaded_relief(elev, 30.0, 1000, 2000, 315, 45, 1.0, seed=7, shadow=1.0)
    assert not np.array_equal(off, on_a), "shadow=1 changed nothing"
    assert np.array_equal(on_a, on_b), "shadow pass is not deterministic (invariant 3)"

def test_cast_shadow_has_a_penumbra():
    # the mask must carry a soft edge (values strictly between lit and shadowed),
    # not a hard binary cliff -- that's what keeps proof and final in agreement.
    m = cast_shadow_mask(_ridge(), 30.0, azimuth=270, altitude=45)
    soft = ((m > 0.05) & (m < 0.95)).sum()
    hard = (m >= 0.95).sum()
    assert soft > hard * 0.2 and soft > 50, f"no penumbra: soft={soft} hard={hard}"

def test_shadows_stay_cool_not_black():
    # deep shadow keeps luminance above a floor AND cools (blue/red rises) --
    # Imhof's skylight fill, not a black hole.
    elev = _ridge(height=800.0)
    img = shaded_relief(elev, 30.0, 0, 1000, azimuth=270, altitude=35, seed=7, shadow=1.0)
    m = cast_shadow_mask(elev, 30.0, azimuth=270, altitude=35)
    deep = img[m > 0.9]; lit = img[m < 0.05]
    assert len(deep) and len(lit)
    assert deep.min() > 20, f"shadow crushed to black: min {deep.min()}"
    br_deep = deep[:, 2].mean() / max(deep[:, 0].mean(), 1e-6)
    br_lit = lit[:, 2].mean() / max(lit[:, 0].mean(), 1e-6)
    assert br_deep > br_lit, "shadows did not cool (blue/red should rise in shadow)"

def test_sky_occlusion_darkens_pits_not_peaks():
    yy, xx = np.mgrid[0:128, 0:128]
    r2 = ((xx - 64) ** 2 + (yy - 64) ** 2) / (30.0 ** 2)
    bowl = (1500 - 400 * np.exp(-r2)).astype("float32")
    dome = (1500 + 400 * np.exp(-r2)).astype("float32")
    ao_bowl = sky_occlusion(bowl, 30.0)
    ao_dome = sky_occlusion(dome, 30.0)
    assert ao_bowl[64, 64] > 0.2, "bowl centre must be occluded"
    assert ao_dome[64, 64] < 0.05, "dome summit must stay open to the sky"

def test_shadow_terms_are_stable_across_grid_resolution():
    # THE DPI-stability guard (invariant 1): the same ground truth sampled at 10 m
    # and ~31 m, both pinned to the same 31.25 m working grid, must yield nearly
    # the same masks -- this is what keeps the proof a faithful scale of the final.
    work = 31.25
    def terrain(n, res):
        yy, xx = np.mgrid[0:n, 0:n].astype("float64") * res
        return (300 * np.sin(xx / 900.0) * np.cos(yy / 1100.0)
                + 200 * np.sin((xx + yy) / 1700.0) + 1500).astype("float32")
    fine = terrain(320, 10.0)      # 3200 m square at 10 m
    coarse = terrain(100, 32.0)    # 3200 m square at 32 m
    cast_f, ao_f = _shadow_terms(fine, 10.0, 315, 45, 1.0, shadow_res_m=work)
    cast_c, ao_c = _shadow_terms(coarse, 32.0, 315, 45, 1.0, shadow_res_m=work)
    # compare on the coarse grid: block-average the fine mask down (320 = 100*3.2)
    from scipy.ndimage import zoom as _zoom
    cast_f_ds = _zoom(cast_f, 100 / 320, order=1)
    ao_f_ds = _zoom(ao_f, 100 / 320, order=1)
    mad_cast = np.abs(cast_f_ds - cast_c).mean()
    mad_ao = np.abs(ao_f_ds - ao_c).mean()
    assert mad_cast < 0.03, f"cast mask drifts with source grid: MAD {mad_cast:.4f}"
    assert mad_ao < 0.03, f"AO mask drifts with source grid: MAD {mad_ao:.4f}"

def test_hillshade_comes_from_requested_azimuth():
    # Registration/correctness guard for the light: a slope must be brightest when
    # the sun sits in the direction the slope faces. Catches an azimuth/aspect
    # mismatch in hillshade (the centerpiece of the whole render).
    east_facing = _planar("E")
    west_facing = _planar("W")
    # Under an eastern sun (azimuth=90), the east-facing slope must out-shine the west.
    e = hillshade(east_facing, 30.0, azimuth=90, altitude=45).mean()
    w = hillshade(west_facing, 30.0, azimuth=90, altitude=45).mean()
    assert e > w

def test_concurrent_relief_passes_do_not_move_a_pixel(monkeypatch):
    # The independent passes (texture, valley, the ray-marched shadow, the
    # slope/aspect lights) are pure functions of one elevation window, so they run
    # concurrently. Concurrency is a scheduling change ONLY: each task combines its
    # own result with the same expressions in the same order, and the tasks are
    # merged in submission order, so the sheet must be bit-identical to the serial
    # one (invariant 3). Every optional block is on, so all four tasks are exercised.
    elev = synthetic_terrain()
    kw = dict(res_m=30.0, elev_min=1000, elev_max=2000, azimuth=315, altitude=45,
              z_factor=1.0, seed=7, depth=1.0, shadow=0.8,
              sun_azimuth=200.0, sun_altitude=30.0, golden=0.9)
    monkeypatch.setattr(relief, "RELIEF_WORKERS", 1)
    serial = shaded_relief(elev, **kw)
    monkeypatch.setattr(relief, "RELIEF_WORKERS", 4)
    parallel = shaded_relief(elev, **kw)
    assert np.array_equal(serial, parallel)

def test_margin_ring_fill_matches_the_edt_on_a_clean_off_dem_margin():
    # The shape every near-full-plate crop makes: _read_window pads 6% past the crop
    # and fills the overhang with NaN, so the finite data is one solid rectangle inside
    # an all-NaN margin. Nearest-finite for a margin pixel is then its projection onto
    # that rectangle (a convex set, so the minimiser is unique), which is exactly what
    # edge replication does -- no ray of doubt, and no 60 MP distance transform.
    rng = np.random.default_rng(0)
    a = np.full((60, 74), np.nan, dtype="float32")
    a[10:50, 12:62] = rng.normal(1500, 200, (40, 50)).astype("float32")
    fast = relief._margin_ring_fill(a, np.isnan(a))
    assert fast is not None, "a clean off-DEM margin must take the fast path"
    idx = distance_transform_edt(np.isnan(a), return_distances=False, return_indices=True)
    assert np.array_equal(fast, a[tuple(idx)])

def test_margin_ring_fill_declines_when_the_finite_block_has_a_hole():
    # lassen_ca's DEM does not fill its own UTM rectangle (the reprojected footprint
    # leaves two opposite corners nodata), so the finite set is not convex and the
    # projection argument does not hold. The fast path must decline and let the
    # general distance transform answer, rather than guess.
    a = np.full((20, 20), np.nan, dtype="float32")
    a[5:15, 5:15] = 1500.0
    a[7, 7] = np.nan                      # an interior hole
    assert relief._margin_ring_fill(a, np.isnan(a)) is None

# ---- the memory trim: bands, in-place steps and the deferred land cover -------------
# None of these may move a pixel. The trim changes WHERE a result is stored and how
# large a temporary is, never an operation or its order.

def _everything_on(**extra):
    kw = dict(res_m=30.0, elev_min=1000, elev_max=2000, azimuth=315, altitude=45,
              z_factor=1.0, seed=7, depth=1.0, shadow=0.8,
              sun_azimuth=200.0, sun_altitude=30.0, golden=0.9)
    kw.update(extra)
    return kw

def _land_cover(shape):
    """A tint and a weight that vary over the sheet, so the blend has work to do."""
    yy, xx = np.mgrid[0:shape[0], 0:shape[1]].astype("float32")
    tint = np.stack([0.35 + 0.2 * np.sin(xx / 17.0), 0.45 + 0.2 * np.cos(yy / 23.0),
                     0.30 + 0.1 * np.sin((xx + yy) / 31.0)], axis=-1).astype("float32")
    weight = np.clip(0.5 + 0.5 * np.sin(xx / 40.0) * np.cos(yy / 35.0), 0, 1).astype("float32")
    return tint, weight

def _terrain_with_a_pan():
    """The synthetic hills beside a low, dead-flat basin: the one ground the salt pan
    and its seeded mottle are drawn on, so the depth pass has every step to do."""
    elev = synthetic_terrain()
    elev[:, :110] = 1010.0
    return elev

def test_the_band_size_does_not_move_a_pixel(monkeypatch):
    # The per-pixel blocks run a band of rows at a time so their temporaries are
    # band-sized. That is only legal when no pixel reads another, and this is the
    # check: ONE band is the whole-array computation, and many short bands (with a
    # shorter last one, 256 = 36 * 7 + 4) must give the same bytes. A block that
    # reads a neighbour, a whole-array statistic or its own RNG draw fails here.
    elev = _terrain_with_a_pan()
    kw = _everything_on(biome=_land_cover(elev.shape))
    monkeypatch.setattr(relief, "BAND_ROWS", 10 ** 9)
    whole = shaded_relief(elev, **kw)
    # the pan is really drawn: without its salt lift this test would not reach the mottle
    flat = shaded_relief(elev, **{**kw, "depth": 0.0})
    assert whole[:, 10:100].mean() > flat[:, 10:100].mean() + 5
    for rows in (1, 7, 256):
        monkeypatch.setattr(relief, "BAND_ROWS", rows)
        assert np.array_equal(whole, shaded_relief(elev, **kw)), f"{rows}-row bands"

def test_bands_cover_every_row_once_in_order(monkeypatch):
    monkeypatch.setattr(relief, "BAND_ROWS", 7)
    got = [r for s in relief._bands(30) for r in range(s.start, s.stop)]
    assert got == list(range(30))
    assert list(relief._bands(0)) == []

def test_tonal_finish_writes_its_argument_only_when_told():
    rng = np.random.default_rng(3)
    src = rng.uniform(-0.2, 1.2, (300, 41, 3)).astype("float32")   # past both ends
    kept = src.copy()
    out = relief._tonal_finish(src)
    assert np.array_equal(src, kept), "the default must leave a caller's array alone"
    assert not np.shares_memory(out, src)
    # consume=True: the same floats, built in the caller's buffer
    given = src.copy()
    took = relief._tonal_finish(given, consume=True)
    assert np.shares_memory(took, given), "consume=True must not build a second sheet"
    assert np.array_equal(took, out)
    # a read-only array cannot be consumed: it is copied, not written and not refused
    frozen = src.copy()
    frozen.flags.writeable = False
    assert np.array_equal(relief._tonal_finish(frozen, consume=True), out)
    assert np.array_equal(frozen, kept)

def test_the_lit_sheet_is_the_same_built_in_place_or_fresh(monkeypatch):
    # `base *= light` reuses the colour plane's buffer. It must be the product
    # `base * light` and nothing else, so forcing the allocating form changes no byte.
    elev = synthetic_terrain()
    kw = _everything_on(biome=_land_cover(elev.shape))
    in_place = shaded_relief(elev, **kw)
    monkeypatch.setattr(relief, "_in_place_ok", lambda a, b: False)
    assert np.array_equal(in_place, shaded_relief(elev, **kw))

def test_in_place_is_refused_where_it_would_change_the_product():
    base = np.ones((4, 5, 3), "float32")
    light = np.full((4, 5, 1), 0.5, "float32")
    assert relief._in_place_ok(base, light)
    # a float64 light: the product is float64, and a float32 store would round it
    assert not relief._in_place_ok(base, light.astype("float64"))
    frozen = base.copy()
    frozen.flags.writeable = False
    assert not relief._in_place_ok(frozen, light)            # somebody else's array
    assert not relief._in_place_ok(base[:, :, ::-1], light)  # a view into one
    assert not relief._in_place_ok(np.ones((1, 1, 3), "float32"), light)   # would grow

def test_a_deferred_land_cover_is_read_once_and_blends_the_same():
    # render._paint_terrain hands the land cover over as a function, so the two
    # planes live only inside the blend. The function is called exactly once, and
    # the sheet is the one the planes themselves give.
    elev = synthetic_terrain()
    planes = _land_cover(elev.shape)
    calls = []

    def deferred():
        calls.append(1)
        return planes

    eager = shaded_relief(elev, **_everything_on(biome=planes))
    assert np.array_equal(eager, shaded_relief(elev, **_everything_on(biome=deferred)))
    assert calls == [1]
    # no land cover is None, from the caller or from the function (a plate with no
    # landcover.tif: render._biome_layers returns None)
    plain = shaded_relief(elev, **_everything_on())
    assert not np.array_equal(plain, eager)
    assert np.array_equal(plain, shaded_relief(elev, **_everything_on(biome=None)))
    assert np.array_equal(plain, shaded_relief(elev, **_everything_on(biome=lambda: None)))
    # the planes are read, never written
    kept = _land_cover(elev.shape)
    assert np.array_equal(planes[0], kept[0]) and np.array_equal(planes[1], kept[1])

def test_base_colour_refuses_false_as_it_always_did():
    # `biome` is a pair, a function or None. False was never "off" and still is not.
    import pytest
    with pytest.raises(TypeError):
        relief.base_colour(synthetic_terrain(40, 50), 1000, 2000, biome=False)

def test_the_land_cover_blend_keeps_the_dtype_of_its_inputs():
    # The engine's planes are float32 and the blend stays float32, in the ramp's own
    # buffer. A direct caller with float64 planes got a float64 colour plane from the
    # whole-array expression, and the banded blend must give that same plane: stored
    # into float32 it would be rounded.
    elev = synthetic_terrain(300, 60)
    tint, weight = _land_cover(elev.shape)
    assert relief.base_colour(elev, 1000, 2000, biome=(tint, weight)).dtype == np.float32
    got = relief.base_colour(elev, 1000, 2000, biome=(tint.astype("float64"), weight))
    norm = np.clip((elev - 1000) / (2000 - 1000 + 1e-9), 0, 1)
    base = relief.hypsometric(elev, 1000, 2000, norm=norm)
    t64 = tint.astype("float64")
    matched = np.clip(t64 * (base.mean(axis=2, keepdims=True)
                             / (t64.mean(axis=2, keepdims=True) + 1e-6)), 0, 1)
    fade = np.clip((relief.ALPINE_FADE_END - norm) /
                   (relief.ALPINE_FADE_END - relief.ALPINE_FADE_START), 0, 1)
    w3 = (weight * relief.BIOME_MIX * fade)[..., None]
    want = base * (1 - w3) + matched * w3
    assert got.dtype == want.dtype == np.float64
    assert np.array_equal(got, want)

def test_the_ramp_colours_a_line_and_a_point_like_the_sheet():
    # hypsometric bands a 2-D window; a profile line or one elevation takes the
    # whole-array expression, and must agree with the same values inside a sheet.
    elev = synthetic_terrain(300, 60)
    sheet = relief.hypsometric(elev, 1000, 2000)
    assert np.array_equal(relief.hypsometric(elev[5], 1000, 2000), sheet[5])
    assert np.array_equal(relief.hypsometric(elev[5, 9], 1000, 2000), sheet[5, 9])

def test_shadow_terms_read_the_window_and_never_write_it():
    # _shadow_terms no longer copies a float32 window before reading it, so it must
    # leave it untouched on both of its paths: the coarse working grid and the native one.
    elev = synthetic_terrain()
    kept = elev.copy()
    for shadow_res_m in (None, 90.0):
        cast, ao = _shadow_terms(elev, 30.0, shadow_res_m=shadow_res_m)
        assert np.array_equal(elev, kept)
        assert cast.dtype == ao.dtype == np.float32
        assert not np.shares_memory(cast, elev) and not np.shares_memory(ao, elev)
