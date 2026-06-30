# tests/test_hydro.py
import geopandas as gpd
from shapely.geometry import Polygon, LineString
from region_prep import bake_hydro

def test_bake_reprojects_and_filters_by_order():
    # one lake polygon + two flowlines (order 2 dropped, order 4 kept), EPSG:4326
    lake = gpd.GeoDataFrame(
        {"gnis_name": ["Eagle Lake"]},
        geometry=[Polygon([(-120.74, 40.60), (-120.72, 40.60), (-120.72, 40.62), (-120.74, 40.62)])],
        crs="EPSG:4326")
    rivers = gpd.GeoDataFrame(
        {"streamorde": [2, 4], "gnis_name": ["Creek", "Susan River"]},
        geometry=[LineString([(-120.70, 40.50), (-120.69, 40.51)]),
                  LineString([(-120.66, 40.41), (-120.66, 40.45)])],
        crs="EPSG:4326")
    hydro = bake_hydro(lake, rivers, "EPSG:32610", min_order=3)
    assert hydro["crs"] == "EPSG:32610"
    assert len(hydro["lakes"]) == 1
    assert hydro["lakes"][0]["coords"][0][0] > 100000          # reprojected metres
    assert len(hydro["rivers"]) == 1                            # order-2 filtered out
    assert hydro["rivers"][0]["order"] == 4
    assert hydro["rivers"][0]["name"] == "Susan River"

def test_bake_handles_empty():
    assert bake_hydro(None, None, "EPSG:32610") == {"crs": "EPSG:32610", "lakes": [], "rivers": []}
