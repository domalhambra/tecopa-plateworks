# app/marks.py
"""Which hotspots are real marks: places a person put on the poster on purpose.

A mark is the observer of the viewshed wash (docs/superpowers/specs/2026-11-01-
viewshed-wash-design.md, decisions 2 and 16). A density spot (app.density.hotspots)
sits at the centre of a busy cell: nobody stood there on purpose, so it is not a mark.
Pure functions over hotspot dicts; nothing here reads a plate.
"""
from __future__ import annotations
import math

# two waypoints this close (metres, in the plate's CRS) are the same waypoint arriving twice:
# a re-export, or two overlapping exports of one phone, carries last year's pins again.
WAYPOINT_SAME_M = 1.0


def is_mark(hs: dict) -> bool:
    """True for a waypoint (`mark: true`), a hotspot with a photo, or one with a
    non-empty label. A manifest from before `mark` existed needs no migration: its
    named and photo spots count, and its unnamed density spots do not."""
    if not isinstance(hs, dict):
        return False
    if hs.get("mark") is True or hs.get("photo"):
        return True
    label = hs.get("label")
    return isinstance(label, str) and bool(label.strip())


def observers(hotspots: list) -> list[tuple[float, float]]:
    """The (x, y) of every mark in order, duplicates kept. A mark whose position is
    missing or not finite has no place to look from and is left out."""
    out = []
    for hs in hotspots or []:
        if not is_mark(hs):
            continue
        try:
            x, y = float(hs["x"]), float(hs["y"])
        except (KeyError, TypeError, ValueError):
            continue
        if math.isfinite(x) and math.isfinite(y):
            out.append((x, y))
    return out


def within(a: dict, b: dict, metres: float) -> bool:
    """True when hotspots `a` and `b` are closer than `metres` (their x, y in metres)."""
    return ((a["x"] - b["x"]) ** 2 + (a["y"] - b["y"]) ** 2) ** 0.5 < metres


def is_same_waypoint(w: dict, spots: list) -> bool:
    """True when some waypoint (`mark: true`) in `spots` is within WAYPOINT_SAME_M of `w`:
    `w` is that waypoint arriving a second time. The upload path (app.main) and an order's
    Prepare both ask this one question."""
    return any(s.get("mark") is True and within(w, s, WAYPOINT_SAME_M) for s in spots)


def collapse_waypoints(waypoints: list) -> tuple[list, int]:
    """(kept, collapsed): `waypoints` in order, each one dropped when it is the same waypoint
    (is_same_waypoint) as one kept before it, and how many were dropped. Two waypoints
    that are close but not the same both stay (decision 17). A grid of WAYPOINT_SAME_M cells
    finds the neighbours, so a thousand waypoints cost a thousand look-ups, not a million
    comparisons."""
    kept, collapsed, cells = [], 0, {}
    for w in waypoints:
        cx, cy = math.floor(w["x"] / WAYPOINT_SAME_M), math.floor(w["y"] / WAYPOINT_SAME_M)
        near = [s for dx in (-1, 0, 1) for dy in (-1, 0, 1)
                for s in cells.get((cx + dx, cy + dy), ())]
        if is_same_waypoint(w, near):
            collapsed += 1
            continue
        kept.append(w)
        cells.setdefault((cx, cy), []).append(w)
    return kept, collapsed
