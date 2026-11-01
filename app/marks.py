# app/marks.py
"""Which hotspots are real marks: places a person put on the poster on purpose.

A mark is the observer of the viewshed wash (docs/superpowers/specs/2026-11-01-
viewshed-wash-design.md, decisions 2 and 16). A density spot (app.density.hotspots)
sits at the centre of a busy cell: nobody stood there on purpose, so it is not a mark.
Pure functions over hotspot dicts; nothing here reads a plate.
"""
from __future__ import annotations
import math


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
