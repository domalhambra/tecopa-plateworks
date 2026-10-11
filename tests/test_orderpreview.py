# tests/test_orderpreview.py
import json
import os

import numpy as np
import pytest

from app import orderprep as op
from app import orderpreview as opv
from app import order as od
from app import orderplate as opl
from app.orderplate import (CoverageError, PlateError, nestled_frame, order_epsg, project_bbox,
                            track_shares)
from tests.test_orderprep import WIDE, _gpx, _make_order, tools  # noqa: F401

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


def test_the_lines_of_the_report_give_prepare_the_frame_of_the_preview(tmp_path, tools):
    d = _make_order(tmp_path, bbox=SIERRA_DIAGONAL, size="11x17")
    (d / "order.toml").write_text('title = "Smith home ground"\nsizes = ["17x22", "two"]\n')
    for e in _preview(d, tools)["sizes"]:
        if not e["offered"]:
            continue
        gap = f"gap = {e['gap']:g}\n" if e["panels"] > 1 else ""
        (d / "order.toml").write_text(f'title = "Smith home ground"\nsize = "{e["key"]}"\n'
                                      f'orientation = "{e["orientation"]}"\n{gap}')
        state = op.prepare(str(d), tools, log=lambda s: None)
        assert state["epsg"] == e["epsg"] and state["print_in"] == e["print_in"]
        assert state["frame"] == pytest.approx(e["frame"], abs=1e-6)
        assert state["fill"] == e["fill"]


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


def test_a_wrong_sizes_file_stops_the_preview_before_any_plate(tmp_path, tools, monkeypatch):
    # the plate takes minutes to build: the names and prices are read first
    bad = tmp_path / "sizes.toml"
    bad.write_text('[[size]]\nkey = "11x17"\nname = "Small"\n')
    monkeypatch.setattr(opv.sizes, "default_path", lambda: str(bad))
    d = _make_order(tmp_path, bbox=WIDE, size="11x17")
    with pytest.raises(opv.OrderError, match="has no row for 17x22, two, three"):
        _preview(d, tools)
    assert not (d / "work" / "preview").exists()


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
    assert f'order.toml: size = "11x17", orientation = "{small["orientation"]}"' in report
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
        '- Three panels, landscape, 70 x 17 in: offered, tracks fill 60%. '
        'order.toml: size = "three", orientation = "landscape", gap = 2',
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
    assert 'order.toml: size = "11x17"' in out and "not offered" in out


def test_each_command_names_itself_when_it_stops(tmp_path, tools, capsys):
    from scripts import order as order_cli
    d = _make_order(tmp_path, bbox=WIDE)
    (d / "order.toml").write_text('size = "11x17"\n')          # no title
    assert order_cli.main(["preview", str(d)], tools=tools) == 1
    assert "preview stopped: order.toml needs a title" in capsys.readouterr().err
    assert order_cli.main(["prepare", str(d)], tools=tools) == 1
    assert "prepare stopped: order.toml needs a title" in capsys.readouterr().err


def test_a_title_the_map_cannot_hold_stops_the_command(tmp_path, tools, capsys, monkeypatch):
    # render_maps raises SpecError for a title past the spec's limit
    # (tests/test_orderpreview_render.py); the command must name it, not show a traceback
    from scripts import order as order_cli
    from app.spec import SpecError

    def render(entries, tracks, plate_dir, title, out_dir):
        raise SpecError("title_text must be at most 200 characters")
    d = _make_order(tmp_path, bbox=WIDE, size="11x17")
    monkeypatch.setattr(opv, "render_maps", render)
    assert order_cli.main(["preview", str(d)], tools=tools) == 1
    captured = capsys.readouterr()
    assert "preview stopped: title_text must be at most 200 characters" in captured.err
    assert "Sizes:" not in captured.out
    assert not (d / "work" / "preview" / "preview.json").exists()
    assert not (d / "work" / "preview" / "report.txt").exists()
    assert not (d / "out").exists()


def test_a_failed_coverage_query_stops_the_command(tmp_path, tools, capsys):
    from scripts import order as order_cli
    bad = tmp_path / "stubs" / "bad_coverage.py"
    bad.write_text('import sys\nsys.exit("boom")\n')
    tools = op.Tools(**{**tools.__dict__, "coverage_script": str(bad)})
    d = _make_order(tmp_path, bbox=WIDE, size="11x17")
    assert order_cli.main(["preview", str(d)], tools=tools) == 1
    assert "preview stopped: The 3DEP coverage check failed" in capsys.readouterr().err
