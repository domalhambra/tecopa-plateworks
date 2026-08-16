"""Route demo journeys over a real road/trail network (spec:
docs/superpowers/specs/2026-08-15-real-network-demo-tracks-design.md).

Pure module: reads the gitignored cache written by fetch_track_network.py,
never the network. Vertex-per-point graph -- every way point is a vertex keyed
by its rounded coords, so ways that share OSM nodes connect automatically and
no way-splitting logic exists to get wrong. County-scale plates stay small."""
from __future__ import annotations
import heapq
import json
import os
from datetime import date, timedelta

import numpy as np

SNAP_MAX_M = 2_000.0          # destination -> network snap ceiling (spec §3)
LOOP_SHARE_MAX = 0.35         # loops: 2nd path may reuse <=35% of 1st path's edges
LOOP_PENALTY = 4.0            # cost multiplier on 1st-path edges when seeking the 2nd
POINT_SPACING_M = 15.0        # GPS densification (spec §3)
JITTER_M = 3.0                # seeded GPS jitter (spec §3)
WEIGHTS = {                   # class-weighted edge costs (spec §2)
    "outing":   {"trail": 0.6, "4wd": 0.7,  "road": 1.5},
    "approach": {"trail": 1.3, "4wd": 1.0,  "road": 0.7},
    "4wd_day":  {"trail": 2.5, "4wd": 0.5,  "road": 1.0},
}
SEASONS = {                   # kind -> (first day-of-year, last), spec §3 date buckets
    "lake":   (60, 181),      # Mar-Jun
    "gap":    (152, 243),     # Jun-Aug
    "summit": (182, 304),     # Jul-Oct
}


class Graph:
    def __init__(self):
        self.adj: dict[tuple, list[tuple]] = {}   # key -> [(other_key, edge_idx)]
        self.edges: list[dict] = []               # {"class", "coords", "len_m"}

    @staticmethod
    def key(pt) -> tuple:
        return (round(float(pt[0]), 1), round(float(pt[1]), 1))

    def vertex_array(self):
        ks = list(self.adj.keys())
        return ks, np.array(ks, dtype=float)


def build_graph(ways: list[dict]) -> Graph:
    g = Graph()
    for w in ways:
        pts = w["coords"]
        for a, b in zip(pts, pts[1:]):
            ka, kb = g.key(a), g.key(b)
            if ka == kb:
                continue
            length = float(np.hypot(b[0] - a[0], b[1] - a[1]))
            idx = len(g.edges)
            g.edges.append({"class": w["class"],
                            "coords": [list(map(float, a)), list(map(float, b))],
                            "len_m": length})
            g.adj.setdefault(ka, []).append((kb, idx))
            g.adj.setdefault(kb, []).append((ka, idx))
    return g


def load_network(path: str) -> list[dict]:
    with open(path) as f:
        return json.load(f)["ways"]


def dijkstra(*a, **k):
    raise NotImplementedError
