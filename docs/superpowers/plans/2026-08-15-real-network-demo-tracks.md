# Real-Network Demo Tracks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the farm's sine-wave demo tracks with seeded journeys routed over a real OSM road/trail network, anchored at real named destinations spread across the whole plate.

**Architecture:** Two new modules under `scripts/` — `track_network.py` (pure: cache loading, graph, Dijkstra, journey composer; no network access) and `fetch_track_network.py` (operator script: Overpass → gitignored `cache/networks/<region>.json`). One seam change in `render_asset_farm.py`: use the cache when present, fall back to `_synth_tracks` otherwise. Engine (`app/`) untouched.

**Tech Stack:** Python 3.14, numpy, pyproj (all already in `.venv`), `heapq` from stdlib. No new dependencies. Spec: `docs/superpowers/specs/2026-08-15-real-network-demo-tracks-design.md`.

**Conventions:** Repo policy overrides the worktree default — the Mac commits straight to `main`, only when green (`CLAUDE.md` Workflow). Run everything with `./.venv/bin/python`. All tests: `./.venv/bin/python -m pytest tests/test_track_network.py -q`.

**Ground truth already verified (do not re-derive):**
- `labels.json` = `{"crs", "features"}`; features are `{"name","kind","rank","coords"}`; kinds across all five plates: `range, summit, gap, basin, flat, valley` — **no `lake` kind**. `summit`/`gap` coords are `[[x,y]]` (single point).
- `hydro.json` = `{"crs", "lakes", "rivers"}`; lakes are `{"coords": [[x,y],…], "name": str}` — **some names are empty/whitespace; strip and require non-empty**.
- `app.density.hotspots` returns `[{"x","y","weight"}]`; `_annotate` (farm `:205`) currently overwrites `s["label"]` unconditionally — Task 7 makes it conditional.
- `Track` is `app.ingest.Track(track_id=str, coords=ndarray, day="YYYY-MM-DD")`.
- `cache/` is already in `.gitignore` (line 19) — nothing to add there.

---

## File structure

| File | Responsibility |
|---|---|
| `scripts/track_network.py` (create) | Load cache → graph → Dijkstra → `network_tracks(region, net, seed)` returning `(tracks, spots)`. Pure functions, module constants for all tuning. |
| `scripts/fetch_track_network.py` (create) | One plate per run: Overpass query → classify → reproject → write cache JSON. Network-touching, hand-verified (same policy as `region_prep.py`). |
| `scripts/render_asset_farm.py` (modify) | Dispatch cache-vs-synthetic; `_annotate` labels only unnamed spots; `--synthetic-tracks` flag. |
| `marketing/landing.html` (modify) | One footer attribution line. |
| `tests/test_track_network.py` (create) | Spec tests 1–6, fixture-driven, no network. |
| `tests/test_marketing_page.py` (modify) | Attribution line is a tested claim. |

---

### Task 1: Cache loading and graph build

**Files:**
- Create: `scripts/track_network.py`
- Test: `tests/test_track_network.py`

- [ ] **Step 1: Write the failing tests (fixture + graph)**

```python
# tests/test_track_network.py
"""Spec: docs/superpowers/specs/2026-08-15-real-network-demo-tracks-design.md.
Fixture network, no Overpass: a T of roads spanning the plate, a trail spur to a
summit, a 4wd loop pair, and a lake by the road. Distances in region-CRS metres."""
import numpy as np
import pytest

from scripts.track_network import build_graph, dijkstra, WEIGHTS

BOUNDS = (500_000.0, 4_400_000.0, 530_000.0, 4_420_000.0)   # 30 x 20 km


def _ways():
    """Hand-built network. Shared coordinates are shared vertices."""
    return [
        # east-west road across the whole plate
        {"class": "road",  "coords": [[500_000, 4_410_000], [510_000, 4_410_000],
                                      [515_000, 4_410_000], [530_000, 4_410_000]]},
        # north-south road crossing it at (515000, 4410000)
        {"class": "road",  "coords": [[515_000, 4_400_000], [515_000, 4_410_000],
                                      [515_000, 4_420_000]]},
        # trail spur from the crossing to a summit NE (short)
        {"class": "trail", "coords": [[515_000, 4_410_000], [517_000, 4_412_000],
                                      [519_000, 4_414_000]]},
        # long road detour to the same summit endpoint (for weight testing)
        {"class": "road",  "coords": [[515_000, 4_410_000], [524_000, 4_410_000],
                                      [524_000, 4_414_000], [519_000, 4_414_000]]},
        # 4wd pair forming a loop west of the crossing
        {"class": "4wd",   "coords": [[510_000, 4_410_000], [510_000, 4_415_000],
                                      [505_000, 4_415_000]]},
        {"class": "4wd",   "coords": [[505_000, 4_415_000], [505_000, 4_410_000],
                                      [510_000, 4_410_000]]},
    ]


def test_graph_shares_vertices_between_ways():
    g = build_graph(_ways())
    crossing = g.key((515_000.0, 4_410_000.0))
    # the crossing joins the EW road, NS road, trail spur, and road detour
    assert len(g.adj[crossing]) >= 4


def test_graph_keeps_edge_geometry_and_class():
    g = build_graph(_ways())
    classes = {e["class"] for e in g.edges}
    assert classes == {"road", "trail", "4wd"}
    assert all(len(e["coords"]) == 2 for e in g.edges)   # vertex-per-point edges
```

- [ ] **Step 2: Run to verify failure**

Run: `./.venv/bin/python -m pytest tests/test_track_network.py -q`
Expected: FAIL — `ModuleNotFoundError` / `ImportError` on `scripts.track_network`.

- [ ] **Step 3: Implement the module skeleton + graph**

```python
# scripts/track_network.py
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
```

- [ ] **Step 4: Run to verify pass**

Run: `./.venv/bin/python -m pytest tests/test_track_network.py -q`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/track_network.py tests/test_track_network.py
git commit -m "tracks: vertex-per-point graph over the cached network

Every way point is a vertex keyed by rounded coords, so ways that share
OSM nodes connect automatically and no way-splitting logic exists to
get wrong."
```

---

### Task 2: Dijkstra with class-weighted costs

**Files:**
- Modify: `scripts/track_network.py`
- Test: `tests/test_track_network.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_dijkstra_outing_prefers_the_trail():
    g = build_graph(_ways())
    src = g.key((515_000.0, 4_410_000.0))
    dst = g.key((519_000.0, 4_414_000.0))
    path = dijkstra(g, src, dst, WEIGHTS["outing"])
    # the trail spur, not the long road detour
    assert g.key(path[1]) == g.key((517_000.0, 4_412_000.0))


def test_dijkstra_approach_prefers_the_road():
    g = build_graph(_ways())
    src = g.key((515_000.0, 4_410_000.0))
    dst = g.key((519_000.0, 4_414_000.0))
    path = dijkstra(g, src, dst, WEIGHTS["approach"])
    # trail costs 1.3x its ~5.7 km; road detour 0.7x its ~18 km -- trail still wins?
    # No: 5657*1.3=7354 < 18000*0.7=12600, trail still cheaper. Force the contrast:
    hostile = {"trail": 10.0, "4wd": 10.0, "road": 1.0}
    path = dijkstra(g, src, dst, hostile)
    assert g.key(path[1]) == g.key((524_000.0, 4_410_000.0))


def test_dijkstra_unreachable_returns_none():
    g = build_graph(_ways())
    island = g.key((515_000.0, 4_410_000.0))
    assert dijkstra(g, island, ("nope", "nope"), WEIGHTS["outing"]) is None
```

- [ ] **Step 2: Run to verify failure**

Run: `./.venv/bin/python -m pytest tests/test_track_network.py -q`
Expected: FAIL — `dijkstra` raises / not found on the new tests.

- [ ] **Step 3: Implement**

```python
def dijkstra(g: Graph, src: tuple, dst: tuple, weights: dict,
             edge_penalty: dict | None = None):
    """Cheapest path src->dst as a coord list, or None. `edge_penalty` maps
    edge_idx -> multiplier (loop-finding). heapq only; county-scale graphs."""
    if src not in g.adj or dst not in g.adj:
        return None
    dist = {src: 0.0}
    prev: dict[tuple, tuple] = {}
    pq = [(0.0, src)]
    while pq:
        d, u = heapq.heappop(pq)
        if u == dst:
            break
        if d > dist.get(u, float("inf")):
            continue
        for v, ei in g.adj[u]:
            e = g.edges[ei]
            c = e["len_m"] * weights[e["class"]]
            if edge_penalty:
                c *= edge_penalty.get(ei, 1.0)
            nd = d + c
            if nd < dist.get(v, float("inf")):
                dist[v], prev[v] = nd, (u, ei)
                heapq.heappush(pq, (nd, v))
    if dst not in prev and src != dst:
        return None
    path, edge_ids, u = [dst], [], dst
    while u != src:
        u, ei = prev[u]
        path.append(u)
        edge_ids.append(ei)
    path.reverse(); edge_ids.reverse()
    return [list(p) for p in path]


def path_edge_ids(g: Graph, path: list) -> list[int]:
    """Edge indices along a dijkstra path (for loop-share accounting)."""
    ids = []
    for a, b in zip(path, path[1:]):
        ka, kb = g.key(a), g.key(b)
        ids.append(next(ei for v, ei in g.adj[ka] if v == kb))
    return ids
```

- [ ] **Step 4: Run to verify pass**

Run: `./.venv/bin/python -m pytest tests/test_track_network.py -q`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/track_network.py tests/test_track_network.py
git commit -m "tracks: heapq Dijkstra with class-weighted, penalizable edges"
```

---

### Task 3: Destination pool — labels + hydro lakes, snapped

**Files:**
- Modify: `scripts/track_network.py`
- Test: `tests/test_track_network.py`

- [ ] **Step 1: Write the failing tests**

```python
from scripts.track_network import destination_pool

LABELS = {"crs": "EPSG:32611", "features": [
    {"name": "Near Summit", "kind": "summit", "rank": 70, "coords": [[519_000, 4_414_000]]},
    {"name": "Far Summit",  "kind": "summit", "rank": 70, "coords": [[500_000, 4_419_900]]},
    {"name": "Some Range",  "kind": "range",  "rank": 100, "coords": [[510_000, 4_412_000]]},
]}
HYDRO = {"crs": "EPSG:32611", "lakes": [
    # centroid (515000, 4408500) -> 1500 m from the road crossing vertex: safely
    # inside SNAP_MAX_M, not sitting on the threshold boundary it tests
    {"name": "Road Lake", "coords": [[514_000, 4_409_500], [516_000, 4_409_500],
                                     [516_000, 4_407_500], [514_000, 4_407_500]]},
    {"name": "   ",       "coords": [[501_000, 4_401_000], [502_000, 4_401_000]]},
], "rivers": []}


def test_destination_pool_snaps_and_drops(tmp_path):
    import json
    (tmp_path / "labels.json").write_text(json.dumps(LABELS))
    (tmp_path / "hydro.json").write_text(json.dumps(HYDRO))
    g = build_graph(_ways())
    pool = destination_pool(str(tmp_path), g)
    names = {d["name"] for d in pool}
    assert "Near Summit" in names          # 0 m from a trail vertex
    assert "Road Lake" in names            # centroid 1.5 km from the crossing vertex
    assert "Far Summit" not in names       # ~10 km from anything: dropped
    assert "Some Range" not in names       # kind not summit/gap
    assert "   " not in names and "" not in names   # whitespace lake name dropped
    lake = next(d for d in pool if d["name"] == "Road Lake")
    assert lake["kind"] == "lake"
    assert lake["node"] in g.adj           # snapped onto the graph
```

- [ ] **Step 2: Run to verify failure**

Run: `./.venv/bin/python -m pytest tests/test_track_network.py -q`
Expected: FAIL — `destination_pool` not defined.

- [ ] **Step 3: Implement**

```python
def destination_pool(region_dir: str, g: Graph) -> list[dict]:
    """Real named destinations: labels.json summits/gaps (point coords) plus
    hydro.json named lakes (polygon centroid; labels.json has NO lake kind).
    Snapped to the nearest graph vertex within SNAP_MAX_M or dropped."""
    keys, verts = g.vertex_array()
    out = []

    def _snap(name, kind, x, y):
        if not len(verts):
            return
        d2 = (verts[:, 0] - x) ** 2 + (verts[:, 1] - y) ** 2
        i = int(np.argmin(d2))
        if float(np.sqrt(d2[i])) <= SNAP_MAX_M:
            out.append({"name": name, "kind": kind, "x": float(x), "y": float(y),
                        "node": keys[i]})

    with open(os.path.join(region_dir, "labels.json")) as f:
        for ft in json.load(f)["features"]:
            if ft["kind"] in ("summit", "gap") and str(ft.get("name") or "").strip():
                (x, y), = ft["coords"][:1]
                _snap(ft["name"].strip(), ft["kind"], x, y)
    with open(os.path.join(region_dir, "hydro.json")) as f:
        for lk in json.load(f)["lakes"]:
            name = str(lk.get("name") or "").strip()
            if name and lk.get("coords"):
                c = np.asarray(lk["coords"], dtype=float)
                _snap(name, "lake", float(c[:, 0].mean()), float(c[:, 1].mean()))
    return out
```

- [ ] **Step 4: Run to verify pass**

Run: `./.venv/bin/python -m pytest tests/test_track_network.py -q`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/track_network.py tests/test_track_network.py
git commit -m "tracks: destination pool from labels summits/gaps + hydro named lakes

labels.json carries no lake kind on any plate; named lakes live in
hydro.json and enter as polygon centroids. Whitespace names drop."
```

---

### Task 4: Farthest-point selection over the 3×3 grid

**Files:**
- Modify: `scripts/track_network.py`
- Test: `tests/test_track_network.py`

- [ ] **Step 1: Write the failing tests**

```python
from scripts.track_network import select_destinations


def _cands(n=40, seed=0):
    rng = np.random.default_rng(seed)
    w, s, e, nb = BOUNDS
    return [{"name": f"d{i}", "kind": "summit",
             "x": float(rng.uniform(w, e)), "y": float(rng.uniform(s, nb)),
             "node": ("k", i)} for i in range(n)]


def test_selection_spreads_over_the_grid():
    rng = np.random.default_rng(7)
    picks = select_destinations(_cands(), BOUNDS, 8, rng)
    assert len(picks) == 8
    w, s, e, n = BOUNDS
    cells = {(min(2, int(3 * (d["x"] - w) / (e - w))),
              min(2, int(3 * (d["y"] - s) / (n - s)))) for d in picks}
    assert len(cells) >= 5                 # spec test 3's cell floor


def test_selection_is_deterministic():
    a = select_destinations(_cands(), BOUNDS, 6, np.random.default_rng(7))
    b = select_destinations(_cands(), BOUNDS, 6, np.random.default_rng(7))
    assert [d["name"] for d in a] == [d["name"] for d in b]
```

- [ ] **Step 2: Run to verify failure**

Run: `./.venv/bin/python -m pytest tests/test_track_network.py -q`
Expected: FAIL — `select_destinations` not defined.

- [ ] **Step 3: Implement**

```python
def select_destinations(pool: list[dict], bounds: tuple, n: int, rng) -> list[dict]:
    """Greedy farthest-point pick of n destinations, refusing to reuse a 3x3
    grid cell until every occupied cell has been used once (spec §3): the
    mechanical guarantee that ink reaches the corners."""
    if not pool:
        return []
    w, s, e, nb = bounds

    def cell(d):
        return (min(2, int(3 * (d["x"] - w) / (e - w))),
                min(2, int(3 * (d["y"] - s) / (nb - s))))

    remaining = list(pool)
    picks = [remaining.pop(int(rng.integers(len(remaining))))]
    used_cells = {cell(picks[0])}
    occupied = {cell(d) for d in pool}
    while remaining and len(picks) < n:
        fresh = [d for d in remaining if cell(d) not in used_cells]
        cands = fresh if fresh or used_cells >= occupied else remaining
        if not cands:
            cands = remaining
        dmin = [min((c["x"] - p["x"]) ** 2 + (c["y"] - p["y"]) ** 2
                    for p in picks) for c in cands]
        best = cands[int(np.argmax(dmin))]
        remaining.remove(best)
        picks.append(best)
        used_cells.add(cell(best))
    return picks
```

- [ ] **Step 4: Run to verify pass**

Run: `./.venv/bin/python -m pytest tests/test_track_network.py -q`
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/track_network.py tests/test_track_network.py
git commit -m "tracks: farthest-point destination spread over a 3x3 plate grid"
```

---

### Task 5: Journey composer — trips, dates, densify, jitter

**Files:**
- Modify: `scripts/track_network.py`
- Test: `tests/test_track_network.py`

- [ ] **Step 1: Write the failing tests**

```python
from scripts.track_network import network_tracks


class _StubRegion:
    def __init__(self, tmpdir):
        self.id = "stub"
        self.dir = str(tmpdir)
        self.cfg = {"bounds": list(BOUNDS)}


def _region(tmp_path):
    import json
    (tmp_path / "labels.json").write_text(json.dumps(LABELS))
    (tmp_path / "hydro.json").write_text(json.dumps(HYDRO))
    return _StubRegion(tmp_path)


def test_network_tracks_shape_and_determinism(tmp_path):
    r = _region(tmp_path)
    t1, s1 = network_tracks(r, _ways(), seed=7)
    t2, s2 = network_tracks(r, _ways(), seed=7)
    assert len(t1) >= 2 and len(s1) >= 2       # tiny fixture: both snapped dests
    for a, b in zip(t1, t2):
        assert a.day == b.day
        assert np.array_equal(a.coords, b.coords)
    assert [x["label"] for x in s1] == [x["label"] for x in s2]


def test_tracks_are_dated_by_season_bucket_and_sorted(tmp_path):
    from scripts.track_network import SEASONS
    from datetime import date
    r = _region(tmp_path)
    tracks, spots = network_tracks(r, _ways(), seed=7)
    days = [date.fromisoformat(t.day) for t in tracks]
    assert days == sorted(days)
    by_label = {s["label"]: s for s in spots}
    for t, d in zip(tracks, days):
        kind = t.track_id.split(":")[0]        # track_id = "<kind>:<name>"
        lo, hi = SEASONS[kind]
        assert lo <= d.timetuple().tm_yday <= hi


def test_tracks_are_densified_and_jittered(tmp_path):
    r = _region(tmp_path)
    tracks, _ = network_tracks(r, _ways(), seed=7)
    seg = np.hypot(*np.diff(tracks[0].coords, axis=0).T)
    assert np.median(seg) < 40.0               # ~15 m spacing, jitter-widened
    assert len(tracks[0].coords) > 100


def test_spots_carry_real_names_and_positions(tmp_path):
    r = _region(tmp_path)
    _, spots = network_tracks(r, _ways(), seed=7)
    names = {s["label"] for s in spots}
    assert names <= {"Near Summit", "Road Lake"} and names
    for s in spots:
        assert set(s) >= {"x", "y", "weight", "label"}
```

- [ ] **Step 2: Run to verify failure**

Run: `./.venv/bin/python -m pytest tests/test_track_network.py -q`
Expected: FAIL — `network_tracks` not defined.

- [ ] **Step 3: Implement**

```python
def _densify(path: np.ndarray, rng) -> np.ndarray:
    """~POINT_SPACING_M sampling along the polyline + seeded GPS jitter, so ink
    reads recorded rather than vector-perfect (spec §3)."""
    p = np.asarray(path, dtype=float)
    seg = np.hypot(*np.diff(p, axis=0).T)
    keep = seg > 1e-9
    if not keep.all():
        p = np.vstack([p[:1], p[1:][keep]])
        seg = seg[keep]
    s = np.concatenate([[0.0], np.cumsum(seg)])
    n = max(2, int(s[-1] / POINT_SPACING_M))
    t = np.linspace(0.0, s[-1], n)
    out = np.column_stack([np.interp(t, s, p[:, 0]), np.interp(t, s, p[:, 1])])
    return out + rng.normal(0.0, JITTER_M, out.shape)


def _trailhead_for(g: Graph, dest_node: tuple, worn: list, rng) -> tuple:
    """A road-touching vertex to start from. Reuse a worn trailhead when one
    lies within 12 km but NOT closer than 1 km (a trailhead that IS the
    destination -- a lake beside the road -- degenerates the trip to two
    points); else the nearest road vertex outside 1 km."""
    for th in worn:
        d = np.hypot(th[0] - dest_node[0], th[1] - dest_node[1])
        if 1_000 < d < 12_000:
            return th
    road_keys = sorted({k for k, nbrs in g.adj.items()
                        if any(g.edges[ei]["class"] == "road" for _, ei in nbrs)})
    arr = np.array(road_keys, dtype=float)
    d = np.hypot(arr[:, 0] - dest_node[0], arr[:, 1] - dest_node[1])
    ok = np.where(d > 1_000)[0]
    cand = ok[np.argsort(d[ok])[:5]] if len(ok) else np.argsort(d)[:1]
    return road_keys[int(rng.choice(cand))]


def network_tracks(region, ways: list[dict], seed: int = 7, n_trips: int = 8):
    """The year of trips (spec §3): seeded, deterministic from (ways, plate
    files, seed) alone. Returns (tracks, spots) ready for the farm."""
    rng = np.random.default_rng(seed)
    g = build_graph(ways)
    pool = destination_pool(region.dir, g)
    dests = select_destinations(pool, tuple(region.cfg["bounds"]), n_trips, rng)

    worn: list[tuple] = []
    year = 2024
    trips = []
    # NOTE: a destination in a different connected component than its trailhead
    # routes to None and is skipped below. That is correct but silent, and on a
    # clipped OSM extract it can quietly thin the trip list -- so count the
    # skips and print one line if any occurred, rather than shipping a poster
    # with three journeys where eight were intended.
    skipped = 0
    for d in dests:
        th = _trailhead_for(g, d["node"], worn, rng)
        if len(worn) < 2:
            worn.append(th)
        # dijkstra_edges, not dijkstra + path_edge_ids: the loop penalty and the
        # 4wd-share test must act on the edges actually traversed. Real OSM data
        # carries parallel edges (a path mapped over a track), and resolving them
        # by first-match would mis-apply the penalty silently -- a worse route,
        # never an error.
        got = dijkstra_edges(g, th, d["node"], WEIGHTS["outing"])
        if got is None:
            skipped += 1
            continue
        out_path, out_ids = got
        shape = rng.choice(["out_and_back", "loop", "4wd"])
        path = None
        if shape == "loop":
            pen = {ei: LOOP_PENALTY for ei in out_ids}
            back = dijkstra_edges(g, d["node"], th, WEIGHTS["outing"], edge_penalty=pen)
            if back is not None:
                back_path, back_ids = back
                shared = set(back_ids) & set(out_ids)
                if len(shared) <= LOOP_SHARE_MAX * len(out_ids):
                    path = out_path + back_path[1:]
        elif shape == "4wd":
            p4 = dijkstra_edges(g, th, d["node"], WEIGHTS["4wd_day"])
            if p4 is not None:
                p, ids = p4
                l4 = sum(g.edges[i]["len_m"] for i in ids if g.edges[i]["class"] == "4wd")
                lt = sum(g.edges[i]["len_m"] for i in ids) or 1.0
                if l4 / lt >= 0.4:
                    path = p + p[-2::-1]                   # 4wd out-and-back
        if path is None:                                    # default / fallbacks
            path = out_path + out_path[-2::-1]
        lo, hi = SEASONS[d["kind"]]
        day = date(year, 1, 1) + timedelta(days=int(rng.integers(lo, hi + 1)) - 1)
        trips.append((day, d, _densify(np.asarray(path, dtype=float), rng)))

    if skipped:
        print(f"  tracks: {skipped} of {len(dests)} destinations unreachable "
              f"from their trailhead (disconnected network) -- skipped")
    trips.sort(key=lambda t: t[0])
    from app.ingest import Track
    tracks = [Track(track_id=f"{d['kind']}:{d['name']}", coords=coords,
                    day=day.isoformat()) for day, d, coords in trips]
    seen: dict[str, dict] = {}
    for day, d, _ in trips:
        s = seen.setdefault(d["name"], {"x": d["x"], "y": d["y"], "weight": 0,
                                        "label": d["name"]})
        s["weight"] += 1
    return tracks, list(seen.values())
```

- [ ] **Step 4: Run to verify pass**

Run: `./.venv/bin/python -m pytest tests/test_track_network.py -q`
Expected: 12 passed. (If the loop/4wd draws make the tiny fixture flaky, the fixture is too small for that shape — the composer must fall back to out-and-back, not fail; fix the composer, not the test.)

- [ ] **Step 5: Commit**

```bash
git add scripts/track_network.py tests/test_track_network.py
git commit -m "tracks: the year of trips -- seeded journeys routed to real places

Out-and-backs, loops when the network offers a mostly-disjoint return,
4wd days when 4wd ways dominate; kind-bucketed seasonal dates; densified
and jittered so ink reads recorded. Deterministic from cache+plate+seed."
```

---

### Task 6: Coverage guarantee on a plate-spanning fixture

**Files:**
- Test: `tests/test_track_network.py`

- [ ] **Step 1: Write the test (may already pass — it is the spec's acceptance test 3)**

```python
def _big_network():
    """A road ring near the plate edge + spokes + trail spurs to 9 summits,
    one per 3x3 cell -- coverage is achievable, the composer must achieve it."""
    w, s, e, n = BOUNDS
    xs = [w + (e - w) * f for f in (0.1, 0.5, 0.9)]
    ys = [s + (n - s) * f for f in (0.1, 0.5, 0.9)]
    ways = [{"class": "road", "coords": [[x, ys[0]] for x in xs]},
            {"class": "road", "coords": [[x, ys[2]] for x in xs]},
            {"class": "road", "coords": [[xs[0], y] for y in ys]},
            {"class": "road", "coords": [[xs[2], y] for y in ys]},
            {"class": "road", "coords": [[xs[1], y] for y in ys]}]
    feats, k = [], 0
    for x in xs:
        for y in ys:
            k += 1
            ways.append({"class": "trail",
                         "coords": [[x, y], [x + 900, y + 900], [x + 1800, y + 1500]]})
            feats.append({"name": f"Summit {k}", "kind": "summit", "rank": 70,
                          "coords": [[x + 1800, y + 1500]]})
    return ways, feats


def test_coverage_spans_the_plate(tmp_path):
    import json
    ways, feats = _big_network()
    (tmp_path / "labels.json").write_text(json.dumps({"crs": "x", "features": feats}))
    (tmp_path / "hydro.json").write_text(json.dumps({"crs": "x", "lakes": [],
                                                     "rivers": []}))
    tracks, _ = network_tracks(_StubRegion(tmp_path), ways, seed=7)
    allpts = np.vstack([t.coords for t in tracks])
    w, s, e, n = BOUNDS
    assert (allpts[:, 0].max() - allpts[:, 0].min()) >= 0.6 * (e - w)
    assert (allpts[:, 1].max() - allpts[:, 1].min()) >= 0.6 * (n - s)
    cells = {(min(2, int(3 * (x - w) / (e - w))), min(2, int(3 * (y - s) / (n - s))))
             for x, y in allpts[::25]}
    assert len(cells) >= 5
```

- [ ] **Step 2: Run — expected PASS (composer built for this); if FAIL, fix the composer**

Run: `./.venv/bin/python -m pytest tests/test_track_network.py -q`
Expected: 13 passed.

- [ ] **Step 3: Commit**

```bash
git add tests/test_track_network.py
git commit -m "tracks: pin the coverage guarantee -- 60% span, 5+ of 9 cells inked"
```

---

### Task 7: Farm seam — dispatch, fallback, `_annotate`, flag

**Files:**
- Modify: `scripts/render_asset_farm.py` (imports `:54-75`, `_annotate` `:205`, `_editions` `:305`, argparse `:447-463`, main loop `:493-495`)
- Test: `tests/test_track_network.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_farm_falls_back_without_cache(tmp_path, monkeypatch):
    """Spec test 5: no cache file -> _synth_tracks, byte-identical to today."""
    import scripts.render_asset_farm as farm
    monkeypatch.chdir(tmp_path)            # no cache/networks/ here
    r = _StubRegion(tmp_path)
    r.cfg["bounds"] = list(BOUNDS)
    old = farm._synth_tracks(r)
    got_tracks, got_spots = farm._demo_journeys(r, str(tmp_path / "out"),
                                               force_synthetic=False)
    for a, b in zip(old, got_tracks):
        assert np.array_equal(a.coords, b.coords) and a.day == b.day


def test_annotate_keeps_existing_labels(tmp_path):
    import scripts.render_asset_farm as farm
    spots = [{"x": 1.0, "y": 2.0, "weight": 3, "label": "Antelope Mountain"},
             {"x": 4.0, "y": 5.0, "weight": 1}]
    out = farm._annotate(spots, str(tmp_path))
    assert out[0]["label"] == "Antelope Mountain"      # real name survives
    assert out[1]["label"] in farm.HOTSPOT_LABELS      # unnamed spot gets one
    assert all("icon" in s for s in out)
    assert "photo" in out[0]


def test_edition_spots_keep_real_names_for_network_tracks(tmp_path):
    """_editions regenerates spots per subset; for network journeys it must keep
    the real destination names, not re-mint 'Base Camp' from density.hotspots."""
    import scripts.render_asset_farm as farm
    from app.ingest import Track
    tracks = [Track(track_id="summit:Near Summit", coords=np.zeros((4, 2)), day="2024-07-01"),
              Track(track_id="lake:Road Lake",     coords=np.ones((4, 2)),  day="2024-04-01"),
              Track(track_id="summit:Near Summit", coords=np.zeros((4, 2)), day="2024-09-01")]
    spots = [{"x": 1.0, "y": 2.0, "weight": 2, "label": "Near Summit"},
             {"x": 3.0, "y": 4.0, "weight": 1, "label": "Road Lake"}]
    r = _StubRegion(tmp_path)
    sub = tracks[:2]                                   # edition 1: one visit each
    eds = farm._edition_spots(sub, spots, r, str(tmp_path))
    assert {s["label"] for s in eds} == {"Near Summit", "Road Lake"}
    assert next(s for s in eds if s["label"] == "Near Summit")["weight"] == 1
    # synthetic ids (no colon) keep the density path -- track INSIDE bounds so
    # hotspots() actually yields a spot and the assertion has teeth
    synth = [Track(track_id="day-1",
                   coords=np.array([[505_000, 4_405_000], [512_000, 4_412_000]]),
                   day="2024-06-01")]
    eds = farm._edition_spots(synth, [], r, str(tmp_path))
    assert eds and all(s["label"] in farm.HOTSPOT_LABELS for s in eds)
```

- [ ] **Step 2: Run to verify failure**

Run: `./.venv/bin/python -m pytest tests/test_track_network.py -q`
Expected: FAIL — `_demo_journeys` missing; `_annotate` overwrites the real name.

- [ ] **Step 3: Implement the seam**

In `scripts/render_asset_farm.py`:

```python
# with the other imports (:66)
from scripts.track_network import load_network, network_tracks

NETWORK_CACHE = os.path.join("cache", "networks")   # near HOTSPOT_LABELS


def _demo_journeys(region, out_dir: str, force_synthetic: bool = False):
    """Tracks + spots for a region: journeys routed over the cached OSM network
    when cache/networks/<id>.json exists, else the synthetic generator. The
    fallback keeps the farm runnable on a fresh clone and in CI (spec §4)."""
    cache = os.path.join(NETWORK_CACHE, f"{region.id}.json")
    if not force_synthetic and os.path.exists(cache):
        tracks, spots = network_tracks(region, load_network(cache))
        print(f"  tracks: routed over {cache} (OSM, ODbL)")
        return tracks, _annotate(spots, out_dir)
    tracks = _synth_tracks(region)
    return tracks, _annotate(hotspots(tracks, tuple(region.cfg["bounds"])), out_dir)
```

`_annotate` — label only unnamed spots (`:209`):

```python
    for k, s in enumerate(spots):
        if "label" not in s:
            s["label"] = HOTSPOT_LABELS[k % len(HOTSPOT_LABELS)]
        s["icon"] = HOTSPOT_ICONS[k % len(HOTSPOT_ICONS)]
```

`_editions` (`:305`) regenerates spots per edition subset via `density.hotspots`,
which would re-mint fake names next to a poster carrying real ones. Extract the
choice into a helper and use it inside `_editions`:

```python
def _edition_spots(sub: list, spots: list, region, out_dir: str) -> list:
    """Spots for an edition's track subset. Network journeys carry their
    destination in track_id ("<kind>:<name>"): the edition shows the real
    destinations its ink has reached, weights recounted for the subset.
    Synthetic tracks (ids like "day-1") keep the density-hotspot path."""
    names = [t.track_id.split(":", 1)[1] for t in sub if ":" in t.track_id]
    if names:
        # drop any inherited "photo" pin -- _annotate re-pins on eds[0], and an
        # edition must carry ONE pinned photo like the poster, not two
        eds = [{k: v for k, v in dict(s, weight=names.count(s["label"])).items()
                if k != "photo"}
               for s in spots if s.get("label") in names]
        return _annotate(eds, out_dir)
    return _annotate(hotspots(sub, tuple(region.cfg["bounds"])), out_dir)
```

and in `_editions`, replace

```python
        subspots = _annotate(hotspots(sub, tuple(region.cfg["bounds"])), out_dir)
```

with

```python
        subspots = _edition_spots(sub, spots, region, out_dir)
```

(the `spots` parameter `_editions` already receives finally gets used).

Main loop (`:493-495`) becomes:

```python
        tracks, spots = _demo_journeys(region, out_dir, args.synthetic_tracks) \
            if needs_render else ([], [])
```

Argparse (next to `--synthetic-dem`):

```python
    ap.add_argument("--synthetic-tracks", action="store_true",
                    help="force the synthetic track generator even when a "
                         "network cache exists (parity with --synthetic-dem)")
```

- [ ] **Step 4: Run the new tests AND the frame tests (same file was touched)**

Run: `./.venv/bin/python -m pytest tests/test_track_network.py tests/test_asset_farm_frame.py -q`
Expected: all pass (16 in test_track_network.py + 3 frame tests).

- [ ] **Step 5: Commit**

```bash
git add scripts/render_asset_farm.py tests/test_track_network.py
git commit -m "farm: route demo journeys over the network cache when present

No cache -> the synthetic generator, unchanged, so a fresh clone and CI
render exactly what they rendered yesterday. _annotate labels only spots
that arrive unnamed, and editions reuse the caller's real destination
spots instead of re-minting fake names from density hotspots."
```

---

### Task 8: Landing-page attribution (tested claim)

**Files:**
- Modify: `marketing/landing.html` (footer)
- Test: `tests/test_marketing_page.py`

- [ ] **Step 1: Write the failing test**

```python
def test_osm_attribution_is_present():
    # demo route geometry is ODbL: the produced-work attribution must ship
    assert "OpenStreetMap contributors" in PAGE
```

- [ ] **Step 2: Run to verify failure**

Run: `./.venv/bin/python -m pytest tests/test_marketing_page.py -q`
Expected: FAIL.

- [ ] **Step 3: Add the footer line**

In `marketing/landing.html`, inside the existing footer block (find `<footer`), add alongside the existing fine print:

```html
<p class="fine">Demo route geometry © OpenStreetMap contributors (ODbL).</p>
```

- [ ] **Step 4: Run to verify pass**

Run: `./.venv/bin/python -m pytest tests/test_marketing_page.py -q`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add marketing/landing.html tests/test_marketing_page.py
git commit -m "marketing: OSM attribution for demo route geometry, as a tested claim"
```

---

### Task 9: The fetch script (hand-verified, no unit tests)

**Files:**
- Create: `scripts/fetch_track_network.py`

- [ ] **Step 1: Write the script**

```python
#!/usr/bin/env python3
"""Fetch one plate's road/trail network from Overpass into the gitignored cache.

    ./.venv/bin/python scripts/fetch_track_network.py --region lassen_ca

ODbL data stays in cache/networks/ (gitignored -- .gitignore:19); it must never
be committed and never enter a plate (plates are CC0). The cache is the snapshot
of record: renders read it, never live Overpass, so same cache + seed -> same
image. Network-touching and hand-verified, same policy as region_prep.py."""
from __future__ import annotations
import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.regions import Region                                    # noqa: E402

ENDPOINTS = ["https://overpass-api.de/api/interpreter",
             "https://overpass.kumi.systems/api/interpreter"]
HIGHWAYS = ("motorway|trunk|primary|secondary|tertiary|unclassified|residential|"
            "service|track|path|footway|bridleway|cycleway")
CLASSES = {"track": "4wd", "path": "trail", "footway": "trail",
           "bridleway": "trail", "cycleway": "trail"}             # else: road


def fetch(region: Region) -> dict:
    from pyproj import Transformer
    w, s, e, n = region.lonlat_bbox
    q = (f'[out:json][timeout:180];'
         f'way["highway"~"^({HIGHWAYS})$"]({s},{w},{n},{e});out geom;')
    body = urllib.parse.urlencode({"data": q}).encode()
    last = None
    for url in ENDPOINTS:
        for attempt in range(3):
            try:
                with urllib.request.urlopen(
                        urllib.request.Request(url, data=body), timeout=300) as r:
                    payload = json.load(r)
                break
            except Exception as ex:                               # noqa: BLE001
                last = ex
                time.sleep(15 * (attempt + 1))
        else:
            continue
        break
    else:
        raise SystemExit(f"every Overpass endpoint failed; last error: {last}\n"
                         f"mirror list: https://wiki.openstreetmap.org/wiki/Overpass_API")

    fwd = Transformer.from_crs("EPSG:4326", region.cfg["crs"], always_xy=True)
    ways = []
    for el in payload.get("elements", []):
        geom = el.get("geometry") or []
        if el.get("type") != "way" or len(geom) < 2:
            continue
        cls = CLASSES.get(el.get("tags", {}).get("highway", ""), "road")
        xs, ys = fwd.transform([p["lon"] for p in geom], [p["lat"] for p in geom])
        ways.append({"class": cls,
                     "coords": [[round(x, 1), round(y, 1)] for x, y in zip(xs, ys)]})
    return {"region_id": region.id, "crs": region.cfg["crs"],
            "fetched": date.today().isoformat(),
            "source": "OpenStreetMap via Overpass, ODbL 1.0", "ways": ways}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--region", required=True)
    args = ap.parse_args()
    region = Region(args.region)
    net = fetch(region)
    os.makedirs(os.path.join("cache", "networks"), exist_ok=True)
    out = os.path.join("cache", "networks", f"{region.id}.json")
    with open(out, "w") as f:
        json.dump(net, f)
    from collections import Counter
    c = Counter(w["class"] for w in net["ways"])
    print(f"{out}: {len(net['ways'])} ways "
          f"({c.get('road',0)} road / {c.get('4wd',0)} 4wd / {c.get('trail',0)} trail), "
          f"{os.path.getsize(out)/1048576:.1f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Hand-verify against one plate**

Run: `./.venv/bin/python scripts/fetch_track_network.py --region lassen_ca`
Expected: a line like `cache/networks/lassen_ca.json: N ways (r road / f 4wd / t trail), X MB` with N in the thousands and **all three classes non-zero**. If trail count is 0, the query regex is wrong — stop and fix before proceeding.

- [ ] **Step 3: Smoke the full path on the real plate**

Run: `./.venv/bin/python -c "
import time
from app.regions import Region
from scripts.track_network import load_network, network_tracks, build_graph
r = Region('lassen_ca')
ways = load_network('cache/networks/lassen_ca.json')
t0 = time.time(); g = build_graph(ways); t1 = time.time()
print(f'graph: {len(g.adj):,} vertices, {len(g.edges):,} edges in {t1-t0:.1f}s')
t0 = time.time(); tracks, spots = network_tracks(r, ways); t1 = time.time()
print(f'{len(tracks)} trips in {t1-t0:.1f}s;', [s['label'] for s in spots])"`
Expected: 6–8 trips; real place names (no 'Base Camp').

**This is also the vertex-per-point measurement gate** (spec §2 amendment).
Record graph size and wall-clock. If composing takes **over ~3 minutes**, stop
and add a `contract_chains()` pass to `track_network.py` — collapse degree-2
vertex runs into polyline edges, recovering the intersection-only graph behind
the same API — then re-measure. Do not proceed to the rollout on a routing
step that slow; it makes every future re-render painful.

- [ ] **Step 4: Commit**

```bash
git add scripts/fetch_track_network.py
git commit -m "tracks: Overpass fetch into the gitignored network cache

One plate per run, retry with backoff across two endpoints, reprojected
to the region CRS at fetch time. The cache is the snapshot of record."
```

---

### Task 10: Rollout — fetch, re-render, eyeball, deploy

**Files:** none new — operator steps.

- [ ] **Step 1: Fetch caches for all five plates** (sequential — Overpass etiquette)

```bash
for r in lassen_ca susanville_reno elko_bonneville rifle_aspen tushar_beaver_ut; do
  ./.venv/bin/python scripts/fetch_track_network.py --region $r
done
```

- [ ] **Step 2: Full suite green before any render**

Run: `./.venv/bin/python -m pytest -q`
Expected: no new failures beyond the 7 known font-metric failures (CLAUDE.md "Known local failures").

- [ ] **Step 3: Re-render — full farm for the hero plate, poster+model for the rest**

```bash
./.venv/bin/python scripts/render_asset_farm.py --regions lassen_ca
./.venv/bin/python scripts/render_asset_farm.py --regions susanville_reno rifle_aspen tushar_beaver_ut --only poster model
./.venv/bin/python scripts/render_asset_farm.py --regions elko_bonneville --only poster model --dpi 220
```

- [ ] **Step 4: EYEBALL GATE — human review before deploy.** Downscale each poster, look at all five: routes follow visible terrain lines (valley roads, ridge trails), ink reaches the plate corners, no empty-middle clustering, real names on hotspots. **Show Dom lassen + elko before deploying; do not deploy unseen.**

- [ ] **Step 5: Stage, deploy, verify**

```bash
python3 marketing/build_deploy.py
export NETLIFY_AUTH_TOKEN=$(cat ~/.config/netlify/token)
netlify deploy --prod --dir=dist/landing
```

Verify live: five model-viewers, all `/assets/...` 200, `OpenStreetMap contributors` present, no retired claims, form intact:

```bash
L=$(curl -s https://tecopa.plateworks.org); echo "$L" | grep -c "OpenStreetMap contributors"
```

- [ ] **Step 6: Log the session** (Notion per CLAUDE.md; close the loop on the tracks work).
