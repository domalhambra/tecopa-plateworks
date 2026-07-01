# tests/test_readyz.py
# Region.readiness() is the /readyz check: a DEM must be present and its own bounds
# + CRS must match region.json (the single source of truth). Guards red-team V1-2
# (susanville shipped with no DEM) and the V1-1 bounds-overhang that fabricates terrain.
import json, os
import numpy as np
import rasterio
from rasterio.transform import from_bounds
from app import regions


def _write_region(root, rid, cfg_bounds, dem_bounds, crs="EPSG:32610", with_dem=True):
    d = os.path.join(root, rid)
    os.makedirs(d, exist_ok=True)
    cfg = {"id": rid, "name": rid, "crs": crs, "bounds": list(cfg_bounds),
           "overview_size": [100, 100], "dem_path": "dem.tif",
           "native_resolution_m": 10, "elevation_min": 1000.0, "elevation_max": 2000.0}
    with open(os.path.join(d, "region.json"), "w") as f:
        json.dump(cfg, f)
    if with_dem:
        w, s, e, n = dem_bounds
        prof = dict(driver="GTiff", dtype="float32", count=1, height=20, width=20,
                    crs=crs, transform=from_bounds(w, s, e, n, 20, 20), nodata=np.nan)
        with rasterio.open(os.path.join(d, "dem.tif"), "w", **prof) as ds:
            ds.write(np.full((20, 20), 1500.0, "float32"), 1)
    return d


def test_readiness_ok_when_bounds_match(tmp_path):
    b = (600000.0, 4400000.0, 610000.0, 4410000.0)
    _write_region(str(tmp_path), "match", b, b)
    rep = regions.Region("match", root=str(tmp_path)).readiness()
    assert rep["dem_present"] and rep["ready"] and rep["bounds_match"] and rep["crs_match"]


def test_readiness_flags_bounds_drift(tmp_path):
    cfg_b = (600000.0, 4400000.0, 610000.0, 4410000.0)
    dem_b = (605000.0, 4405000.0, 615000.0, 4415000.0)   # DEM shifted 5 km -> overhang
    _write_region(str(tmp_path), "drift", cfg_b, dem_b)
    rep = regions.Region("drift", root=str(tmp_path)).readiness()
    assert rep["dem_present"] and rep["ready"] is False
    assert rep["bounds_drift_m"] > 1000


def test_readiness_flags_crs_mismatch(tmp_path):
    b = (600000.0, 4400000.0, 610000.0, 4410000.0)
    # region.json says UTM 10N but the DEM is written in UTM 11N -> water/tracks would
    # mis-register silently; readiness must catch it.
    _write_region(str(tmp_path), "wrongcrs", b, b, crs="EPSG:32610")
    # rewrite the DEM in a different CRS while region.json still says 32610
    d = os.path.join(str(tmp_path), "wrongcrs")
    prof = dict(driver="GTiff", dtype="float32", count=1, height=20, width=20,
                crs="EPSG:32611", transform=from_bounds(*b, 20, 20), nodata=np.nan)
    with rasterio.open(os.path.join(d, "dem.tif"), "w", **prof) as ds:
        ds.write(np.full((20, 20), 1500.0, "float32"), 1)
    rep = regions.Region("wrongcrs", root=str(tmp_path)).readiness()
    assert rep["crs_match"] is False and rep["ready"] is False


def test_readiness_flags_missing_dem(tmp_path):
    b = (600000.0, 4400000.0, 610000.0, 4410000.0)
    _write_region(str(tmp_path), "nodem", b, b, with_dem=False)
    rep = regions.Region("nodem", root=str(tmp_path)).readiness()
    assert rep["dem_present"] is False and rep["ready"] is False
