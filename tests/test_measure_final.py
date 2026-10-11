# tests/test_measure_final.py
import pytest

from scripts import measure_final as mf


def test_the_crop_is_centred_and_has_the_sheet_aspect():
    crop = mf.centred_crop((0.0, 0.0, 100_000.0, 60_000.0), 59 / 22, 50_000.0)
    w, h = crop[2] - crop[0], crop[3] - crop[1]
    assert abs(w / h - 59 / 22) < 1e-9
    assert abs((crop[0] + crop[2]) / 2 - 50_000.0) < 1e-6
    assert abs((crop[1] + crop[3]) / 2 - 30_000.0) < 1e-6
    assert w <= 100_000.0 and h <= 60_000.0


def test_a_region_that_is_too_small_is_refused_by_name():
    with pytest.raises(SystemExit, match="too small"):
        mf.centred_crop((0.0, 0.0, 40_000.0, 40_000.0), 59 / 22, 88_500.0)


def test_peak_is_reported_in_gigabytes():
    assert mf.peak_gb(8 * 1024 ** 3, "darwin") == 8.0      # macOS reports bytes
    assert mf.peak_gb(8 * 1024 ** 2, "linux") == 8.0       # Linux reports KiB
