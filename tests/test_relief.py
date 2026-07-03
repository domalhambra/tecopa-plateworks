# tests/test_relief.py
import numpy as np
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
