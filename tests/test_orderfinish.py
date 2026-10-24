# tests/test_orderfinish.py
# Finish: the approved spec as print TIFFs for the 17 in roll, and the print note. The plate
# is the synthetic Lassen mirror; the fixture is order_with_plate in tests/conftest.py.
# Every test renders at 10 ppi: the geometry is the same at any ppi.
import json
import os

import pytest
from PIL import Image

from app import icc, order as od, orderfinish, orderspec, orderstudio, papers
from app.serialize import spec_to_json

DPI = 10


def _save_and_approve(order):
    """What the studio does, without the proof files: save the spec, record the approval."""
    state = od.read_state(order)
    spec = orderspec.order_spec(order, state)
    od.set_manual(order, "spec", spec_to_json(spec))
    orderstudio.approve(order, spec)
    return spec


@pytest.fixture
def order(order_with_plate):
    return order_with_plate


@pytest.fixture
def approved(order):
    _save_and_approve(order)
    return order


@pytest.fixture
def set_order(order_with_plate):
    """A set of two landscape panels, 22 x 17 in each, with a 2 in gap: 46 x 17 in on the
    wall. (The synthetic plate cannot hold three panels at the zoom cap; two fit at 10 ppi.)"""
    order = order_with_plate
    with open(os.path.join(order.dir, "order.toml"), "w") as f:
        f.write('title = "Smith home ground"\nsize = "two"\norientation = "landscape"\n'
                "gap = 2\n")
    order = od.load(order.dir)
    assert order.print_in() == (46.0, 17.0) and order.panels == 2
    st = od.read_state(order)
    cx, cy = (st["frame"][0] + st["frame"][2]) / 2, (st["frame"][1] + st["frame"][3]) / 2
    half_w = 30000.0
    half_h = half_w * 17.0 / 46.0
    od.write_state(order, {"print_in": [46.0, 17.0], "panels": 2, "gap": 2.0,
                           "frame": [cx - half_w, cy - half_h, cx + half_w, cy + half_h]})
    _save_and_approve(order)
    return order


def _note(order) -> list:
    with open(os.path.join(order.dir, "out", "print", "PRINT.txt"), encoding="utf-8") as f:
        return f.read().splitlines()


def test_finish_refuses_without_approval(order):
    with pytest.raises(od.OrderError, match="Approve the proof in the studio first."):
        orderfinish.finish(order.dir, dpi=DPI)
    assert not os.path.exists(os.path.join(order.dir, "out", "print"))


def test_finish_refuses_a_change_after_approval(approved):
    spec = orderspec.order_spec(approved, od.read_state(approved))
    import dataclasses
    other = dataclasses.replace(spec, title_text="Another title")
    od.set_manual(approved, "spec", spec_to_json(other))      # saved after approval
    with pytest.raises(od.OrderError, match="The order changed after approval: approve it again."):
        orderfinish.finish(approved.dir, dpi=DPI)
    assert not os.path.exists(os.path.join(approved.dir, "out", "print"))


def test_finish_refuses_a_hand_edited_state(approved):
    with open(approved.state_path) as f:
        state = json.load(f)
    state["manual"]["spec"]["title_text"] = "Edited by hand"
    with open(approved.state_path, "w") as f:
        json.dump(state, f)
    with pytest.raises(od.OrderError, match="changed after approval"):
        orderfinish.finish(approved.dir, dpi=DPI)


def test_finish_refuses_an_approval_with_no_saved_spec(order):
    od.write_state(order, {"approval": {"at": "2026-10-24T00:00:00+00:00", "hash": "abc"}})
    with pytest.raises(od.OrderError, match="changed after approval"):
        orderfinish.finish(order.dir, dpi=DPI)


def test_a_single_sheet_tiff_is_the_print_at_its_size(approved):
    r = orderfinish.finish(approved.dir, dpi=DPI)
    assert len(r["files"]) == 1
    assert os.path.basename(r["files"][0]) == "smith_home_ground-11x17.tif"
    assert os.path.dirname(r["files"][0]) == os.path.join(approved.dir, "out", "print")
    with Image.open(r["files"][0]) as im:
        assert im.size == (170, 110)        # 11x17 portrait at 10 dpi, rotated 90° to feed (P6)
        assert im.mode == "RGB"
        assert im.info["icc_profile"] == icc.srgb_profile()
        assert round(im.info["dpi"][0]) == 10 and round(im.info["dpi"][1]) == 10
        assert im.info.get("compression") == "raw"


def test_the_tiff_is_the_render_turned_counter_clockwise(approved):
    from app import render
    st = od.read_state(approved)
    spec = orderspec.order_spec(approved, st)
    path = orderspec.plate_dir(st)
    raw = render.rasterize(spec, dpi=DPI, region_dir=path)
    r = orderfinish.finish(approved.dir, dpi=DPI)
    want = raw.convert("RGB").rotate(90, expand=True)
    with Image.open(r["files"][0]) as im:
        assert im.tobytes() == want.tobytes()


def test_a_17_inch_wide_sheet_is_not_turned(order):
    import dataclasses
    spec = orderspec.order_spec(order, od.read_state(order))
    cx, cy = (spec.crop[0] + spec.crop[2]) / 2, (spec.crop[1] + spec.crop[3]) / 2
    half_w = 14000.0
    half_h = half_w * 11.0 / 17.0
    spec = dataclasses.replace(spec, print_w_in=17.0, print_h_in=11.0,
                               crop=(cx - half_w, cy - half_h, cx + half_w, cy + half_h))
    od.set_manual(order, "spec", spec_to_json(spec))
    orderstudio.approve(order, spec)
    r = orderfinish.finish(order.dir, dpi=DPI)
    with Image.open(r["files"][0]) as im:
        assert im.size == (170, 110)
    assert "  Feed: as it is, the 17 in side across the roll" in _note(order)


def test_a_two_panel_set_writes_rotated_panels_in_hang_order(set_order):
    r = orderfinish.finish(set_order.dir, dpi=DPI)
    names = [os.path.basename(f) for f in r["files"]]
    assert names == ["smith_home_ground-two-1of2.tif", "smith_home_ground-two-2of2.tif"]
    for f in r["files"]:
        with Image.open(f) as im:
            assert im.size == (170, 220)    # 22 x 17 in panel turned 90°: 17 x 22 in
            assert im.info["icc_profile"] == icc.srgb_profile()
    # the gap strip is not printed: the two files plus the gap tile the sheet's width
    assert not [n for n in os.listdir(os.path.join(set_order.dir, "out", "print"))
                if n.endswith(".tif") and n not in names]


def test_a_set_cuts_the_sheet_at_the_panels_and_drops_the_gap(set_order):
    from app import render
    st = od.read_state(set_order)
    spec = orderspec.order_spec(set_order, st)
    raw = render.rasterize(spec, dpi=DPI, region_dir=orderspec.plate_dir(st)).convert("RGB")
    r = orderfinish.finish(set_order.dir, dpi=DPI)
    # panel 1 is x 0..220, the gap 220..240, panel 2 is 240..460
    for f, box in zip(r["files"], [(0, 0, 220, 170), (240, 0, 460, 170)]):
        with Image.open(f) as im:
            assert im.tobytes() == raw.crop(box).rotate(90, expand=True).tobytes()


def test_the_print_note_lists_paper_profile_intent_and_each_file(approved):
    r = orderfinish.finish(approved.dir, dpi=DPI)
    paper = papers.enabled_paper()
    st = od.read_state(approved)
    note = _note(approved)
    assert r["print_note"] == os.path.join(approved.dir, "out", "print", "PRINT.txt")
    assert note[:8] == [
        "Tecopa Plateworks print note",
        "Order: 2026-10-001-smith · Smith home ground",
        "Paper: Red River Premium Matte 230, 17 in roll",
        "Profile: RR Premium Matte Canon Pro-1100.icc",
        f"Intent: {paper.intent}",
        f"Preset: {paper.preset}",
        "Print at 100 %, centred, from Canon Professional Print & Layout.",
        f"Approved: {st['approval']['at']}, hash {st['approval']['hash'][:12]}"]
    assert note[8] == ""
    assert note[9:] == [
        "File: smith_home_ground-11x17.tif",
        "  Size: 17 × 11 in, 170 × 110 px at 10 ppi",
        "  Feed: rotated 90° counter-clockwise, the 17 in side across the roll; "
        "the map's top is on the left"]


def test_the_print_note_names_the_order_number_and_the_panels_of_a_set(set_order):
    with open(os.path.join(set_order.dir, "order.toml"), "a") as f:
        f.write('order_number = "TP-26-007"\n')
    orderfinish.finish(set_order.dir, dpi=DPI)
    note = _note(set_order)
    assert note[1] == "Order: TP-26-007 · Smith home ground"
    assert "File: smith_home_ground-two-1of2.tif" in note
    assert "File: smith_home_ground-two-2of2.tif" in note
    assert "  Panel: 1 of 2" in note and "  Panel: 2 of 2" in note
    assert note[-1] == "Hang: panels 1 to 2, left to right, with a 2 in gap"
    assert note[-2] == ""


def test_the_record_png_carries_the_manifest(approved):
    from app import provenance
    orderfinish.finish(approved.dir, dpi=DPI)
    path = os.path.join(approved.dir, "work", "record.png")
    with Image.open(path) as im:
        assert im.size == (110, 170)                   # the unrotated render
        assert provenance.MANIFEST_KEY in im.text
        assert im.info["icc_profile"] == icc.srgb_profile()
        assert round(im.info["dpi"][0]) == 10
    manifest = provenance.extract(open(path, "rb").read())
    assert manifest["spec"]["title_text"] == "Smith home ground"
    assert "region_pack" in manifest


def test_finishing_again_removes_a_print_file_that_is_no_longer_the_print(approved):
    r = orderfinish.finish(approved.dir, dpi=DPI)
    stale = os.path.join(approved.dir, "out", "print", "old-title-11x17.tif")
    with open(stale, "wb") as f:
        f.write(b"old")
    r2 = orderfinish.finish(approved.dir, dpi=DPI)
    assert r2["files"] == r["files"]
    assert not os.path.exists(stale)


def test_a_render_that_fails_leaves_the_earlier_print_files(approved, monkeypatch):
    r = orderfinish.finish(approved.dir, dpi=DPI)
    before = open(r["files"][0], "rb").read()
    from app import render

    def boom(*a, **k):
        raise RuntimeError("render failed")
    monkeypatch.setattr(render, "rasterize", boom)
    with pytest.raises(RuntimeError):
        orderfinish.finish(approved.dir, dpi=DPI)
    assert open(r["files"][0], "rb").read() == before


def test_the_cli_finish_stops_with_the_reason(order, capsys):
    from scripts import order as order_cli
    assert order_cli.main(["finish", order.dir]) == 1
    err = capsys.readouterr().err
    assert err.startswith("finish stopped: ") and "Approve the proof in the studio first." in err


def test_the_cli_finish_prints_the_note(approved, capsys, monkeypatch):
    from scripts import order as order_cli
    real = orderfinish.finish
    monkeypatch.setattr(orderfinish, "finish",
                        lambda folder, log=print, dpi=None: real(folder, log=log, dpi=DPI))
    assert order_cli.main(["finish", approved.dir]) == 0
    out = capsys.readouterr().out
    assert "Tecopa Plateworks print note" in out and "smith_home_ground-11x17.tif" in out
