# app/geo.py
from __future__ import annotations
from dataclasses import dataclass
from functools import lru_cache
from pyproj import Transformer

@dataclass(frozen=True)
class RegionGeo:
    crs: str                       # e.g. "EPSG:32611"
    bounds: tuple                  # (min_x, min_y, max_x, max_y) in CRS meters
    overview_size: tuple           # (width_px, height_px)

@lru_cache(maxsize=8)
def _to_crs(crs: str) -> Transformer:
    # always_xy keeps argument order (lon, lat) -> (x, y)
    return Transformer.from_crs("EPSG:4326", crs, always_xy=True)

def lonlat_to_crs(region: RegionGeo, lon: float, lat: float):
    return _to_crs(region.crs).transform(lon, lat)

def crs_to_overview_px(region: RegionGeo, x: float, y: float):
    min_x, min_y, max_x, max_y = region.bounds
    w, h = region.overview_size
    px = (x - min_x) / (max_x - min_x) * w
    py = (max_y - y) / (max_y - min_y) * h   # image y grows downward
    return px, py

def overview_px_to_crs(region: RegionGeo, px: float, py: float):
    min_x, min_y, max_x, max_y = region.bounds
    w, h = region.overview_size
    x = min_x + (px / w) * (max_x - min_x)
    y = max_y - (py / h) * (max_y - min_y)
    return x, y

def crop_px_to_crs_window(region: RegionGeo, x0, y0, x1, y1):
    """A crop rectangle in overview pixels -> a CRS window (min_x, min_y, max_x, max_y)."""
    ax, ay = overview_px_to_crs(region, min(x0, x1), max(y0, y1))  # lower-left
    bx, by = overview_px_to_crs(region, max(x0, x1), min(y0, y1))  # upper-right
    return (ax, ay, bx, by)
