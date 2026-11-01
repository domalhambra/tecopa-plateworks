# tests/test_stripe_check.py
# The detector behind the DEM stripe repair: a sharp periodic spectral peak means a
# resampling pattern, and natural terrain has no such peak.
import numpy as np
import pytest
from scipy.ndimage import gaussian_filter

rasterio = pytest.importorskip("rasterio")
from rasterio.transform import from_origin  # noqa: E402

from scripts import stripe_check as sc  # noqa: E402


def _terrain(n=600, seed=1):
    r = np.random.default_rng(seed)
    return sum(gaussian_filter(r.standard_normal((n, n)), s) * s ** 2 * 3
               for s in (2, 5, 12, 30))


def test_natural_terrain_stays_green():
    assert sc.peaks(_terrain(), 10, 10)[0]["score"] < sc.STRIPE_RED_SCORE


def test_stripes_go_red_with_their_period_and_angle():
    a = _terrain()
    y, x = np.indices(a.shape)
    top = sc.peaks(a + 0.5 * np.sin(2 * np.pi * (x * 0.7 + y * 0.7) * 10 / 40), 10, 10)[0]
    assert top["score"] >= sc.STRIPE_RED_SCORE
    assert abs(top["period_m"] - 40.4) <= 2
    assert abs(top["angle_deg"] - 45) <= 2


def _write(path, a):
    with rasterio.open(path, "w", driver="GTiff", dtype="float32", count=1,
                       height=a.shape[0], width=a.shape[1], crs="EPSG:32613",
                       transform=from_origin(300000, 4300000, 10, 10), nodata=np.nan) as d:
        d.write(a.astype("float32"), 1)


def test_a_mostly_nan_window_is_skipped(tmp_path):
    p = str(tmp_path / "dem.tif")
    _write(p, np.full((900, 900), np.nan))
    assert sc.scan(p)["valid"] == 0


def test_scan_counts_a_striped_file(tmp_path):
    a = _terrain(900)
    y, x = np.indices(a.shape)
    p = str(tmp_path / "dem.tif")
    _write(p, a + 0.5 * np.sin(2 * np.pi * (x * 0.7 + y * 0.7) * 10 / 40))
    s = sc.scan(p, grid=2, size=300)
    assert s["valid"] == 4 and s["red"] == 4
    assert s["worst"] >= s["median"] >= sc.STRIPE_RED_SCORE
