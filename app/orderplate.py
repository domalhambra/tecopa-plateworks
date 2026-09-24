# app/orderplate.py
"""Plate planning for one customer order (order pipeline spec, sections 2 and 3).

Frame the tracks "nestled", size the plate around the frame, and choose the DEM grid
and the 3DEP layer so the print is sharp without building terrain it cannot show.
Pure logic: pyproj and math only. The coverage query and the build itself run in
.venv-prep as subprocesses (app/orderprep.py)."""
from __future__ import annotations

import math

from pyproj import Transformer

from app.regionbuild import utm_epsg
from app.spec import MAX_UPSAMPLE

DPI = 300
NESTLE_FILL = 0.60        # tracks span this share of the frame, on the side they fill more
FILL_WARN = 0.40          # below this the tracks no longer read as nestled
PLATE_MARGIN = 0.10       # the plate is the frame grown by this share on every side
PLATE_PAD_M = 1000.0      # extra ground under region_prep's 500 m grid inset
MIN_FRAME_M = 2000.0      # a walk round the block still gets a 2 km frame
ALBERS_EPSG = 5070
ALBERS_ABOVE_M = 600_000.0
COVERAGE_MIN = 0.995      # a layer counts only if it covers this share of the plate
STATIC_LAYERS_M = (10, 30, 60)   # py3dep's fast static tiles
# Below 10 m the grid is fetched from the 3DEP dynamic service, which resamples the
# finest source it holds. Plan Task 1 measured whether that is real lidar detail.
USE_DYNAMIC_FINE = True
CONUS = (-125.5, 24.3, -66.8, 49.5)


class PlateError(ValueError):
    """An order's plate cannot be planned or built. The message is for Dom."""


def conus_covered(bbox) -> bool:
    w, s, e, n = bbox
    return w >= CONUS[0] and s >= CONUS[1] and e <= CONUS[2] and n <= CONUS[3]


def _ring(bbox, n=41):
    """Points along all four edges: edges curve under projection, corners don't bound."""
    w, s, e, nn = bbox
    t = [i / (n - 1) for i in range(n)]
    xs = [w + f * (e - w) for f in t] * 2 + [w] * n + [e] * n
    ys = [s] * n + [nn] * n + [s + f * (nn - s) for f in t] * 2
    return xs, ys


def project_bbox(bbox_lonlat, epsg) -> tuple:
    fwd = Transformer.from_crs("EPSG:4326", f"EPSG:{epsg}", always_xy=True)
    xs, ys = fwd.transform(*_ring(bbox_lonlat))
    return (min(xs), min(ys), max(xs), max(ys))


def to_lonlat_bbox(bounds_m, epsg, pad_m=0.0) -> tuple:
    minx, miny, maxx, maxy = bounds_m
    padded = (minx - pad_m, miny - pad_m, maxx + pad_m, maxy + pad_m)
    inv = Transformer.from_crs(f"EPSG:{epsg}", "EPSG:4326", always_xy=True)
    lons, lats = inv.transform(*_ring(padded))
    return (min(lons), min(lats), max(lons), max(lats))


def _centred(cx, cy, w, h) -> tuple:
    return (cx - w / 2.0, cy - h / 2.0, cx + w / 2.0, cy + h / 2.0)


def nestled_frame(track_bounds_m, aspect, fill=NESTLE_FILL) -> tuple:
    """A frame centred on the tracks, `aspect` (width / height), in which the tracks
    span `fill` of the frame on the side they fill more."""
    minx, miny, maxx, maxy = track_bounds_m
    w = max((maxx - minx) / fill, (maxy - miny) / fill * aspect, MIN_FRAME_M)
    return _centred((minx + maxx) / 2.0, (miny + maxy) / 2.0, w, w / aspect)


def track_fill(track_bounds_m, frame) -> float:
    tw = track_bounds_m[2] - track_bounds_m[0]
    th = track_bounds_m[3] - track_bounds_m[1]
    return max(tw / (frame[2] - frame[0]), th / (frame[3] - frame[1]))


def order_epsg(bbox, aspect) -> int:
    """The UTM zone of the tracks' centre, unless the print's own nestled frame is
    wider than 600 km, in which case CONUS Albers.

    The 600 km line is drawn on the frame that will actually be built, in a
    provisional UTM, not on a straight-line estimate of the tracks: a tall narrow
    track can need Albers in landscape while staying UTM in portrait, and a track
    under 600 km wide can still open out past it once nestled to fill the frame."""
    utm = utm_epsg(bbox)
    frame = nestled_frame(project_bbox(bbox, utm), aspect)
    return ALBERS_EPSG if (frame[2] - frame[0]) > ALBERS_ABOVE_M else utm


def widen_frame(frame, width_m) -> tuple:
    """The same centre and aspect, `width_m` wide. Never shrinks."""
    w0, h0 = frame[2] - frame[0], frame[3] - frame[1]
    if width_m <= w0:
        return tuple(frame)
    return _centred((frame[0] + frame[2]) / 2.0, (frame[1] + frame[3]) / 2.0,
                    width_m, width_m * h0 / w0)


def plate_bounds(frame, margin=PLATE_MARGIN) -> tuple:
    w, h = frame[2] - frame[0], frame[3] - frame[1]
    return (frame[0] - margin * w, frame[1] - margin * h,
            frame[2] + margin * w, frame[3] + margin * h)


def needed_resolution(frame, print_w_in, dpi=DPI) -> float:
    """Metres of ground per printed pixel: the finest detail the print can show."""
    return (frame[2] - frame[0]) / (print_w_in * dpi)


def _nice_floor(m) -> float:
    step = 5.0 if m < 100 else 10.0 if m < 500 else 50.0
    return step * math.floor(m / step)


def _nice_grid(need_m, finest) -> float:
    """The plate cell region_prep would reach for at `need_m`, ignoring whether a
    static layer is actually covered: nice steps (5 m under 100 m, 10 m under 500 m,
    else 50 m) at or above 10 m, quarter metres below it, never finer than `finest`."""
    if need_m >= STATIC_LAYERS_M[0]:
        return _nice_floor(need_m)
    return max(float(finest), math.floor(need_m * 4) / 4.0)


def choose_grid(need_m, coverage) -> dict:
    """The plate's grid for a print that needs `need_m` metres of ground per pixel.
    `coverage` maps 3DEP layer metres (int, or a string as JSON round-trips them) to
    the share of the plate it covers.

    region_prep fetches every grid at its own cell size: 10, 30 and 60 m from the
    static tiles, anything else from the dynamic service, which resamples the finest
    data it holds. grid_m is the plate's cell (its native_resolution_m). layer_m is
    the 3DEP layer the data comes from. upsample is grid_m / need_m, at least 1.
    widen is True when even the finest layer is past MAX_UPSAMPLE, so the caller
    must widen the frame.

    A nice grid at or above 10 m can land on a static size (10, 30, 60) whose own
    layer isn't fully covered even when a finer layer is: region_prep would then
    reach for a static tile with holes in it. When that happens the grid steps down
    to the next non-static value below that size (10 -> 9.75, 30 -> 25, 60 -> 55) so
    the dynamic service serves it from the finest layer that is actually covered,
    and layer_m records that layer instead of the uncovered static one."""
    coverage = {int(r): share for r, share in coverage.items()}
    covered = sorted(r for r, share in coverage.items()
                     if share >= COVERAGE_MIN
                     and (USE_DYNAMIC_FINE or r in STATIC_LAYERS_M))
    if not covered:
        raise PlateError("No 3DEP elevation layer fully covers this ground.")
    finest = covered[0]
    if finest > need_m:
        upsample = finest / need_m
        return {"grid_m": float(finest), "layer_m": finest, "upsample": upsample,
                "widen": upsample > MAX_UPSAMPLE}
    grid = _nice_grid(need_m, finest)
    if grid in STATIC_LAYERS_M and int(grid) not in covered:
        grid = _nice_grid(grid - 1e-6, finest)
        layer = finest
    else:
        layer = int(grid) if grid in STATIC_LAYERS_M else finest
    return {"grid_m": grid, "layer_m": layer, "upsample": 1.0, "widen": False}


def widen_for_upsample(frame, layer_m, print_w_in, dpi=DPI) -> tuple:
    """Grow the frame until `layer_m` data is at most MAX_UPSAMPLE times too coarse.
    The 1e-6 headroom keeps validate()'s strict `<` from reading exactly 2x as too
    tight after float round-trips; it assumes a whole-number print width, since
    validate() rounds to whole pixels and every paper-table size is a whole number
    of inches."""
    width = layer_m / MAX_UPSAMPLE * print_w_in * dpi * (1.0 + 1e-6)
    return widen_frame(frame, width)


def curated_fit(track_bbox_lonlat, aspect, print_w_in, regions):
    """The first curated plate that holds the nestled frame's plate (the frame plus
    its PLATE_MARGIN border) at the print's resolution with no upsampling. A built
    plate carries that margin round the frame for oblique previews and studio frame
    changes, so a reused plate must hold it too, not just the bare frame. `regions`
    holds dicts with id, crs ("EPSG:n"), bounds (CRS metres) and native_resolution_m.
    Returns {"region", "frame", "need_m", "epsg"} or None."""
    for r in regions:
        epsg = int(str(r["crs"]).split(":")[1])
        frame = nestled_frame(project_bbox(track_bbox_lonlat, epsg), aspect)
        need = needed_resolution(frame, print_w_in)
        plate = plate_bounds(frame)
        b = r["bounds"]
        inside = (plate[0] >= b[0] and plate[1] >= b[1]
                  and plate[2] <= b[2] and plate[3] <= b[3])
        if inside and r["native_resolution_m"] <= need:
            return {"region": r, "frame": frame, "need_m": need, "epsg": epsg}
    return None
