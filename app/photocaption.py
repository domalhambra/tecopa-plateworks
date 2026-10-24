# app/photocaption.py
"""A photo's default caption: the nearest named place on the plate (order-photos B5).

The name comes from the plate's ``labels.json`` (GNIS landforms), measured from the spot
to each feature's nearest vertex, and only within ``CAPTION_RADIUS_M``; else the caption
is empty. ``hydro.json`` names are not used. A tie in distance takes the higher kind rank,
the one ``render._label_candidates`` orders by (``GEO_KINDS[kind][2]``, not the rank stored
in labels.json), then the name, so the answer never depends on feature order (invariant 3).
Pure: no rendering, no I/O; the caller passes the parsed ``labels.json``. The kind ranks are
copied here so the module stays free of ``app.render``; a test fails if they drift.
"""
from __future__ import annotations

import math

CAPTION_RADIUS_M = 2000.0   # a named place further than this from the spot is not its name

# Copy of render.GEO_KINDS[kind][2]; tests/test_photocaption.py asserts it still matches.
_KIND_RANK = {"range": 100, "summit": 85, "lake": 66, "gap": 60, "flat": 52,
              "basin": 50, "valley": 44, "river": 40}


def nearest_name(x: float, y: float, labels: dict | None,
                 radius_m: float = CAPTION_RADIUS_M) -> str:
    """The name of the labels.json feature nearest ``(x, y)`` (plate CRS metres) within
    ``radius_m`` (inclusive), or ``""``. Distance is to a feature's nearest vertex."""
    best_key, best_name = None, ""
    for feat in ((labels or {}).get("features") or []):
        name = (feat.get("name") or "").strip()
        if not name:
            continue
        dists = [math.hypot(px - x, py - y) for px, py in (feat.get("coords") or [])]
        if not dists:
            continue
        d = min(dists)
        if not d <= radius_m:
            continue
        key = (d, -_KIND_RANK.get(feat.get("kind"), 0), name)
        if best_key is None or key < best_key:
            best_key, best_name = key, name
    return best_name
