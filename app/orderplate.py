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
COVERAGE_TOLERANCE = 0.005   # a layer counts only if it covers everything the best
                              # layer covers, within 0.5%: ocean and foreign ground
                              # count against no layer
US_SHARE_MIN = 0.5        # below this, the plate is mostly outside US elevation data
STATIC_LAYERS_M = (10, 30, 60)   # py3dep's fast static tiles
# A covered static layer serves needs up to this multiple of its own cell before
# choose_grid falls back to the dynamic service; see choose_grid's docstring.
STATIC_SPAN = 2.0
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
    must widen the frame. us_share is the reference share coverage is judged
    against: the caller warns when it is below 1.0 (ocean or a border clips the
    plate).

    For need_m >= 10, a covered static layer (10 or 30 m; never 60, Alaska-only in
    the lower 48) is preferred whenever it can serve the need without upsampling
    past STATIC_SPAN: the largest such L with L <= need_m <= STATIC_SPAN * L is
    used exactly, as its own layer. The static tiles are COGs and fetch reliably;
    the dynamic WMS (elevation.nationalmap.gov) does not -- a real 35 m order plate
    failed it three times running even with generous retries, while static fetches
    never have. Since STATIC_SPAN is 2.0, a plate built this way holds at most 4x
    the print's pixel count (2x per side). When no covered static layer's span
    holds the need, grid selection falls back to the nice-floor path below,
    unchanged.

    Coverage is judged relative to a reference layer, not against an absolute bar:
    a plate that reaches the Pacific or a national border can never be fully
    covered by any layer, but a layer that covers everything the reference layer
    covers is still the right one to use (COVERAGE_TOLERANCE). The reference is the
    best share among the layers at or finer than 10 m that are present in
    `coverage` (1, 3, 10): 10 m is the 1/3 arc-second nationwide layer, the honest
    read of "how much of this plate is the US." A coarser layer (30, 60) can cover
    Canada or Mexico too -- a Montana/Alberta border box once read {10: 0.5253,
    30: 1.0}, and taking 30 m's 1.0 as the reference would have called the plate
    fully covered and silently dropped 10 m detail from the US two-thirds of it.
    When no layer at or finer than 10 m is present in `coverage` (a coarse-need
    query that only asked for 30 m and up), the reference falls back to the best
    share among whatever layers are present. A plate mostly outside US elevation
    data (US_SHARE_MIN) is refused outright rather than quietly built from
    whatever scrap of US ground it has.

    The static 60 m 3DEP tiles cover Alaska only (USGS_Seamless_DEM_2.vrt, lon
    -180..-127, lat 51..72); the 3DEP index correctly reads 0.0 for the 60 m layer
    everywhere in the lower 48, even well inland, because there is genuinely no
    60 m tile there. A nice grid landing on 60 m therefore always steps down to
    55 m in an order plate, served dynamically from whatever finer layer really is
    covered -- this is required, not a cosmetic fallback: region_prep has no 60 m
    data to reach for south of Alaska.

    A nice grid at or above 10 m can land on a static size (10, 30, 60) whose own
    layer isn't fully covered even when a finer layer is: region_prep would then
    reach for a static tile with holes in it. When that happens the grid steps down
    to the next non-static value below that size (10 -> 9.75, 30 -> 25, 60 -> 55) so
    the dynamic service serves it from the finest layer that is actually covered,
    and layer_m records that layer instead of the uncovered static one."""
    coverage = {int(r): share for r, share in coverage.items()}
    eligible = {r: share for r, share in coverage.items()
               if USE_DYNAMIC_FINE or r in STATIC_LAYERS_M}
    if not eligible:
        raise PlateError("No 3DEP elevation layer reports any coverage for this "
                         "ground.")
    us_reference = {r: share for r, share in eligible.items() if r <= 10}
    best = max(us_reference.values()) if us_reference else max(eligible.values())
    if best < US_SHARE_MIN:
        raise PlateError("Most of this plate has no US elevation data (ocean or "
                         "across a border). Frame the tracks tighter or choose a "
                         "smaller print.")
    covered = sorted(r for r, share in eligible.items()
                     if share >= best - COVERAGE_TOLERANCE)
    finest = covered[0]
    if finest > need_m:
        upsample = finest / need_m
        return {"grid_m": float(finest), "layer_m": finest, "upsample": upsample,
                "widen": upsample > MAX_UPSAMPLE, "us_share": best}
    if need_m >= STATIC_LAYERS_M[0]:
        static_pick = max((L for L in STATIC_LAYERS_M[:-1]
                           if L in covered and L <= need_m <= STATIC_SPAN * L),
                          default=None)
        if static_pick is not None:
            return {"grid_m": float(static_pick), "layer_m": static_pick,
                    "upsample": 1.0, "widen": False, "us_share": best}
    grid = _nice_grid(need_m, finest)
    if grid in STATIC_LAYERS_M and int(grid) not in covered:
        grid = _nice_grid(grid - 1e-6, finest)
        layer = finest
    else:
        layer = int(grid) if grid in STATIC_LAYERS_M else finest
    return {"grid_m": grid, "layer_m": layer, "upsample": 1.0, "widen": False,
            "us_share": best}


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
