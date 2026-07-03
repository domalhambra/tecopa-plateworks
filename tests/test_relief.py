# tests/test_relief.py
import numpy as np
from app.relief import (shaded_relief, hillshade, _fill_nan,
                        multidirectional_hillshade)

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
