# tests/test_region_prep.py
# NaN-edge trimming in region_prep (DEM-free logic, but region_prep imports the
# pandas/py3dep build stack at module load, so importorskip the whole module to
# skip cleanly in the core CI env instead of erroring collection (red-team V1-4).
import numpy as np
import pytest
_trim_nan_edges = pytest.importorskip("region_prep")._trim_nan_edges

def test_trims_nan_frame_keeps_interior():
    a = np.full((20, 30), 100.0, dtype="float32")
    a[:3, :] = np.nan          # 3 NaN rows on top
    a[:, :4] = np.nan          # 4 NaN cols on left
    a[-2:, :] = np.nan         # 2 NaN rows on bottom
    r0, r1, c0, c1 = _trim_nan_edges(a)
    assert (r0, r1, c0, c1) == (3, 18, 4, 30)
    assert np.isfinite(a[r0:r1, c0:c1]).all()

def test_clean_array_is_untouched():
    a = np.ones((10, 10), dtype="float32")
    assert _trim_nan_edges(a) == (0, 10, 0, 10)

def test_sparse_interior_nan_is_left_alone():
    # a few scattered interior NaNs (below the 2% edge threshold) must NOT trigger trim
    a = np.ones((50, 50), dtype="float32")
    a[25, 25] = np.nan
    assert _trim_nan_edges(a) == (0, 50, 0, 50)
