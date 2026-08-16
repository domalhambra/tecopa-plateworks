"""Route demo journeys over a real road/trail network (spec:
docs/superpowers/specs/2026-08-15-real-network-demo-tracks-design.md).

Pure module: reads the gitignored cache written by fetch_track_network.py,
never the network. Vertex-per-point graph -- every way point is a vertex keyed
by its rounded coords, so ways that share OSM nodes connect automatically and
no way-splitting logic exists to get wrong. County-scale plates stay small."""
from __future__ import annotations
import heapq
import json
import math
import os
from datetime import date, timedelta

import numpy as np

SNAP_MAX_M = 2_000.0          # destination -> network snap ceiling (spec §3)
LOOP_SHARE_MAX = 0.35         # loops: 2nd path may reuse <=35% of 1st path's edges
LOOP_PENALTY = 4.0            # cost multiplier on 1st-path edges when seeking the 2nd
POINT_SPACING_M = 15.0        # GPS densification (spec §3)
JITTER_M = 3.0                # seeded GPS jitter (spec §3)
TRAILHEAD_MIN_M = 1_000.0     # hard floor: a trailhead nearer than this to the
                              # destination renders as a dot, not a journey
TRAILHEAD_CANDIDATES = 5      # draw among the 5 best-matching, for variety
# Trip length is a TARGET, not a floor. Under the vertex-per-point graph, way
# points sit 20-300 m apart, so "the nearest road vertex beyond the floor" is
# always ON the floor -- measured on a 2 km road mesh at 50 m node spacing, the
# five nearest candidates spanned 1001-1005 m and every journey came out a
# ~1-2 km stub (0.07 of the plate) regardless of plate size. Scaling to the
# plate's SHORT side instead makes a day out read as a day out at any scale.
TRIP_SPAN_FRAC = (0.06, 0.18)  # trailhead->destination, as a fraction of that side
TRIP_SPAN_MIN_M = 2_000.0     # ...clamped: a small plate still needs a real walk
TRIP_SPAN_MAX_M = 45_000.0    # ...and elko_bonneville, whose SHORT side is
                              # 331 km, would otherwise ask for up to 60 km
                              # (0.18 x 331). Measured off min(), not the
                              # 483 km long axis -- that is what trip_target_m
                              # scales on.
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
# kind -> marker glyph (spec §3). Total over the kinds `destination_pool` can
# produce -- it emits exactly summit/gap from labels.json and lake from
# hydro.json -- and every value is a glyph `render._draw_glyph` already knows.
# The farm's positional icon cycle is fine for invented density hotspots but
# libellous next to a real name: it put a tent on "Road Lake" and a camera on a
# summit. KIND_ICONS is the fix; the `.get` fallback keeps a future kind from
# taking down a farm run over a marker glyph.
KIND_ICONS = {"summit": "peak", "gap": "flag", "lake": "water"}
KIND_ICON_DEFAULT = "dot"


class Graph:
    def __init__(self):
        self.adj: dict[tuple, list[tuple]] = {}   # key -> [(other_key, edge_idx)]
        self.edges: list[dict] = []               # {"class", "coords", "len_m"}

    @staticmethod
    def key(pt) -> tuple:
        return (round(float(pt[0]), 1), round(float(pt[1]), 1))

    def vertex_array(self):
        ks = list(self.adj.keys())
        if not ks:
            # np.array([], dtype=float) would be shape (0,), not (0, 2); Task 3's
            # argmin-over-coordinates indexing needs the 2-D shape even when empty.
            return ks, np.empty((0, 2))
        return ks, np.array(ks, dtype=float)


def build_graph(ways: list[dict]) -> Graph:
    g = Graph()
    for w in ways:
        pts = w["coords"]
        for a, b in zip(pts, pts[1:]):
            ka, kb = g.key(a), g.key(b)
            if ka == kb:
                continue
            length = math.hypot(b[0] - a[0], b[1] - a[1])
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


def dijkstra_edges(g: Graph, src: tuple, dst: tuple, weights: dict,
                    edge_penalty: dict | None = None):
    """Cheapest path src->dst as (coords, edge_ids), or None. `edge_ids` are
    the exact edges Dijkstra traversed, in path order -- reconstructed from
    the same `prev` chain the search builds, so they are unambiguous even
    when parallel edges join a vertex pair (two ways over the same two
    coords, common on real OSM data: a path mapped over a track, duplicated
    imports, dual-carriageway merges). `edge_penalty` maps edge_idx ->
    multiplier (loop-finding). heapq only; county-scale graphs."""
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
            # cost must stay >= 0: both the break-on-pop-dst early exit below
            # and Dijkstra's correctness assume non-negative edge costs, which
            # holds today only because WEIGHTS and LOOP_PENALTY are positive.
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
    path.reverse()
    edge_ids.reverse()
    return [list(p) for p in path], edge_ids


def dijkstra(g: Graph, src: tuple, dst: tuple, weights: dict,
             edge_penalty: dict | None = None):
    """Cheapest path src->dst as a coord list, or None. Thin wrapper over
    `dijkstra_edges` -- there is exactly one search implementation."""
    result = dijkstra_edges(g, src, dst, weights, edge_penalty=edge_penalty)
    return None if result is None else result[0]


def destination_pool(region_dir: str, g: Graph) -> list[dict]:
    """Real named destinations: labels.json summits/gaps (point coords) plus
    hydro.json named lakes (polygon centroid -- labels.json has NO lake
    kind). Each candidate is snapped to the nearest graph vertex and dropped
    if that vertex is farther than SNAP_MAX_M away.

    The lake centroid is the plain mean of the ring's vertices, not the true
    area centroid -- biased toward densely-sampled parts of the ring, and in
    a pathological concave ring (a horseshoe lake, say) it could in theory
    fall outside the polygon. For snapping to a road within a 2 km ceiling
    this is judged acceptable: it would have to land implausibly far from
    the lake's own shape to snap to the wrong network vertex, and no such
    case has shown up on the five built plates.

    Duplicate names are collapsed to one entry per name, because downstream
    consumers (T5's hotspot dict, T7's edition filter) key by name and would
    otherwise let a later duplicate silently clobber an earlier one.
    build_labels.py already dedupes labels.json on (name.lower(), kind), so
    the collision this actually guards against is lake vs. lake (real:
    "Bear Lake" appears twice on elko_bonneville, "Dry Lake" three times) and
    label vs. lake (a summit and a lake sharing a name). labels.json entries
    carry a `rank`; the higher-rank entry wins. hydro.json lakes carry no
    rank and are ranked below any labels.json entry, so a named lake never
    evicts a same-named summit/gap; among lake-vs-lake duplicates, the first
    one encountered (hydro.json order) wins.
    """
    keys, verts = g.vertex_array()
    best: dict[str, dict] = {}
    best_rank: dict[str, int] = {}

    def _snap(name: str, kind: str, x: float, y: float, rank: int) -> None:
        if not len(verts):
            return
        d2 = (verts[:, 0] - x) ** 2 + (verts[:, 1] - y) ** 2
        i = int(np.argmin(d2))
        if float(np.sqrt(d2[i])) > SNAP_MAX_M:
            return
        if name in best and rank <= best_rank[name]:
            return   # an equal-or-higher-rank entry already claimed this name
        best[name] = {"name": name, "kind": kind, "x": float(x), "y": float(y),
                      "node": keys[i]}
        best_rank[name] = rank

    with open(os.path.join(region_dir, "labels.json")) as f:
        for ft in json.load(f)["features"]:
            name = str(ft.get("name") or "").strip()
            if ft["kind"] in ("summit", "gap") and name and ft.get("coords"):
                (x, y), = ft["coords"][:1]
                _snap(name, ft["kind"], x, y, int(ft.get("rank", 0)))

    with open(os.path.join(region_dir, "hydro.json")) as f:
        for lk in json.load(f)["lakes"]:
            name = str(lk.get("name") or "").strip()
            if name and lk.get("coords"):
                c = np.asarray(lk["coords"], dtype=float)
                _snap(name, "lake", float(c[:, 0].mean()), float(c[:, 1].mean()), -1)

    return list(best.values())


def select_destinations(pool: list[dict], bounds: tuple, n: int, rng) -> list[dict]:
    """Greedy farthest-point pick of n destinations, refusing to reuse a 3x3
    grid cell until every occupied cell has been used once: the mechanical
    guarantee that ink reaches the plate's corners instead of pooling in the
    middle, which is the whole reason this module exists.

    Works over indices into `pool`, not the dicts themselves -- `list.remove`
    on dicts scans by equality, and while destination_pool's real output is
    deduped by name (so no two candidates ever compare equal), nothing here
    should rely on that guarantee holding for every future caller.

    Cell indices are clamped on both ends: a destination that sits just off
    the nominal plate bounds (a label snapped near the edge, say) must still
    land in one of the 9 real cells rather than growing its own out-of-range
    cell that inflates the apparent spread."""
    if not pool or n < 1:
        return []
    w, s, e, nb = bounds

    def cell(d):
        cx = min(2, max(0, int(3 * (d["x"] - w) / (e - w))))
        cy = min(2, max(0, int(3 * (d["y"] - s) / (nb - s))))
        return (cx, cy)

    remaining = list(range(len(pool)))
    start = remaining.pop(int(rng.integers(len(remaining))))
    picks = [start]
    used_cells = {cell(pool[start])}

    while remaining and len(picks) < n:
        fresh = [i for i in remaining if cell(pool[i]) not in used_cells]
        # `fresh` is empty exactly when every occupied cell has already been
        # used once (any occupied-but-unused cell would still have its
        # original candidate sitting in `remaining`), so falling back to
        # `remaining` here is precisely "start repeating cells now".
        cands = fresh if fresh else remaining
        dmin = [min((pool[i]["x"] - pool[p]["x"]) ** 2 + (pool[i]["y"] - pool[p]["y"]) ** 2
                    for p in picks) for i in cands]
        best = cands[int(np.argmax(dmin))]
        remaining.remove(best)
        picks.append(best)
        used_cells.add(cell(pool[best]))
    return [pool[i] for i in picks]


def _densify(path: np.ndarray, rng) -> np.ndarray:
    """~POINT_SPACING_M sampling along the polyline + seeded GPS jitter, so ink
    reads recorded rather than vector-perfect.

    Zero-length segments are dropped first: `np.interp` needs a strictly
    increasing `xp`, and a repeated vertex (the graph rounds to 0.1 m, but an
    out-and-back's turnaround and any hand-built fixture can still repeat one)
    would otherwise leave a flat step in the arc-length array."""
    p = np.asarray(path, dtype=float)
    if len(p) < 2:
        # a one-point path can't be interpolated; hand back two identical
        # samples rather than dividing by a zero-length arc
        p = np.repeat(p.reshape(-1, 2)[:1], 2, axis=0) if len(p) else np.zeros((2, 2))
        return p + rng.normal(0.0, JITTER_M, p.shape)
    seg = np.hypot(*np.diff(p, axis=0).T)
    keep = seg > 1e-9
    if not keep.all():
        p = np.vstack([p[:1], p[1:][keep]])
        seg = seg[keep]
    total = float(seg.sum())
    if total <= 0.0:                      # every vertex identical after filtering
        out = np.repeat(p[:1], 2, axis=0)
        return out + rng.normal(0.0, JITTER_M, out.shape)
    s = np.concatenate([[0.0], np.cumsum(seg)])
    n = max(2, int(s[-1] / POINT_SPACING_M))
    t = np.linspace(0.0, s[-1], n)
    out = np.column_stack([np.interp(t, s, p[:, 0]), np.interp(t, s, p[:, 1])])
    return out + rng.normal(0.0, JITTER_M, out.shape)


def road_vertex_index(g: Graph):
    """(keys, Nx2 array) of every road-touching vertex. Loop-invariant, so
    `network_tracks` builds it ONCE: the set-comprehension scan plus its array
    build cost ~1.2 s at 728k vertices, and doing it per trip cost 9.2 s for
    eight trips.

    Falls back to every vertex when the extract holds no `road` way at all (a
    wilderness-interior tile), and returns the 2-D empty array on an empty
    graph for the same reason `Graph.vertex_array` does -- `np.array([])` is
    shape (0,), and the `arr[:, 0]` below would raise IndexError on it."""
    keys = sorted({k for k, nbrs in g.adj.items()
                   if any(g.edges[ei]["class"] == "road" for _, ei in nbrs)})
    if not keys:
        keys = sorted(g.adj.keys())
    if not keys:
        return [], np.empty((0, 2))
    return keys, np.array(keys, dtype=float)


def trip_target_m(bounds: tuple, rng) -> float:
    """How far from its destination this trip should start, in metres, scaled
    to the plate's short side and clamped. See TRIP_SPAN_FRAC."""
    w, s, e, n = bounds
    short = min(abs(e - w), abs(n - s))
    lo, hi = TRIP_SPAN_FRAC
    return float(np.clip(rng.uniform(lo, hi) * short,
                         TRIP_SPAN_MIN_M, TRIP_SPAN_MAX_M))


def _trailhead_for(index, dest_node: tuple, target: float, rng):
    """A road-touching vertex to start from, given a destination's snapped
    graph key (an (x, y) tuple from `destination_pool`'s `node` field) and a
    plate-scaled distance `target`.

    Candidates are the road vertices whose distance from the destination is
    CLOSEST TO the target -- not the globally nearest, which under
    vertex-per-point just returns whatever sits on the 1 km floor and makes
    every journey a stub. The floor stays as a hard ceiling on closeness: a
    trailhead that IS the destination (a lake beside the road) degenerates the
    trip to two points.

    There is deliberately no trailhead REUSE across trips. Spec §3 once asked
    for one or two "worn" trailheads to keep `density.py`'s visitation story
    alive, but that justification died when destinations became the hotspot
    list directly and `density.hotspots` stopped being consulted. Instrumented
    before removal, reuse fired 0/96 on lassen_ca, 0/96 on elko_bonneville and
    2/96 on tushar_beaver_ut: it is structurally opposed to T4's farthest-point
    selection, whose whole job is maximising destination separation (on lassen
    the nearest two picks are 19-28 km apart against a ~16.8 km window, so
    widening it would not have helped either). The worn-path look still arrives
    on real posters, from trips funnelling onto shared road corridors -- honest
    topology rather than forced geometry.

    The last-resort branch (every road vertex inside the floor) takes the
    FARTHEST one, not the nearest: in a dense road web the nearest vertex can
    be the destination itself."""
    keys, arr = index
    if not keys:
        return None
    d = np.hypot(arr[:, 0] - dest_node[0], arr[:, 1] - dest_node[1])
    ok = np.where(d > TRAILHEAD_MIN_M)[0]
    if len(ok):
        cand = ok[np.argsort(np.abs(d[ok] - target))[:TRAILHEAD_CANDIDATES]]
    else:
        cand = np.argsort(d)[-1:]
    return keys[int(rng.choice(cand))]


def network_tracks(region, ways: list[dict], seed: int = 7, n_trips: int = 8):
    """The year of trips: seeded, deterministic from (ways, plate files, seed)
    alone. Returns (tracks, spots) ready for the farm."""
    from app.ingest import Track          # local: the graph half of this module
                                          # must stay importable without the engine
    rng = np.random.default_rng(seed)
    g = build_graph(ways)
    bounds = tuple(region.cfg["bounds"])
    pool = destination_pool(region.dir, g)
    dests = select_destinations(pool, bounds, n_trips, rng)
    index = road_vertex_index(g)           # built once: see road_vertex_index

    year = 2024
    trips = []
    # A destination in a different connected component than its trailhead routes
    # to None and is skipped. Correct but silent, and on a clipped OSM extract it
    # quietly thins the trip list -- so count and report rather than shipping a
    # poster with three journeys where eight were intended.
    skipped = 0
    for seq, d in enumerate(dests):
        target = trip_target_m(bounds, rng)
        th = _trailhead_for(index, d["node"], target, rng)
        if th is None:                     # empty graph: nothing to route over
            skipped += 1
            continue
        # dijkstra_edges, not dijkstra + path_edge_ids: the loop penalty and the
        # 4wd-share test must act on the edges actually traversed. Real OSM data
        # carries parallel edges (a path mapped over a track), and resolving them
        # by first-match would mis-apply the penalty silently.
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
                    path = p + p[-2::-1]               # 4wd out-and-back
        if path is None:                               # default / fallbacks
            path = out_path + out_path[-2::-1]
        lo, hi = SEASONS[d["kind"]]
        day = date(year, 1, 1) + timedelta(days=int(rng.integers(lo, hi + 1)) - 1)
        trips.append((day, seq, d, _densify(np.asarray(path, dtype=float), rng)))

    if skipped:
        print(f"  tracks: {skipped} of {len(dests)} destinations unreachable "
              f"from their trailhead (disconnected network) -- skipped")
    # `seq` is the tiebreaker on purpose. Shared dates are ordinary here, not
    # exotic -- buckets as narrow as 91 days, up to 8 trips -- so the sort key
    # must be TOTAL over dates. Sorting on the bare date works today only
    # because Timsort is stable, i.e. the order of same-day trips rests on an
    # unstated invariant; and the obvious "make it explicit" edit,
    # `key=lambda t: (t[0], t[2])`, raises TypeError the first time two trips
    # tie, because a tuple key falls through to comparing the dicts. `seq` is
    # unique and already deterministic (selection order), so the key is total
    # and never reaches the payload either way.
    trips.sort(key=lambda t: (t[0], t[1]))
    tracks = [Track(track_id=f"{d['kind']}:{d['name']}", coords=coords,
                    day=day.isoformat()) for day, _seq, d, coords in trips]
    # One spot per trip, weight 1, stated outright rather than accumulated:
    # `destination_pool` dedupes by name and `select_destinations` removes each
    # pick from its pool, so a destination can never be visited twice and the
    # accumulation loop this replaces could only ever count to 1. x/y are the
    # real summit/lake position, NOT the snapped road vertex -- the marker
    # belongs on the place, not on the trailhead path. The icon rides along so
    # the glyph agrees with the name (see KIND_ICONS); the farm's `_annotate`
    # leaves both alone once they are set.
    return tracks, [{"x": d["x"], "y": d["y"], "weight": 1, "label": d["name"],
                     "icon": KIND_ICONS.get(d["kind"], KIND_ICON_DEFAULT)}
                    for _day, _seq, d, _coords in trips]


def path_edge_ids(g: Graph, path: list) -> list[int]:
    """Edge indices along a coord path (for loop-share accounting), resolved
    by taking the FIRST edge found joining each consecutive vertex pair.
    This is ambiguous when parallel edges join a pair (two ways over the
    same two coords) -- it may not be the edge Dijkstra actually traversed.
    Callers that need the exact traversed edges should use
    `dijkstra_edges`, which returns them directly from the search."""
    ids = []
    for a, b in zip(path, path[1:]):
        ka, kb = g.key(a), g.key(b)
        ids.append(next(ei for v, ei in g.adj[ka] if v == kb))
    return ids
