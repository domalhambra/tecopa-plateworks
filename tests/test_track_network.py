"""Spec: docs/superpowers/specs/2026-08-15-real-network-demo-tracks-design.md.
Fixture network, no Overpass: a T of roads spanning the plate, a trail spur to a
summit, a 4wd loop pair, and a lake by the road. Distances in region-CRS metres."""
import numpy as np
import pytest

from scripts.track_network import (build_graph, destination_pool, dijkstra,
                                    dijkstra_edges, path_edge_ids,
                                    select_destinations, WEIGHTS)

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
    """The whole point: a plate with candidates in all 9 cells must not put two
    trips in one cell while another cell sits empty."""
    w, s, e, n = BOUNDS
    pool = []
    for i in range(3):
        for j in range(3):
            pool.append({"name": f"c{i}{j}", "kind": "summit",
                         "x": w + (e - w) * (i + 0.5) / 3,
                         "y": s + (n - s) * (j + 0.5) / 3, "node": ("k", i, j)})
    picks = select_destinations(pool, BOUNDS, 9, np.random.default_rng(3))
    assert len({_cell(d) for d in picks}) == 9     # all nine, no repeats


def test_selection_handles_fewer_candidates_than_requested():
    picks = select_destinations(_cands(3), BOUNDS, 8, np.random.default_rng(7))
    assert len(picks) == 3
    assert len({d["name"] for d in picks}) == 3    # no duplicates padded in


def test_selection_on_an_empty_pool():
    assert select_destinations([], BOUNDS, 8, np.random.default_rng(7)) == []


def test_selection_clamps_cells_for_out_of_bounds_candidates():
    """A destination that sits just off the nominal plate bounds (a label
    snapped near the edge, say) must not blow up the cell grid with a
    negative index -- confirms the low-side clamp, not just the high-side
    one the BOUNDS-edge case already exercises via min(2, ...)."""
    w, s, e, n = BOUNDS
    pool = [
        {"name": "on_ne_corner", "kind": "summit", "x": e, "y": n, "node": ("k", 0)},
        {"name": "west_of_plate", "kind": "summit", "x": w - 50_000, "y": s + 5_000,
         "node": ("k", 1)},
        {"name": "south_of_plate", "kind": "summit", "x": w + 5_000, "y": s - 50_000,
         "node": ("k", 2)},
    ]
    picks = select_destinations(pool, BOUNDS, 3, np.random.default_rng(1))
    assert len(picks) == 3
    assert {d["name"] for d in picks} == {"on_ne_corner", "west_of_plate",
                                          "south_of_plate"}
