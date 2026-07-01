# tests/test_registration.py
# Invariant 5: prove the coordinate chain lands a known place on the right ground
# before any styling. lon/lat -> region CRS -> DEM sample must return a real
# elevation at a control point.
import json, os
import pytest
import rasterio
from app.geo import RegionGeo, lonlat_to_crs

REGION_DIR = "regions/lassen_ca"
DEM_PATH = os.path.join(REGION_DIR, "dem.tif")


def _dem_is_synthetic(path):
    """True if the DEM here is the one tests/conftest.py builds (tagged synthetic=1),
    so a real-terrain assertion can skip when only the CI DEM is present."""
    if not os.path.exists(path):
        return False
    with rasterio.open(path) as ds:
        return ds.tags().get("synthetic") == "1"


def load_region():
    cfg = json.load(open(os.path.join(REGION_DIR, "region.json")))
    return RegionGeo(crs=cfg["crs"], bounds=tuple(cfg["bounds"]),
                     overview_size=tuple(cfg["overview_size"])), cfg


def test_coordinate_chain_lands_on_dem():
    # A lon/lat known to sit inside Lassen County -> region CRS -> DEM sample must
    # land ON the DEM: finite, and inside the region's own elevation range. A swapped
    # axis order or wrong CRS would push the point off the DEM and sample NaN. Runs on
    # both the synthetic (CI) and real DEM, so the chain is guarded on every push.
    LON, LAT = -120.6530, 40.4163           # downtown-ish Susanville, in-region
    region, cfg = load_region()
    x, y = lonlat_to_crs(region, LON, LAT)
    # the projected point must land INSIDE the region's CRS bounds -- an axis swap or
    # wrong CRS would push it far outside, which is the registration error we guard.
    min_x, min_y, max_x, max_y = cfg["bounds"]
    assert min_x <= x <= max_x and min_y <= y <= max_y, f"projected ({x:.0f},{y:.0f}) outside bounds"
    with rasterio.open(DEM_PATH) as ds:
        val = float(list(ds.sample([(x, y)]))[0][0])
    import math
    assert math.isfinite(val), "control point sampled NaN -> reprojected off the DEM"
    lo, hi = cfg["elevation_min"], cfg["elevation_max"]
    span = hi - lo
    assert lo - 0.05 * span <= val <= hi + 0.05 * span, f"got {val} m, out of region range"


@pytest.mark.skipif(_dem_is_synthetic(DEM_PATH) or not os.path.exists(DEM_PATH),
                    reason="needs the real 3DEP DEM (run region_prep.py)")
def test_control_point_elevation():
    # Downtown Susanville, CA sits at ~1265 m (4150 ft). Sampling the DEM there
    # proves the lon/lat -> UTM 10N -> DEM chain hits the right ground. Real-terrain
    # only; skipped when only the synthetic CI DEM is present.
    LON, LAT, KNOWN_ELEV_M, TOL_M = -120.6530, 40.4163, 1265.0, 150.0
    region, cfg = load_region()
    x, y = lonlat_to_crs(region, LON, LAT)
    with rasterio.open(os.path.join(REGION_DIR, cfg["dem_path"])) as ds:
        val = list(ds.sample([(x, y)]))[0][0]
    assert abs(val - KNOWN_ELEV_M) < TOL_M, f"got {val} m at control point"
