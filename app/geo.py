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


def refit_crop_aspect(crop, aspect, bounds, floor_w=0.0):
    """Re-fit a CRS crop window to a new width/height aspect, preserving its center
    and (roughly) its area, clamped inside `bounds` -- the server-side twin of the
    Frame step's refitForSize (canvas.js), used when one accepted composition is
    re-targeted at a differently-shaped sheet (wallpaper presets). `floor_w` (metres)
    is the zoom-cap floor width for the target output (native_resolution_m * output
    width in px): the box is grown to it so the result clears the cap whenever the
    region can hold such a box. A region too small for a floor-sized box at this
    aspect yields the largest in-bounds crop (best effort) and the too-tight state is
    surfaced by the caller's validate(), same contract as starter_crop. Returns
    (min_x, min_y, max_x, max_y) in CRS metres."""
    min_x, min_y, max_x, max_y = bounds
    reg_w, reg_h = max_x - min_x, max_y - min_y
    cx = (crop[0] + crop[2]) / 2.0
    cy = (crop[1] + crop[3]) / 2.0
    area = max((crop[2] - crop[0]) * (crop[3] - crop[1]), 1.0)
    # 1e-6 relative headroom on the floor: at UTM magnitudes (~1e6 m) the caller's
    # (x0 + w) - x0 round-trip can lose an ulp, and validate()'s zoom cap is a strict
    # `<` -- a box grown to EXACTLY the floor could spuriously read as too tight.
    # The nudge is ~1 cm of ground on a 10 km floor: invisible, never load-bearing.
    w = max((area * aspect) ** 0.5, floor_w * (1.0 + 1e-6))
    w = min(w, reg_w, reg_h * aspect)          # clamp to what the region box can hold
    h = w / aspect
    # keep the center, then slide the box fully inside the region bounds
    x0 = min(max(cx - w / 2, min_x), max_x - w)
    y0 = min(max(cy - h / 2, min_y), max_y - h)
    return (x0, y0, x0 + w, y0 + h)


def starter_crop(region: RegionGeo, tracks_px, print_w_in, print_h_in,
                 native_resolution_m, dpi=300, track_fraction=1 / 3):
    """A generous default crop (in overview px) for the Frame step: centered on the
    track centroid, aspect-locked to the print size, clamped to region bounds, and --
    WHEN the region is large enough to hold a floor-sized aspect box -- at or above the
    zoom-cap floor at `dpi`, so the first proof clears the cap. Deliberately NOT the
    tight track bounding box: a tight cluster blown up to print aspect would trip the
    cap and frame cramped terrain.

    A region too small to hold a floor-sized box at this aspect (region width <
    native_resolution_m * round(print_w_in * dpi), or too short for the aspect height)
    physically cannot satisfy the cap at this print size; this returns the largest
    in-region crop (best effort) and the too-tight state is surfaced downstream (the
    Frame red-tint and the proof's humanized 422). The two bundled regions both hold
    the 18x24 floor. tracks_px: polylines in overview px (as /api/upload returns).
    Returns (x0, y0, x1, y1) in overview pixels, ordered.
    """
    min_x, min_y, max_x, max_y = region.bounds
    reg_w, reg_h = max_x - min_x, max_y - min_y
    aspect = print_w_in / print_h_in                       # width / height

    # track centroid + span, converted to CRS metres (the cap lives in metres)
    pts = [p for t in tracks_px for p in t]
    if pts:
        xs = [overview_px_to_crs(region, px, py)[0] for px, py in pts]
        ys = [overview_px_to_crs(region, px, py)[1] for px, py in pts]
        cx, cy = sum(xs) / len(xs), sum(ys) / len(ys)
        span_w = (max(xs) - min(xs)) / track_fraction      # tracks ~ middle third
        span_h = (max(ys) - min(ys)) / track_fraction
    else:
        cx, cy = (min_x + max_x) / 2, (min_y + max_y) / 2
        span_w = span_h = 0.0

    floor_w = native_resolution_m * round(print_w_in * dpi)   # cap floor, metres
    # target width: the largest of (track-driven, aspect-fit of track height, floor),
    # then clamp to what the region box can actually hold at this aspect
    w = max(span_w, span_h * aspect, floor_w)
    w = min(w, reg_w, reg_h * aspect)
    h = w / aspect
    if h > reg_h:                                          # aspect vs region: refit on h
        h = reg_h
        w = h * aspect

    # center on the tracks, then slide the box fully inside the region bounds
    x0 = min(max(cx - w / 2, min_x), max_x - w)
    y0 = min(max(cy - h / 2, min_y), max_y - h)
    win = (x0, y0, x0 + w, y0 + h)                         # CRS (min_x,min_y,max_x,max_y)
    # map the CRS window back to overview px (image y flips)
    px0, py0 = crs_to_overview_px(region, win[0], win[3])   # top-left
    px1, py1 = crs_to_overview_px(region, win[2], win[1])   # bottom-right
    return (min(px0, px1), min(py0, py1), max(px0, px1), max(py0, py1))
