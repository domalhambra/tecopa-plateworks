"""Spec: docs/superpowers/specs/2026-08-15-real-network-demo-tracks-design.md.
Fixture network, no Overpass: a T of roads spanning the plate, a trail spur to a
summit, a 4wd loop pair, and a lake by the road. Distances in region-CRS metres."""
import numpy as np
import pytest

import math

from scripts import track_network
from scripts.track_network import (build_graph, destination_pool, dijkstra,
                                    dijkstra_edges, network_tracks,
                                    path_edge_ids, road_vertex_index,
                                    select_destinations, trip_target_m,
                                    JITTER_M, SEASONS, TRIP_SPAN_MAX_M,
                                    TRIP_SPAN_MIN_M, WEIGHTS)

BOUNDS = (500_000.0, 4_400_000.0, 530_000.0, 4_420_000.0)   # 30 x 20 km

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
    # the crossing joins the EW road (2 segments), NS road (2 segments), trail
    # spur (1 segment), and road detour (1 segment) -- exactly 6 adjacency entries
    assert len(g.adj[crossing]) == 6


def test_graph_keeps_edge_geometry_and_class():
    g = build_graph(_ways())
    classes = {e["class"] for e in g.edges}
    assert classes == {"road", "trail", "4wd"}
    assert all(len(e["coords"]) == 2 for e in g.edges)   # vertex-per-point edges


def test_zero_length_segment_is_skipped():
    # a duplicate consecutive point (and a near-duplicate within 0.1 m, which
    # rounds to the same vertex key) must not produce a zero-length edge
    ways = [
        {"class": "road", "coords": [[500_000, 4_410_000],
                                      [500_000, 4_410_000],          # exact duplicate
                                      [500_000.02, 4_410_000.02],     # rounds to same key
                                      [501_000, 4_410_000]]},
    ]
    g = build_graph(ways)
    # only the final real segment (dup point -> 501_000) should produce an edge
    assert len(g.edges) == 1
    assert g.edges[0]["coords"] == [[500_000.02, 4_410_000.02], [501_000.0, 4_410_000.0]]


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
    # the trail is short enough that even the approach profile prefers it
    # (5657 m x 1.3 = 7354 < 18000 m x 0.7 = 12600); force the contrast with a
    # profile that makes road the only sane choice, proving weights steer routing
    hostile = {"trail": 10.0, "4wd": 10.0, "road": 1.0}
    path = dijkstra(g, src, dst, hostile)
    assert g.key(path[1]) == g.key((524_000.0, 4_410_000.0))


def test_dijkstra_unreachable_returns_none():
    g = build_graph(_ways())
    island = g.key((515_000.0, 4_410_000.0))
    assert dijkstra(g, island, ("nope", "nope"), WEIGHTS["outing"]) is None


def test_dijkstra_disconnected_component_returns_none():
    """dst=('nope','nope') above never reaches the search loop -- it's caught
    by the `dst not in g.adj` fast path. The line it doesn't exercise,
    `dst not in prev and src != dst`, guards two REAL vertices in disconnected
    components, which happens on clipped OSM extracts. Build a graph with a
    genuinely isolated component to cover it."""
    ways = [
        {"class": "road", "coords": [[0.0, 0.0], [10.0, 0.0]]},
        # a separate way sharing no vertex with the one above
        {"class": "road", "coords": [[100.0, 100.0], [110.0, 100.0]]},
    ]
    g = build_graph(ways)
    src = g.key((0.0, 0.0))
    dst = g.key((110.0, 100.0))
    assert src in g.adj and dst in g.adj   # both are real, valid vertices
    assert dijkstra(g, src, dst, WEIGHTS["outing"]) is None
    assert dijkstra_edges(g, src, dst, WEIGHTS["outing"]) is None


def test_edge_penalty_pushes_the_route_off_its_first_choice():
    """The loop-finding mechanism (T5): penalising the first path's edges must
    make Dijkstra return a different route when one exists. Models the SAFE
    pattern -- penalise the edge_ids dijkstra_edges actually walked, never
    path_edge_ids (610db72: ambiguous under parallel edges, which is exactly
    the shape a real second-loop search can hit)."""
    g = build_graph(_ways())
    src = g.key((515_000.0, 4_410_000.0))
    dst = g.key((519_000.0, 4_414_000.0))
    first_path, first_edge_ids = dijkstra_edges(g, src, dst, WEIGHTS["outing"])
    pen = {ei: 100.0 for ei in first_edge_ids}
    second_path, second_edge_ids = dijkstra_edges(g, src, dst, WEIGHTS["outing"],
                                                   edge_penalty=pen)
    assert second_path is not None
    assert second_path != first_path


def test_path_edge_ids_match_the_path():
    g = build_graph(_ways())
    src = g.key((515_000.0, 4_410_000.0))
    dst = g.key((519_000.0, 4_414_000.0))
    path = dijkstra(g, src, dst, WEIGHTS["outing"])
    ids = path_edge_ids(g, path)
    assert len(ids) == len(path) - 1
    # every id is a real edge joining its consecutive pair
    for (a, b), ei in zip(zip(path, path[1:]), ids):
        assert set(map(tuple, g.edges[ei]["coords"])) == {tuple(a), tuple(b)}


def test_dijkstra_edges_resolves_parallel_edges_correctly():
    """Two ways over the IDENTICAL two coords -- a road and a trail -- are a
    real OSM shape (a path mapped over a track, duplicated imports,
    dual-carriageway merges). path_edge_ids can't tell them apart (it takes
    the first match, which here is the more expensive road); dijkstra_edges
    must, because it returns the edge the search actually walked."""
    ways = [
        {"class": "road",  "coords": [[0.0, 0.0], [100.0, 0.0]]},
        {"class": "trail", "coords": [[0.0, 0.0], [100.0, 0.0]]},
    ]
    g = build_graph(ways)
    src, dst = g.key((0.0, 0.0)), g.key((100.0, 0.0))

    # outing weights make trail (0.6) strictly cheaper than road (1.5) here
    path, edge_ids = dijkstra_edges(g, src, dst, WEIGHTS["outing"])
    assert len(edge_ids) == 1
    assert g.edges[edge_ids[0]]["class"] == "trail"

    # path_edge_ids, given only the coord path, can't distinguish the two
    # parallel edges -- it returns the first one added (the road), which is
    # NOT the edge Dijkstra traversed. This demonstrates the ambiguity.
    ambiguous_ids = path_edge_ids(g, path)
    assert g.edges[ambiguous_ids[0]]["class"] == "road"
    assert ambiguous_ids != edge_ids


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


def test_destination_pool_on_an_empty_graph(tmp_path):
    """A cache that yielded no ways must produce an empty pool, not an
    argmin-over-empty crash."""
    import json
    (tmp_path / "labels.json").write_text(json.dumps(LABELS))
    (tmp_path / "hydro.json").write_text(json.dumps(HYDRO))
    assert destination_pool(str(tmp_path), build_graph([])) == []


def test_destination_pool_dedupes_repeated_lake_names(tmp_path):
    """The real duplicate shape on committed plates: build_labels.py already
    dedupes labels.json on (name.lower(), kind), so labels never collide
    with each other, but hydro.json carries no such guarantee -- elko_bonneville
    has "Bear Lake" x2, "Dry Lake" x3. First-in-file wins."""
    import json
    # both rectangles' vertex-mean centroids sit well within SNAP_MAX_M of the
    # road crossing at (515_000, 4_410_000) -- 1000 m and ~1655 m respectively
    # -- so both are real candidates and the tie is resolved by file order,
    # not by one of them being unreachable.
    hydro = {"crs": "EPSG:32611", "lakes": [
        {"name": "Bear Lake", "coords": [[514_000, 4_408_500], [516_000, 4_408_500],
                                         [516_000, 4_409_500], [514_000, 4_409_500]]},
        {"name": "Bear Lake", "coords": [[516_000, 4_409_000], [517_000, 4_409_000],
                                         [517_000, 4_409_600], [516_000, 4_409_600]]},
    ], "rivers": []}
    (tmp_path / "labels.json").write_text(
        json.dumps({"crs": "EPSG:32611", "features": []}))
    (tmp_path / "hydro.json").write_text(json.dumps(hydro))
    g = build_graph(_ways())
    pool = destination_pool(str(tmp_path), g)
    matches = [d for d in pool if d["name"] == "Bear Lake"]
    assert len(matches) == 1
    assert matches[0]["x"] == pytest.approx(515_000.0)   # first lake's centroid


def test_destination_pool_label_beats_lake_of_the_same_name(tmp_path):
    """A summit and a lake sharing a name is the other real collision shape.
    The summit must win regardless of which file lists it first -- lakes
    carry no rank and are ranked below every labels.json entry."""
    import json
    labels = {"crs": "EPSG:32611", "features": [
        {"name": "Twin Lake", "kind": "summit", "rank": 70,
         "coords": [[515_200, 4_410_100]]},
    ]}
    hydro = {"crs": "EPSG:32611", "lakes": [
        {"name": "Twin Lake", "coords": [[514_000, 4_409_500], [516_000, 4_409_500],
                                         [516_000, 4_407_500], [514_000, 4_407_500]]},
    ], "rivers": []}
    (tmp_path / "labels.json").write_text(json.dumps(labels))
    (tmp_path / "hydro.json").write_text(json.dumps(hydro))
    g = build_graph(_ways())
    pool = destination_pool(str(tmp_path), g)
    matches = [d for d in pool if d["name"] == "Twin Lake"]
    assert len(matches) == 1
    assert matches[0]["kind"] == "summit"
    assert matches[0]["x"] == 515_200


def test_destination_pool_is_order_stable(tmp_path):
    """T4's seeded selection depends on destination_pool returning the same
    list, same order, every time for the same inputs -- pin that directly
    rather than leaving it to rest on dict-insertion-order as an accident."""
    import json
    (tmp_path / "labels.json").write_text(json.dumps(LABELS))
    (tmp_path / "hydro.json").write_text(json.dumps(HYDRO))
    g = build_graph(_ways())
    first = destination_pool(str(tmp_path), g)
    second = destination_pool(str(tmp_path), g)
    assert first == second


def test_destination_pool_skips_a_feature_with_no_coords(tmp_path):
    """destination_pool reads plate JSON directly with no schema validation --
    a malformed labels.json row (empty coords) must not take down the whole
    pool build. Mirrors the guard hydro.json lakes already had."""
    import json
    labels = {"crs": "EPSG:32611", "features": [
        {"name": "Broken Summit", "kind": "summit", "rank": 70, "coords": []},
        {"name": "Near Summit", "kind": "summit", "rank": 70,
         "coords": [[519_000, 4_414_000]]},
    ]}
    (tmp_path / "labels.json").write_text(json.dumps(labels))
    (tmp_path / "hydro.json").write_text(
        json.dumps({"crs": "EPSG:32611", "lakes": [], "rivers": []}))
    g = build_graph(_ways())
    pool = destination_pool(str(tmp_path), g)
    names = {d["name"] for d in pool}
    assert "Broken Summit" not in names
    assert "Near Summit" in names


def _cands(n=40, seed=0):
    rng = np.random.default_rng(seed)
    w, s, e, nb = BOUNDS
    return [{"name": f"d{i}", "kind": "summit",
             "x": float(rng.uniform(w, e)), "y": float(rng.uniform(s, nb)),
             "node": ("k", i)} for i in range(n)]


def _cell(d, bounds=BOUNDS):
    w, s, e, n = bounds
    return (min(2, int(3 * (d["x"] - w) / (e - w))),
            min(2, int(3 * (d["y"] - s) / (n - s))))


def test_selection_spreads_over_the_grid():
    picks = select_destinations(_cands(), BOUNDS, 8, np.random.default_rng(7))
    assert len(picks) == 8
    assert len({_cell(d) for d in picks}) >= 5     # spec's cell floor


def test_selection_is_deterministic():
    a = select_destinations(_cands(), BOUNDS, 6, np.random.default_rng(7))
    b = select_destinations(_cands(), BOUNDS, 6, np.random.default_rng(7))
    assert [d["name"] for d in a] == [d["name"] for d in b]


def test_selection_uses_every_occupied_cell_before_repeating_one():
    """The whole point, made with a fixture that can actually catch a
    regression. Nine-candidates-in-nine-cells-asking-for-nine (the original
    shape here) is tautological: n == len(pool), so every candidate comes
    back regardless of whether the cell-rotation logic exists at all -- a
    stripped-down plain-farthest-point selector with no cell awareness
    passes it too.

    This fixture instead crowds one cell (two points at opposite corners,
    so pure distance makes them look maximally attractive to each other)
    against three lone cells, and asks for one fewer than the candidate
    count. Plain farthest-point picks both crowded-cell points before ever
    reaching the fourth occupied cell at seeds 21 and 24 (confirmed by hand
    against a stripped variant with the cell-rotation logic deleted); the
    cell-aware selector must not repeat the crowded cell while a cell sits
    untouched."""
    pool = [
        {"name": "crowded_sw", "kind": "summit", "x": 500_500.0, "y": 4_400_500.0,
         "node": ("k", 0)},
        {"name": "crowded_ne", "kind": "summit", "x": 509_500.0, "y": 4_406_000.0,
         "node": ("k", 1)},
        {"name": "lone_mid",   "kind": "summit", "x": 515_000.0, "y": 4_410_000.0,
         "node": ("k", 2)},
        {"name": "lone_ne",    "kind": "summit", "x": 525_000.0, "y": 4_416_000.0,
         "node": ("k", 3)},
        {"name": "lone_nw",    "kind": "summit", "x": 502_000.0, "y": 4_415_000.0,
         "node": ("k", 4)},
    ]
    picks = select_destinations(pool, BOUNDS, 4, np.random.default_rng(21))
    assert len(picks) == 4
    assert len({_cell(d) for d in picks}) == 4     # all four occupied cells, no repeat


def test_selection_handles_fewer_candidates_than_requested():
    picks = select_destinations(_cands(3), BOUNDS, 8, np.random.default_rng(7))
    assert len(picks) == 3
    assert len({d["name"] for d in picks}) == 3    # no duplicates padded in


def test_selection_on_an_empty_pool():
    assert select_destinations([], BOUNDS, 8, np.random.default_rng(7)) == []


def test_selection_with_n_less_than_one_returns_nothing():
    """n=0 (or negative) must return an empty list, not one destination --
    the unconditional `picks = [start]` before the loop would otherwise
    hand back a single pick, and burn an RNG draw, for a caller that asked
    for none. Not reachable today, but the signature promises n destinations
    and a future caller may pass a computed count that lands on zero."""
    assert select_destinations(_cands(), BOUNDS, 0, np.random.default_rng(7)) == []
    assert select_destinations(_cands(), BOUNDS, -1, np.random.default_rng(7)) == []


def test_selection_clamps_cells_for_out_of_bounds_candidates():
    """A destination that sits just off the nominal plate bounds (a label
    snapped near the edge, say) must not grow its own out-of-range pseudo
    cell -- confirms the low-side clamp, not just the high-side one the
    BOUNDS-edge corner point already exercises via min(2, ...).

    west_of_plate and south_of_plate sit on opposite sides of the plate but
    both clamp to the SAME real cell, (0, 0); on_ne_corner is the sole
    occupant of (2, 2). Asking for n=2 with only 2 real cells occupied is
    not tautological (n < len(pool)) and forces exactly one destination
    from each real cell -- on_ne_corner must always come back. Without the
    low-side clamp (only min(2, ...), no max(0, ...)), west_of_plate's
    negative raw index reads as a permanently-fresh cell of its own, and at
    seed 0 that bug picks BOTH crowded-cell members while skipping (2, 2)
    entirely -- confirmed by hand against an unclamped variant."""
    w, s, e, n = BOUNDS
    pool = [
        {"name": "on_ne_corner", "kind": "summit", "x": e, "y": n, "node": ("k", 0)},
        {"name": "west_of_plate", "kind": "summit", "x": w - 50_000, "y": s + 5_000,
         "node": ("k", 1)},
        {"name": "south_of_plate", "kind": "summit", "x": w + 5_000, "y": s - 50_000,
         "node": ("k", 2)},
    ]
    picks = select_destinations(pool, BOUNDS, 2, np.random.default_rng(0))
    names = {d["name"] for d in picks}
    assert len(picks) == 2
    assert "on_ne_corner" in names
    assert not {"west_of_plate", "south_of_plate"} <= names


def _region(tmp_path):
    import json
    (tmp_path / "labels.json").write_text(json.dumps(LABELS))
    (tmp_path / "hydro.json").write_text(json.dumps(HYDRO))
    return _StubRegion(tmp_path)


class _StubRegion:
    def __init__(self, tmpdir):
        self.id = "stub"
        self.dir = str(tmpdir)
        self.cfg = {"bounds": list(BOUNDS)}


def test_network_tracks_shape_and_determinism(tmp_path):
    r = _region(tmp_path)
    t1, s1 = network_tracks(r, _ways(), seed=7)
    t2, s2 = network_tracks(r, _ways(), seed=7)
    assert len(t1) >= 2 and len(s1) >= 2
    for a, b in zip(t1, t2):
        assert a.day == b.day
        assert np.array_equal(a.coords, b.coords)
    assert [x["label"] for x in s1] == [x["label"] for x in s2]


def test_tracks_are_dated_by_season_bucket_and_sorted(tmp_path):
    from datetime import date
    r = _region(tmp_path)
    tracks, _ = network_tracks(r, _ways(), seed=7)
    days = [date.fromisoformat(t.day) for t in tracks]
    assert days == sorted(days)
    for t, d in zip(tracks, days):
        kind = t.track_id.split(":", 1)[0]      # track_id = "<kind>:<name>"
        lo, hi = SEASONS[kind]
        assert lo <= d.timetuple().tm_yday <= hi


def test_tracks_are_densified_and_jittered(tmp_path, monkeypatch):
    r = _region(tmp_path)
    tracks, _ = network_tracks(r, _ways(), seed=7)
    seg = np.hypot(*np.diff(tracks[0].coords, axis=0).T)
    assert np.median(seg) < 40.0
    assert len(tracks[0].coords) > 100

    # ...and the jitter is real. Without this the test passed with JITTER_M
    # zeroed, i.e. it only ever checked the densify half of the name. Seeded
    # jitter is what makes the ink read recorded rather than vector-perfect.
    monkeypatch.setattr(track_network, "JITTER_M", 0.0)
    clean, _ = network_tracks(r, _ways(), seed=7)
    assert len(clean[0].coords) == len(tracks[0].coords)
    off = np.hypot(*(tracks[0].coords - clean[0].coords).T)
    assert 0.3 * JITTER_M < np.median(off) < 4 * JITTER_M
    # a straight leg sampled at a fixed spacing has near-constant segment
    # lengths; jitter is what gives them spread
    assert np.std(seg) > 0.5 * JITTER_M


def test_spots_carry_real_names_and_positions(tmp_path):
    r = _region(tmp_path)
    _, spots = network_tracks(r, _ways(), seed=7)
    names = {s["label"] for s in spots}
    assert names <= {"Near Summit", "Road Lake"} and names
    for s in spots:
        assert set(s) >= {"x", "y", "weight", "label"}
        assert s["weight"] == 1          # one trip per destination, by construction

    # The marker belongs on the PLACE, not on the road vertex the router
    # snapped it to. Road Lake's centroid is 1.5 km from its snapped node, so
    # this separates the two; Near Summit's coincide and cannot.
    lake = next(s for s in spots if s["label"] == "Road Lake")
    assert (lake["x"], lake["y"]) == pytest.approx((515_000.0, 4_408_500.0))


def test_different_seeds_give_different_journeys(tmp_path):
    """Determinism must not mean the seed is ignored."""
    r = _region(tmp_path)
    a, _ = network_tracks(r, _ways(), seed=7)
    b, _ = network_tracks(r, _ways(), seed=99)
    same = (len(a) == len(b)
            and all(np.array_equal(x.coords, y.coords) for x, y in zip(a, b)))
    assert not same


def test_no_track_is_degenerate(tmp_path):
    """Every rendered journey must be a real path, not two points at a road-side
    destination -- the trailhead distance floor exists for this.

    Swept across seeds, not pinned to one: the trailhead is a seeded draw from
    the five nearest candidates, so a single seed tests one draw. "Road Lake"
    snaps ONTO the road crossing, which is exactly the shape that degenerates
    -- with the 1 km floor deleted, 9 of the first 30 seeds produce a
    sub-10 m track and seed 7 is not among them (measured). The guarantee is
    per-journey and per-seed, so the test has to be too."""
    r = _region(tmp_path)
    for seed in range(12):
        tracks, _ = network_tracks(r, _ways(), seed=seed)
        assert tracks
        for t in tracks:
            span = np.hypot(*(t.coords.max(axis=0) - t.coords.min(axis=0)))
            assert span > 500.0, f"seed {seed}: {t.track_id} spans only {span:.0f} m"


def test_trailhead_never_lands_on_the_destination_itself():
    """The last-resort branch: a destination inside a dense road web, where
    EVERY road vertex sits within the 1 km floor. Taking the nearest vertex
    then returns the destination's own node, and a trip from a point to itself
    renders as a dot -- so this branch takes the farthest instead.

    The main fixture can never reach here (it always has a road vertex beyond
    1 km), which is why this is a direct unit test rather than a
    network_tracks assertion."""
    ways = [{"class": "road", "coords": [[0.0, 0.0], [300.0, 0.0], [600.0, 0.0]]}]
    g = build_graph(ways)
    dest = g.key((0.0, 0.0))
    th = track_network._trailhead_for(road_vertex_index(g), dest, [], 5_000.0,
                                      np.random.default_rng(3))
    assert th != dest                       # not a dot
    assert th == g.key((600.0, 0.0))        # the farthest available, not the nearest


def test_trailhead_on_a_network_with_no_roads():
    """A clipped OSM extract can hold trails and 4wd tracks but no `road` way
    at all (a wilderness-interior tile). Without the fall-back to any vertex,
    the empty road_keys list becomes a 1-D numpy array and `arr[:, 0]` raises
    IndexError, taking down the whole farm run rather than routing a trip."""
    g = build_graph([{"class": "trail", "coords": [[0.0, 0.0], [5_000.0, 0.0]]}])
    th = track_network._trailhead_for(road_vertex_index(g), g.key((0.0, 0.0)),
                                      [], 5_000.0, np.random.default_rng(0))
    assert th in g.adj
    assert th == g.key((5_000.0, 0.0))


def test_trailhead_on_an_empty_graph_returns_none():
    """`np.array([])` is shape (0,), so `arr[:, 0]` raises IndexError on an
    empty graph -- the same trap `Graph.vertex_array` already guards. Reachable
    from a cache that yielded no ways."""
    keys, arr = road_vertex_index(build_graph([]))
    assert keys == [] and arr.shape == (0, 2)
    assert track_network._trailhead_for((keys, arr), (0.0, 0.0), [], 5_000.0,
                                        np.random.default_rng(0)) is None


def test_trip_target_scales_to_the_plate_and_clamps():
    """Trip length is a target scaled to the plate's SHORT side, so a day out
    reads as a day out at any plate scale -- and clamped at both ends, because
    a tiny plate still needs a real walk and elko_bonneville (483 km wide)
    must not ask for a 90 km day."""
    rng = np.random.default_rng(0)
    # 40 x 30 km plate -> short side 30 km -> 6%-18% is 1.8-5.4 km, floor 2 km
    mid = [trip_target_m((0.0, 0.0, 40_000.0, 30_000.0), rng) for _ in range(200)]
    assert TRIP_SPAN_MIN_M <= min(mid) and max(mid) <= 5_400.0
    assert max(mid) - min(mid) > 1_000.0          # genuinely varied, not constant
    # a 5 km plate would ask for 300-900 m: the floor must lift it
    assert all(t == TRIP_SPAN_MIN_M
               for t in (trip_target_m((0.0, 0.0, 5_000.0, 5_000.0), rng)
                         for _ in range(20)))
    # a 483 km corridor plate would ask for 29-87 km: the ceiling must cap it
    assert max(trip_target_m((0.0, 0.0, 483_000.0, 483_000.0), rng)
               for _ in range(200)) == TRIP_SPAN_MAX_M


def test_road_vertex_index_covers_only_road_touching_vertices():
    """Hoisted out of the trip loop (it is loop-invariant and cost 9.2 s for
    eight trips at 728k vertices), so it needs its own test now that
    network_tracks builds it once."""
    keys, arr = road_vertex_index(build_graph(_ways()))
    assert len(keys) == len(arr)
    # the 4wd-only loop west of the crossing must not appear...
    assert build_graph(_ways()).key((505_000.0, 4_415_000.0)) not in keys
    # ...but the crossing, which several roads touch, must
    assert build_graph(_ways()).key((515_000.0, 4_410_000.0)) in keys


# --- dense fixture -------------------------------------------------------
# _ways() spaces its points 5-15 km apart, which HIDES a whole bug class: under
# the vertex-per-point graph, real OSM way points sit 20-300 m apart, so "the
# nearest road vertex beyond the 1 km floor" is always ON the floor. Measured
# against the pre-fix composer here: the five trailhead candidates spanned
# 1001-1005 m and every journey came out a ~2 km stub (0.07 of the plate),
# whatever the plate's size. This fixture reproduces that density. Do NOT fold
# it into _ways() -- the sparse fixture is load-bearing for the routing tests.

DENSE_BOUNDS = (500_000.0, 4_400_000.0, 540_000.0, 4_430_000.0)   # 40 x 30 km


def _line(a, b, spacing=50.0):
    n = max(1, int(math.hypot(b[0] - a[0], b[1] - a[1]) / spacing))
    return [[a[0] + (b[0] - a[0]) * i / n, a[1] + (b[1] - a[1]) * i / n]
            for i in range(n + 1)]


def _dense_ways():
    """A 2 km road mesh at ~50 m node spacing -- real-extract density -- plus
    trails out to the summits and a 4wd corridor onto the north summit."""
    w = []
    for i in range(15):
        y = 4_400_500.0 + i * 2_000.0
        if y <= 4_429_500.0:
            w.append({"class": "road", "coords": _line([500_500.0, y], [539_500.0, y])})
    for i in range(20):
        x = 500_500.0 + i * 2_000.0
        if x <= 539_500.0:
            w.append({"class": "road", "coords": _line([x, 4_400_500.0], [x, 4_429_500.0])})
    for a, b in ((( 520_500.0, 4_424_500.0), (521_500.0, 4_428_000.0)),
                 (( 504_500.0, 4_414_500.0), (502_500.0, 4_412_000.0)),
                 (( 534_500.0, 4_416_500.0), (538_000.0, 4_420_000.0)),
                 (( 520_500.0, 4_404_500.0), (512_000.0, 4_402_500.0))):
        w.append({"class": "trail", "coords": _line(list(a), list(b))})
    w.append({"class": "4wd",
              "coords": _line([534_500.0, 4_424_500.0], [521_500.0, 4_428_000.0])})
    return w


DENSE_LABELS = {"crs": "EPSG:32611", "features": [
    {"name": "North Summit", "kind": "summit", "rank": 70, "coords": [[521_500, 4_428_000]]},
    {"name": "West Summit",  "kind": "summit", "rank": 70, "coords": [[502_500, 4_412_000]]},
    {"name": "East Gap",     "kind": "gap",    "rank": 70, "coords": [[538_000, 4_420_000]]},
]}
DENSE_HYDRO = {"crs": "EPSG:32611", "lakes": [
    {"name": "South Lake", "coords": [[511_500, 4_402_000], [512_500, 4_402_000],
                                      [512_500, 4_403_000], [511_500, 4_403_000]]},
], "rivers": []}


def _dense_region(tmp_path):
    import json
    (tmp_path / "labels.json").write_text(json.dumps(DENSE_LABELS))
    (tmp_path / "hydro.json").write_text(json.dumps(DENSE_HYDRO))
    r = _StubRegion(tmp_path)
    r.cfg = {"bounds": list(DENSE_BOUNDS)}
    return r


def _retrace_error(coords):
    """Mean |c[i] - c[-1-i]|. An out-and-back's arc-length samples are
    symmetric about the turnaround, so this is jitter-sized (~5 m); a genuine
    loop returns by a different line, so it is hundreds of metres."""
    return float(np.abs(coords - coords[::-1]).mean())


def test_trips_span_a_real_fraction_of_the_plate(tmp_path):
    """The whole point of the project, asserted plate-RELATIVE so it stays
    meaningful on a 40 km plate and on elko_bonneville's 483 km corridor alike.

    Against the pre-fix composer (globally-nearest trailhead) this fixture
    gave a median span of 0.071 of the plate short side and a minimum of
    0.034 -- the user's "squiggly lines clustered in the middle" in a new
    costume. Trip length has to be a designed target, not an accident of how
    far the nearest road happens to be."""
    r = _dense_region(tmp_path)
    ways = _dense_ways()
    short = min(DENSE_BOUNDS[2] - DENSE_BOUNDS[0], DENSE_BOUNDS[3] - DENSE_BOUNDS[1])
    spans = []
    for seed in range(6):
        tracks, _ = network_tracks(r, ways, seed=seed)
        assert tracks
        for t in tracks:
            spans.append(float(np.hypot(*(t.coords.max(0) - t.coords.min(0)))))
    spans = np.array(spans)
    assert spans.min() / short > 0.05, f"shortest trip is {spans.min():.0f} m"
    assert np.median(spans) / short > 0.12, (
        f"median trip {np.median(spans):.0f} m is {np.median(spans)/short:.3f} "
        "of the plate -- trips have collapsed toward the trailhead floor again")


def test_loop_trips_actually_happen(tmp_path):
    """The loop branch was dead in practice before trips were plate-scaled:
    0 of 51 fired, and mutation-testing showed nothing guarded it --
    LOOP_SHARE_MAX = -1.0 passed the whole suite. A loop is the only shape that
    returns by a different line, so a large retrace error proves one rendered."""
    r = _dense_region(tmp_path)
    ways = _dense_ways()
    errs = [_retrace_error(t.coords)
            for seed in range(6) for t in network_tracks(r, ways, seed=seed)[0]]
    assert max(errs) > 300.0, (
        "no trip returned by a different line -- every journey retraced itself, "
        "so the loop branch never accepted a second path")


def _4wd_fixture(tmp_path):
    """Trailhead road, then TWO ways onto one summit: a 10 km trail and a 20 km
    4wd corridor that swings east. The weights make these disagree on purpose
    -- outing takes the trail (10 km x 0.6 = 6000 < 20 km x 0.7 = 14000) while
    4wd_day takes the track (20 km x 0.5 = 10000 < 10 km x 2.5 = 25000) -- so
    the corridor is reached ONLY when the 4wd branch fires. Road-vs-4wd alone
    cannot show this: whenever outing prefers road, so does 4wd_day."""
    import json
    j = [510_000.0, 4_400_500.0]
    ways = [
        {"class": "road",  "coords": _line([500_500.0, 4_400_500.0], j)},
        {"class": "trail", "coords": _line(j, [510_000.0, 4_410_500.0])},
        {"class": "4wd",   "coords": _line(j, [515_000.0, 4_400_500.0])},
        {"class": "4wd",   "coords": _line([515_000.0, 4_400_500.0],
                                           [515_000.0, 4_410_500.0])},
        {"class": "4wd",   "coords": _line([515_000.0, 4_410_500.0],
                                           [510_000.0, 4_410_500.0])},
    ]
    (tmp_path / "labels.json").write_text(json.dumps({"crs": "EPSG:32611", "features": [
        {"name": "Track Peak", "kind": "summit", "rank": 70,
         "coords": [[510_000, 4_410_500]]}]}))
    (tmp_path / "hydro.json").write_text(
        json.dumps({"crs": "EPSG:32611", "lakes": [], "rivers": []}))
    r = _StubRegion(tmp_path)
    r.cfg = {"bounds": [500_000.0, 4_400_000.0, 530_000.0, 4_430_000.0]}
    return r, ways


def test_4wd_trips_actually_happen(tmp_path, monkeypatch):
    """The 4wd branch was dead too: 0 of 46 fired, and a threshold of
    `>= 99.0` passed the whole suite. Only the 4wd corridor reaches east of
    x=513000, so ink out there proves the branch produced the route.

    Loops are disabled for the duration: the corridor is also the only
    alternative path a loop could take, so with the loop branch live this
    assertion passes even when the 4wd branch is dead -- measured, it was the
    reason the first version of this test failed to catch a 99.0 threshold."""
    monkeypatch.setattr(track_network, "LOOP_SHARE_MAX", -1.0)
    r, ways = _4wd_fixture(tmp_path)
    reached = [seed for seed in range(12)
               for t in network_tracks(r, ways, seed=seed)[0]
               if t.coords[:, 0].max() > 513_000.0]
    assert reached, ("no trip took the 4wd corridor -- the 4wd branch never "
                     "accepted its route, so every trip fell back to the trail")


def test_4wd_route_is_dominated_by_4wd_ways(tmp_path):
    """The share test the branch applies, pinned directly: the 4wd_day profile
    must return a route that really is mostly `highway=track`, not a road
    detour that merely touches one."""
    r, ways = _4wd_fixture(tmp_path)
    g = build_graph(ways)
    src = g.key((510_000.0, 4_400_500.0))
    dst = g.key((510_000.0, 4_410_500.0))
    _, ids = dijkstra_edges(g, src, dst, WEIGHTS["4wd_day"])
    total = sum(g.edges[i]["len_m"] for i in ids)
    four = sum(g.edges[i]["len_m"] for i in ids if g.edges[i]["class"] == "4wd")
    assert four / total >= 0.4
    # and the outing profile disagrees -- otherwise the fixture proves nothing
    _, outing_ids = dijkstra_edges(g, src, dst, WEIGHTS["outing"])
    assert {g.edges[i]["class"] for i in outing_ids} == {"trail"}


def test_worn_trailhead_is_reused_between_nearby_destinations(tmp_path):
    """Spec §3's "worn path": trips share a trailhead so the visitation-density
    story survives. The fixed 1-12 km window this replaces never fired on a
    real plate (0 reuses in 200 trips), making the feature a silent no-op --
    deleting the whole worn block passed every test.

    Reuse is geometric, so the fixture has to be: two destinations ~4 km apart,
    inside the scaled window. On a plate whose destinations are deliberately
    spread to the corners (T4's job) reuse correctly stays rare.

    Asserted through `network_tracks`, not against `_trailhead_for` directly:
    the window and the `worn` bookkeeping are separate pieces, and a direct
    unit test passes with the whole `worn.append` block deleted -- which is
    exactly how the no-op survived. Two trips starting at the SAME point is
    the observable effect, and it separates cleanly: 7 of 30 seeds share a
    start with the block, 0 of 30 without it."""
    import json
    ways = []
    for i in range(9):
        y = 4_400_500.0 + i * 2_000.0
        ways.append({"class": "road", "coords": _line([500_500.0, y], [519_500.0, y])})
    for i in range(10):
        x = 500_500.0 + i * 2_000.0
        ways.append({"class": "road", "coords": _line([x, 4_400_500.0], [x, 4_416_500.0])})
    (tmp_path / "labels.json").write_text(json.dumps({"crs": "EPSG:32611", "features": [
        {"name": "Twin Peak East", "kind": "summit", "rank": 70,
         "coords": [[512_500, 4_408_500]]},
        {"name": "Twin Peak West", "kind": "summit", "rank": 70,
         "coords": [[508_500, 4_408_500]]}]}))
    (tmp_path / "hydro.json").write_text(
        json.dumps({"crs": "EPSG:32611", "lakes": [], "rivers": []}))
    r = _StubRegion(tmp_path)
    bounds = (500_000.0, 4_400_000.0, 520_000.0, 4_417_000.0)
    r.cfg = {"bounds": list(bounds)}
    assert len(destination_pool(str(tmp_path), build_graph(ways))) == 2

    shared = 0
    for seed in range(30):
        tracks, _ = network_tracks(r, ways, seed=seed)
        if len(tracks) == 2 and np.hypot(*(tracks[0].coords[0]
                                           - tracks[1].coords[0])) < 4 * JITTER_M:
            shared += 1
    assert shared > 0, ("no two trips ever shared a trailhead between "
                        "destinations 4 km apart -- the worn path is a no-op")


def test_worn_reuse_scales_to_a_corridor_plate(tmp_path):
    """The window has to SCALE, not just exist. On a 20 km plate the old fixed
    1-12 km window works by accident, so the test above cannot tell the two
    apart -- this one can. elko_bonneville is 483 km wide with ~88 km grid
    cells, and there the fixed window is far too small: on this 400 x 200 km
    plate with destinations 20 km apart, the scaled window shares a trailhead
    on 14 of 20 seeds and the fixed one on 1."""
    import json
    ways = []
    for i in range(11):
        y = i * 20_000.0
        ways.append({"class": "road", "coords": _line([0.0, y], [400_000.0, y], 2_000.0)})
    for i in range(21):
        x = i * 20_000.0
        ways.append({"class": "road", "coords": _line([x, 0.0], [x, 200_000.0], 2_000.0)})
    (tmp_path / "labels.json").write_text(json.dumps({"crs": "EPSG:32611", "features": [
        {"name": "Mesa A", "kind": "summit", "rank": 70, "coords": [[200_000, 100_000]]},
        {"name": "Mesa B", "kind": "summit", "rank": 70, "coords": [[220_000, 100_000]]}]}))
    (tmp_path / "hydro.json").write_text(
        json.dumps({"crs": "EPSG:32611", "lakes": [], "rivers": []}))
    r = _StubRegion(tmp_path)
    r.cfg = {"bounds": [0.0, 0.0, 400_000.0, 200_000.0]}

    shared = 0
    for seed in range(20):
        tracks, _ = network_tracks(r, ways, seed=seed)
        if len(tracks) == 2 and np.hypot(*(tracks[0].coords[0]
                                           - tracks[1].coords[0])) < 4 * JITTER_M:
            shared += 1
    assert shared >= 5, (
        f"only {shared}/20 seeds shared a trailhead on a corridor plate -- the "
        "reuse window is not scaling with the plate")


def test_densify_follows_the_source_geometry(tmp_path):
    """Registration is correctness (invariant 5), and _densify emits the FINAL
    coordinates. Both a transposition (swapping x and y) and interpolating by
    vertex index instead of arc length passed the entire suite before this
    test existed -- a coordinate bug in this function must not be invisible.

    An L-shaped path pins both: it is asymmetric, so a transpose moves it, and
    unevenly sampled, so index-interpolation bunches points on the short leg."""
    src = np.array([[0.0, 0.0], [9_000.0, 0.0], [9_000.0, 3_000.0]])
    out = track_network._densify(src, np.random.default_rng(0))

    # endpoints land on the source's endpoints, jitter aside
    assert np.hypot(*(out[0] - src[0])) < 4 * JITTER_M
    assert np.hypot(*(out[-1] - src[-1])) < 4 * JITTER_M

    # every sample sits on the source polyline
    def seg_dist(p, a, b):
        ab = b - a
        t = np.clip(np.dot(p - a, ab) / np.dot(ab, ab), 0.0, 1.0)
        return float(np.hypot(*(p - (a + t * ab))))
    dev = np.array([min(seg_dist(p, src[i], src[i + 1]) for i in range(len(src) - 1))
                    for p in out])
    assert dev.max() < 4 * JITTER_M, f"max deviation {dev.max():.1f} m off the path"

    # arc-length sampling, not index sampling: the 9 km leg must carry ~3x the
    # points of the 3 km leg, not the same number
    long_leg = int((out[:, 1] < 1_000.0).sum())
    short_leg = int((out[:, 0] > 8_000.0).sum())
    assert long_leg > 1.8 * short_leg


def test_two_trips_on_the_same_date_still_sort(tmp_path, monkeypatch):
    """Dates are seeded draws inside buckets as narrow as 91 days, with up to 8
    trips -- collisions are ordinary, not exotic. Two things must survive one:
    the sort must not raise, and the resulting order must be deterministic.

    A tuple sort key whose second element is the destination dict --
    `key=lambda t: (t[0], t[2])`, the natural way to write "date then
    payload" -- raises TypeError on the first tie and kills the farm run;
    verified by mutation, this test catches exactly that. (A key of the bare
    date does NOT raise: `sort(key=...)` compares only the extracted keys, so
    the dict is never reached. It survives on Timsort's stability instead,
    which is why the explicit `seq` tiebreaker is there.)

    Collapse every season bucket to a single day to force the tie: the
    fixture's two destinations are a summit and a lake, whose real buckets
    are disjoint, so they can never collide on their own.

    The assertion is the EXACT resulting order, not merely that two runs agree
    -- re-running one seed cannot detect order instability, so the weaker form
    of this test passed with `seq` deleted. Tied trips must come back in
    selection order, which for seed 7 puts Road Lake first."""
    monkeypatch.setattr(track_network, "SEASONS",
                        {"lake": (200, 200), "gap": (200, 200), "summit": (200, 200)})
    r = _region(tmp_path)
    tracks, _ = network_tracks(r, _ways(), seed=7)
    assert len(tracks) == 2
    assert len({t.day for t in tracks}) == 1          # the collision really happened
    assert [t.track_id for t in tracks] == ["lake:Road Lake", "summit:Near Summit"]
