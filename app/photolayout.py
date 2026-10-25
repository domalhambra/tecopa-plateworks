# app/photolayout.py
"""Lay order photos out in open ground, or send them all to the gallery band.

Pure geometry on an ``render.Occupancy`` (what a box must stay off, in pixels at its
``dpi``). Spots are sheet inches (x, y), y down, the canvas origin: pixel = inch x dpi.
A box is a square of side ``box_in``. A box offset ``(dx_in, dy_in)`` is the PHOTO's centre offset from
its spot, in inches, y down, as ``render._photo_box_offset`` reads it.

What a box occupies is the whole frame the renderer paints, not the bare square: the
photo plus its mat. ``frame = (side, top, bottom)`` are fractions of ``box_in`` (the triple
``render._photo_frame_fracs(style)`` returns), so the occupied rect runs from
``cx - box/2 - side*box`` to ``cx + box/2 + side*box`` across and from
``cy - box/2 - top*box`` to ``cy + box/2 + bottom*box`` down. That rect is the one tested
against the trim, the keep-out rects, the route and the other boxes (``BAND_PAD_IN`` clear),
and the one the leader ends on. The open-ground photo draws no caption (only the band
does), so there is no caption allowance here.

A leader runs from the spot to the edge of the frame on the line toward the frame's
centre: ``render._leader_end``, the line the renderer draws, so layout and render agree.
A candidate's leader length is the distance from the spot to that edge point.

Candidates are RING_DIRECTIONS directions (N, NE, E, SE, S, SW, W, NW) at each of
RING_STEPS_IN. A step is the gap between the spot and the nearest edge of the box along
the direction (the frame edge, mat included), so the leader is that long. With ``hx`` and
``hy`` the half-extents of the frame from the photo centre on the side facing the spot,
an axis direction puts the centre at ``step + h`` and a diagonal with unit direction ``u``
at ``u * step + (sx * hx, sy * hy)``, which puts the frame's nearest corner ``step`` away
along the diagonal.

Extra rule beyond the ring: a candidate's frame may not touch a placed leader, and its
leader may not pass through a placed frame. This is how a later photo avoids a fixed box
and its leader, and it holds for every placed photo. A photo whose spot lies inside a
placed frame therefore has no valid candidate, so a candidate frame may not cover any other
photo's spot either (a spot equal to its own does not count). Leaders that start at one
spot (photos at the same place) ignore contact at that start, but not a shared line.

Deterministic: no randomness, and no dependence on dict order or on the order of float
ties (ties go to the earlier direction).
"""
from __future__ import annotations

import math

from app import render

OPEN_MAX = 8                       # more spots than this, and the photos hang in the band
BAND_MAX = 12                      # the band's capacity (enforced by the caller)
RING_DIRECTIONS = 8
RING_STEPS_IN = (0.6, 1.0, 1.5)    # spot to nearest box edge, inches

# N, NE, E, SE, S, SW, W, NW as (sx, sy), y down the sheet
_DIRECTIONS = ((0, -1), (1, -1), (1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1))
_EPS = 1e-6


def _centre_offset(direction, step, box_in, frame):
    """The photo-centre offset that puts the frame's near edge `step` from the spot."""
    sx, sy = direction
    norm = math.hypot(sx, sy)
    fs, ft, fb = frame
    hx = box_in * (0.5 + fs)
    hy = box_in * (0.5 + (fb if sy < 0 else ft))     # box above: its bottom mat faces the spot
    return (round(sx / norm * step + sx * hx, 9), round(sy / norm * step + sy * hy, 9))


def _box_rect(spot, off, box_in, dpi, frame):
    """The frame as a float pixel rect (x0, y0, x1, y1): photo plus mat."""
    fs, ft, fb = frame
    cx, cy = (spot[0] + off[0]) * dpi, (spot[1] + off[1]) * dpi
    h = box_in * dpi / 2.0
    s, t, b = box_in * dpi * fs, box_in * dpi * ft, box_in * dpi * fb
    return (cx - h - s, cy - h - t, cx + h + s, cy + h + b)


def _leader(spot, rect, dpi):
    """((ax, ay), (ex, ey)) in pixels, or None when the spot is inside the box."""
    ax, ay = spot[0] * dpi, spot[1] * dpi
    end = render._leader_end(ax, ay, rect)
    return None if end is None else ((ax, ay), end)


def _length(seg):
    (ax, ay), (ex, ey) = seg
    return math.hypot(ex - ax, ey - ay)


def _rects_overlap(a, b, pad=0.0):
    return (a[0] < b[2] + pad - _EPS and b[0] < a[2] + pad - _EPS
            and a[1] < b[3] + pad - _EPS and b[1] < a[3] + pad - _EPS)


def _orient(a, b, c):
    v = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    return 0 if abs(v) < _EPS else (1 if v > 0 else -1)


def _on_segment(a, b, c):
    return (min(a[0], b[0]) - _EPS <= c[0] <= max(a[0], b[0]) + _EPS
            and min(a[1], b[1]) - _EPS <= c[1] <= max(a[1], b[1]) + _EPS)


def _segments_touch(s, t):
    """True when the two segments cross or touch (collinear overlap included)."""
    p1, p2 = s
    p3, p4 = t
    o1, o2, o3, o4 = _orient(p1, p2, p3), _orient(p1, p2, p4), _orient(p3, p4, p1), _orient(p3, p4, p2)
    if o1 != o2 and o3 != o4:
        return True
    return ((o1 == 0 and _on_segment(p1, p2, p3)) or (o2 == 0 and _on_segment(p1, p2, p4))
            or (o3 == 0 and _on_segment(p3, p4, p1)) or (o4 == 0 and _on_segment(p3, p4, p2)))


def _leaders_clash(s, t, dpi):
    """True when two leaders cross, or run along each other. Leaders that start at the same
    spot (photos at one spot, within 1e-9 in) touch there by construction: that contact is
    ignored, but two leaders leaving it along the same line still clash."""
    if (abs(s[0][0] - t[0][0]) <= 1e-9 * dpi and abs(s[0][1] - t[0][1]) <= 1e-9 * dpi):
        (ax, ay), (ex, ey) = s
        (_, _), (fx, fy) = t
        ux, uy, vx, vy = ex - ax, ey - ay, fx - ax, fy - ay
        cross = ux * vy - uy * vx
        return abs(cross) <= _EPS * max(1.0, math.hypot(ux, uy) * math.hypot(vx, vy)) \
            and ux * vx + uy * vy > 0
    return _segments_touch(s, t)


def _segment_hits_rect(seg, rect):
    """Liang-Barsky: does the segment touch the rect (edges included)?"""
    (x0, y0), (x1, y1) = seg
    dx, dy = x1 - x0, y1 - y0
    t0, t1 = 0.0, 1.0
    for p, q in ((-dx, x0 - rect[0]), (dx, rect[2] - x0), (-dy, y0 - rect[1]), (dy, rect[3] - y0)):
        if abs(p) < 1e-12:
            if q < -_EPS:
                return False
            continue
        r = q / p
        if p < 0:
            if r > t1 + _EPS:
                return False
            t0 = max(t0, r)
        else:
            if r < t0 - _EPS:
                return False
            t1 = min(t1, r)
    return t0 <= t1 + _EPS


def _covers(rect, other_spot, own_spot, dpi):
    """True when the frame rect covers another photo's spot (a spot equal to the photo's own
    does not count): that photo's leader would start inside a frame and could never be placed."""
    if (abs(other_spot[0] - own_spot[0]) <= 1e-9 and abs(other_spot[1] - own_spot[1]) <= 1e-9):
        return False
    x, y = other_spot[0] * dpi, other_spot[1] * dpi
    return rect[0] - _EPS <= x <= rect[2] + _EPS and rect[1] - _EPS <= y <= rect[3] + _EPS


def _ground_ok(rect, occ):
    """Inside the trim, outside every keep-out rect, off the route mask."""
    w, h = occ.size_px
    tx0, ty0, tx1, ty1 = occ.trim_px if occ.trim_px is not None else (0, 0, w, h)
    if rect[0] < tx0 - _EPS or rect[1] < ty0 - _EPS or rect[2] > tx1 + _EPS or rect[3] > ty1 + _EPS:
        return False
    if any(_rects_overlap(rect, r) for r in occ.rects):
        return False
    x0, y0 = max(0, math.floor(rect[0] + _EPS)), max(0, math.floor(rect[1] + _EPS))
    x1, y1 = min(w, math.ceil(rect[2] - _EPS)), min(h, math.ceil(rect[3] - _EPS))
    return not occ.route[y0:y1, x0:x1].any()


def layout(spots_in: list, box_in: float, occ, fixed: dict | None = None,
           frame: tuple = (0.0, 0.0, 0.0)) -> dict:
    """Place a square photo of side ``box_in`` (plus its ``frame`` mat) for each spot, or send
    every photo to the band.

    Returns ``{"layout": "open" | "band", "boxes": {i: (dx_in, dy_in)}, "unplaced": []}``.
    "open" carries a box for every photo (``fixed`` ones as given); "band" carries
    ``boxes = {}`` and ``unplaced = []`` (the renderer lays the band out itself, and the
    two layouts never mix). ``fixed`` maps photo index -> (dx_in, dy_in), Dom's moves, kept
    as they are even if invalid; later photos still keep off the fixed box and its leader.
    ``frame`` is (side, top, bottom) as fractions of ``box_in``: ``render._photo_frame_fracs``.

    Order: fixed photos by index, then the rest by spot y, then x, then index. A candidate
    is valid when its box is inside the trim, outside every ``occ.rects`` rect (a set's seam
    bands are among them), off ``occ.route``, ``BAND_PAD_IN`` clear of every placed box, its
    leader crosses no placed leader, and neither does its box meet a placed leader nor its
    leader a placed box. The valid candidate with the shortest leader wins; ties go to the
    earlier direction. No valid candidate for any photo -> the band."""
    band = {"layout": "band", "boxes": {}, "unplaced": []}
    n = len(spots_in)
    fixed_map = {int(i): (float(o[0]), float(o[1]))
                 for i, o in (fixed or {}).items() if 0 <= int(i) < n}
    if n > OPEN_MAX:
        return band
    frame = tuple(float(f) for f in frame)
    dpi = float(occ.dpi)
    pad = render.BAND_PAD_IN * dpi
    boxes, rects, leaders = {}, {}, []
    for i in sorted(fixed_map):
        rect = _box_rect(spots_in[i], fixed_map[i], box_in, dpi, frame)
        boxes[i], rects[i] = fixed_map[i], rect
        seg = _leader(spots_in[i], rect, dpi)
        if seg is not None:
            leaders.append(seg)
    rest = sorted((i for i in range(n) if i not in fixed_map),
                  key=lambda i: (spots_in[i][1], spots_in[i][0], i))
    for i in rest:
        best = None                                   # (rounded length, direction rank, offset)
        for step in RING_STEPS_IN:
            for rank, direction in enumerate(_DIRECTIONS):
                off = _centre_offset(direction, step, box_in, frame)
                rect = _box_rect(spots_in[i], off, box_in, dpi, frame)
                if not _ground_ok(rect, occ):
                    continue
                if any(_covers(rect, spots_in[j], spots_in[i], dpi)
                       for j in range(n) if j != i):
                    continue
                if any(_rects_overlap(rect, other, pad) for other in rects.values()):
                    continue
                seg = _leader(spots_in[i], rect, dpi)
                if seg is None:
                    continue
                if any(_leaders_clash(seg, other, dpi) for other in leaders):
                    continue
                if any(_segment_hits_rect(seg, other) for other in rects.values()):
                    continue
                if any(_segment_hits_rect(other, rect) for other in leaders):
                    continue
                key = (round(_length(seg), 6), rank)
                if best is None or key < best[0]:
                    best = (key, off, rect, seg)
        if best is None:
            return band
        _, off, rect, seg = best
        boxes[i], rects[i] = off, rect
        leaders.append(seg)
    return {"layout": "open", "boxes": {i: boxes[i] for i in sorted(boxes)}, "unplaced": []}
