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
