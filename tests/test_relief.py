# tests/test_relief.py
import numpy as np
from app.relief import shaded_relief, hillshade, _fill_nan

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
