# app/orderpreview.py
"""The size preview of an order: frame the tracks at every size, offer the sizes that
suit them, and show each one on a coarse plate.

Spec: docs/superpowers/specs/2026-10-11-print-sizes-panel-sets-and-size-preview-design.md,
section 5. This file never imports app.main, and it imports the renderer only inside
render_maps, so the framing can be tested with no DEM."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from app.order import ORIENTATIONS, SIZE_KEYS, parse_order_size
from app.orderplate import PlateError, nestled_frame, track_shares

SET_MIN_FILL = 0.30        # a set is offered when the tracks span this share of its width
PREVIEW_GAP_IN = 2.0       # every set is framed and shown at this gap


@dataclass(frozen=True)
class Candidate:
    key: str               # "11x17", "17x22", "two" or "three"
    panels: int
    orientation: str       # "portrait" or "landscape"
    print_in: tuple        # (width, height) in inches: for a set, the hung sheet
    gap: float

    @property
    def aspect(self) -> float:
        return self.print_in[0] / self.print_in[1]


def candidates(key) -> list:
    """The two orientations of one size. Landscape on a set is panels 22 in across."""
    (short, long_), panels = parse_order_size(key)
    gap = PREVIEW_GAP_IN if panels > 1 else 0.0
    out = []
    for orientation in ORIENTATIONS:
        landscape = orientation == "landscape"
        if panels > 1:
            across = long_ if landscape else short
            size = (panels * across + (panels - 1) * gap, short if landscape else long_)
        else:
            size = (long_, short) if landscape else (short, long_)
        out.append(Candidate(key, panels, orientation, size, gap))
    return out


def choose(cands, bounds_m) -> Candidate:
    """The orientation with less wasted ground: the one whose nestled frame the
    tracks fill more on their weaker side. A tie keeps the first, portrait."""
    return max(cands, key=lambda c: min(track_shares(bounds_m, nestled_frame(bounds_m, c.aspect))))


def _samples(tracks_m, step) -> np.ndarray:
    """Points along every track, at most `step` metres apart, so a long straight
    leg counts on every panel it crosses."""
    out = []
    for t in tracks_m:
        t = np.asarray(t, float).reshape(-1, 2)
        if len(t) < 2:
            out.append(t)
            continue
        dist = np.concatenate([[0.0], np.cumsum(np.hypot(*np.diff(t, axis=0).T))])
        at = np.linspace(0.0, dist[-1], max(2, int(dist[-1] / step) + 1))
        out.append(np.column_stack([np.interp(at, dist, t[:, 0]), np.interp(at, dist, t[:, 1])]))
    return np.concatenate(out) if out else np.empty((0, 2))


def panels_with_track(tracks_m, frame, cand) -> list:
    """For each panel of a set, True when some part of a track lies on it."""
    w_in = cand.print_in[0]
    pts = _samples(tracks_m, (frame[2] - frame[0]) / 500.0)
    xs = (pts[:, 0] - frame[0]) / (frame[2] - frame[0]) * w_in
    ys = (pts[:, 1] - frame[1]) / (frame[3] - frame[1])
    inside = (ys >= 0.0) & (ys <= 1.0)
    across = (w_in - (cand.panels - 1) * cand.gap) / cand.panels
    step = across + cand.gap
    return [bool(np.any(inside & (xs >= k * step) & (xs <= k * step + across)))
            for k in range(cand.panels)]


def gaps_hiding_ends(tracks_m, frame, cand) -> list:
    """The gaps of a window set, numbered from 1, that hide a route end: the first
    or the last point of a track. A route end is tied to the ground, so only the
    frame can move it. A cut set and a single sheet hide nothing."""
    if cand.panels == 1 or not cand.gap:
        return []
    w_in = cand.print_in[0]
    step = (w_in - (cand.panels - 1) * cand.gap) / cand.panels + cand.gap
    hidden = set()
    for t in tracks_m:
        t = np.asarray(t, float).reshape(-1, 2)
        for x, y in ((t[0], t[-1]) if len(t) else ()):
            if not frame[1] <= y <= frame[3]:
                continue
            at = (x - frame[0]) / (frame[2] - frame[0]) * w_in
            hidden.update(k for k in range(1, cand.panels) if k * step - cand.gap < at < k * step)
    return sorted(hidden)


def judge(cand, frame, bounds_m, tracks_m) -> dict:
    """One size's entry: its frame, its shares, and the fit rule's answer."""
    w_share, h_share = track_shares(bounds_m, frame)
    entry = {"key": cand.key, "panels": cand.panels, "orientation": cand.orientation,
             "print_in": [float(v) for v in cand.print_in], "gap": cand.gap,
             "frame": [float(v) for v in frame],
             "fill": round(max(w_share, h_share), 3), "width_share": round(w_share, 3),
             "offered": True, "why": "", "warning": "", "blocked": False,
             "ends_behind": gaps_hiding_ends(tracks_m, frame, cand)}
    if cand.panels > 1:
        empty = [str(k + 1) for k, has in enumerate(panels_with_track(tracks_m, frame, cand))
                 if not has]
        if round(w_share, 3) < SET_MIN_FILL:
            entry.update(offered=False, why=f"the tracks span {w_share:.0%} of the sheet's "
                                            f"width, under {SET_MIN_FILL:.0%}")
        elif empty:
            entry.update(offered=False, why=f"panel {' and '.join(empty)} holds no track")
    return entry


def plan_sizes(bounds_m, tracks_m, widen=None, forced=()) -> list:
    """One entry for each size, in menu order.

    `widen(cand, frame)` returns the frame the real print would get under the 2x
    rule, or raises PlateError when the terrain cannot hold the size. `forced` is
    the `sizes` list of order.toml: it overrides the fit rule, never the terrain."""
    entries = []
    for key in SIZE_KEYS:
        cand = choose(candidates(key), bounds_m)
        frame = nestled_frame(bounds_m, cand.aspect)
        try:
            if widen is not None:
                frame = widen(cand, frame)
            entry = judge(cand, frame, bounds_m, tracks_m)
        except PlateError as ex:
            entry = judge(cand, frame, bounds_m, tracks_m)
            entry.update(offered=False, why=str(ex), blocked=True)
        if forced and not entry["blocked"]:
            if key in forced:
                entry.update(offered=True, warning=entry["why"], why="")
            else:
                entry.update(offered=False, why="it is not in the sizes list of order.toml")
        entries.append(entry)
    return entries
