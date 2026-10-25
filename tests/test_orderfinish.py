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


def _proof_written(order):
    """Record in state.json the client proof that Save to order writes of the saved spec,
    without rendering it."""
    spec = orderspec.order_spec(order, od.read_state(order))
    od.write_state(order, {"proof": {"files": [], "hash": orderspec.spec_hash(spec)}})


def _save_and_approve(order):
    """What the studio does, without the proof files: save the spec, record the approval."""
    state = od.read_state(order)
    spec = orderspec.order_spec(order, state)
    od.set_manual(order, "spec", spec_to_json(spec))
    _proof_written(order)
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


def _no_render(monkeypatch):
    """Make any render fail loudly: a refusal that must come before the render."""
    from app import render

    def boom(*a, **k):
        raise AssertionError("Finish rendered before it refused")
    monkeypatch.setattr(render, "rasterize", boom)


SIZE_MISMATCH = ("The saved studio spec is not this order's size: open the order, proof, "
                 "save and approve again.")


@pytest.mark.parametrize("state", [{"print_in": [17.0, 22.0]}, {"panels": 2, "gap": 2.0}])
def test_finish_refuses_a_spec_that_is_not_the_orders_size_before_rendering(
        approved, monkeypatch, state):
    od.write_state(approved, state)        # Prepare framed another size after the approval
    _no_render(monkeypatch)
    with pytest.raises(od.OrderError) as ex:
        orderfinish.finish(approved.dir, dpi=DPI)
    assert str(ex.value) == SIZE_MISMATCH
    assert not os.path.exists(os.path.join(approved.dir, "out", "print"))


def _approve_spec(order, **change):
    import dataclasses
    spec = dataclasses.replace(orderspec.order_spec(order, od.read_state(order)), **change)
    od.set_manual(order, "spec", spec_to_json(spec))
    _proof_written(order)
    orderstudio.approve(order, spec)


def test_finish_refuses_a_bleed_before_rendering(order, monkeypatch):
    _approve_spec(order, bleed_in=0.125)
    _no_render(monkeypatch)
    with pytest.raises(od.OrderError, match="a print with bleed cannot go to the roll"):
        orderfinish.finish(order.dir, dpi=DPI)
    assert not os.path.exists(os.path.join(order.dir, "out", "print"))


def test_finish_refuses_a_piece_the_roll_cannot_take_before_rendering(order, monkeypatch):
    od.write_state(order, {"print_in": [12.0, 18.0]})
    _approve_spec(order, print_w_in=12.0, print_h_in=18.0)
    _no_render(monkeypatch)
    with pytest.raises(papers.PaperError, match="does not fit the 17 in roll"):
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
    od.write_state(order, {"print_in": [17.0, 11.0]})          # a landscape 11x17 order
    od.set_manual(order, "spec", spec_to_json(spec))
    _proof_written(order)
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
    lines = []
    r2 = orderfinish.finish(approved.dir, dpi=DPI, log=lines.append)
    assert r2["files"] == r["files"]
    assert not os.path.exists(stale)
    assert "Removed: old-title-11x17.tif" in lines          # the log names the file
    assert _note(approved)[-1] == "Removed: old-title-11x17.tif"    # and so does PRINT.txt


def test_the_print_note_has_no_removed_line_when_nothing_was_removed(approved):
    orderfinish.finish(approved.dir, dpi=DPI)
    assert not any(line.startswith("Removed:") for line in _note(approved))


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


# --- a photo Finish cannot read, and a failure partway through the writes ---------------

def _spots(order, tmp_path, readable, gone):
    spec = orderspec.order_spec(order, od.read_state(order))
    cx, cy = (spec.crop[0] + spec.crop[2]) / 2, (spec.crop[1] + spec.crop[3]) / 2
    spots = []
    for k in range(readable):
        path = tmp_path / f"photo{k}.jpg"
        Image.new("RGB", (60, 40), (12, 200, 80)).save(path, "JPEG")
        spots.append({"x": cx + 500 * k, "y": cy, "weight": 1, "photo": str(path)})
    for k in range(gone):                   # swept from uploads/ after 24 h
        spots.append({"x": cx, "y": cy + 500 * (k + 1), "weight": 1,
                      "photo": str(tmp_path / f"swept{k}.jpg")})
    return spots


def test_finish_refuses_a_photo_it_can_no_longer_read(order, tmp_path, monkeypatch):
    _approve_spec(order, hotspots=_spots(order, tmp_path, readable=1, gone=2))
    _no_render(monkeypatch)
    with pytest.raises(od.OrderError) as ex:
        orderfinish.finish(order.dir, dpi=DPI)
    assert str(ex.value) == ("2 photo(s) on the approved proof can no longer be read: open "
                             "the order, attach them again, save and approve.")
    assert not os.path.exists(os.path.join(order.dir, "out", "print"))


def test_finish_prints_the_photos_it_can_read(order, tmp_path):
    from app import provenance
    _approve_spec(order, hotspots=_spots(order, tmp_path, readable=2, gone=0))
    orderfinish.finish(order.dir, dpi=DPI)
    manifest = provenance.extract(open(os.path.join(order.dir, "work", "record.png"),
                                       "rb").read())
    photos = [h.get("photo") for h in manifest["spec"]["hotspots"]]
    assert len(photos) == 2 and all(p.startswith(provenance.PHOTO_DATA_PREFIX) for p in photos)


# --- the order's photos: Finish refuses a tray photo and a band over 12 -----------------

TRAY = "{n} photos have no spot: place or drop them in the studio."
OVER = "{n} photos: the band holds 12. Drop some in the studio."


def _photo_state(order, placed, tray=0, dropped=0, layout="open", manual=None,
                 size=(60, 40), noisy=False):
    """State photos as Prepare leaves them: `placed` with a spot and a work JPEG on disk,
    `tray` with no spot (the first of them unreadable: no work JPEG), `dropped` placed but
    dropped. Then the spec is saved and approved. `manual` is manual.photos."""
    state = od.read_state(order)
    cx, cy = (state["frame"][0] + state["frame"][2]) / 2, \
        (state["frame"][1] + state["frame"][3]) / 2
    os.makedirs(os.path.join(order.dir, "work", "photos"), exist_ok=True)
    photos = []

    def entry(name, spot, work=True, **kw):
        rel = os.path.join("work", "photos", name + ".jpg")
        if work:
            if noisy:
                import numpy as np
                px = np.random.default_rng(len(photos)).integers(
                    0, 256, (size[1], size[0], 3), dtype=np.uint8)
                im = Image.fromarray(px, "RGB")
            else:
                im = Image.new("RGB", size, (12, 200, 80))
            im.save(os.path.join(order.dir, rel), "JPEG")
        photos.append({"file": name, "work": rel if work else None, "spot": spot,
                       "source": "gps" if spot else None, "caption": "", "box": None,
                       "crop": {"cx": 0.5, "cy": 0.5}, "dropped": False, "warnings": [],
                       **kw})
    for k in range(placed):
        entry(f"p{k:02d}", {"x": cx + 300 * k, "y": cy})
    for k in range(tray):
        entry(f"t{k:02d}", None, work=k > 0)
    for k in range(dropped):
        entry(f"d{k:02d}", {"x": cx, "y": cy + 300 * (k + 1)}, dropped=True)
    od.write_state(order, {"photos": photos, "photo_layout": layout,
                           "photo_band_side": "top"})
    if manual:
        od.set_manual(order, "photos", manual)
    return _save_and_approve(order)


def _no_print(order):
    assert not os.path.exists(os.path.join(order.dir, "out", "print"))


def test_finish_refuses_a_tray_photo(order, monkeypatch):
    _photo_state(order, placed=2, tray=2)          # one of them unreadable: still the tray
    _no_render(monkeypatch)
    with pytest.raises(od.OrderError) as ex:
        orderfinish.finish(order.dir, dpi=DPI)
    assert str(ex.value) == TRAY.format(n=2)
    _no_print(order)


def test_a_dropped_photo_and_a_photo_placed_by_hand_are_not_in_the_tray(order, tmp_path):
    cx = (od.read_state(order)["frame"][0] + od.read_state(order)["frame"][2]) / 2
    cy = (od.read_state(order)["frame"][1] + od.read_state(order)["frame"][3]) / 2
    _photo_state(order, placed=1, tray=2, dropped=1, manual={
        "t00": {"dropped": True},                  # the unreadable one: Dom dropped it
        "t01": {"spot": {"x": cx, "y": cy + 900}}})  # the other one: Dom placed it
    orderfinish.finish(order.dir, dpi=DPI)
    assert os.path.isdir(os.path.join(order.dir, "out", "print"))


def test_finish_refuses_more_than_12_photos(order, monkeypatch):
    _photo_state(order, placed=13, dropped=2, layout="band")   # a dropped one is not counted
    _no_render(monkeypatch)
    with pytest.raises(od.OrderError) as ex:
        orderfinish.finish(order.dir, dpi=DPI)
    assert str(ex.value) == OVER.format(n=13)
    _no_print(order)


def test_the_tray_is_refused_before_the_band_count(order, monkeypatch):
    _photo_state(order, placed=13, tray=1, layout="band")
    _no_render(monkeypatch)
    with pytest.raises(od.OrderError) as ex:
        orderfinish.finish(order.dir, dpi=DPI)
    assert str(ex.value) == TRAY.format(n=1)


def test_the_photo_refusals_come_after_the_approval_check(order, monkeypatch):
    _photo_state(order, placed=1, tray=1)
    od.write_state(order, {"approval": None})
    _no_render(monkeypatch)
    with pytest.raises(od.OrderError) as ex:
        orderfinish.finish(order.dir, dpi=DPI)
    assert str(ex.value) == orderfinish.NOT_APPROVED


def test_finish_embeds_placed_photos(order):
    from app import provenance
    _photo_state(order, placed=3, tray=0, dropped=1)
    orderfinish.finish(order.dir, dpi=DPI)
    manifest = provenance.extract(open(os.path.join(order.dir, "work", "record.png"),
                                       "rb").read())
    photos = [h.get("photo") for h in manifest["spec"]["hotspots"]]
    assert len(photos) == 3
    assert all(p.startswith(provenance.PHOTO_DATA_PREFIX) for p in photos)


def test_twelve_photos_in_the_band_are_printed(order):
    _photo_state(order, placed=12, layout="band")
    result = orderfinish.finish(order.dir, dpi=DPI)
    assert len(result["files"]) == 1


def test_finish_refuses_a_hand_placed_photo_with_no_work_jpeg(order, monkeypatch):
    state = od.read_state(order)
    cx, cy = state["frame"][0], state["frame"][1]
    # t00 has no work JPEG (Prepare could not read it); Dom clicked a spot for it anyway
    _photo_state(order, placed=1, tray=1, manual={"t00": {"spot": {"x": cx + 900, "y": cy}}})
    _no_render(monkeypatch)
    with pytest.raises(od.OrderError) as ex:
        orderfinish.finish(order.dir, dpi=DPI)
    assert str(ex.value) == "1 photos cannot be read: drop them in the studio."
    _no_print(order)


def test_the_tray_is_refused_before_an_unreadable_photo(order, monkeypatch):
    state = od.read_state(order)
    cx, cy = state["frame"][0], state["frame"][1]
    _photo_state(order, placed=0, tray=2, manual={"t00": {"spot": {"x": cx + 900, "y": cy}}})
    _no_render(monkeypatch)
    with pytest.raises(od.OrderError) as ex:
        orderfinish.finish(order.dir, dpi=DPI)
    assert str(ex.value) == TRAY.format(n=1)           # t01 is still in the tray


def test_the_print_is_painted_from_the_full_resolution_work_jpegs(order, monkeypatch):
    from app import provenance
    _photo_state(order, placed=2, size=(1500, 1000))
    seen = []
    real = provenance.load_photo

    def spy(value):
        im = real(value)
        seen.append((provenance.is_embedded_photo(value), im.size))
        return im
    monkeypatch.setattr(provenance, "load_photo", spy)
    orderfinish.finish(order.dir, dpi=DPI)
    # every photo the renderer opened was the order folder's own file, whole: never the
    # record's smaller embedded copy
    assert seen and all(not emb and size == (1500, 1000) for emb, size in seen)


def test_the_record_holds_the_photos_as_embedded_jpegs_the_print_does_not_need(order):
    from app import provenance
    _photo_state(order, placed=3, size=(1500, 1000))
    orderfinish.finish(order.dir, dpi=DPI)
    got = provenance.extract(open(os.path.join(order.dir, "work", "record.png"), "rb").read())
    assert got is not None
    assert len(provenance._manifest_str(got)) <= provenance.MAX_RECORD_MANIFEST_BYTES


def test_the_approval_hash_is_of_the_spec_with_paths_and_finish_leaves_it_be(order):
    spec = _photo_state(order, placed=2)
    state = od.read_state(order)
    assert all(not str(h["photo"]).startswith("data:") for h in spec.hotspots)
    before = state["approval"]["hash"]
    orderfinish.finish(order.dir, dpi=DPI)
    after = od.read_state(order)
    assert after["approval"]["hash"] == before
    assert orderstudio.approval_ok(order, after)


def test_two_finish_runs_write_the_same_record_bytes(order):
    _photo_state(order, placed=3, size=(1500, 1000))
    record = os.path.join(order.dir, "work", "record.png")
    orderfinish.finish(order.dir, dpi=DPI)
    first = open(record, "rb").read()
    orderfinish.finish(order.dir, dpi=DPI)
    assert open(record, "rb").read() == first


def test_a_record_that_cannot_be_read_back_puts_nothing_in_place(order, monkeypatch):
    from app import provenance
    _photo_state(order, placed=2)
    orderfinish.finish(order.dir, dpi=DPI)                  # an earlier run to keep whole
    before = _snapshot(order)
    monkeypatch.setattr(provenance, "extract", lambda png: None)
    with pytest.raises(od.OrderError) as ex:
        orderfinish.finish(order.dir, dpi=DPI)
    assert str(ex.value).startswith("The record could not be read back: ")
    assert _snapshot(order) == before and _leftover_temps(order) == []


def test_a_first_run_whose_record_cannot_be_read_back_writes_nothing(order, monkeypatch):
    from app import provenance
    _photo_state(order, placed=1)
    monkeypatch.setattr(provenance, "extract", lambda png: None)
    with pytest.raises(od.OrderError, match="The record could not be read back"):
        orderfinish.finish(order.dir, dpi=DPI)
    assert not os.path.exists(os.path.join(order.dir, "work", "record.png"))
    assert not [n for n in os.listdir(os.path.join(order.dir, "out", "print"))] \
        if os.path.isdir(os.path.join(order.dir, "out", "print")) else True


def test_the_note_says_so_when_the_record_carries_reduced_photos(order, monkeypatch):
    from app import provenance
    _photo_state(order, placed=2, size=(1500, 1000), noisy=True)
    orderfinish.finish(order.dir, dpi=60)           # a box of 125 px: noise that is not tiny
    note = open(os.path.join(order.dir, "out", "print", "PRINT.txt")).read()
    assert "reduced photos" not in note                    # the photos fit whole
    record = open(os.path.join(order.dir, "work", "record.png"), "rb").read()
    full = len(provenance._manifest_str(provenance.extract(record)))
    monkeypatch.setattr(provenance, "MAX_RECORD_MANIFEST_BYTES", full - 8_000)
    orderfinish.finish(order.dir, dpi=60)
    note = open(os.path.join(order.dir, "out", "print", "PRINT.txt")).read()
    assert ("record.png carries reduced photos (the 1 MB record limit); reprint from this "
            "order folder for full resolution.") in note.splitlines()
    record = open(os.path.join(order.dir, "work", "record.png"), "rb").read()
    assert len(provenance._manifest_str(provenance.extract(record))) <= full - 8_000


def _snapshot(order) -> dict:
    """Every file of a Finish, by path, with its bytes."""
    out = {}
    for folder in (os.path.join(order.dir, "out", "print"), order.work_dir):
        for name in sorted(os.listdir(folder)):
            path = os.path.join(folder, name)
            if os.path.isfile(path) and (folder != order.work_dir or name == "record.png"):
                out[path] = open(path, "rb").read()
    return out


def _leftover_temps(order) -> list:
    return [n for folder in (os.path.join(order.dir, "out", "print"), order.work_dir)
            for n in os.listdir(folder) if n.endswith(".tmp")]


@pytest.mark.parametrize("fail_on", [("TIFF", 2), ("PNG", 1)])
def test_a_write_that_fails_partway_keeps_the_last_run_whole(set_order, monkeypatch, fail_on):
    orderfinish.finish(set_order.dir, dpi=DPI)
    before = _snapshot(set_order)
    # a new approval whose pixels differ, with the same file names
    _approve_spec(set_order, title_text="Smith home ground, again")
    real_save = Image.Image.save
    seen = []

    def save(self, fp, format=None, **kw):
        seen.append(format)
        if format == fail_on[0] and seen.count(format) == fail_on[1]:
            raise OSError(28, "No space left on device")
        return real_save(self, fp, format, **kw)
    monkeypatch.setattr(Image.Image, "save", save)
    with pytest.raises(od.OrderError, match="No space left on device"):
        orderfinish.finish(set_order.dir, dpi=DPI)
    assert _snapshot(set_order) == before
    assert not _leftover_temps(set_order)


def test_a_stale_print_file_that_cannot_be_removed_stops_finish(approved, monkeypatch):
    orderfinish.finish(approved.dir, dpi=DPI)
    stale = os.path.join(approved.dir, "out", "print", "old-title-11x17.tif")
    with open(stale, "wb") as f:
        f.write(b"old")
    real_remove = os.remove

    def remove(path, *a, **k):
        if path == stale:
            raise PermissionError(13, "Permission denied")
        return real_remove(path, *a, **k)
    monkeypatch.setattr(os, "remove", remove)
    with pytest.raises(od.OrderError, match="old-title-11x17.tif.*Permission denied"):
        orderfinish.finish(approved.dir, dpi=DPI)
    assert not _leftover_temps(approved)


# --- final fix I2: a photo whose pixels changed after approval is a changed order --------

def test_finish_refuses_when_a_work_jpeg_changed_after_approval(order, monkeypatch):
    spec = _photo_state(order, placed=2)
    Image.new("RGB", (60, 40), (200, 20, 20)).save(spec.hotspots[0]["photo"], "JPEG")
    _no_render(monkeypatch)
    with pytest.raises(od.OrderError) as ex:
        orderfinish.finish(order.dir, dpi=DPI)
    assert str(ex.value) == orderfinish.CHANGED
    _no_print(order)


# --- final fix I3: a record over the 1 MB limit never stops a paid print -----------------

OVER_LINE = ("record.png is over the 1 MB record limit: it will not reopen in the studio; "
             "keep this order folder.")


def _huge_tracks(order, n=70_000):
    """One track of `n` points zig-zagging inside the frame: a manifest past 1 MiB."""
    import numpy as np
    f = od.read_state(order)["frame"]
    t = np.linspace(0.0, 1.0, n)
    xs = f[0] + (f[2] - f[0]) * (0.2 + 0.6 * t) + 0.123456789
    ys = f[1] + (f[3] - f[1]) * (0.5 + 0.3 * np.sin(t * 400.0)) + 0.987654321
    return [np.column_stack([xs, ys])]


def test_a_photo_less_order_whose_record_is_over_1_mib_still_finishes(order):
    from app import provenance
    _approve_spec(order, tracks=_huge_tracks(order), track_days=None)
    spec = orderspec.order_spec(order, od.read_state(order))
    assert len(provenance._manifest_str(provenance.build_manifest(spec))) > 1_048_576
    result = orderfinish.finish(order.dir, dpi=DPI)
    assert len(result["files"]) == 1 and os.path.isfile(result["files"][0])
    assert os.path.isfile(os.path.join(order.dir, "work", "record.png"))
    assert OVER_LINE in _note(order)


def test_a_record_whose_base_is_over_the_budget_keeps_its_photo_paths(order, monkeypatch):
    from app import provenance
    spec = _photo_state(order, placed=2)
    monkeypatch.setattr(provenance, "MAX_RECORD_MANIFEST_BYTES", 500)   # the base is over
    orderfinish.finish(order.dir, dpi=DPI)
    got = provenance.extract(open(os.path.join(order.dir, "work", "record.png"), "rb").read())
    photos = [h["photo"] for h in got["spec"]["hotspots"] if h.get("photo")]
    assert photos == [h["photo"] for h in spec.hotspots]              # paths, not JPEGs
    assert OVER_LINE in _note(order)
    assert not [n for n in _note(order) if "reduced photos" in n]


def test_an_over_budget_record_that_does_not_read_back_is_written_anyway(order, monkeypatch):
    from app import provenance
    _approve_spec(order)
    monkeypatch.setattr(provenance, "MAX_RECORD_MANIFEST_BYTES", 500)
    monkeypatch.setattr(provenance, "extract", lambda png: None)
    orderfinish.finish(order.dir, dpi=DPI)
    assert os.path.isfile(os.path.join(order.dir, "work", "record.png"))
    assert OVER_LINE in _note(order)


def test_a_record_under_the_budget_has_no_over_line(approved):
    orderfinish.finish(approved.dir, dpi=DPI)
    assert OVER_LINE not in _note(approved)


def test_a_record_that_does_not_read_back_never_says_run_finish_again(order, monkeypatch):
    from app import provenance
    _photo_state(order, placed=1)
    monkeypatch.setattr(provenance, "extract", lambda png: None)
    with pytest.raises(od.OrderError) as ex:
        orderfinish.finish(order.dir, dpi=DPI)
    assert "run Finish again" not in str(ex.value)
