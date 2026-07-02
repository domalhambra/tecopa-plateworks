# tests/test_regions.py
# The region registry only reads region.json (committed), so these run on a fresh
# clone without the DEM.
from app.regions import discover

REGIONS_ROOT = "regions"

def test_discover_finds_lassen():
    regions = discover(REGIONS_ROOT)
    assert "lassen_ca" in regions
    assert regions["lassen_ca"].name == "Lassen County, California"

def test_region_meta_shape():
    r = discover(REGIONS_ROOT)["lassen_ca"]
    m = r.meta()
    assert set(m) >= {"id", "name", "bounds", "overview_size", "overview",
                      "lonlat_bbox", "native_resolution_m"}
    assert m["overview"] == "/regions/lassen_ca/overview.png"
    assert len(m["bounds"]) == 4 and len(m["lonlat_bbox"]) == 4
    assert m["native_resolution_m"] == 10

def test_lonlat_bbox_roundtrips_to_input_bbox():
    # Lassen was built from --bbox -121.06 40.16 -120.34 40.85. Recovering lon/lat
    # from the UTM-metre bounds is approximate (curved meridians push the corners
    # out a touch), so just assert it lands within ~0.1 deg of the input box.
    r = discover(REGIONS_ROOT)["lassen_ca"]
    w, s, e, n = r.lonlat_bbox
    assert abs(w - (-121.06)) < 0.1 and abs(e - (-120.34)) < 0.1
    assert abs(s - 40.16) < 0.1 and abs(n - 40.85) < 0.1
    assert w < e and s < n

# (detect_region/contains_lonlat were removed as production-dead code -- upload
# routing is main._best_region, covered by tests/test_region_recovery.py.)
