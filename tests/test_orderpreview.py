# tests/test_orderpreview.py
import json
import os
import stat
import tomllib

import numpy as np
import pytest

from app import orderprep as op
from app import orderpreview as opv
from app import order as od
from app import orderplate as opl
from app.orderplate import (CoverageError, PlateError, nestled_frame, order_epsg, project_bbox,
                            track_shares)
from tests.test_orderprep import (NO_LIDAR, SMALL, WIDE, _gpx, _make_order,  # noqa: F401
                                  _no_real_proof, tools)

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


def test_two_panels_with_no_track_are_named_in_the_plural():
    cand = [c for c in opv.candidates("three") if c.orientation == "landscape"][0]   # 70 x 17 in
    frame = (0.0, 0.0, 70 * KM, 17 * KM)                      # 1 km of ground for each inch
    middle = [_line(30, 8, 40, 8)]                            # all of it on panel 2 (24-46 in)
    entry = opv.judge(cand, frame, (30 * KM, 8 * KM, 40 * KM, 8 * KM), middle)
    assert not entry["offered"]
    # 14 % of the width would refuse it first; a route across 30 % that the frame
    # holds on one panel is the case of test_a_widened_frame_is_judged_as_widened
    wide = [_line(24.5, 8, 45.5, 8)]
    entry = opv.judge(cand, frame, (24.5 * KM, 8 * KM, 45.5 * KM, 8 * KM), wide)
    assert entry["why"] == "panels 1 and 3 hold no track"


def test_the_rule_follows_the_line_and_not_its_vertices():
    cand = [c for c in opv.candidates("three") if c.orientation == "landscape"][0]
    track = [_line(0, 0, 200, 5)]                             # two vertices, at the ends
    frame = nestled_frame(_bounds(track), cand.aspect)
    assert opv.panels_with_track(track, frame, cand) == [True, True, True]


def test_a_vertex_that_is_not_a_number_is_left_out_of_the_line():
    cand = [c for c in opv.candidates("three") if c.orientation == "landscape"][0]
    track = [np.array([[0.0, 0.0], [np.nan, np.nan], [200 * KM, 5 * KM]])]
    frame = nestled_frame((0.0, 0.0, 200 * KM, 5 * KM), cand.aspect)
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


def test_a_failed_coverage_query_is_not_a_refused_size():
    def widen(cand, frame):
        if cand.key == "three":
            raise CoverageError("The 3DEP coverage check failed:\nboom")
        return frame
    with pytest.raises(CoverageError, match="coverage check failed"):
        _plan([_line(0, 0, 200, 5)], widen=widen)


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
    assert plan["three"]["why"] == "panels 1 and 3 hold no track"
    plan = _plan([_line(0, 0, 200, 5)], widen=lambda c, f: widen(c, widen(c, f)))
    for key in ("two", "three"):                             # 15 % of the width
        assert plan[key]["why"] == "the tracks span 15% of the sheet's width, under 30%"


def _share_of_two(share):
    """The entry of the 46 x 17 in set for tracks that span `share` of its width."""
    cand = [c for c in opv.candidates("two") if c.orientation == "landscape"][0]
    frame = (0.0, 0.0, 46 * KM, 17 * KM)
    half = share * 46 / 2
    box = ((23 - half) * KM, 8 * KM, (23 + half) * KM, 8 * KM)
    return opv.judge(cand, frame, box, [_line(23 - half, 8, 23 + half, 8)])


def test_a_refusal_never_says_30_percent_is_under_30_percent():
    # the rule compares the share at three places, and the sentence printed none:
    # "the tracks span 30% of the sheet's width, under 30%"
    entry = _share_of_two(0.296)
    assert not entry["offered"] and entry["width_share"] == 0.296
    assert entry["why"] == "the tracks span 29.6% of the sheet's width, under 30%"
    assert _share_of_two(0.2994)["why"] == "the tracks span 29.9% of the sheet's width, under 30%"
    # 0.2996 is 0.300 at three places: the rule offers it, so there is no sentence
    at_the_line = _share_of_two(0.2996)
    assert at_the_line["offered"] and at_the_line["width_share"] == 0.3 and at_the_line["why"] == ""
    # away from the line a whole number is enough
    assert _share_of_two(0.2944)["why"] == "the tracks span 29% of the sheet's width, under 30%"
    assert _share_of_two(0.15)["why"] == "the tracks span 15% of the sheet's width, under 30%"
    for share in np.arange(0.2900, 0.2996, 0.0001):          # no share near the line contradicts itself
        why = _share_of_two(float(share))["why"]
        assert why and float(why.split("span ")[1].split("%")[0]) < 30.0, (share, why)


# ---- the coarse plate and the maps: Prepare's stub subprocesses, no network ----

def _fake_render(calls):
    def render(entries, tracks, plate_dir, title, out_dir):
        calls.append({"plate_dir": plate_dir, "title": title, "tracks": len(tracks),
                      "coords": [t.coords for t in tracks],
                      "keys": [e["key"] for e in entries if e["offered"]]})
        for e in entries:
            if e["offered"]:
                e["image"], e["dpi"] = os.path.join(out_dir, e["key"] + ".png"), opv.preview_dpi(e)
    return render


def _tree(folder):
    """Every file under `folder`, by its path. test_orderprep's _snapshot reads one
    flat folder, and work/plate/ holds the plate's own folder beside builds.log."""
    return {str(p.relative_to(folder)): p.read_bytes()
            for p in sorted(folder.rglob("*")) if p.is_file()}


def _preview(d, tools, calls=None, pdfs=None):
    calls = [] if calls is None else calls
    pdfs = [] if pdfs is None else pdfs
    return opv.preview(str(d), tools, log=lambda s: None, render=_fake_render(calls),
                       write_pdf=lambda path, entries, names, title: pdfs.append(path))


def test_the_dpi_of_a_preview_map():
    assert opv.preview_dpi({"panels": 1, "print_in": [17.0, 22.0]}) == pytest.approx(1600 / 22)
    assert opv.preview_dpi({"panels": 1, "print_in": [17.0, 11.0]}) == pytest.approx(1600 / 17)
    assert opv.preview_dpi({"panels": 3, "print_in": [70.0, 17.0]}) == 50.0


def test_the_preview_plate_holds_every_offered_frame():
    entries = [{"offered": True, "frame": [0, 0, 10, 10], "panels": 1, "print_in": [17.0, 22.0]},
               {"offered": True, "frame": [-5, 2, 30, 8], "panels": 3, "print_in": [70.0, 17.0]},
               {"offered": False, "frame": [-99, -99, 99, 99], "panels": 2, "print_in": [46.0, 17.0]}]
    assert opv.union_frame(entries) == (-5, 0, 30, 10)
    # the finest ground per pixel that any offered map needs
    assert opv.preview_need_m(entries) == pytest.approx(min(10 / 17 / (1600 / 22), 35 / 70 / 50.0))


def test_preview_builds_one_coarse_plate_beside_the_orders_own(tmp_path, tools):
    d = _make_order(tmp_path, bbox=WIDE, size="11x17")
    calls, pdfs = [], []
    state = _preview(d, tools, calls, pdfs)
    plate = state["plate"]
    assert plate["id"] == "preview_2026_10_001_smith" and plate["kind"] == "built"
    assert plate["root"] == str(d / "work" / "preview" / "plate")
    assert os.path.isfile(d / "work" / "preview" / "plate" / plate["id"] / "region.json")
    assert plate["grid_m"] >= 10.0                           # the preview's pixels, not a print's
    assert not (d / "work" / "plate").exists()               # the order's own plate is not built
    assert [e["key"] for e in state["sizes"]] == ["11x17", "17x22", "two", "three"]
    assert calls[0]["plate_dir"] == os.path.join(plate["root"], plate["id"])
    assert calls[0]["keys"] == [e["key"] for e in state["sizes"] if e["offered"]]
    assert calls[0]["tracks"] == 1 and calls[0]["title"] == "Smith home ground"
    saved = json.loads((d / "work" / "preview" / "preview.json").read_text())
    assert saved["epsg"] == state["epsg"] and saved["plate"] == plate
    assert len(saved["sizes"]) == 4 and saved["seconds"] >= 0
    assert pdfs == [str(d / "out" / "preview" / "smith_home_ground-preview.pdf")]


def test_a_preview_does_not_touch_a_prepared_order(tmp_path, tools):
    d = _make_order(tmp_path, bbox=WIDE, size="11x17")
    op.prepare(str(d), tools, log=lambda s: None)
    before = _tree(d / "work" / "plate")
    assert "builds.log" in before and "order_2026_10_001_smith/region.json" in before
    state_before = (d / "work" / "state.json").read_text()
    state = _preview(d, tools)
    assert state["plate"]["root"] == str(d / "work" / "preview" / "plate")
    assert _tree(d / "work" / "plate") == before
    assert (d / "work" / "state.json").read_text() == state_before
    lines = []
    op.prepare(str(d), tools, log=lines.append)
    assert any("Plate is current" in l for l in lines)


def test_a_preview_can_run_again(tmp_path, tools):
    d = _make_order(tmp_path, bbox=WIDE, size="11x17")
    first = _preview(d, tools)
    second = _preview(d, tools)
    assert second["plate"]["id"] == first["plate"]["id"]
    assert [e["frame"] for e in second["sizes"]] == [e["frame"] for e in first["sizes"]]


def test_a_folder_with_no_track_stops_the_preview(tmp_path, tools):
    d = _make_order(tmp_path, bbox=WIDE)
    (d / "in" / "trip.gpx").write_text("<gpx></gpx>")
    with pytest.raises(opv.OrderError, match="no track points"):
        _preview(d, tools)


# A query of the 3DEP index that fails only for a box wider than 1 degree: the
# single sheets of WIDE are 0.5 degrees across, and a set is wider.
STUB_COVERAGE_FAILS_WHEN_WIDE = """
import json, os, sys
w, s, e, n = map(float, sys.argv[1:5])
with open(os.environ["STUB_COVERAGE_LOG"], "a") as f:
    f.write("failed\\n" if e - w > 1.0 else "answered\\n")
if e - w > 1.0:
    sys.exit("the index did not answer")
print(json.dumps({"1": 1.0, "3": 0.0, "10": 1.0, "30": 1.0, "60": 0.0}))
"""


def test_a_failed_coverage_query_stops_the_whole_preview(tmp_path, tools, monkeypatch):
    # it must not read as "this size is refused": the client would lose a size to a
    # network fault and nobody would know
    bad = tmp_path / "stubs" / "wide_fails.py"
    bad.write_text(STUB_COVERAGE_FAILS_WHEN_WIDE)
    asked = tmp_path / "coverage_asks.txt"
    monkeypatch.setenv("STUB_COVERAGE_LOG", str(asked))
    tools = op.Tools(**{**tools.__dict__, "coverage_script": str(bad)})
    d = _make_order(tmp_path, bbox=WIDE, size="11x17")
    # the fit rule refuses both sets of this route, and a refused size is not queried:
    # the list asks for the set of two
    (d / "order.toml").write_text('title = "Smith home ground"\n'
                                  'sizes = ["11x17", "17x22", "two"]\n')
    calls, pdfs = [], []
    with pytest.raises(CoverageError, match=r"(?s)coverage check failed.*the index did not answer"):
        _preview(d, tools, calls, pdfs)
    # the single sheets were answered; the fault came at a later size
    assert asked.read_text().split() == ["answered", "answered", "failed"]
    assert calls == [] and pdfs == []
    assert not (d / "work" / "preview" / "preview.json").exists()


def test_a_coverage_query_with_no_result_stops_the_preview(tmp_path, tools):
    bad = tmp_path / "stubs" / "silent.py"
    bad.write_text("print('not json')\n")
    tools = op.Tools(**{**tools.__dict__, "coverage_script": str(bad)})
    d = _make_order(tmp_path, bbox=WIDE, size="11x17")
    with pytest.raises(CoverageError, match="printed no result"):
        _preview(d, tools)
    assert not (d / "work" / "preview" / "preview.json").exists()


def test_terrain_too_coarse_for_one_size_still_gives_a_preview(tmp_path, tools, monkeypatch):
    real = op._plan_grid

    def plan(tools, frame, epsg, print_w_in, env):
        if print_w_in > 60:                                  # the three-panel set only
            raise PlateError("The terrain data is still too coarse for this print size "
                             "after 5 widenings.")
        return real(tools, frame, epsg, print_w_in, env)
    monkeypatch.setattr(op, "_plan_grid", plan)
    d = _make_order(tmp_path, bbox=(-117.9, 35.80, -115.7, 35.86), size="11x17")
    (d / "order.toml").write_text('title = "Smith home ground"\nsizes = ["17x22", "three"]\n')
    state = _preview(d, tools)
    by_key = {e["key"]: e for e in state["sizes"]}
    assert by_key["three"]["blocked"] and not by_key["three"]["offered"]
    assert by_key["three"]["why"].startswith("The terrain data is still too coarse")
    assert by_key["17x22"]["offered"]
    assert (d / "work" / "preview" / "preview.json").exists()


def test_the_preview_keeps_its_own_build_log(tmp_path, tools):
    d = _make_order(tmp_path, bbox=WIDE, size="11x17")
    op.prepare(str(d), tools, log=lambda s: None)
    before = (d / "work" / "build.log").read_bytes()
    assert before
    state = _preview(d, tools)
    assert state["plate"]["kind"] == "built"
    assert (d / "work" / "build.log").read_bytes() == before
    assert b"cache=" in (d / "work" / "preview" / "build.log").read_bytes()


# ---- every size is framed in the projection Prepare gives it ----

SIERRA = (-118.75, 36.6, -118.70, 37.5)                # 100 km north to south, 4 km wide
SIERRA_DIAGONAL = (-119.5, 36.5, -118.4612, 37.5649)   # 93 km east, 118 km north
# 280 km east and 150 km north in UTM zone 14: every single sheet and the set of two
# stay in UTM, and the set of three frames 640 km wide, so Prepare gives it Albers
PLAINS = (-102.0, 39.5, -98.7, 40.85)


def _order_plan(bbox):
    ground = opv.OrderGround([(_gpx(*bbox).encode(), "trip.gpx")], bbox)
    return {e["key"]: e for e in opv.plan_sizes(ground=ground)}


def _as_prepare_frames(bbox, entry):
    """(projection, track box, frame) of the order that asks for this entry's size,
    orientation and gap, by the lines of orderprep.prepare."""
    size, panels = od.parse_order_size(entry["key"])
    order = od.Order(dir="x", title="t", subtitle="", size=size, notes="", panels=panels,
                     orientation=entry["orientation"], gap=entry["gap"])
    pw, ph = order.print_in()
    assert [pw, ph] == entry["print_in"]
    epsg = order_epsg(bbox, pw / ph)
    box = project_bbox(bbox, epsg)
    return epsg, box, nestled_frame(box, pw / ph)


@pytest.mark.parametrize("bbox", [SIERRA, SIERRA_DIAGONAL, PLAINS])
def test_every_size_is_framed_as_prepare_frames_it(bbox):
    plan = _order_plan(bbox)
    assert list(plan) == list(opv.SIZE_KEYS)
    for entry in plan.values():
        epsg, box, frame = _as_prepare_frames(bbox, entry)
        assert entry["epsg"] == epsg
        assert entry["frame"] == pytest.approx(list(frame), abs=1e-6)
        shares = track_shares(box, frame)
        assert entry["width_share"] == round(shares[0], 3)
        assert entry["fill"] == round(max(shares), 3)


def test_one_albers_candidate_does_not_move_the_other_sizes():
    # the 70 x 17 in landscape sheet of this route frames 680 km wide, so Prepare gives
    # it Albers. One projection for all eight candidates gave every size Albers, and
    # the map of a single sheet was 12.6 degrees off its print.
    assert order_epsg(SIERRA, 70 / 17) == 5070 and order_epsg(SIERRA, 17 / 22) == 32611
    plan = _order_plan(SIERRA)
    assert [(e["epsg"], e["orientation"]) for e in plan.values()] == [
        (32611, "portrait"), (32611, "portrait"), (32611, "portrait"), (5070, "landscape")]
    assert plan["11x17"]["offered"] and plan["17x22"]["offered"]
    assert not plan["two"]["offered"] and not plan["three"]["offered"]
    assert opv.plate_groups(plan.values()) == {32611: [plan["11x17"], plan["17x22"]]}


def test_a_set_is_judged_at_the_share_prepare_frames():
    # in Albers this route spans 31.3 % of the two-panel sheet, and the set was offered;
    # Prepare frames it in UTM zone 11 at 29.0 %
    two = _order_plan(SIERRA_DIAGONAL)["two"]
    epsg, box, frame = _as_prepare_frames(SIERRA_DIAGONAL, two)
    assert (two["epsg"], two["orientation"]) == (32611, "portrait")
    assert two["width_share"] == round(track_shares(box, frame)[0], 3) == 0.29
    assert not two["offered"]
    assert two["why"] == "the tracks span 29% of the sheet's width, under 30%"


def _prepare_from_the_report(d, tools, offered) -> dict:
    """Paste the report's lines for each offered size into order.toml, run Prepare,
    and hold its state.json to the preview's entry: the projection, the sheet, the
    frame and the fill. Returns {size key: Prepare's state}."""
    pasted = _toml_lines((d / "work" / "preview" / "report.txt").read_text())
    assert list(pasted) == list(offered)
    states = {}
    for key, e in offered.items():
        (d / "order.toml").write_text('title = "Smith home ground"\n' + pasted[key])
        state = op.prepare(str(d), tools, log=lambda s: None)
        assert state == json.loads((d / "work" / "state.json").read_text())
        assert state["epsg"] == e["epsg"] and state["print_in"] == e["print_in"], key
        assert (state["panels"], state["gap"]) == (e["panels"], e["gap"])
        assert state["frame"] == pytest.approx(e["frame"], abs=1e-6), key
        assert state["fill"] == e["fill"]
        states[key] = state
    return states


def test_the_lines_of_the_report_give_prepare_the_frame_of_the_preview(tmp_path, tools):
    d = _make_order(tmp_path, bbox=SIERRA_DIAGONAL, size="11x17")
    (d / "order.toml").write_text('title = "Smith home ground"\nsizes = ["17x22", "two"]\n')
    offered = {e["key"]: e for e in _preview(d, tools)["sizes"] if e["offered"]}
    assert list(offered) == ["17x22", "two"]
    states = _prepare_from_the_report(d, tools, offered)
    assert {s["plate"]["kind"] for s in states.values()} == {"built"}


# ---- a route on a curated plate: Prepare reuses the plate, in the plate's projection ----

# 54 km east to west in UTM zone 12, as the east part of regions/elko_bonneville is: a
# curated plate in zone 11 (EPSG:32611) over zone 12 ground
ZONE_12 = (-113.6, 36.50, -113.0, 36.53)
OVER_ZONE_12 = (-115.5, 35.5, -111.5, 37.5)            # the ground of the curated plate


def _plate_over_zone_12(tmp_path, grid_m):
    _curated_plate(tmp_path, project_bbox(OVER_ZONE_12, 32611), crs="EPSG:32611", grid_m=grid_m)


def test_a_candidate_that_fits_a_curated_plate_is_on_that_plates_ground(tmp_path, tools):
    assert order_epsg(ZONE_12, 70 / 17) == order_epsg(ZONE_12, 17 / 11) == 32612
    _plate_over_zone_12(tmp_path, grid_m=2.0)
    regions = op.curated_regions(tools.curated_root)
    assert [r["id"] for r in regions] == ["big"]
    payloads = [(_gpx(*ZONE_12).encode(), "trip.gpx")]
    ground = opv.OrderGround(payloads, ZONE_12, regions)
    for key in opv.SIZE_KEYS:
        for cand in opv.candidates(key):
            fit = opl.curated_fit(ZONE_12, cand.aspect, cand.print_in[0], regions)
            here = ground(cand)
            assert (here.epsg, here.curated) == (32611, regions[0]) == (fit["epsg"], fit["region"])
            assert here.bounds_m == project_bbox(ZONE_12, 32611)
            assert nestled_frame(here.bounds_m, cand.aspect) == fit["frame"]
    plan = opv.plan_sizes(ground=ground, widen=lambda cand, frame: 1 / 0)   # no widening is asked
    assert [(e["epsg"], e["curated"], e["offered"]) for e in plan] == [(32611, "big", True)] * 4
    # with no curated plate, the same route is on its own zone, and the entry says so
    alone = opv.plan_sizes(ground=opv.OrderGround(payloads, ZONE_12))
    assert [(e["epsg"], e["curated"]) for e in alone] == [(32612, None)] * 4
    assert [e["curated"] for e in opv.plan_sizes(_bounds([_line(0, 0, 200, 5)]),
                                                 [_line(0, 0, 200, 5)])] == [None] * 4


def test_a_route_on_a_curated_plate_is_previewed_as_prepare_prints_it(tmp_path, tools,
                                                                    monkeypatch):
    # Prepare first asks curated_fit, and a fit gives the plate's projection and its
    # nestled frame with no widening. The preview used the route's own zone: zone 12
    # here, a degree or two off the print on a plate in zone 11.
    _plate_over_zone_12(tmp_path, grid_m=2.0)
    asked = tmp_path / "coverage_asks.jsonl"
    monkeypatch.setenv("STUB_COVERAGE_LOG", str(asked))
    monkeypatch.setenv("STUB_COVERAGE", json.dumps(NO_LIDAR))  # a built plate would widen
    d = _make_order(tmp_path, bbox=ZONE_12, size="11x17")
    calls, lines = [], []
    state = opv.preview(str(d), tools, log=lines.append, render=_fake_render(calls),
                        write_pdf=lambda path, entries, names, title: None)
    offered = {e["key"]: e for e in state["sizes"] if e["offered"]}
    assert list(offered) == list(opv.SIZE_KEYS)
    regions = op.curated_regions(tools.curated_root)
    for e in offered.values():
        assert (e["epsg"], e["curated"], e["plate"]) == (32611, "big", "big")
        fit = opl.curated_fit(ZONE_12, e["print_in"][0] / e["print_in"][1], e["print_in"][0],
                              regions)
        assert e["frame"] == list(fit["frame"]) and e["fill"] == 0.6     # nestled, not widened
    assert _asks(asked) == []                                # no query of the 3DEP index
    assert state["epsg"] == 32611 and state["plates"] == [state["plate"]] == [
        {"id": "big", "root": tools.curated_root, "kind": "curated", "grid_m": 2.0,
         "epsg": 32611, "sizes": list(opv.SIZE_KEYS)}]
    assert not (d / "work" / "preview" / "plate").exists()   # and no build
    assert "Reusing curated plate big for 11x17, 17x22, two, three, as Prepare does." in lines
    # the maps are drawn on that plate, with the tracks in the plate's projection
    assert [(c["plate_dir"], c["keys"]) for c in calls] == [
        (os.path.join(tools.curated_root, "big"), list(opv.SIZE_KEYS))]
    want = opv.load_tracks_m(opv.load(str(d)).payloads(), 32611)
    assert np.array_equal(calls[0]["coords"][0], want[0].coords)
    report = (d / "work" / "preview" / "report.txt").read_text()
    assert report.splitlines()[2:4] == ["Plate: big (curated), 2 m grid", "Sizes:"]
    # the report's lines give Prepare the same projection and the same frame
    states = _prepare_from_the_report(d, tools, offered)
    for st in states.values():
        assert (st["plate"]["id"], st["plate"]["kind"]) == ("big", "curated")
    assert _asks(asked) == []


def test_a_size_too_wide_for_the_curated_plate_takes_the_built_path(tmp_path, tools,
                                                                   monkeypatch):
    # at 10 m the plate holds the single sheets (17 in needs 17.6 m, 22 in 13.6 m) and
    # not a set (46 in needs 6.5 m, 70 in 4.3 m): Prepare builds a plate for a set, in
    # the route's own zone
    _plate_over_zone_12(tmp_path, grid_m=10.0)
    asked = tmp_path / "coverage_asks.jsonl"
    monkeypatch.setenv("STUB_COVERAGE_LOG", str(asked))
    d = _make_order(tmp_path, bbox=ZONE_12, size="11x17")
    calls = []
    state = _preview(d, tools, calls)
    offered = {e["key"]: e for e in state["sizes"] if e["offered"]}
    assert list(offered) == list(opv.SIZE_KEYS)
    assert [(e["epsg"], e["curated"]) for e in offered.values()] == [
        (32611, "big"), (32611, "big"), (32612, None), (32612, None)]
    # the two sets are asked of the 3DEP index, and so is their plate: the sheets are not
    assert len(_asks(asked)) == 3
    curated, built = state["plates"]
    assert state["plate"] == curated and state["epsg"] == 32611
    assert curated == {"id": "big", "root": tools.curated_root, "kind": "curated",
                       "grid_m": 10.0, "epsg": 32611, "sizes": ["11x17", "17x22"]}
    assert (built["id"], built["kind"], built["epsg"], built["sizes"]) == (
        "preview_2026_10_001_smith_32612", "built", 32612, ["two", "three"])
    root = d / "work" / "preview" / "plate"
    assert json.loads((root / built["id"] / "region.json").read_text())["crs"] == "EPSG:32612"
    assert [offered[k]["plate"] for k in opv.SIZE_KEYS] == ["big", "big", built["id"], built["id"]]
    payloads = opv.load(str(d)).payloads()
    assert [(c["plate_dir"], c["keys"]) for c in calls] == [
        (os.path.join(tools.curated_root, "big"), ["11x17", "17x22"]),
        (os.path.join(str(root), built["id"]), ["two", "three"])]
    for call, epsg in zip(calls, (32611, 32612)):
        assert np.array_equal(call["coords"][0], opv.load_tracks_m(payloads, epsg)[0].coords)
    report = (d / "work" / "preview" / "report.txt").read_text()
    assert report.splitlines()[2:5] == [
        "Plate: big (curated), 10 m grid, EPSG:32611, for 11x17, 17x22",
        f"Plate: {built['id']} (built), {built['grid_m']:g} m grid, EPSG:32612, for two, three",
        "Sizes:"]
    asked.unlink()
    states = _prepare_from_the_report(d, tools, offered)
    assert [states[k]["plate"]["kind"] for k in opv.SIZE_KEYS] == ["curated", "curated",
                                                                  "built", "built"]
    assert len(_asks(asked)) == 2                            # Prepare asks for the two sets only


def test_a_curated_plate_that_shows_every_size_is_one_plate_in_the_report(tmp_path, tools,
                                                                         monkeypatch):
    # a route in the plate's own zone: the sheets fit the plate as prints, and the sets
    # do not, but the plate holds the sets' frames at the preview's pixels. One plate
    # draws all four sizes, and it is listed once.
    route = (-117.6, 36.50, -117.0, 36.53)
    assert order_epsg(route, 70 / 17) == 32611
    _curated_plate(tmp_path, project_bbox((-119.0, 35.5, -115.5, 37.5), 32611), grid_m=10.0)
    asked = tmp_path / "coverage_asks.jsonl"
    monkeypatch.setenv("STUB_COVERAGE_LOG", str(asked))
    d = _make_order(tmp_path, bbox=route, size="11x17")
    calls = []
    state = _preview(d, tools, calls)
    offered = {e["key"]: e for e in state["sizes"] if e["offered"]}
    assert [(e["epsg"], e["curated"]) for e in offered.values()] == [
        (32611, "big"), (32611, "big"), (32611, None), (32611, None)]
    assert len(_asks(asked)) == 2                            # the 2x rule of the two sets
    assert state["plates"] == [{"id": "big", "root": tools.curated_root, "kind": "curated",
                                "grid_m": 10.0, "epsg": 32611, "sizes": list(opv.SIZE_KEYS)}]
    assert [c["keys"] for c in calls] == [list(opv.SIZE_KEYS)]
    assert (d / "work" / "preview" / "report.txt").read_text().count("Plate: ") == 1
    states = _prepare_from_the_report(d, tools, offered)
    assert [states[k]["plate"]["kind"] for k in opv.SIZE_KEYS] == ["curated", "curated",
                                                                  "built", "built"]


def test_a_set_the_curated_plate_cannot_hold_gets_a_built_plate_in_the_same_zone(
        tmp_path, tools, monkeypatch):
    # the route and the curated plate are both in zone 11. The plate holds the single
    # sheets and ends 1 km past them. With 10 m data the 2x rule widens the set of
    # three past the plate, so the sets get a built plate: one projection, two plates.
    route = (-117.6, 36.50, -117.0, 36.53)
    tallest = nestled_frame(project_bbox(route, 32611), 11 / 17)
    hold = opl.plate_bounds(tallest)
    _curated_plate(tmp_path, (hold[0] - KM, hold[1] - KM, hold[2] + KM, hold[3] + KM), grid_m=10.0)
    monkeypatch.setenv("STUB_COVERAGE", json.dumps(NO_LIDAR))
    d = _make_order(tmp_path, bbox=route, size="11x17")
    calls = []
    state = _preview(d, tools, calls)
    offered = {e["key"]: e for e in state["sizes"] if e["offered"]}
    assert [(e["key"], e["epsg"], e["curated"]) for e in offered.values()] == [
        ("11x17", 32611, "big"), ("17x22", 32611, "big"), ("two", 32611, None),
        ("three", 32611, None)]
    three, small = offered["three"]["frame"], offered["11x17"]["frame"]
    assert three[2] - three[0] > (small[2] - small[0]) * 1.1          # widened, and the sheet is not
    assert offered["11x17"]["fill"] == 0.6 > offered["three"]["fill"]
    assert [(p["id"], p["kind"], p["epsg"], p["sizes"]) for p in state["plates"]] == [
        ("big", "curated", 32611, ["11x17", "17x22"]),
        ("preview_2026_10_001_smith_32611", "built", 32611, ["two", "three"])]
    assert [c["keys"] for c in calls] == [["11x17", "17x22"], ["two", "three"]]
    _prepare_from_the_report(d, tools, offered)


def test_a_size_is_drawn_on_the_curated_plate_prepare_reuses_for_it(tmp_path, tools):
    # two curated plates hold the frame. The first is fine enough for the preview's
    # pixels and too coarse for the print: Prepare reuses the second, and so the map
    # of the preview is drawn on the second.
    bounds = project_bbox(OVER_ZONE_12, 32611)
    _curated_plate(tmp_path, bounds, grid_m=8.0, rid="a_coarse")
    _curated_plate(tmp_path, bounds, grid_m=2.0, rid="b_fine")
    assert [r["id"] for r in op.curated_regions(tools.curated_root)] == ["a_coarse", "b_fine"]
    d = _make_order(tmp_path, bbox=ZONE_12, size="11x17")
    (d / "order.toml").write_text('title = "Smith home ground"\nsizes = ["three"]\n')
    calls = []
    state = _preview(d, tools, calls)
    three = state["sizes"][3]
    assert three["offered"] and (three["curated"], three["plate"]) == ("b_fine", "b_fine")
    assert [p["id"] for p in state["plates"]] == ["b_fine"]
    assert calls[0]["plate_dir"] == os.path.join(tools.curated_root, "b_fine")
    states = _prepare_from_the_report(d, tools, {"three": three})
    assert states["three"]["plate"]["id"] == "b_fine"


def test_a_preview_on_curated_plates_only_needs_no_prep_venv(tmp_path, tools):
    # as Prepare: reusing a curated plate runs no subprocess
    _plate_over_zone_12(tmp_path, grid_m=2.0)
    tools = op.Tools(**{**tools.__dict__,
                        "prep_python": str(tmp_path / "no-venv" / "bin" / "python")})
    d = _make_order(tmp_path, bbox=ZONE_12, size="11x17")
    state = _preview(d, tools)
    assert [e["curated"] for e in state["sizes"]] == ["big"] * 4
    # one size on the built path needs the venv, and the preview says so before any work
    (tmp_path / "curated" / "big" / "region.json").write_text(json.dumps({
        **json.loads((tmp_path / "curated" / "big" / "region.json").read_text()),
        "native_resolution_m": 10.0}))
    with pytest.raises(PlateError, match="The prep venv is missing: .*no-venv"):
        _preview(d, tools)


def test_a_set_that_needs_albers_gets_a_plate_of_its_own(tmp_path, tools):
    d = _make_order(tmp_path, bbox=PLAINS, size="11x17")
    calls = []
    state = _preview(d, tools, calls)
    by_key = {e["key"]: e for e in state["sizes"]}
    assert [e["epsg"] for e in state["sizes"]] == [32614, 32614, 32614, 5070]
    assert all(e["offered"] for e in state["sizes"])
    utm, albers = state["plates"]
    assert state["plate"] == utm and state["epsg"] == 32614
    assert (utm["id"], utm["epsg"], utm["sizes"]) == (
        "preview_2026_10_001_smith", 32614, ["11x17", "17x22", "two"])
    assert (albers["id"], albers["epsg"], albers["sizes"]) == (
        "preview_2026_10_001_smith_5070", 5070, ["three"])
    assert [by_key[k]["plate"] for k in opv.SIZE_KEYS] == [utm["id"]] * 3 + [albers["id"]]
    root = d / "work" / "preview" / "plate"
    assert (root / "builds.log").read_text().split() == [utm["id"], albers["id"]]
    for plate in (utm, albers):
        assert plate["root"] == str(root) and plate["kind"] == "built"
        built = json.loads((root / plate["id"] / "region.json").read_text())
        assert built["crs"] == f"EPSG:{plate['epsg']}"
        # the plate holds the frames of its own sizes, and no frame of the other projection
        frames = opv.union_frame([by_key[k] for k in plate["sizes"]])
        assert built["bbox"] == pytest.approx(list(opl.to_lonlat_bbox(
            opl.plate_bounds(frames), plate["epsg"], pad_m=opl.PLATE_PAD_M)))
    # each build keeps its own log
    assert b"cache=" in (d / "work" / "preview" / "build.log").read_bytes()
    assert b"cache=" in (d / "work" / "preview" / "build_5070.log").read_bytes()
    # each map is drawn on its own plate, with the tracks in that plate's projection
    assert [c["keys"] for c in calls] == [["11x17", "17x22", "two"], ["three"]]
    payloads = opv.load(str(d)).payloads()
    for call, plate in zip(calls, (utm, albers)):
        assert call["plate_dir"] == os.path.join(plate["root"], plate["id"])
        want = opv.load_tracks_m(payloads, plate["epsg"])
        assert len(call["coords"]) == len(want) == 1
        assert np.array_equal(call["coords"][0], want[0].coords)
    assert calls[0]["coords"][0][0, 0] > 0 > calls[1]["coords"][0][0, 0]   # UTM east, Albers west
    saved = json.loads((d / "work" / "preview" / "preview.json").read_text())
    assert saved["plates"] == [utm, albers] and saved["plate"] == utm
    report = (d / "work" / "preview" / "report.txt").read_text()
    assert report.splitlines()[2:5] == [
        "Plate: preview_2026_10_001_smith (built), 260 m grid, EPSG:32614, for 11x17, 17x22, two",
        "Plate: preview_2026_10_001_smith_5070 (built), 240 m grid, EPSG:5070, for three",
        "Sizes:"]


def test_the_rules_and_the_painter_get_the_tracks_of_the_entrys_projection(
        tmp_path, tools, monkeypatch):
    real_load, real_judge, real_plan = opv.load_tracks_m, opv.judge, op._plan_grid
    loaded, judged, widened = {}, [], []

    def load(payloads, epsg):
        loaded[epsg] = real_load(payloads, epsg)
        return loaded[epsg]

    def judge(cand, frame, bounds_m, tracks_m):
        judged.append((cand.key, bounds_m, tracks_m))
        return real_judge(cand, frame, bounds_m, tracks_m)

    def plan(tools, frame, epsg, print_w_in, env):
        widened.append((epsg, print_w_in))
        return real_plan(tools, frame, epsg, print_w_in, env)
    monkeypatch.setattr(opv, "load_tracks_m", load)
    monkeypatch.setattr(opv, "judge", judge)
    monkeypatch.setattr(op, "_plan_grid", plan)
    d = _make_order(tmp_path, bbox=PLAINS, size="11x17")
    calls = []
    state = _preview(d, tools, calls)
    by_key = {e["key"]: e for e in state["sizes"]}
    assert sorted(loaded) == [5070, 32614]                   # no other projection is read
    assert {key for key, _, _ in judged} == set(opv.SIZE_KEYS)
    for key, bounds_m, tracks_m in judged:                   # the fit rule
        epsg = by_key[key]["epsg"]
        assert bounds_m == project_bbox(PLAINS, epsg)
        assert len(tracks_m) == 1 and np.array_equal(tracks_m[0], loaded[epsg][0].coords)
    # the 2x rule: each size in its own projection, by the width of its sheet
    assert widened == [(e["epsg"], e["print_in"][0]) for e in state["sizes"]]
    for call in calls:                                       # the painter
        epsg = by_key[call["keys"][0]]["epsg"]
        assert np.array_equal(call["coords"][0], loaded[epsg][0].coords)


# ---- the PDF's place, the report and the command ----

def test_every_entry_of_preview_json_says_why(tmp_path, tools):
    d = _make_order(tmp_path, bbox=WIDE, size="11x17")
    state = _preview(d, tools)
    saved = json.loads((d / "work" / "preview" / "preview.json").read_text())
    assert saved["sizes"] == state["sizes"] and saved["pdf"] == state["pdf"]
    # the names and prices the PDF was written with, as config/sizes.toml gave them
    assert saved["names"] == state["names"] == opv.sizes.load()
    assert saved["names"]["11x17"] == {"name": "11 × 17 in", "price": "$69"}
    for e in saved["sizes"]:
        assert {"ends_behind", "warning", "why", "blocked", "offered", "fill"} <= set(e)
        assert isinstance(e["ends_behind"], list) and isinstance(e["blocked"], bool)
        assert bool(e["why"]) == (not e["offered"])          # a refusal always has its reason


def test_the_real_pdf_writer_is_the_default(tmp_path, tools, monkeypatch):
    d = _make_order(tmp_path, bbox=WIDE, size="11x17")
    seen = []
    monkeypatch.setattr(opv.previewpdf, "write",
                        lambda path, entries, names, title: seen.append((path, names, title)))
    state = opv.preview(str(d), tools, log=lambda s: None, render=_fake_render([]))
    assert seen == [(state["pdf"], opv.sizes.load(), "Smith home ground")]


SIZES_TOML = "".join(f'[[size]]\nkey = "{k}"\nname = "{k}"\n' for k in od.SIZE_KEYS)


@pytest.mark.parametrize("body,words", [
    (b'[[size]]\nkey = "11x17"\nname = "Small"\n', "has no row for 17x22, two, three"),
    (SIZES_TOML.encode() + b"price = 69\n", 'size "three": price must be text in quotes, not 69'),
    (SIZES_TOML.encode() + b'prise = "$69"\n', 'size "three" has an unknown field prise'),
    (SIZES_TOML.replace('"11x17"\nname = "11x17"', '"11x17"\nname = "11 × 17 in"').encode("latin-1"),
     "cannot be read: it is not UTF-8 text"),
    (SIZES_TOML.replace('name = "two"', f'name = "{"n" * 500}"').encode(),
     'size "two": name has 500 characters, and the page holds at most 40'),
], ids=["a missing row", "a price that is a number", "an unknown field", "Latin-1", "a long name"])
def test_a_wrong_sizes_file_stops_the_preview_before_any_query_or_build(
        tmp_path, tools, monkeypatch, capsys, body, words):
    # the plate takes minutes to build: the names and prices are read first
    from scripts import order as order_cli
    bad = tmp_path / "sizes.toml"
    bad.write_bytes(body)
    monkeypatch.setattr(opv.sizes, "default_path", lambda: str(bad))
    asked = tmp_path / "coverage_asks.jsonl"
    monkeypatch.setenv("STUB_COVERAGE_LOG", str(asked))
    d = _make_order(tmp_path, bbox=WIDE, size="11x17")
    calls, pdfs = [], []
    with pytest.raises(opv.OrderError, match=words):
        _preview(d, tools, calls, pdfs)
    # the command stops with a sentence, never a traceback
    assert order_cli.main(["preview", str(d)], tools=tools) == 1
    assert "preview stopped: config/sizes.toml" in capsys.readouterr().err
    assert _asks(asked) == []                                # no query of the 3DEP index
    assert calls == [] and pdfs == []
    assert not (d / "work").exists() and not (d / "out").exists()      # and no build
    bad.write_text(SIZES_TOML)                               # the same order, a good file
    _preview(d, tools, calls, pdfs)
    assert len(_asks(asked)) >= 2 and len(pdfs) == 1         # the count sees a real preview


def test_the_report_lists_each_size_and_the_lines_for_order_toml(tmp_path, tools):
    d = _make_order(tmp_path, bbox=WIDE, size="11x17")
    state = _preview(d, tools)
    report = (d / "work" / "preview" / "report.txt").read_text()
    assert report.startswith("Order: Smith home ground\n")
    assert f"Preview: {state['pdf']}" in report
    assert "Plate: preview_2026_10_001_smith (built)," in report
    small = [e for e in state["sizes"] if e["key"] == "11x17"][0]
    assert (f'- 11 × 17 in, {small["orientation"]}, 11 x 17 in: offered' in report
            or f'- 11 × 17 in, {small["orientation"]}, 17 x 11 in: offered' in report)
    assert (f'tracks fill {small["fill"]:.0%}. In order.toml:\n    size = "11x17"\n'
            f'    orientation = "{small["orientation"]}"\n- 17 × 22 in') in report
    # each offered size with the price the PDF prints, so the PDF need not be opened
    assert f': offered, price "$69", tracks fill {small["fill"]:.0%}. In order.toml:' in report
    assert report.count('offered, price "$99", tracks fill') == 1
    offered = [e for e in state["sizes"] if e["offered"]]
    assert report.count(', price "') == len(offered)         # a refused size has no price
    assert "- Three panels" in report and "not offered" in report
    assert report.rstrip().splitlines()[-1].startswith("Time: ")


def _state(**entry):
    base = {"key": "three", "panels": 3, "orientation": "landscape", "print_in": [70.0, 17.0],
            "gap": 2.0, "fill": 0.6, "offered": True, "why": "", "warning": "",
            "blocked": False, "ends_behind": []}
    return {"pdf": "/x/out/preview/t-preview.pdf", "seconds": 12.5,
            "plate": {"id": "preview_x", "kind": "built", "grid_m": 30.0},
            "sizes": [{**base, **entry}]}


def test_the_report_gives_a_set_its_gap_and_its_warnings(tmp_path, tools):
    order = opv.load(str(_make_order(tmp_path, bbox=WIDE)))
    names = opv.sizes.load()
    text = opv.write_preview_report(order, _state(
        warning="the tracks span 24% of the sheet's width, under 30%", ends_behind=[1, 2]), names)
    assert text.splitlines() == [
        "Order: Smith home ground",
        "Preview: /x/out/preview/t-preview.pdf",
        "Plate: preview_x (built), 30 m grid",
        "Sizes:",
        '- Three panels, landscape, 70 x 17 in: offered, price "$189", '
        "tracks fill 60%. In order.toml:",
        '    size = "three"',
        '    orientation = "landscape"',
        "    gap = 2",
        "  Warning: the tracks span 24% of the sheet's width, under 30%.",
        "  Warning: a route end is behind gap 1.",
        "  Warning: a route end is behind gap 2.",
        "Time: 12.5 s"]
    assert (tmp_path / "orders" / "2026-10-001-smith" / "work" / "preview"
            / "report.txt").read_text() == text


def test_the_report_gives_a_refusal_one_line_and_one_full_stop(tmp_path, tools):
    order = opv.load(str(_make_order(tmp_path, bbox=WIDE)))
    text = opv.write_preview_report(order, _state(
        offered=False, blocked=True,
        why="The terrain data is still too coarse for this print size\nafter 5 widenings."),
        opv.sizes.load())
    assert ("- Three panels, landscape, 70 x 17 in: not offered, The terrain data is still too "
            "coarse for this print size after 5 widenings.\n") in text
    assert "order.toml" not in text


def test_the_command_prints_the_preview_report(tmp_path, tools, capsys, monkeypatch):
    from scripts import order as order_cli
    d = _make_order(tmp_path, bbox=WIDE, size="11x17")
    monkeypatch.setattr(opv, "render_maps", _fake_render([]))
    monkeypatch.setattr(opv.previewpdf, "write", lambda path, entries, names, title: 1)
    assert order_cli.main(["preview", str(d)], tools=tools) == 0
    out = capsys.readouterr().out
    assert "Order: Smith home ground" in out and "Sizes:" in out
    assert out.endswith((d / "work" / "preview" / "report.txt").read_text())
    assert 'In order.toml:\n    size = "11x17"\n' in out and "not offered" in out


def test_each_command_names_itself_when_it_stops(tmp_path, tools, capsys):
    from scripts import order as order_cli
    d = _make_order(tmp_path, bbox=WIDE)
    (d / "order.toml").write_text('size = "11x17"\n')          # no title
    assert order_cli.main(["preview", str(d)], tools=tools) == 1
    assert "preview stopped: order.toml needs a title" in capsys.readouterr().err
    assert order_cli.main(["prepare", str(d)], tools=tools) == 1
    assert "prepare stopped: order.toml needs a title" in capsys.readouterr().err


def test_a_title_the_map_cannot_hold_stops_the_preview_before_any_query(
        tmp_path, tools, capsys, monkeypatch):
    # the painter refuses a title past the spec's limit; found there, it cost the plate
    from scripts import order as order_cli
    from app.spec import TITLE_MAX_CHARS
    asked = tmp_path / "coverage_asks.jsonl"
    monkeypatch.setenv("STUB_COVERAGE_LOG", str(asked))
    d = _make_order(tmp_path, bbox=WIDE, size="11x17", title="x" * (TITLE_MAX_CHARS + 1))
    with pytest.raises(opv.OrderError, match="the title in order.toml has 201 characters, "
                                             "and a map holds at most 200"):
        _preview(d, tools)
    assert order_cli.main(["preview", str(d)], tools=tools) == 1
    assert "preview stopped: the title in order.toml has 201" in capsys.readouterr().err
    assert not asked.exists() and not (d / "work").exists() and not (d / "out").exists()
    _make_order(tmp_path, bbox=WIDE, size="11x17", title="x" * TITLE_MAX_CHARS)
    assert _preview(d, tools)["sizes"]                       # the limit itself is a title


def test_a_failed_coverage_query_stops_the_command(tmp_path, tools, capsys):
    from scripts import order as order_cli
    bad = tmp_path / "stubs" / "bad_coverage.py"
    bad.write_text('import sys\nsys.exit("boom")\n')
    tools = op.Tools(**{**tools.__dict__, "coverage_script": str(bad)})
    d = _make_order(tmp_path, bbox=WIDE, size="11x17")
    assert order_cli.main(["preview", str(d)], tools=tools) == 1
    assert "preview stopped: The 3DEP coverage check failed" in capsys.readouterr().err


# ---- a size the painter refuses ----

EAST_WEST = (-117.9, 35.80, -115.7, 35.86)             # 200 km by 7 km: every size is offered
OFF_DEM = ("The selected frame extends past the available elevation data "
           "(31% of it has no DEM coverage). Pan or shrink the crop to keep it inside the region.")


def _painter(monkeypatch, refuses):
    """The real render_maps over a stand-in for the engine's painter, which refuses
    the sheets `refuses(spec)` names as it refuses a frame with too much no-data."""
    from PIL import Image

    from app import render
    from app.spec import OffDemError

    def rasterize(spec, dpi, **kw):
        if refuses(spec):
            raise OffDemError(OFF_DEM)
        return Image.new("RGB", spec.pixel_size(dpi), "white")
    monkeypatch.setattr(render, "rasterize", rasterize)


def test_a_size_the_painter_refuses_is_left_out_and_the_others_are_drawn(
        tmp_path, tools, monkeypatch):
    _painter(monkeypatch, lambda spec: spec.panels == 2)
    d = _make_order(tmp_path, bbox=EAST_WEST, size="11x17")
    pdfs = []
    state = opv.preview(str(d), tools, log=lambda s: None,
                        write_pdf=lambda path, entries, names, title: pdfs.append(
                            [e["key"] for e in entries if e["offered"]]))
    by_key = {e["key"]: e for e in state["sizes"]}
    work = d / "work" / "preview"
    assert not by_key["two"]["offered"] and by_key["two"]["why"] == OFF_DEM
    assert "image" not in by_key["two"] and "plate" not in by_key["two"]
    assert not (work / "two.png").exists()
    for key in ("11x17", "17x22", "three"):
        assert by_key[key]["offered"] and os.path.isfile(by_key[key]["image"])
    assert pdfs == [["11x17", "17x22", "three"]]             # the PDF shows what was drawn
    assert state["plate"]["sizes"] == ["11x17", "17x22", "three"]
    assert json.loads((work / "preview.json").read_text())["sizes"] == state["sizes"]
    report = (work / "report.txt").read_text()
    assert ("- Two panels, landscape, 46 x 17 in: not offered, The selected frame extends past "
            "the available elevation data (31% of it has no DEM coverage). Pan or shrink the "
            "crop to keep it inside the region.\n") in report
    assert report.count("In order.toml:") == 3


@pytest.mark.skipif(os.geteuid() == 0, reason="root can write to a read-only folder")
def test_an_out_folder_that_cannot_be_written_stops_the_command_with_a_sentence(
        tmp_path, tools, monkeypatch, capsys):
    # the real PDF writer: a PermissionError was a traceback after the plate was built
    from scripts import order as order_cli
    _painter(monkeypatch, lambda spec: False)
    d = _make_order(tmp_path, bbox=WIDE, size="11x17")
    (d / "out").mkdir()
    (d / "out").chmod(0o555)
    try:
        assert order_cli.main(["preview", str(d)], tools=tools) == 1
        err = capsys.readouterr().err
        pdf = d / "out" / "preview" / "smith_home_ground-preview.pdf"
        assert f"preview stopped: The preview PDF cannot be written to {pdf}: " in err
        assert "Traceback" not in err and list((d / "out").iterdir()) == []
        assert not (d / "work" / "preview" / "preview.json").exists()
    finally:
        (d / "out").chmod(0o755)
    assert order_cli.main(["preview", str(d)], tools=tools) == 0      # the folder is fixed
    assert pdf.read_bytes().startswith(b"%PDF")


def test_no_size_the_painter_can_draw_stops_the_preview_before_the_pdf(
        tmp_path, tools, monkeypatch):
    _painter(monkeypatch, lambda spec: True)
    d = _make_order(tmp_path, bbox=WIDE, size="11x17")
    pdfs = []
    with pytest.raises(PlateError, match="No size could be drawn: 11x17: The selected frame "
                                         "extends past .*; 17x22: The selected frame"):
        opv.preview(str(d), tools, log=lambda s: None,
                    write_pdf=lambda path, entries, names, title: pdfs.append(path))
    assert pdfs == [] and not (d / "out").exists()
    assert not (d / "work" / "preview" / "preview.json").exists()
    assert not (d / "work" / "preview" / "report.txt").exists()


def test_a_plate_with_no_size_drawn_is_not_in_the_report(tmp_path, tools, monkeypatch):
    _painter(monkeypatch, lambda spec: spec.panels == 3)     # the one size of the Albers plate
    d = _make_order(tmp_path, bbox=PLAINS, size="11x17")
    state = opv.preview(str(d), tools, log=lambda s: None,
                        write_pdf=lambda path, entries, names, title: None)
    assert [p["epsg"] for p in state["plates"]] == [32614]
    assert state["plates"][0]["sizes"] == ["11x17", "17x22", "two"]
    report = (d / "work" / "preview" / "report.txt").read_text()
    assert report.count("Plate: ") == 1 and "- Three panels, portrait, 55 x 22 in: not offered" in report


# ---- the preview's own wiring: each line of preview() that a test must hold ----

def _asks(path):
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def test_the_2x_rule_widens_each_sheet_by_its_own_width(tmp_path, tools, monkeypatch):
    # 10 m data and a 4 km walk: at 2x a sheet shows 1,500 m of ground for each inch of width
    monkeypatch.setenv("STUB_COVERAGE", json.dumps(NO_LIDAR))
    d = _make_order(tmp_path, bbox=SMALL, size="11x17")
    by_key = {e["key"]: e for e in _preview(d, tools)["sizes"]}
    for key, width_in in (("11x17", 11), ("17x22", 17)):
        frame = by_key[key]["frame"]
        assert by_key[key]["orientation"] == "portrait"
        assert frame[2] - frame[0] == pytest.approx(width_in * 1500.0, rel=1e-3)
    assert by_key["17x22"]["fill"] < 0.2                     # judged on the widened frame


def test_the_sizes_list_of_the_order_reaches_the_fit_rule(tmp_path, tools):
    d = _make_order(tmp_path, bbox=EAST_WEST, size="11x17")
    (d / "order.toml").write_text('title = "Smith home ground"\nsizes = ["17x22"]\n')
    calls = []
    state = _preview(d, tools, calls)
    assert [e["key"] for e in state["sizes"] if e["offered"]] == ["17x22"] == calls[0]["keys"]
    assert state["sizes"][0]["why"] == "it is not in the sizes list of order.toml"


def test_only_a_size_that_can_be_offered_is_asked_of_the_3dep_index(tmp_path, tools, monkeypatch):
    # each query is a subprocess and a request: a set the fit rule refuses needs none
    asked = tmp_path / "coverage_asks.jsonl"
    monkeypatch.setenv("STUB_COVERAGE_LOG", str(asked))
    d = _make_order(tmp_path, bbox=SMALL, size="11x17")
    state = _preview(d, tools)
    offered = [e["key"] for e in state["sizes"] if e["offered"]]
    assert offered == ["11x17", "17x22"]                     # a compact walk: no set
    assert len(_asks(asked)) == len(offered) + len(state["plates"]) == 3
    asked.unlink()
    (d / "order.toml").write_text('title = "Smith home ground"\nsizes = ["17x22"]\n')
    _preview(d, tools)
    assert len(_asks(asked)) == 2                            # the one size, and the plate
    asked.unlink()
    (d / "order.toml").write_text('title = "Smith home ground"\nsizes = ["17x22", "three"]\n')
    _preview(d, tools)
    assert len(_asks(asked)) == 3                            # a forced set is asked: terrain can refuse it


def _curated_plate(tmp_path, bounds, crs="EPSG:32611", grid_m=10.0, rid="big"):
    """A curated plate with a real (tiny) DEM, as _curated of tests/test_orderprep.py
    makes one, with its own bounds, projection and grid."""
    import rasterio
    from rasterio.transform import from_bounds
    rdir = tmp_path / "curated" / rid
    rdir.mkdir()
    (rdir / "region.json").write_text(json.dumps({
        "crs": crs, "bounds": list(bounds), "overview_size": [30, 40],
        "native_resolution_m": grid_m}))
    with rasterio.open(rdir / "dem.tif", "w", driver="GTiff", dtype="float32", count=1,
                       width=30, height=40, crs=crs, nodata=np.nan,
                       transform=from_bounds(*bounds, 30, 40)) as ds:
        ds.write(np.full((40, 30), 900.0, dtype="float32"), 1)


def _preview_needs(d, tools):
    """(plate bounds, metres per pixel) that the preview of this order asks of a plate."""
    offered = [e for e in _preview(d, tools)["sizes"] if e["offered"]]
    return opl.plate_bounds(opv.union_frame(offered)), opv.preview_need_m(offered)


def test_the_preview_reuses_a_curated_plate_that_holds_its_frames(tmp_path, tools):
    d = _make_order(tmp_path, bbox=WIDE, size="11x17")
    hold, need = _preview_needs(d, tools)
    # the coarsest grid that is still at most 2x upsampled, and 1 m of ground to spare
    _curated_plate(tmp_path, (hold[0] - 1, hold[1] - 1, hold[2] + 1, hold[3] + 1),
                   grid_m=need * opl.MAX_UPSAMPLE * 0.999)
    built = d / "work" / "preview" / "plate" / "builds.log"
    assert built.read_text().split() == ["preview_2026_10_001_smith"]
    calls, lines = [], []
    state = opv.preview(str(d), tools, log=lines.append, render=_fake_render(calls),
                        write_pdf=lambda path, entries, names, title: None)
    plate = state["plate"]
    assert (plate["kind"], plate["id"], plate["root"]) == ("curated", "big", tools.curated_root)
    assert plate["grid_m"] == pytest.approx(need * opl.MAX_UPSAMPLE * 0.999)
    assert calls[0]["plate_dir"] == os.path.join(tools.curated_root, "big")
    assert "Reusing curated plate big for the preview." in lines
    assert built.read_text().split() == ["preview_2026_10_001_smith"]     # nothing new was built
    assert "Plate: big (curated)," in (d / "work" / "preview" / "report.txt").read_text()


@pytest.mark.parametrize("fault", ["west", "south", "east", "north", "projection", "grid"])
def test_a_curated_plate_that_cannot_show_the_frames_is_not_reused(tmp_path, tools, fault):
    d = _make_order(tmp_path, bbox=WIDE, size="11x17")
    hold, need = _preview_needs(d, tools)
    bounds = [hold[0] - 1, hold[1] - 1, hold[2] + 1, hold[3] + 1]
    sides = ("west", "south", "east", "north")
    if fault in sides:                                       # 1 m short on one side
        k = sides.index(fault)
        bounds[k] = hold[k] + (1 if k < 2 else -1)
    _curated_plate(tmp_path, bounds,
                   crs="EPSG:32610" if fault == "projection" else "EPSG:32611",
                   grid_m=need * opl.MAX_UPSAMPLE * (1.001 if fault == "grid" else 0.999))
    assert [r["id"] for r in op.curated_regions(tools.curated_root)] == ["big"]   # a real plate
    state = _preview(d, tools)
    assert state["plate"]["kind"] == "built"
    assert state["plate"]["id"] == "preview_2026_10_001_smith"


def test_the_preview_build_runs_in_the_shared_cache_folder(tmp_path, tools):
    # a fetch library writes cache/failed_ids*.txt beside its working folder: that must
    # be the orders' cache, never the public repo (orderprep.cache_env)
    d = _make_order(tmp_path, bbox=WIDE, size="11x17")
    _preview(d, tools)
    lines = (d / "work" / "preview" / "build.log").read_text().splitlines()
    cache_dir = str(tmp_path / "orders" / "_cache")
    assert "prep_cwd=" + cache_dir in lines
    assert "cache=" + os.path.join(cache_dir, "aiohttp_cache.sqlite") in lines


def test_preview_refuses_an_orders_root_inside_the_repo(tmp_path, tmp_path_factory, tools,
                                                        monkeypatch):
    # the order folder is outside the patched repo: only the check of TECOPA_ORDERS_DIR,
    # which the `tools` fixture sets under tmp_path, can refuse this
    monkeypatch.setattr(od, "_repo_root", lambda: str(tmp_path))
    d = _make_order(tmp_path_factory.mktemp("external"), bbox=WIDE)
    with pytest.raises(od.OrderError, match="Order folders must live outside the repo"):
        _preview(d, tools)
    assert not (d / "work").exists()


def test_tracks_outside_the_lower_48_stop_the_preview(tmp_path, tools, monkeypatch):
    asked = tmp_path / "coverage_asks.jsonl"
    monkeypatch.setenv("STUB_COVERAGE_LOG", str(asked))
    d = _make_order(tmp_path, bbox=(-150.1, 61.1, -149.9, 61.2))
    with pytest.raises(PlateError, match="outside the lower 48"):
        _preview(d, tools)
    assert not asked.exists() and not (d / "work").exists()


def test_a_missing_prep_venv_stops_the_preview(tmp_path, tools):
    tools = op.Tools(**{**tools.__dict__,
                        "prep_python": str(tmp_path / "no-venv" / "bin" / "python")})
    d = _make_order(tmp_path, bbox=WIDE)
    with pytest.raises(PlateError, match="The prep venv is missing: .*no-venv"):
        _preview(d, tools)
    assert not (d / "work").exists()


def test_preview_json_has_the_mode_of_the_orders_other_files(tmp_path, tools):
    d = _make_order(tmp_path, bbox=WIDE, size="11x17")
    _preview(d, tools)
    work = d / "work" / "preview"
    mode = stat.S_IMODE(os.stat(work / "preview.json").st_mode)
    assert mode == stat.S_IMODE(os.stat(work / "report.txt").st_mode)
    assert mode & stat.S_IRGRP or not stat.S_IMODE(os.stat(d / "order.toml").st_mode) & stat.S_IRGRP
    assert not list(work.glob("*.tmp"))


def _toml_lines(report) -> dict:
    """{size key: the lines the report gives for order.toml}, exactly as printed."""
    out, lines = {}, report.splitlines()
    for at, line in enumerate(lines):
        if line.endswith("In order.toml:"):
            block = []
            for nxt in lines[at + 1:]:
                if not nxt.startswith("    "):
                    break
                block.append(nxt)
            out[tomllib.loads("\n".join(block))["size"]] = "\n".join(block) + "\n"
    return out


def test_the_lines_of_the_report_paste_into_order_toml(tmp_path, tools):
    d = _make_order(tmp_path, bbox=EAST_WEST, size="11x17")
    state = _preview(d, tools)
    pasted = _toml_lines((d / "work" / "preview" / "report.txt").read_text())
    assert list(pasted) == [e["key"] for e in state["sizes"] if e["offered"]] == list(opv.SIZE_KEYS)
    for e in state["sizes"]:
        (d / "order.toml").write_text('title = "Smith home ground"\n' + pasted[e["key"]])
        order = opv.load(str(d))
        assert list(order.print_in()) == e["print_in"]
        assert (order.orientation, order.panels, order.gap) == (
            e["orientation"], e["panels"], e["gap"])


# ---- a coarse preview plate comes from the static 30 m tiles when it is small enough ----

# 9 km east and 17 km north: a single sheet's map needs 17 m of ground for each pixel
MID = (-116.3, 35.8, -116.2, 35.95)
# the 30 m layer stops short of the plate, and the 10 m layer holds it
NO_30_M = {"1": 0.0, "3": 0.0, "10": 1.0, "30": 0.9, "60": 0.0}


def _logged_preview(d, tools):
    lines = []
    state = opv.preview(str(d), tools, log=lines.append, render=_fake_render([]),
                        write_pdf=lambda path, entries, names, title: None)
    return state, lines


def _grid_of(state):
    """(the grid the build was asked for, the plate's grid, its layer) of the first plate."""
    plate = state["plate"]
    built = json.loads(open(os.path.join(plate["root"], plate["id"], "region.json")).read())
    return built["native_resolution_m"], plate["grid_m"], plate["layer_m"]


def _need_and_cells(state):
    """(metres for each pixel of the finest map, the cells of the plate at 30 m)."""
    offered = [e for e in state["sizes"] if e["offered"]]
    box = opl.to_lonlat_bbox(opl.plate_bounds(opv.union_frame(offered)), state["epsg"],
                             pad_m=opl.PLATE_PAD_M)
    return opv.preview_need_m(offered), opv.static_cells(box, state["epsg"])


@pytest.mark.parametrize("bbox,epsg", [(SIERRA, 32611), (PLAINS, 32614), (PLAINS, 5070)])
def test_the_cell_estimate_is_the_grid_that_the_build_makes(bbox, epsg):
    # the plate's box goes to the build in degrees and is projected again there, so the
    # grid is larger than the plate: in Albers, more than twice as large
    import region_prep
    plate = opl.plate_bounds(nestled_frame(project_bbox(bbox, epsg), 17 / 22))
    box = opl.to_lonlat_bbox(plate, epsg, pad_m=opl.PLATE_PAD_M)
    w, h, _ = region_prep.projected_grid(box, f"EPSG:{epsg}", opv.PREVIEW_STATIC_LAYER_M)
    assert opv.GRID_INSET_M == region_prep.GRID_INSET_M
    assert opv.static_cells(box, epsg) == pytest.approx(w * h, rel=1e-3)
    assert w * h > (plate[2] - plate[0]) * (plate[3] - plate[1]) / 30.0 ** 2


def test_a_coarse_preview_plate_is_built_from_the_static_30_m_tiles(tmp_path, tools, monkeypatch):
    # 100 km north to south: a map of 1,600 px needs 104 m for each pixel, and
    # choose_grid sends a need above 60 m to the dynamic service
    d = _make_order(tmp_path, bbox=SIERRA, size="11x17")
    state, lines = _logged_preview(d, tools)
    need, cells = _need_and_cells(state)
    assert need > opl.STATIC_SPAN * 30 and 30e6 < cells < opv.PREVIEW_STATIC_MAX_CELLS
    assert _grid_of(state) == (30.0, 30.0, 30)
    assert ("Preview plate preview_2026_10_001_smith: 30 m grid from the static 3DEP tiles "
            "(a 100 m grid would come from the dynamic service).") in lines
    assert "Building plate preview_2026_10_001_smith: 30 m grid from the 30 m 3DEP layer." in lines
    report = (d / "work" / "preview" / "report.txt").read_text()
    assert "Plate: preview_2026_10_001_smith (built), 30 m grid\n" in report
    # the same order with a lower limit keeps the coarse grid
    monkeypatch.setattr(opv, "PREVIEW_STATIC_MAX_CELLS", 20e6)
    state, lines = _logged_preview(d, tools)
    assert _grid_of(state) == (100.0, 100.0, 10)
    assert (f"Preview plate preview_2026_10_001_smith: 100 m grid from the 3DEP dynamic service "
            f"(at 30 m the plate has {cells / 1e6:.0f} million cells, and the limit is "
            f"20 million).") in lines
    # the limit is the last size that the tiles serve
    monkeypatch.setattr(opv, "PREVIEW_STATIC_MAX_CELLS", cells - 1)
    assert _grid_of(_logged_preview(d, tools)[0]) == (100.0, 100.0, 10)
    monkeypatch.setattr(opv, "PREVIEW_STATIC_MAX_CELLS", cells)
    assert _grid_of(_logged_preview(d, tools)[0]) == (30.0, 30.0, 30)


@pytest.mark.parametrize("bbox,span,grid,source", [
    (WIDE, (30.0, 60.0), (30.0, 30.0, 30), "the static 3DEP tiles"),
    (MID, (10.0, 20.0), (10.0, 10.0, 10), "the static 3DEP tiles"),
    (SMALL, (0.0, 10.0), (4.75, 4.75, 1), "the 3DEP dynamic service")])
def test_a_need_inside_a_static_span_or_finer_keeps_its_grid(tmp_path, tools, bbox, span,
                                                             grid, source):
    d = _make_order(tmp_path, bbox=bbox, size="11x17")
    state, lines = _logged_preview(d, tools)
    need, cells = _need_and_cells(state)
    assert span[0] <= need <= span[1] and cells < opv.PREVIEW_STATIC_MAX_CELLS
    assert _grid_of(state) == grid == _grid_of_choose_grid(need, state)
    assert f"Preview plate preview_2026_10_001_smith: {grid[0]:g} m grid from {source}." in lines


def _grid_of_choose_grid(need, state):
    """The grid that choose_grid alone gives the need, with the coverage of the stubs."""
    cov = json.loads(os.environ["STUB_COVERAGE"])
    if need >= op.COARSE_NEED_M:
        cov = {k: v for k, v in cov.items() if int(k) in op.COARSE_LAYERS_M}
    g = opl.choose_grid(need, cov)
    return g["grid_m"], g["grid_m"], g["layer_m"]


def test_a_plate_that_the_30_m_tiles_do_not_cover_keeps_the_coarse_grid(tmp_path, tools,
                                                                        monkeypatch):
    # choose_grid gives a need of 60 m a 55 m grid here, from the dynamic service: that
    # is not the static grid, so the preview keeps the grid of its own need
    monkeypatch.setenv("STUB_COVERAGE", json.dumps(NO_30_M))
    assert opl.choose_grid(60.0, {10: 1.0, 30: 0.9})["grid_m"] == 55.0
    d = _make_order(tmp_path, bbox=SIERRA, size="11x17")
    state, lines = _logged_preview(d, tools)
    need, cells = _need_and_cells(state)
    assert need > 60 and cells < opv.PREVIEW_STATIC_MAX_CELLS
    assert _grid_of(state) == (100.0, 100.0, 10) == _grid_of_choose_grid(need, state)
    assert ("Preview plate preview_2026_10_001_smith: 100 m grid from the 3DEP dynamic service "
            "(the static 30 m tiles do not cover the plate).") in lines


def test_prepare_keeps_its_grid_when_the_preview_takes_the_static_tiles(tmp_path, tools,
                                                                       monkeypatch):
    # the rule is the preview's own: with no limit at all, a print that needs 100 m for
    # each pixel still gets the 100 m grid
    monkeypatch.setattr(opv, "PREVIEW_STATIC_MAX_CELLS", float("inf"))
    d = _make_order(tmp_path, bbox=EAST_WEST, size="11x17")
    state, _ = _logged_preview(d, tools)
    assert _need_and_cells(state)[0] > 60 and _grid_of(state) == (30.0, 30.0, 30)
    plate = op.prepare(str(d), tools, log=lambda s: None)["plate"]
    assert (plate["grid_m"], plate["layer_m"]) == (100.0, 10)


def test_a_curated_plate_is_reused_before_the_static_tiles_are_asked(tmp_path, tools):
    d = _make_order(tmp_path, bbox=SIERRA, size="11x17")
    hold, need = _preview_needs(d, tools)
    assert need > 60
    _curated_plate(tmp_path, (hold[0] - 1, hold[1] - 1, hold[2] + 1, hold[3] + 1),
                   grid_m=need * opl.MAX_UPSAMPLE * 0.999)
    state, lines = _logged_preview(d, tools)
    assert (state["plate"]["kind"], state["plate"]["id"]) == ("curated", "big")
    assert state["plate"]["grid_m"] > 200
    assert not [l for l in lines if l.startswith("Preview plate")]
