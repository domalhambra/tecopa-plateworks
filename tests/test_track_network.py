"""Spec: docs/superpowers/specs/2026-08-15-real-network-demo-tracks-design.md.
Fixture network, no Overpass: a T of roads spanning the plate, a trail spur to a
summit, a 4wd loop pair, and a lake by the road. Distances in region-CRS metres."""
import numpy as np
import pytest

from scripts.track_network import (build_graph, dijkstra, dijkstra_edges,
                                    path_edge_ids, WEIGHTS)

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
