# tests/test_dem_coverage.py
# Coverage is what keeps an order honest: the 3DEP dynamic service fills gaps in a
# fine layer with resampled coarse data and says nothing. The pure fraction runs in
# CI; the network query is checked by hand on the Mac (plan Task 4).
import subprocess
import sys

import pytest
from shapely.geometry import box

rp = pytest.importorskip("region_prep")
BBOX = (0.0, 0.0, 2.0, 1.0)


def test_full_cover():
    assert rp.coverage_fraction([box(-1, -1, 3, 2)], BBOX) == pytest.approx(1.0)


def test_half_cover_from_two_overlapping_footprints():
    parts = [box(0, 0, 0.8, 1), box(0.5, 0, 1.0, 1)]      # union is x 0..1
    assert rp.coverage_fraction(parts, BBOX) == pytest.approx(0.5)


def test_no_cover():
    assert rp.coverage_fraction([box(5, 5, 6, 6)], BBOX) == 0.0
    assert rp.coverage_fraction([], BBOX) == 0.0


def test_cli_usage_error_exits_2():
    out = subprocess.run([sys.executable, "scripts/dem_coverage.py", "1", "2"],
                         capture_output=True, text=True)
    assert out.returncode == 2
    assert "usage" in out.stderr
