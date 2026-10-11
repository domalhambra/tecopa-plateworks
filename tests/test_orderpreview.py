# tests/test_orderpreview.py
import numpy as np
import pytest

from app import orderpreview as opv
from app.orderplate import PlateError, nestled_frame, track_shares

KM = 1000.0


def _line(x0, y0, x1, y1):
    return np.array([[x0 * KM, y0 * KM], [x1 * KM, y1 * KM]])


def _bounds(tracks):
    pts = np.concatenate(tracks)
    return (pts[:, 0].min(), pts[:, 1].min(), pts[:, 0].max(), pts[:, 1].max())


def _plan(tracks, **kw):
    return {e["key"]: e for e in opv.plan_sizes(_bounds(tracks), tracks, **kw)}


def test_the_shares_of_a_frame():
    assert track_shares((0, 0, 30, 10), (0, 0, 100, 50)) == (0.3, 0.2)


def test_the_two_orientations_of_each_size():
    three = {c.orientation: c for c in opv.candidates("three")}
    assert three["portrait"].print_in == (55.0, 22.0) and three["landscape"].print_in == (70.0, 17.0)
    assert three["portrait"].gap == three["landscape"].gap == 2.0 and three["portrait"].panels == 3
    small = {c.orientation: c for c in opv.candidates("11x17")}
    assert small["portrait"].print_in == (11.0, 17.0) and small["landscape"].print_in == (17.0, 11.0)
    assert small["portrait"].gap == 0.0 and small["portrait"].panels == 1


def test_a_compact_loop_gets_the_single_sheets_and_no_three_panel_set():
    loop = [np.array([[0, 0], [10 * KM, 0], [10 * KM, 10 * KM], [0, 10 * KM], [0, 0]], float)]
    plan = _plan(loop)
    assert plan["11x17"]["offered"] and plan["17x22"]["offered"]
    assert not plan["three"]["offered"]
    assert plan["three"]["why"] == "the tracks span 24% of the sheet's width, under 30%"
    # two panels 17 in across are 36 x 22 in: the loop spans 37 % of that width
    assert plan["two"]["offered"] and plan["two"]["width_share"] == 0.367


def test_a_thin_east_west_route_gets_three_panels_in_landscape():
    plan = _plan([_line(0, 0, 200, 5)])
    three = plan["three"]
    assert three["offered"], three["why"]
    assert three["orientation"] == "landscape" and three["print_in"] == [70.0, 17.0]
    assert three["width_share"] == 0.6
    assert plan["17x22"]["orientation"] == "landscape"


def test_a_north_south_route_gets_no_set():
    plan = _plan([_line(0, 0, 5, 200)])
    assert plan["17x22"]["orientation"] == "portrait"
    assert not plan["two"]["offered"] and not plan["three"]["offered"]


def test_a_panel_with_no_track_refuses_the_set():
    ends = [_line(0, 0, 8, 6), _line(192, 0, 200, 6)]       # two day walks, 190 km apart
    plan = _plan(ends)
    assert not plan["three"]["offered"]
    assert plan["three"]["why"] == "panel 2 holds no track"
    assert plan["two"]["offered"], plan["two"]["why"]


def test_the_rule_follows_the_line_and_not_its_vertices():
    cand = [c for c in opv.candidates("three") if c.orientation == "landscape"][0]
    track = [_line(0, 0, 200, 5)]                             # two vertices, at the ends
    frame = nestled_frame(_bounds(track), cand.aspect)
    assert opv.panels_with_track(track, frame, cand) == [True, True, True]


def test_a_route_end_behind_a_gap_is_named_by_its_gap():
    cand = [c for c in opv.candidates("two") if c.orientation == "landscape"][0]   # 46 x 17 in
    frame = (0.0, 0.0, 46 * KM, 17 * KM)                      # 1 km of ground for each inch
    ends_in_the_gap = [_line(5, 8, 23, 8)]                    # it stops at 23 in: gap 1 is 22-24
    assert opv.gaps_hiding_ends(ends_in_the_gap, frame, cand) == [1]
    assert opv.gaps_hiding_ends([_line(5, 8, 40, 8)], frame, cand) == []    # it only crosses
    assert opv.gaps_hiding_ends([_line(5, 30, 23, 30)], frame, cand) == []  # outside the frame
    cut = opv.Candidate("two", 2, "landscape", (44.0, 17.0), 0.0)
    assert opv.gaps_hiding_ends(ends_in_the_gap, (0.0, 0.0, 44 * KM, 17 * KM), cut) == []
    entry = opv.judge(cand, frame, (5 * KM, 8 * KM, 23 * KM, 8 * KM), ends_in_the_gap)
    assert entry["ends_behind"] == [1]


def test_the_sizes_list_overrides_the_fit_rule_with_a_warning():
    loop = [np.array([[0, 0], [10 * KM, 0], [10 * KM, 10 * KM], [0, 10 * KM], [0, 0]], float)]
    plan = _plan(loop, forced=("three",))
    assert plan["three"]["offered"] and "of the sheet's width" in plan["three"]["warning"]
    for key in ("11x17", "17x22", "two"):
        assert not plan[key]["offered"]
        assert plan[key]["why"] == "it is not in the sizes list of order.toml"


def test_terrain_too_coarse_refuses_a_size_and_the_list_cannot_force_it():
    def widen(cand, frame):
        if cand.key == "three":
            raise PlateError("The terrain data is still too coarse for this print size.")
        return frame
    plan = _plan([_line(0, 0, 200, 5)], widen=widen, forced=("three", "17x22"))
    assert not plan["three"]["offered"]
    assert plan["three"]["why"] == "The terrain data is still too coarse for this print size."
    assert plan["17x22"]["offered"]


def test_a_widened_frame_is_judged_as_widened():
    def widen(cand, frame):                                   # the 2x rule doubled the frame
        cx, cy = (frame[0] + frame[2]) / 2, (frame[1] + frame[3]) / 2
        w, h = frame[2] - frame[0], frame[3] - frame[1]
        return (cx - w, cy - h, cx + w, cy + h)
    plan = _plan([_line(0, 0, 200, 5)], widen=widen)
    # exactly 30 % of the width is enough: on 46 x 17 in the route runs from 16.1 to
    # 29.9 in, on both panels (0-22 and 24-46)
    assert plan["two"]["width_share"] == 0.3 and plan["two"]["offered"]
    # on 70 x 17 in the same route runs from 24.5 to 45.5 in: all of it is on panel 2
    # (24-46), so the other rule refuses the set
    assert plan["three"]["width_share"] == 0.3 and not plan["three"]["offered"]
    assert plan["three"]["why"].endswith("holds no track")
    plan = _plan([_line(0, 0, 200, 5)], widen=lambda c, f: widen(c, widen(c, f)))
    for key in ("two", "three"):                             # 15 % of the width
        assert plan[key]["why"] == "the tracks span 15% of the sheet's width, under 30%"
