"""A photo's default caption: the nearest named place within 2 km (order-photos Task 3, B5)."""
from __future__ import annotations

import pytest

from app import photocaption


def _labels(*features):
    return {"crs": "EPSG:32611",
            "features": [{"name": n, "kind": k, "rank": r, "coords": c} for n, k, r, c in features]}


def test_the_nearest_vertex_wins():
    labels = _labels(
        ("Far Peak", "summit", 70, [[1000.0, 0.0]]),
        # a long range: its nearest vertex (300 m) beats Far Peak's 1000 m
        ("Long Range", "range", 100, [[-5000.0, 0.0], [0.0, 300.0]]),
    )
    assert photocaption.nearest_name(0.0, 0.0, labels) == "Long Range"
    labels = _labels(
        ("Near Peak", "summit", 70, [[400.0, 0.0]]),
        ("Big Range", "range", 100, [[1500.0, 0.0]]),
    )
    assert photocaption.nearest_name(0.0, 0.0, labels) == "Near Peak"


def test_nothing_within_2_km_is_empty():
    labels = _labels(("Too Far", "summit", 70, [[2000.5, 0.0]]))
    assert photocaption.nearest_name(0.0, 0.0, labels) == ""
    assert photocaption.nearest_name(0.0, 0.0, _labels()) == ""
    assert photocaption.nearest_name(0.0, 0.0, {"crs": "EPSG:32611"}) == ""
    assert photocaption.nearest_name(0.0, 0.0, None) == ""


def test_exactly_2_km_is_inside():
    labels = _labels(("Edge Peak", "summit", 70, [[2000.0, 0.0]]))
    assert photocaption.nearest_name(0.0, 0.0, labels) == "Edge Peak"
    assert photocaption.CAPTION_RADIUS_M == 2000.0


def test_a_tie_takes_the_higher_rank():
    labels = _labels(
        ("Low Valley", "valley", 40, [[500.0, 0.0]]),
        ("High Range", "range", 100, [[0.0, 500.0]]),
        ("Mid Summit", "summit", 70, [[-500.0, 0.0]]),
    )
    assert photocaption.nearest_name(0.0, 0.0, labels) == "High Range"


def test_a_full_tie_is_deterministic_by_name():
    a = _labels(("Beta", "summit", 70, [[500.0, 0.0]]), ("Alpha", "summit", 70, [[0.0, 500.0]]))
    b = _labels(("Alpha", "summit", 70, [[0.0, 500.0]]), ("Beta", "summit", 70, [[500.0, 0.0]]))
    assert photocaption.nearest_name(0.0, 0.0, a) == photocaption.nearest_name(0.0, 0.0, b) == "Alpha"


def test_radius_is_a_parameter_and_junk_features_are_skipped():
    labels = _labels(
        ("", "summit", 70, [[10.0, 0.0]]),                 # no name
        ("No Coords", "summit", 70, []),                   # no vertices
        ("Real", "summit", 70, [[3000.0, 0.0]]),
    )
    assert photocaption.nearest_name(0.0, 0.0, labels) == ""
    assert photocaption.nearest_name(0.0, 0.0, labels, radius_m=3500.0) == "Real"


def test_a_tie_ranks_by_the_renderers_kind_rank_not_the_stored_rank():
    # labels.json stores basin 45 > flat 42, but the renderer ranks flat 52 > basin 50
    labels = _labels(
        ("The Basin", "basin", 45, [[500.0, 0.0]]),
        ("The Flat", "flat", 42, [[0.0, 500.0]]),
    )
    assert photocaption.nearest_name(0.0, 0.0, labels) == "The Flat"


def test_an_unknown_kind_ranks_last_in_a_tie():
    labels = _labels(
        ("Mystery", "mystery", 999, [[500.0, 0.0]]),
        ("The Valley", "valley", 40, [[0.0, 500.0]]),
    )
    assert photocaption.nearest_name(0.0, 0.0, labels) == "The Valley"


def test_the_kind_rank_copy_matches_the_renderer():
    from app import render
    assert photocaption._KIND_RANK == {k: v[2] for k, v in render.GEO_KINDS.items()
                                       if k in photocaption._KIND_RANK}
    assert set(photocaption._KIND_RANK) == set(render.GEO_KINDS)
