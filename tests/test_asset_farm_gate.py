# tests/test_asset_farm_gate.py
# The farm paints marketing images from real terrain, and the deploy guard checks
# the DEM's provenance stamp -- but a DEM that is present, real, and ORPHANED
# (bounds no longer region.json's) would stamp cleanly and paint a misregistered
# poster. _ensure_dem must treat geometry drift as "no usable DEM", never as present.
from app import regions
from scripts.render_asset_farm import _ensure_dem
from tests.test_readyz import _write_region

GOOD = (600000.0, 4400000.0, 610000.0, 4410000.0)
SHIFTED = (605000.0, 4405000.0, 615000.0, 4415000.0)


def test_drifted_dem_is_skipped_with_its_own_reason(tmp_path, capsys):
    _write_region(str(tmp_path), "orphan", GOOD, SHIFTED)
    why = _ensure_dem(regions.Region("orphan", root=str(tmp_path)), allow_synthetic=False)
    assert why is not None and "5000.00 m" in why
    assert "orphan" in capsys.readouterr().out


def test_drifted_dem_is_not_papered_over_by_synthetic_mode(tmp_path):
    """--synthetic-dem hydrates a MISSING DEM only. A drifted real one still refuses."""
    _write_region(str(tmp_path), "orphan", GOOD, SHIFTED)
    why = _ensure_dem(regions.Region("orphan", root=str(tmp_path)), allow_synthetic=True)
    assert why is not None and "5000.00 m" in why


def test_healthy_dem_returns_none(tmp_path):
    _write_region(str(tmp_path), "good", GOOD, GOOD)
    assert _ensure_dem(regions.Region("good", root=str(tmp_path)), allow_synthetic=False) is None


def test_missing_dem_without_synthetic_is_the_old_reason(tmp_path):
    _write_region(str(tmp_path), "nodem", GOOD, GOOD, with_dem=False)
    why = _ensure_dem(regions.Region("nodem", root=str(tmp_path)), allow_synthetic=False)
    assert why is not None and "no DEM" in why
