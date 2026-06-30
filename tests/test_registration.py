# tests/test_registration.py
# Invariant 5: prove the coordinate chain lands a known place on the right ground
# before any styling. lon/lat -> region CRS -> DEM sample must return the real
# elevation at a control point.
import json, os
import pytest
import rasterio
from app.geo import RegionGeo, lonlat_to_crs

REGION_DIR = "regions/lassen_ca"

# The DEM is gitignored (regenerate with region_prep.py); skip rather than error
# on a fresh clone that hasn't built region assets yet.
pytestmark = pytest.mark.skipif(
    not os.path.exists(os.path.join(REGION_DIR, "dem.tif")),
    reason="region assets not built; run region_prep.py")

def load_region():
    cfg = json.load(open(os.path.join(REGION_DIR, "region.json")))
    return RegionGeo(crs=cfg["crs"], bounds=tuple(cfg["bounds"]),
                     overview_size=tuple(cfg["overview_size"])), cfg

def test_control_point_elevation():
    # Downtown Susanville, CA sits at ~1265 m (4150 ft). Sampling the DEM there
    # proves the lon/lat -> UTM 10N -> DEM chain hits the right ground.
    LON, LAT, KNOWN_ELEV_M, TOL_M = -120.6530, 40.4163, 1265.0, 150.0
    region, cfg = load_region()
    x, y = lonlat_to_crs(region, LON, LAT)
    with rasterio.open(os.path.join(REGION_DIR, cfg["dem_path"])) as ds:
        val = list(ds.sample([(x, y)]))[0][0]
    assert abs(val - KNOWN_ELEV_M) < TOL_M, f"got {val} m at control point"
