# tests/test_orderspec.py
# One spec for an order: the proof, the studio and Finish all paint what order_spec
# returns. The plate is the synthetic Lassen mirror; the fixture is order_with_plate
# in tests/conftest.py.
import dataclasses
import json
import os

import pytest

from app import orderspec
from app.order import OrderError, read_state, set_manual, write_state
from app.serialize import spec_to_json


@pytest.fixture
def order(order_with_plate):
    return order_with_plate


def test_default_spec_frames_as_prepare_did(order):
    s = orderspec.order_spec(order, read_state(order))
    assert s.crop == tuple(read_state(order)["frame"]) and s.title_text == order.title


def test_default_spec_is_the_one_the_proof_draws(order):
    st = read_state(order)
    s = orderspec.default_spec(order, st)
    cfg = json.load(open(os.path.join(orderspec.plate_dir(st), "region.json")))
    assert (s.region_id, s.crs) == (cfg["id"], cfg["crs"])
    assert s.native_resolution_m == cfg["native_resolution_m"]
    assert (s.print_w_in, s.print_h_in) == (11.0, 17.0)
    assert (s.panels, s.panel_gap_in) == (1, 0.0)
    assert len(s.tracks) == 1 and s.hotspots == [] and s.seed == 7
    assert s.labels is True                       # the plate holds labels.json
    for k, v in orderspec.ORDER_LOOK.items():
        assert getattr(s, k) == v
    s.validate()


def test_default_spec_has_no_labels_without_labels_json(order):
    st = read_state(order)
    # the mirror's files are symlinks into the shared plate: copy the plate aside
    import shutil
    src = orderspec.plate_dir(st)
    dst = os.path.join(order.work_dir, "p2", "copy")
    shutil.copytree(src, dst, symlinks=False)
    os.remove(os.path.join(dst, "labels.json"))
    write_state(order, {"plate": {**st["plate"], "root": os.path.dirname(dst),
                                  "id": "copy"}})
    assert orderspec.default_spec(order, read_state(order)).labels is False


def test_a_saved_spec_wins_but_follows_the_current_plate(order):
    st = read_state(order)
    saved = spec_to_json(orderspec.default_spec(order, st))
    saved["region_id"] = "old_plate"
    saved["native_resolution_m"] = 99
    saved["title_text"] = "Edited"
    set_manual(order, "spec", saved)
    s = orderspec.order_spec(order, read_state(order))
    assert s.title_text == "Edited" and s.region_id == st["plate"]["id"]
    assert s.crs == "EPSG:32610" and s.native_resolution_m == 10


def test_order_spec_refuses_a_saved_spec_in_another_projection(order):
    saved = spec_to_json(orderspec.default_spec(order, read_state(order)))
    saved["crs"] = "EPSG:32611"
    set_manual(order, "spec", saved)
    with pytest.raises(OrderError, match="projection changed since the studio save"):
        orderspec.order_spec(order, read_state(order))


def test_the_hash_follows_the_spec(order):
    a = orderspec.default_spec(order, read_state(order))
    assert orderspec.spec_hash(a) == orderspec.spec_hash(a)
    assert orderspec.spec_hash(a) != orderspec.spec_hash(
        dataclasses.replace(a, title_text="x"))
    assert len(orderspec.spec_hash(a)) == 64


def test_the_hash_is_the_same_for_a_spec_read_back(order):
    from app.serialize import spec_from_json
    a = orderspec.default_spec(order, read_state(order))
    b = spec_from_json(json.loads(json.dumps(spec_to_json(a))))
    assert orderspec.spec_hash(a) == orderspec.spec_hash(b)


def test_a_title_with_no_letters_names_files_poster():
    assert orderspec.file_stem("★ !!") == "poster"
    assert orderspec.file_stem("") == "poster"


def test_a_title_names_files_by_its_slug():
    assert orderspec.file_stem("Smith home ground!") == "smith_home_ground"


def test_orderpreview_keeps_its_name_for_the_look():
    from app import orderpreview
    assert orderpreview.PREVIEW_LOOK is orderspec.ORDER_LOOK


def test_no_plate_says_run_prepare(order):
    with pytest.raises(OrderError, match="Run Prepare"):
        orderspec.plate_dir({})
    with pytest.raises(OrderError, match="Run Prepare"):
        orderspec.order_spec(order, {"frame": [0, 0, 1, 1]})


def test_a_plate_with_no_region_json_says_run_prepare(order, tmp_path):
    st = {**read_state(order), "plate": {"id": "gone", "root": str(tmp_path)}}
    with pytest.raises(OrderError, match="Run Prepare"):
        orderspec.plate_dir(st)


def test_orderspec_does_not_import_the_app():
    import subprocess
    import sys
    code = ("import sys, app.orderspec, app.orderpreview, app.credit; "
            "assert 'app.main' not in sys.modules")
    subprocess.run([sys.executable, "-c", code], check=True)


def test_a_spec_at_the_orders_size_matches_it(order):
    st = read_state(order)
    assert orderspec.matches_order(orderspec.default_spec(order, st), st) is None


@pytest.mark.parametrize("change", [dict(print_w_in=17.0, print_h_in=22.0),
                                    dict(panels=2), dict(panel_gap_in=2.0)])
def test_a_spec_of_another_size_panels_or_gap_does_not_match(order, change):
    st = read_state(order)
    spec = dataclasses.replace(orderspec.default_spec(order, st), **change)
    why = orderspec.matches_order(spec, st)
    assert why and "11 x 17 in" in why


def test_a_state_from_before_sets_matches_a_single_sheet(order):
    st = read_state(order)
    spec = orderspec.default_spec(order, st)
    old = {k: v for k, v in st.items() if k not in ("panels", "gap")}
    assert orderspec.matches_order(spec, old) is None


def test_the_default_spec_carries_the_plates_credit(order):
    from app import credit
    st = read_state(order)
    s = orderspec.default_spec(order, st)
    assert s.credit_text == credit.credit_text(orderspec.plate_dir(st))
    assert s.credit_text.startswith("Terrain USGS 3DEP")


# --- order photos (Task 7): the photo state becomes the spec's photo hotspots ----------

def _photo(order, name, spot, **kw):
    """A state.json photo entry with its work JPEG on disk, as Prepare writes one."""
    from PIL import Image
    work = os.path.join("work", "photos", name + ".jpg")
    os.makedirs(os.path.join(order.dir, "work", "photos"), exist_ok=True)
    Image.new("RGB", (40, 30), (90, 60, 30)).save(os.path.join(order.dir, work))
    entry = {"file": name, "work": work, "spot": spot, "source": "gps" if spot else None,
             "caption": "", "box": None, "crop": {"cx": 0.5, "cy": 0.5},
             "dropped": False, "warnings": []}
    entry.update(kw)
    return entry


def _with_photos(order, photos, layout="open", box_in=2.09, side="top"):
    write_state(order, {"photos": photos, "photo_layout": layout,
                        "photo_box_in": box_in, "photo_band_side": side})
    return read_state(order)


def _centre(st):
    f = st["frame"]
    return {"x": (f[0] + f[2]) / 2, "y": (f[1] + f[3]) / 2}


def test_default_spec_turns_placed_photos_into_hotspots(order):
    st = read_state(order)
    c = _centre(st)
    st = _with_photos(order, [
        _photo(order, "a.jpg", c, caption="Butte Lake", box={"dx_in": 1.5, "dy_in": -2.0}),
        _photo(order, "b.jpg", {"x": c["x"] + 500, "y": c["y"]}, source="time",
               crop={"cx": 0.25, "cy": 0.75}, box={"dx_in": -1.0, "dy_in": 1.0}),
        _photo(order, "c.jpg", None),                                    # the tray
        _photo(order, "d.jpg", c, dropped=True),                         # dropped
    ])
    s = orderspec.default_spec(order, st)
    assert (s.photo_layout, s.photo_box_in, s.photo_band_side) == ("open", 2.09, "top")
    assert [hs["label"] for hs in s.hotspots] == ["Butte Lake", ""]
    a, b = s.hotspots
    assert a == {"x": c["x"], "y": c["y"], "weight": 1, "label": "Butte Lake",
                 "photo": os.path.join(order.dir, "work", "photos", "a.jpg.jpg"),
                 "box": {"dx_in": 1.5, "dy_in": -2.0}, "crop": {"cx": 0.5, "cy": 0.5},
                 "source": "gps"}
    assert os.path.isabs(a["photo"]) and a["photo"].startswith(order.dir + os.sep)
    assert b["source"] == "time" and b["crop"] == {"cx": 0.25, "cy": 0.75}
    s.validate()


def test_a_band_photo_carries_no_box(order):
    st = read_state(order)
    st = _with_photos(order, [_photo(order, "a.jpg", _centre(st))], layout="band",
                      side="bottom")
    s = orderspec.default_spec(order, st)
    assert (s.photo_layout, s.photo_band_side) == ("band", "bottom")
    assert "box" not in s.hotspots[0]


def test_an_order_with_no_photos_keeps_the_spec_it_had(order):
    st = read_state(order)
    before = orderspec.spec_hash(orderspec.default_spec(order, st))
    st = _with_photos(order, [], box_in=2.09)
    s = orderspec.default_spec(order, st)
    assert s.hotspots == [] and s.photo_box_in == 1.5 and s.photo_layout == "open"
    assert orderspec.spec_hash(s) == before


def test_the_studio_edits_win_field_by_field(order):
    st = read_state(order)
    c = _centre(st)
    hand = {"x": c["x"] - 800.0, "y": c["y"] + 900.0}
    st = _with_photos(order, [_photo(order, "a.jpg", c, caption="Prepare's"),
                              _photo(order, "b.jpg", None),
                              _photo(order, "c.jpg", c)])
    set_manual(order, "photos", {"a.jpg": {"caption": "Dom's", "crop": {"cx": 0.1, "cy": 0.9}},
                                 "b.jpg": {"spot": hand},
                                 "c.jpg": {"dropped": True}})
    s = orderspec.default_spec(order, read_state(order))
    a, b = s.hotspots
    assert (a["label"], a["crop"], a["source"]) == ("Dom's", {"cx": 0.1, "cy": 0.9}, "gps")
    assert (b["x"], b["y"], b["source"]) == (hand["x"], hand["y"], "manual")


def test_a_crafted_manual_photo_is_bounded(order):
    st = read_state(order)
    st = _with_photos(order, [_photo(order, "a.jpg", _centre(st))])
    set_manual(order, "photos", {"a.jpg": {"box": {"dx_in": 1e9, "dy_in": 0.0, "evil": 1},
                                           "crop": {"cx": float("nan"), "cy": 0.5},
                                           "caption": {"not": "text"},
                                           "spot": {"x": "here", "y": 1.0}}})
    (hs,) = orderspec.default_spec(order, read_state(order)).hotspots
    assert "box" not in hs and "crop" not in hs
    assert hs["label"] == "" and hs["source"] == "gps"          # the bad spot is ignored


def test_a_saved_spec_picks_up_a_photo_edit(order):
    st = read_state(order)
    st = _with_photos(order, [_photo(order, "a.jpg", _centre(st), caption="First")])
    saved = spec_to_json(orderspec.default_spec(order, st))
    saved["title_text"] = "Edited"
    saved["hotspots"].append({"x": 1.0, "y": 2.0, "weight": 1, "label": "a marker"})
    set_manual(order, "spec", saved)
    set_manual(order, "photos", {"a.jpg": {"caption": "Second"}})
    _with_photos(order, read_state(order)["photos"], layout="band", box_in=2.5, side="bottom")
    s = orderspec.order_spec(order, read_state(order))
    assert s.title_text == "Edited"                              # the save's own edit
    assert (s.photo_layout, s.photo_box_in, s.photo_band_side) == ("band", 2.5, "bottom")
    labels = [hs.get("label") for hs in s.hotspots]
    assert labels == ["a marker", "Second"]                     # a plain marker stays


def test_a_saved_spec_of_an_order_with_no_photos_is_as_saved(order):
    st = read_state(order)
    saved = spec_to_json(orderspec.default_spec(order, st))
    saved["hotspots"] = [{"x": 1.0, "y": 2.0, "weight": 1, "label": "a marker"}]
    saved["photo_box_in"] = 1.75
    set_manual(order, "spec", saved)
    from app.serialize import spec_from_json
    want = orderspec.spec_hash(dataclasses.replace(
        spec_from_json(saved), region_id=st["plate"]["id"]))
    assert orderspec.spec_hash(orderspec.order_spec(order, read_state(order))) == want


def test_ground_and_sheet_inches_round_trip(order):
    s = orderspec.default_spec(order, read_state(order))
    x0, y0, x1, y1 = s.crop
    assert orderspec.ground_to_sheet_in(s, x0, y1) == pytest.approx((0.0, 0.0))
    assert orderspec.ground_to_sheet_in(s, x1, y0) == pytest.approx((11.0, 17.0))
    assert orderspec.sheet_in_to_ground(s, 0.0, 0.0) == pytest.approx((x0, y1))
    for x, y in ((x0 + 1234.5, y0 + 6789.0), (x1 + 50.0, y1 + 10.0)):
        xi, yi = orderspec.ground_to_sheet_in(s, x, y)
        assert orderspec.sheet_in_to_ground(s, xi, yi) == pytest.approx((x, y))
    # y runs down the sheet: a spot north of the centre is above the middle
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    assert orderspec.ground_to_sheet_in(s, cx, cy + 100.0)[1] < 8.5


@pytest.mark.parametrize("size,panels,want", [((11.0, 17.0), 1, 2.09),
                                               ((12.0, 18.0), 1, 2.25),
                                               ((17.0, 22.0), 1, 2.96),
                                               ((46.0, 17.0), 2, 2.96)])
def test_the_photo_box_scales_with_the_sheet(size, panels, want):
    assert orderspec.photo_box_in(size, panels) == want


# --- fix round 1, A: a saved crop follows the photo layout as Prepare's frame does -----

def _layout_spec(order, box_in=2.09):
    return dataclasses.replace(orderspec.default_spec(order, read_state(order)),
                               photo_box_in=box_in)


def test_crop_for_layout_keeps_a_crop_whose_layout_stands(order):
    s = _layout_spec(order)
    c = s.crop
    assert orderspec.crop_for_layout(c, "open", "top", "open", "bottom", s) == c
    assert orderspec.crop_for_layout(c, "band", "top", "band", "top", s) == c


def test_crop_for_layout_grows_shrinks_and_swaps_as_prepare_frames(order):
    from app import orderplate as opl
    s = _layout_spec(order)
    c, bh = s.crop, orderspec.band_height_for(2.09)
    top = orderspec.crop_for_layout(c, "open", "top", "band", "top", s)
    assert top == pytest.approx(opl.band_frame(c, 17.0, bh, "top"))
    assert top[1] == pytest.approx(c[1]) and top[3] > c[3]           # grows upward
    back = orderspec.crop_for_layout(top, "band", "top", "open", "top", s)
    assert back == pytest.approx(c)                                    # band -> open
    bottom = orderspec.crop_for_layout(top, "band", "top", "band", "bottom", s)
    assert bottom == pytest.approx(opl.band_frame(c, 17.0, bh, "bottom"))
    assert bottom[3] == pytest.approx(c[3]) and bottom[1] < c[1]      # the other end


def test_a_saved_open_crop_grows_when_the_photos_go_to_the_band(order):
    from app import orderplate as opl
    st = read_state(order)
    st = _with_photos(order, [_photo(order, "a.jpg", _centre(st))])
    saved = spec_to_json(orderspec.default_spec(order, st))          # open, the frame
    set_manual(order, "spec", saved)
    _with_photos(order, read_state(order)["photos"], layout="band", side="bottom")
    s = orderspec.order_spec(order, read_state(order))
    bh = orderspec.band_height_for(2.09)
    assert s.crop == pytest.approx(opl.band_frame(tuple(saved["crop"]), 17.0, bh, "bottom"))
    _with_photos(order, read_state(order)["photos"], layout="open")
    assert orderspec.order_spec(order, read_state(order)).crop == pytest.approx(
        tuple(saved["crop"]))


# --- final fix I2: the hash covers an order photo's pixels, and nothing else changed ----

def _fixed_spec(**kw):
    from app.spec import CompositionSpec
    return CompositionSpec(
        region_id="lassen_ca", crs="EPSG:32610",
        crop=(600000.0, 4480000.0, 611000.0, 4497000.0), print_w_in=11.0,
        print_h_in=17.0, native_resolution_m=10.0,
        tracks=[[(601000.0, 4481000.0), (610000.0, 4496000.0)]], track_days=[0], seed=7,
        title_text="Smith home ground",
        hotspots=[{"x": 605000.0, "y": 4490000.0, "weight": 1, "label": "a marker"}], **kw)


# spec_hash of _fixed_spec() as this branch serialized it BEFORE the photo digests (I2) were
# added: it proves only that I2 left photo-less hashing unchanged on this branch. It is not
# a hash from main: this branch added two spec fields (photo_layout, photo_band_side), so
# every spec hashes differently here than on main, and an order approved on main needs
# approving again after the merge. The `viewshed` field moved it again, as any new field
# does: every field reaches the JSON, so an order approved before it is approved again.
PHOTOLESS_HASH_BEFORE_PHOTO_DIGESTS = (
    "d858d23e7fbe8502284acf4a7495121e2317b1ceb4833ebc77cfe409aa378bb5")


def test_a_spec_with_no_order_photo_hashes_as_it_did_before_photo_digests():
    import hashlib
    s = _fixed_spec()
    text = json.dumps(spec_to_json(s), sort_keys=True, separators=(",", ":"))
    assert orderspec.spec_hash(s) == hashlib.sha256(text.encode()).hexdigest()
    assert orderspec.spec_hash(s) == PHOTOLESS_HASH_BEFORE_PHOTO_DIGESTS


def test_the_hash_follows_an_order_photos_pixels(order):
    from PIL import Image
    st = read_state(order)
    st = _with_photos(order, [_photo(order, "a.jpg", _centre(st))])
    s = orderspec.default_spec(order, st)
    before = orderspec.spec_hash(s)
    assert orderspec.spec_hash(s) == before                  # the same bytes, the same hash
    work = s.hotspots[0]["photo"]
    Image.new("RGB", (40, 30), (10, 200, 30)).save(work)      # same path, other pixels
    assert orderspec.spec_hash(s) != before
    assert s.hotspots[0]["photo"] == work and "photo_sha256" not in s.hotspots[0]


# --- the wash (viewshed wash spec, decisions 10, 18-20): an order's waypoints ----------

def _waypoint(order, dx, dy, label="", **kw):
    """A waypoint hotspot as app.ingest makes one, `dx` and `dy` metres from the centre
    of the order's frame, in the plate's CRS."""
    c = _centre(read_state(order))
    hs = {"x": c["x"] + dx, "y": c["y"] + dy, "weight": 3, "label": label, "icon": "flag",
          "mark": True}
    hs.update(kw)
    return hs


def _gpx_with_waypoints(order, waypoints):
    """Rewrite in/trip.gpx so its file carries `waypoints` (hotspots) as <wpt> elements,
    the way a customer's phone exports them."""
    from pyproj import Transformer
    crs = json.load(open(os.path.join(orderspec.plate_dir(read_state(order)),
                                      "region.json")))["crs"]
    to_ll = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
    path = os.path.join(order.in_dir, "trip.gpx")
    text = open(path).read()
    wpts = "".join(f'<wpt lat="{lat}" lon="{lon}"><name>{w["label"]}</name></wpt>'
                   for w in waypoints for lon, lat in [to_ll.transform(w["x"], w["y"])])
    open(path, "w").write(text.replace("<trk>", wpts + "<trk>", 1))


def _asking(order, line="viewshed = true"):
    """The order again, loaded from an order.toml that carries the key."""
    from app import order as od
    path = os.path.join(order.dir, "order.toml")
    text = "".join(l for l in open(path) if not l.startswith("viewshed"))
    open(path, "w").write(text + (line + "\n" if line else ""))
    return od.load(order.dir)


def _pixels(spec, order, state, dpi=20):
    import numpy as np
    from app import render
    return np.asarray(render.rasterize(spec, dpi=dpi,
                                       region_dir=orderspec.plate_dir(state)))


def test_an_order_without_the_key_is_unchanged(order):
    # the same order folder, with a GPX that holds waypoints and a state that holds some
    # from an earlier run with the key: nothing about the spec moves, so neither does a pixel
    st = read_state(order)
    plain_default = orderspec.default_spec(order, st)
    plain_saved = orderspec.order_spec(order, st)
    plain_pixels = _pixels(plain_default, order, st)
    waypoints = [_waypoint(order, -1500, 800, "Elk camp"), _waypoint(order, 2500, -900)]
    _gpx_with_waypoints(order, waypoints)
    write_state(order, {"waypoints": waypoints})
    st = read_state(order)
    assert order.viewshed == 0.0 and orderspec.waypoint_hotspots(order, st) == []
    default, saved = orderspec.default_spec(order, st), orderspec.order_spec(order, st)
    assert default.hotspots == [] and saved.hotspots == [] == plain_default.hotspots
    assert default.viewshed == 0.0 and saved.viewshed == 0.0
    assert orderspec.spec_hash(default) == orderspec.spec_hash(plain_default)
    assert orderspec.spec_hash(saved) == orderspec.spec_hash(plain_saved)
    assert (_pixels(default, order, st) == plain_pixels).all()
    assert (_pixels(saved, order, st) == plain_pixels).all()


def test_an_order_with_the_key_carries_its_waypoints(order):
    c = _centre(read_state(order))
    waypoints = [_waypoint(order, -1500, 800, "Elk camp"), _waypoint(order, 2500, -900)]
    write_state(order, {"waypoints": waypoints})
    asking = _asking(order)
    st = read_state(order)
    assert orderspec.waypoint_hotspots(asking, st) == waypoints
    spec = orderspec.default_spec(asking, st)
    assert spec.hotspots == waypoints and spec.viewshed == 0.6
    assert all(hs["mark"] is True for hs in spec.hotspots)
    spec.validate()
    assert orderspec.order_spec(asking, st).hotspots == waypoints


def test_a_number_in_the_key_is_the_specs_strength(order):
    write_state(order, {"waypoints": [_waypoint(order, 100, 100)]})
    asking = _asking(order, "viewshed = 0.8")
    assert asking.viewshed == 0.8
    assert orderspec.default_spec(asking, read_state(order)).viewshed == 0.8


def test_the_waypoints_go_ahead_of_the_photos(order):
    st = read_state(order)
    waypoints = [_waypoint(order, -1500, 800, "Elk camp"), _waypoint(order, 2500, -900)]
    write_state(order, {"waypoints": waypoints})
    asking = _asking(order)
    st = _with_photos(order, [_photo(order, "a.jpg", _centre(st), caption="Butte Lake")])
    spec = orderspec.default_spec(asking, st)
    assert [hs.get("label") for hs in spec.hotspots] == ["Elk camp", "", "Butte Lake"]
    assert spec.hotspots[:2] == waypoints and spec.hotspots[2]["photo"]
    spec.validate()


def test_the_approval_covers_the_waypoints(order):
    waypoints = [_waypoint(order, -1500, 800, "Elk camp"), _waypoint(order, 2500, -900)]
    write_state(order, {"waypoints": waypoints})
    asking = _asking(order)

    def digest(wps=None, who=asking):
        if wps is not None:
            write_state(order, {"waypoints": wps})
        st = read_state(order)
        return orderspec.spec_hash(orderspec.order_spec(who, st))
    base = digest()
    assert digest() == base                                      # the same waypoints
    moved = [{**waypoints[0], "x": waypoints[0]["x"] + 40.0}, waypoints[1]]
    assert digest(moved) != base                                 # a waypoint moved
    renamed = [{**waypoints[0], "label": "Camp two"}, waypoints[1]]
    assert digest(renamed) != base                               # one renamed
    assert digest(waypoints[:1]) != base                         # one gone
    assert digest(waypoints + [_waypoint(order, 10, 10)]) != base   # one more
    assert digest(waypoints) == base
    # the strength is part of what is approved too
    assert digest(who=_asking(order, "viewshed = 0.9")) != base


def test_a_saved_studio_spec_keeps_its_waypoints(order):
    # RB1's replace keeps the saved spec's plain hotspots as it does today: the waypoints
    # the studio saved stay once, ahead of the photos that state gives now
    st = read_state(order)
    waypoints = [_waypoint(order, -1500, 800, "Elk camp"), _waypoint(order, 2500, -900)]
    write_state(order, {"waypoints": waypoints})
    asking = _asking(order)
    st = _with_photos(order, [_photo(order, "a.jpg", _centre(st), caption="First")])
    saved = spec_to_json(orderspec.default_spec(asking, st))
    saved["title_text"] = "Edited"
    set_manual(order, "spec", saved)
    set_manual(order, "photos", {"a.jpg": {"caption": "Second"}})
    spec = orderspec.order_spec(asking, read_state(order))
    assert spec.title_text == "Edited" and spec.viewshed == 0.6
    assert [hs.get("label") for hs in spec.hotspots] == ["Elk camp", "", "Second"]
    assert spec.hotspots[:2] == waypoints                        # once each, not doubled
    # and a save with no photos keeps them as saved
    saved2 = spec_to_json(orderspec.default_spec(asking, read_state(order)))
    set_manual(order, "spec", saved2)
    write_state(order, {"photos": []})
    assert orderspec.order_spec(asking, read_state(order)).hotspots[:2] == waypoints


def test_a_state_from_before_waypoints_still_works_with_the_key(order):
    st = read_state(order)
    assert "waypoints" not in st
    asking = _asking(order)
    assert orderspec.waypoint_hotspots(asking, st) == []
    spec = orderspec.default_spec(asking, st)
    assert spec.hotspots == [] and spec.viewshed == 0.6          # the pass sees no marks: a no-op
    assert orderspec.order_spec(asking, st).hotspots == []


@pytest.mark.parametrize("junk", [None, "x", 7, [], {"x": 1.0}, {"x": "a", "y": 2.0},
                                  {"x": float("nan"), "y": 1.0}, {"x": 1.0, "y": float("inf")},
                                  {"x": True, "y": 1.0}])
def test_a_malformed_waypoint_in_the_state_is_left_out(order, junk):
    good = _waypoint(order, 10, 10, "ok")
    write_state(order, {"waypoints": [junk, good]})
    asking = _asking(order)
    assert orderspec.waypoint_hotspots(asking, read_state(order)) == [good]
    write_state(order, {"waypoints": "not a list"})
    assert orderspec.waypoint_hotspots(asking, read_state(order)) == []


def test_the_spec_does_not_share_the_states_waypoint_dicts(order):
    write_state(order, {"waypoints": [_waypoint(order, 10, 10, "ok")]})
    asking = _asking(order)
    st = read_state(order)
    got = orderspec.waypoint_hotspots(asking, st)
    got[0]["label"] = "changed"
    assert st["waypoints"][0]["label"] == "ok"
