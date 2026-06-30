# tests/test_geo.py
import numpy as np
from app.geo import RegionGeo, lonlat_to_crs, crs_to_overview_px, overview_px_to_crs

# A minimal synthetic region: a 100km x 80km box in UTM 11N (EPSG:32611),
# rendered to a 1000 x 800 overview image.
REGION = RegionGeo(
    crs="EPSG:32611",
    # bounds in CRS meters: (min_x, min_y, max_x, max_y)
    bounds=(200000.0, 4000000.0, 300000.0, 4080000.0),
    overview_size=(1000, 800),  # width, height in px
)

def test_overview_affine_roundtrip():
    # CRS -> overview px -> CRS should return the original point
    x, y = 250000.0, 4040000.0
    px, py = crs_to_overview_px(REGION, x, y)
    x2, y2 = overview_px_to_crs(REGION, px, py)
    assert abs(x - x2) < 1e-6 and abs(y - y2) < 1e-6

def test_overview_corners():
    # top-left CRS corner maps to pixel (0, 0); bottom-right to (W, H)
    px, py = crs_to_overview_px(REGION, 200000.0, 4080000.0)
    assert abs(px) < 1e-6 and abs(py) < 1e-6
    px, py = crs_to_overview_px(REGION, 300000.0, 4000000.0)
    assert abs(px - 1000) < 1e-6 and abs(py - 800) < 1e-6

def test_control_point_projection():
    # A known lon/lat lands at a sane location inside the box.
    # NOTE: lon -117.0 is the central meridian of UTM zone 11N, so it projects to
    # easting 500000 (the false easting) -- outside this box's 200k..300k easting
    # range. The box sits ~2.8 deg west of the meridian, near lon -119.8, lat 36.5.
    x, y = lonlat_to_crs(REGION, -119.79, 36.47)  # eastern California-ish, inside the box
    assert REGION.bounds[0] <= x <= REGION.bounds[2]
    assert REGION.bounds[1] <= y <= REGION.bounds[3]
