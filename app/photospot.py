# app/photospot.py
"""Find a customer photo's ground spot on the order's plate.

Order (spec section 5): the photo's GPS first; else its capture time on a track (B4);
else ``None`` (the photo waits in the tray). A GPS spot is used as is, even outside the
plate; the caller warns about spots outside the frame. All coordinates are the plate's
CRS metres; ``geo.lonlat_to_crs`` is the only lon/lat source (invariant 5).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from app.geo import RegionGeo, lonlat_to_crs

PHOTO_TIME_TOLERANCE_S = 600   # a photo this far (or less) from a track time still matches


@dataclass(frozen=True)
class Spot:
    x: float
    y: float
    source: str   # "gps" or "time"


def _time_on_track(track, t: float):
    """(gap_s, x, y) for ``t`` on one track, or None. The gap is 0 inside the track's time
    span (the point is interpolated between the two surviving points around ``t``), else
    the distance to the nearest end, whose point is used."""
    times = getattr(track, "coords_t", None)
    if times is None:
        return None
    times = np.asarray(times, dtype=float)
    coords = np.asarray(track.coords, dtype=float)
    if times.shape[0] != coords.shape[0]:
        return None
    keep = np.isfinite(times)
    if not keep.any():
        return None
    ts, xy = times[keep], coords[keep]
    order = np.argsort(ts, kind="stable")
    ts, xy = ts[order], xy[order]
    if t < ts[0]:
        return (float(ts[0] - t), float(xy[0, 0]), float(xy[0, 1]))
    if t > ts[-1]:
        return (float(t - ts[-1]), float(xy[-1, 0]), float(xy[-1, 1]))
    hi = int(np.searchsorted(ts, t, side="left"))
    if ts[hi] == t:
        return (0.0, float(xy[hi, 0]), float(xy[hi, 1]))
    lo = hi - 1
    f = (t - ts[lo]) / (ts[hi] - ts[lo])
    x = xy[lo, 0] + f * (xy[hi, 0] - xy[lo, 0])
    y = xy[lo, 1] + f * (xy[hi, 1] - xy[lo, 1])
    return (0.0, float(x), float(y))


def spot_for(meta, tracks: list, region: RegionGeo) -> Spot | None:
    """GPS first, else the photo's UTC time on the nearest-in-time track, else None."""
    if meta.lonlat is not None:
        x, y = lonlat_to_crs(region, meta.lonlat[0], meta.lonlat[1])
        if math.isfinite(x) and math.isfinite(y):
            return Spot(float(x), float(y), "gps")
    t = meta.taken_utc
    if t is None or not math.isfinite(t):
        return None
    best = None
    for track in tracks:
        hit = _time_on_track(track, float(t))
        if hit is not None and (best is None or hit[0] < best[0]):
            best = hit   # strict <: the earlier track wins a tie (deterministic)
    if best is None or best[0] > PHOTO_TIME_TOLERANCE_S:
        return None
    return Spot(best[1], best[2], "time")


def in_frame(spot: Spot, frame: tuple) -> bool:
    """True when the spot lies inside ``frame`` = (min_x, min_y, max_x, max_y), edges included."""
    x0, y0, x1, y1 = frame
    return x0 <= spot.x <= x1 and y0 <= spot.y <= y1
