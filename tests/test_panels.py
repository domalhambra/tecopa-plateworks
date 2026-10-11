# tests/test_panels.py
import glob
import json

import numpy as np
import pytest
from PIL import Image

from app import panels, provenance, serialize
from app.spec import CompositionSpec, SpecError

SHAPES = [(2, "wide"), (3, "wide"), (2, "tall"), (3, "tall")]


def set_spec(n=3, gap=2.0, shape="wide", **over):
    """A set that passes validate: the sheet of the shape, and a crop at 1x of a
    10 m plate (so the zoom cap holds at 300 dpi)."""
    w, h = panels.sheet_sizes(n, gap)[0 if shape == "wide" else 1]
    cw = 10.0 * w * 300
    kw = dict(region_id="r", crs="EPSG:32612",
              crop=(0.0, 0.0, cw, cw * h / w), print_w_in=w, print_h_in=h,
              native_resolution_m=10.0, tracks=[np.array([[10.0, 10.0], [cw - 10.0, 10.0]])],
              hotspots=[], seed=7, panels=n, panel_gap_in=gap)
    kw.update(over)
    return CompositionSpec(**kw)


def test_the_two_sheets_of_a_set():
    assert panels.sheet_sizes(3, 2) == [(70.0, 17.0), (55.0, 22.0)]
    assert panels.sheet_sizes(2, 0) == [(44.0, 17.0), (34.0, 22.0)]
    assert panels.sheet_sizes(3, 4) == [(74.0, 17.0), (59.0, 22.0)]


@pytest.mark.parametrize("n,shape", SHAPES)
@pytest.mark.parametrize("gap", panels.GAPS_IN)
def test_every_panel_is_a_full_sheet_at_300_dpi(n, shape, gap):
    spec = set_spec(n, gap, shape).validate(300)
    rects = panels.panel_rects_px(spec, 300)
    want = (6600, 5100) if shape == "wide" else (5100, 6600)
    assert [(r[2] - r[0], r[3] - r[1]) for r in rects] == [want] * n
    assert rects[0][0] == 0 and rects[-1][2] == spec.pixel_size(300)[0]
    assert [r[2] - r[0] for r in panels.gap_rects_px(spec, 300)] == (
        [round(gap * 300)] * (n - 1) if gap else [])


def test_panels_and_gaps_tile_the_sheet_at_an_odd_dpi():
    spec = set_spec(3, 2.0, "wide")
    dpi = 41.37
    rects = panels.panel_rects_px(spec, dpi)
    gaps = panels.gap_rects_px(spec, dpi)
    edges = sorted(rects + gaps)
    w, h = spec.pixel_size(dpi)
    assert len(edges) == 5                                       # 3 panels and 2 gap strips
    assert edges[0][0] == 0 and edges[-1][2] == w                # from edge to edge
    assert all(a[2] == b[0] for a, b in zip(edges, edges[1:]))   # no overlap, no hole
    assert all(r[1] == 0 and r[3] == h for r in edges)           # the full height
    assert rects == [(round(x0 * dpi), 0, round(x1 * dpi), h)    # each edge rounded on its own
                     for x0, x1 in ((0, 22), (24, 46), (48, 70))]


def test_a_cut_set_joins_back_into_the_sheet():
    spec = set_spec(3, 0.0, "wide")
    dpi = 10
    w, h = spec.pixel_size(dpi)
    rng = np.random.default_rng(7)
    sheet = Image.fromarray(rng.integers(0, 255, (h, w, 3), dtype=np.uint8))
    parts = panels.cut(sheet, spec, dpi)
    joined = np.concatenate([np.asarray(p) for p in parts], axis=1)
    assert np.array_equal(joined, np.asarray(sheet))


def test_a_window_set_drops_the_gap_strips_and_paints_them_for_a_proof():
    spec = set_spec(2, 2.0, "tall")
    dpi = 10
    w, h = spec.pixel_size(dpi)
    sheet = Image.new("RGB", (w, h), (10, 20, 30))
    parts = panels.cut(sheet, spec, dpi)
    assert [p.size for p in parts] == [(170, 220), (170, 220)]
    shown = np.asarray(panels.paint_gaps(sheet, spec, dpi))
    assert (shown[:, 170:190] == panels.WALL_TONE).all()
    assert (shown[:, :170] == (10, 20, 30)).all() and (shown[:, 190:] == (10, 20, 30)).all()
    assert np.asarray(sheet)[0, 175].tolist() == [10, 20, 30]     # the input is not changed


def test_a_single_sheet_is_its_own_panel():
    spec = set_spec(3, 2.0, "wide", panels=1, panel_gap_in=0.0)
    assert not panels.is_set(spec)
    assert panels.panel_size_in(spec) == (70.0, 17.0)
    assert panels.frame_rects_px(spec, 10, (0, 0, 700, 170)) == [(0, 0, 700, 170)]
    assert panels.furniture_trim_px(spec, 10, (5, 5, 695, 165)) == (5, 5, 695, 165)
    assert panels.span_px_at(spec, 300, 10, 700) == (0, 700)


def test_a_set_gives_panel_one_to_the_furniture_and_a_span_to_each_anchor():
    spec = set_spec(3, 2.0, "wide")
    assert panels.furniture_trim_px(spec, 10, (0, 0, 700, 170)) == (0, 0, 220, 170)
    assert panels.span_px_at(spec, 300, 10, 700) == (240, 460)     # in panel 2
    assert panels.span_px_at(spec, 232, 10, 700) == (240, 460)     # in gap 1: the nearer panel
    assert panels.span_px_at(spec, 225, 10, 700) == (0, 220)
    assert panels.seam_bands_px(spec, 10, 3) == [(217, 0, 243, 170), (457, 0, 483, 170)]
    cut = set_spec(2, 0.0, "tall")
    assert panels.seam_bands_px(cut, 10, 3) == [(167, 0, 173, 220)]


@pytest.mark.parametrize("over,words", [
    ({"panels": 4}, "panels must be 1, 2 or 3"),
    ({"panels": 0}, "panels must be 1, 2 or 3"),
    ({"panel_gap_in": 1.0}, "panel_gap_in must be 0, 2 or 4"),
    ({"panel_gap_in": float("nan")}, "panel_gap_in must be 0, 2 or 4"),
    ({"print_w_in": 68.0}, "a set of 3 panels"),
    ({"print_h_in": 22.0}, "a set of 3 panels"),                 # the height is checked too
    ({"panel_gap_in": 2.0000000001}, "panel_gap_in must be 0, 2 or 4"),
    ({"panel_gap_in": -1e-10}, "panel_gap_in must be 0, 2 or 4"),
    ({"panel_gap_in": float("inf")}, "panel_gap_in must be 0, 2 or 4"),
    ({"panel_gap_in": 10 ** 400}, "panel_gap_in must be 0, 2 or 4"),
    ({"bleed_in": 0.125}, "a set takes no bleed"),
    ({"output_kind": "wallpaper", "screen_ppi": 300.0}, "a set is a print"),
    ({"panels": "3"}, "panels must be a whole number"),
    ({"panel_gap_in": "2"}, "panel_gap_in must be a number"),
])
def test_a_wrong_set_is_a_spec_error(over, words):
    with pytest.raises(SpecError, match=words):
        set_spec(3, 2.0, "wide", **over).validate(300)


def test_a_gap_on_a_single_sheet_is_refused():
    with pytest.raises(SpecError, match="a single sheet has no gap"):
        set_spec(3, 2.0, "wide", panels=1).validate(300)


def test_the_wrong_sheet_message_names_both_sheets():
    with pytest.raises(SpecError, match=r"70x17 or 55x22 in, not 68x17"):
        set_spec(3, 2.0, "wide", print_w_in=68.0).validate(300)


def test_a_single_sheet_validates_as_before():
    spec = set_spec(3, 2.0, "wide", panels=1, panel_gap_in=0.0)
    assert spec.validate(300) is spec
    assert CompositionSpec.__dataclass_fields__["panels"].default == 1
    assert CompositionSpec.__dataclass_fields__["panel_gap_in"].default == 0.0


def test_both_fields_are_always_written_and_default_when_missing():
    d = serialize.spec_to_json(set_spec(3, 2.0, "wide"))
    assert d["panels"] == 3 and d["panel_gap_in"] == 2.0
    del d["panels"], d["panel_gap_in"]
    back = serialize.spec_from_json(d)
    assert back.panels == 1 and back.panel_gap_in == 0.0


def test_every_frozen_manifest_reads_as_a_single_sheet():
    # `manifest*_v1.json`, not `manifest_*_v1.json`: the second pattern needs two
    # underscores, so it misses manifest_v1.json and finds six files.
    paths = sorted(glob.glob("tests/fixtures/manifest*_v1.json"))
    assert len(paths) == 7
    for path in paths:
        spec = provenance.manifest_to_spec(json.load(open(path)))
        assert spec.panels == 1 and spec.panel_gap_in == 0.0, path


def test_a_two_panel_set_with_a_wrong_sheet_is_refused():
    with pytest.raises(SpecError, match=r"a set of 2 panels with a 2 in gap is 46x17 or 36x22 in"):
        set_spec(2, 2.0, "tall", print_w_in=34.0).validate(300)


def test_a_whole_number_gap_is_a_gap():
    assert set_spec(3, 2.0, "wide", panel_gap_in=2).validate(300).panel_gap_in == 2
