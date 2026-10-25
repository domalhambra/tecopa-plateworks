# tests/test_orderprep_photos.py
# Prepare's photo step (order-photos Task 7): spots, captions, the layout, the warnings,
# and a second Prepare after studio edits. The plate is the Plan A stub build (no
# network); the proof is a fake, so nothing here renders a sheet.
import calendar
import json
import os
import sys

import pytest

from app import order as od
from app import orderplate as opl
from app import orderprep as op
from app import orderspec
from tests.test_orderprep import (LIDAR, SMALL, STUB_COVERAGE, STUB_LABELS, STUB_PREP,
                                  _Fake, _make_order)
from tests.test_photos import _make

T0 = calendar.timegm((2026, 10, 3, 16, 0, 0))          # the track starts, UTC
PEAK = ("Tecopa Peak", "summit", -116.208, 35.928)      # a named place in labels.json
NEAR_PEAK = (35.927, "N", 116.207, "W")                 # ~140 m from it
WEST = (35.915, "N", 116.200, "W")                      # ~1.3 km west of the track
FAR_AWAY = (36.3, "N", 116.0, "W")                      # in the lower 48, off the frame
BIG = (700, 500)                                        # past 2.25 in x 300 ppi

# The Plan A stub, plus a labels.json from STUB_LABELS_LONLAT ([name, kind, lon, lat])
STUB_PREP_LABELS = STUB_PREP + """
if os.environ.get("STUB_LABELS_LONLAT"):
    from pyproj import Transformer
    fwd = Transformer.from_crs("EPSG:4326", "EPSG:" + a.epsg, always_xy=True)
    feats = []
    for name, kind, lon, lat in json.loads(os.environ["STUB_LABELS_LONLAT"]):
        x, y = fwd.transform(lon, lat)
        feats.append({"name": name, "kind": kind, "rank": 1, "coords": [[x, y]]})
    json.dump({"crs": "EPSG:" + a.epsg, "features": feats},
              open(os.path.join(out, "labels.json"), "w"))
"""


@pytest.fixture
def tools(tmp_path, monkeypatch):
    """Plan A's tools stub (tests/test_orderprep.py), its plate with a labels.json."""
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    for name, body in (("prep.py", STUB_PREP_LABELS), ("coverage.py", STUB_COVERAGE),
                       ("labels.py", STUB_LABELS)):
        (stubs / name).write_text(body)
    (tmp_path / "curated").mkdir()
    monkeypatch.setenv("TECOPA_ORDERS_DIR", str(tmp_path / "orders"))
    monkeypatch.setenv("STUB_COVERAGE", json.dumps(LIDAR))
    monkeypatch.setenv("STUB_LABELS_LONLAT", json.dumps([list(PEAK)]))
    return op.Tools(prep_python=sys.executable, prep_script=str(stubs / "prep.py"),
                    labels_script=str(stubs / "labels.py"),
                    coverage_script=str(stubs / "coverage.py"),
                    repo_root=str(tmp_path), curated_root=str(tmp_path / "curated"))


def _timed_gpx(w, s, e, n):
    """Two points an hour apart: south-west at T0, north-east at T0 + 3600."""
    def iso(t):
        import time
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))
    pts = "".join(f'<trkpt lat="{lat}" lon="{lon}"><time>{iso(t)}</time></trkpt>'
                  for lon, lat, t in ((w, s, T0), (e, n, T0 + 3600)))
    return ('<?xml version="1.0"?><gpx version="1.1" creator="t" '
            'xmlns="http://www.topografix.com/GPX/1/1"><trk><name>t</name>'
            f"<trkseg>{pts}</trkseg></trk></gpx>")


def _order(tmp_path, size="12x18", extra=""):
    d = _make_order(tmp_path, size=size)
    (d / "in" / "trip.gpx").write_text(_timed_gpx(*SMALL))
    if extra:
        (d / "order.toml").write_text((d / "order.toml").read_text() + extra)
    return d


def _prepare(d, tools):
    return op.prepare(str(d), tools, log=lambda s: None, proofs=_Fake())


def _by_file(state):
    return {p["file"]: p for p in state["photos"]}


def test_photo_files_are_the_photos_in_in_by_name(tmp_path, tools):
    d = _order(tmp_path)
    _make(d / "in" / "b.JPG")
    _make(d / "in" / "a.heic.png")
    (d / "in" / ".hidden.jpg").write_bytes(b"x")
    names = [os.path.basename(p) for p in od.load(str(d)).photo_files()]
    assert names == ["a.heic.png", "b.JPG"]


def test_photos_get_spots_captions_and_boxes(tmp_path, tools):
    d = _order(tmp_path)
    _make(d / "in" / "a_gps.jpg", size=BIG, gps=NEAR_PEAK)
    _make(d / "in" / "b_time.jpg", size=BIG, taken="2026:10:03 09:30:00", offset="-07:00")
    before = {p.name: p.read_bytes() for p in (d / "in").iterdir()}
    state = _prepare(d, tools)
    assert [p["file"] for p in state["photos"]] == ["a_gps.jpg", "b_time.jpg"]
    a, b = state["photos"]
    assert a["source"] == "gps" and a["caption"] == "Tecopa Peak"
    assert b["source"] == "time" and b["caption"] == ""        # 2.6 km from the peak
    # the time spot is halfway along the track, as the photo is halfway in time
    from app.orderpreview import load_tracks_m
    t = load_tracks_m(od.load(str(d)).payloads(), state["epsg"])[0].coords
    assert b["spot"]["x"] == pytest.approx((t[0][0] + t[-1][0]) / 2, abs=0.5)
    assert b["spot"]["y"] == pytest.approx((t[0][1] + t[-1][1]) / 2, abs=0.5)
    assert state["photo_layout"] == "open" and state["band_frame"] is False
    assert state["photo_box_in"] == 2.25                       # B6 on 12 x 18
    for p in (a, b):
        assert set(p["box"]) == {"dx_in", "dy_in"}
        assert p["crop"] == {"cx": 0.5, "cy": 0.5}
        assert p["dropped"] is False and p["warnings"] == []
        assert os.path.isfile(os.path.join(str(d), p["work"]))
        assert p["work"].startswith(os.path.join("work", "photos") + os.sep)
    assert {p.name: p.read_bytes() for p in (d / "in").iterdir()} == before
    report = (d / "work" / "report.txt").read_text()
    assert ("Photos: 2 placed (1 by GPS, 1 by time, 0 by hand), 0 in the tray, "
            "0 dropped; layout open") in report


def test_a_photo_with_no_spot_goes_to_the_tray(tmp_path, tools):
    d = _order(tmp_path)
    _make(d / "in" / "nowhere.jpg", size=BIG)
    state = _prepare(d, tools)
    (p,) = state["photos"]
    assert p["spot"] is None and p["source"] is None and p["box"] is None
    assert p["caption"] == ""
    assert "Photos: 0 placed (0 by GPS, 0 by time, 0 by hand), 1 in the tray, 0 dropped; " \
           "layout open" in (d / "work" / "report.txt").read_text()


def test_small_and_outside_photos_are_warned(tmp_path, tools):
    d = _order(tmp_path)
    _make(d / "in" / "c_small.jpg", size=(60, 40), gps=NEAR_PEAK)
    _make(d / "in" / "d_far.jpg", size=BIG, gps=FAR_AWAY)
    state = _prepare(d, tools)
    small = "c_small.jpg: 60×40 px is small for a 2.25 in box at 300 ppi."
    far = "d_far.jpg: its spot is outside the frame. Widen the frame or drop it."
    photos = _by_file(state)
    assert photos["c_small.jpg"]["warnings"] == [small]
    assert photos["d_far.jpg"]["warnings"] == [far]
    assert small in state["warnings"] and far in state["warnings"]
    # the far photo is kept: its spot stays, it lays out no box, the small one still does
    assert photos["d_far.jpg"]["spot"] is not None and photos["d_far.jpg"]["box"] is None
    assert state["photo_layout"] == "open" and photos["c_small.jpg"]["box"] is not None
    report = (d / "work" / "report.txt").read_text()
    assert f"- {small}" in report and f"- {far}" in report


def test_an_unreadable_photo_is_warned_and_skipped(tmp_path, tools):
    d = _order(tmp_path)
    (d / "in" / "broken.jpg").write_bytes(b"not a picture at all")
    _make(d / "in" / "good.jpg", size=BIG, gps=NEAR_PEAK)
    state = _prepare(d, tools)
    photos = _by_file(state)
    bad = photos["broken.jpg"]
    assert bad["work"] is None and bad["spot"] is None
    assert len(bad["warnings"]) == 1 and bad["warnings"][0].startswith("broken.jpg: ")
    assert bad["warnings"][0] in state["warnings"]
    assert photos["good.jpg"]["source"] == "gps"
    assert not os.path.exists(d / "work" / "photos" / "broken.jpg.jpg")


def test_prepare_again_keeps_the_studio_edits_and_adds_new_photos(tmp_path, tools):
    d = _order(tmp_path)
    _make(d / "in" / "a.jpg", size=BIG, gps=NEAR_PEAK)
    _make(d / "in" / "b.jpg", size=BIG, taken="2026:10:03 09:30:00", offset="-07:00")
    _make(d / "in" / "c.jpg", size=BIG)                                  # the tray
    state = _prepare(d, tools)
    order = od.load(str(d))
    b_spot = _by_file(state)["b.jpg"]["spot"]
    hand = {"x": b_spot["x"] + 300.0, "y": b_spot["y"] - 400.0}
    edits = {"a.jpg": {"box": {"dx_in": 1.25, "dy_in": -1.75}, "caption": "Home",
                       "crop": {"cx": 0.2, "cy": 0.8}},
             "b.jpg": {"dropped": True},
             "c.jpg": {"spot": hand}}
    od.set_manual(order, "photos", edits)
    _make(d / "in" / "e.jpg", size=BIG, gps=WEST)                        # a new photo
    _make(d / "in" / "f.jpg", size=BIG)                                  # a new tray one
    state = _prepare(d, tools)
    photos = _by_file(state)
    assert list(photos) == ["a.jpg", "b.jpg", "c.jpg", "e.jpg", "f.jpg"]
    a, b, c, e, f = (photos[k] for k in photos)
    assert a["box"] == {"dx_in": 1.25, "dy_in": -1.75}                  # not moved
    assert (a["caption"], a["crop"]) == ("Home", {"cx": 0.2, "cy": 0.8})
    assert b["dropped"] is True and b["box"] is None
    assert c["spot"] == hand and c["source"] == "manual" and c["box"] is not None
    assert e["source"] == "gps" and e["box"] is not None
    assert f["spot"] is None and f["box"] is None
    assert od.read_state(order)["manual"]["photos"] == edits             # never erased
    assert ("Photos: 3 placed (1 by GPS, 0 by time, 1 by hand)"
            not in (d / "work" / "report.txt").read_text())
    assert ("Photos: 3 placed (2 by GPS, 0 by time, 1 by hand), 1 in the tray, "
            "1 dropped; layout open") in (d / "work" / "report.txt").read_text()


def test_a_band_grows_the_frame_upward(tmp_path, tools):
    d = _order(tmp_path)
    for k in range(opl_open_max() + 1):                     # past open ground: the band
        _make(d / "in" / f"p{k:02d}.jpg", size=BIG, gps=NEAR_PEAK)
    state = _prepare(d, tools)
    assert state["photo_layout"] == "band" and state["band_frame"] is True
    assert state["photo_band_side"] == "top"
    open_, frame = state["open_frame"], state["frame"]
    assert frame[1] == pytest.approx(open_[1])              # the bottom stays
    assert frame[3] > open_[3]                              # the top grows
    pw, ph = state["print_in"]
    assert (frame[2] - frame[0]) / (frame[3] - frame[1]) == pytest.approx(pw / ph)
    assert all(p["box"] is None for p in state["photos"])
    # the plate was planned round the frame grown at both ends: it holds either band
    region = json.load(open(os.path.join(orderspec.plate_dir(state), "region.json")))
    w, s, e, n = region["bbox"]
    lon0, lat0, lon1, lat1 = opl.to_lonlat_bbox(frame, state["epsg"])
    assert w <= lon0 and s <= lat0 and lon1 <= e and lat1 <= n
    assert "layout band" in (d / "work" / "report.txt").read_text()


def test_a_bottom_band_grows_the_frame_downward(tmp_path, tools):
    d = _order(tmp_path, extra='band_side = "bottom"\n')
    for k in range(opl_open_max() + 1):
        _make(d / "in" / f"p{k:02d}.jpg", size=BIG, gps=NEAR_PEAK)
    state = _prepare(d, tools)
    open_, frame = state["open_frame"], state["frame"]
    assert state["photo_band_side"] == "bottom"
    assert frame[3] == pytest.approx(open_[3]) and frame[1] < open_[1]


def test_more_than_the_band_holds_is_warned(tmp_path, tools):
    d = _order(tmp_path)
    for k in range(13):
        _make(d / "in" / f"p{k:02d}.jpg", size=BIG, gps=NEAR_PEAK)
    state = _prepare(d, tools)
    assert "13 photos: the band holds 12. Drop some in the studio." in state["warnings"]


def test_an_order_with_no_photos_plans_as_before(tmp_path, tools):
    d = _order(tmp_path)
    state = _prepare(d, tools)
    assert state["photos"] == [] and state["band_frame"] is False
    assert state["frame"] == state["open_frame"]
    assert "Photos:" not in (d / "work" / "report.txt").read_text()
    # adding a photo replans the plate round the grown frame: a new build
    _make(d / "in" / "a.jpg", size=BIG, gps=NEAR_PEAK)
    builds = (d / "work" / "plate" / "builds.log").read_text().split()
    state = _prepare(d, tools)
    assert len((d / "work" / "plate" / "builds.log").read_text().split()) == len(builds) + 1
    assert state["photo_plan"] is True


def test_a_photo_behind_a_gap_is_warned(tmp_path, tools):
    from tests.test_orderprep import WIDE
    d = _make_order(tmp_path, bbox=WIDE, size="two")
    state = _prepare(d, tools)
    # a spot on the frame's mid-line, inside the gap strip of a two-panel window set
    f = state["frame"]
    pw = state["print_in"][0]
    gap_mid_in = pw / 2
    x = f[0] + gap_mid_in / pw * (f[2] - f[0])
    y = (f[1] + f[3]) / 2
    from pyproj import Transformer
    lon, lat = Transformer.from_crs(f"EPSG:{state['epsg']}", "EPSG:4326",
                                    always_xy=True).transform(x, y)
    _make(d / "in" / "gap.jpg", size=BIG, gps=(lat, "N", -lon, "W"))
    state = _prepare(d, tools)
    assert any(w.startswith("Photo gap.jpg is behind gap 1") for w in state["warnings"])


def opl_open_max():
    from app.photolayout import OPEN_MAX
    return OPEN_MAX


def test_band_frame_and_plan_frame_keep_the_aspect():
    f = (0.0, 0.0, 1100.0, 1700.0)                        # 11 x 17 at 100 m per inch
    bh = 3.0
    top = opl.band_frame(f, 17.0, bh, "top")
    bottom = opl.band_frame(f, 17.0, bh, "bottom")
    plan = opl.photo_plan_frame(f, 17.0, bh)
    for g in (top, bottom, plan):
        assert (g[2] - g[0]) / (g[3] - g[1]) == pytest.approx(11 / 17)
    assert top[1] == f[1] and top[3] > f[3] and bottom[3] == f[3] and bottom[1] < f[1]
    # the band's ground is the band's inches at the band frame's scale
    gpi = (top[2] - top[0]) / 11.0
    assert top[3] - f[3] == pytest.approx(bh * gpi)
    for g in (top, bottom, f):
        assert plan[0] <= g[0] and plan[1] <= g[1] and g[2] <= plan[2] and g[3] <= plan[3]


def test_band_side_comes_from_order_toml(tmp_path, tools):
    d = _order(tmp_path)
    assert od.load(str(d)).band_side == "top"
    (d / "order.toml").write_text((d / "order.toml").read_text() + 'band_side = "left"\n')
    with pytest.raises(od.OrderError, match='band_side must be "top" or "bottom"'):
        od.load(str(d))


# --- fix round 1 -----------------------------------------------------------------------

def _band_order(tmp_path, extra=""):
    d = _order(tmp_path, extra=extra)
    for k in range(opl_open_max() + 1):
        _make(d / "in" / f"p{k:02d}.jpg", size=BIG, gps=NEAR_PEAK)
    return d


def test_holes_are_measured_on_the_frame_in_use(tmp_path, tools, monkeypatch):
    seen = []
    monkeypatch.setattr(op, "check_holes",
                        lambda tools, plate, frame, *a, **k: seen.append(list(frame)) or [])
    state = _prepare(_band_order(tmp_path), tools)
    assert state["band_frame"] is True
    assert seen == [state["frame"]] and state["frame"] != state["open_frame"]


def test_a_spot_under_the_band_is_outside_the_frame(tmp_path, tools):
    from app import render
    d = _band_order(tmp_path)
    state = _prepare(d, tools)
    order = od.load(str(d))
    spec = orderspec.order_spec(order, state)
    pw, ph = state["print_in"]
    strip = render._band_layout_in(spec, pw, ph)["strip"]
    x, y = orderspec.sheet_in_to_ground(spec, pw / 2, (strip[1] + strip[3]) / 2)
    from pyproj import Transformer
    lon, lat = Transformer.from_crs(f"EPSG:{state['epsg']}", "EPSG:4326",
                                    always_xy=True).transform(x, y)
    assert state["frame"][1] <= y <= state["frame"][3]           # inside the crop ...
    _make(d / "in" / "under.jpg", size=BIG, gps=(lat, "N", -lon, "W"))
    state = _prepare(d, tools)
    assert state["photo_layout"] == "band"
    under = _by_file(state)["under.jpg"]
    assert under["warnings"] == [                                  # ... but under the band
        "under.jpg: its spot is outside the frame. Widen the frame or drop it."]


def test_a_hand_placed_unreadable_photo_takes_no_part(tmp_path, tools):
    d = _order(tmp_path)
    for k in range(12):
        _make(d / "in" / f"p{k:02d}.jpg", size=BIG, gps=NEAR_PEAK)
    (d / "in" / "zz_broken.jpg").write_bytes(b"not a picture")
    state = _prepare(d, tools)
    spot = _by_file(state)["p00.jpg"]["spot"]
    od.set_manual(od.load(str(d)), "photos", {"zz_broken.jpg": {"spot": dict(spot)}})
    state = _prepare(d, tools)
    assert not any("the band holds 12" in w for w in state["warnings"])
    assert "Photos: 12 placed" in (d / "work" / "report.txt").read_text()


def test_a_hand_placed_unreadable_photo_is_not_laid_out(tmp_path, tools):
    d = _order(tmp_path)
    _make(d / "in" / "a.jpg", size=BIG, gps=NEAR_PEAK)
    (d / "in" / "b_broken.jpg").write_bytes(b"not a picture")
    _prepare(d, tools)
    od.set_manual(od.load(str(d)), "photos",
                  {"b_broken.jpg": {"spot": {"x": 1.0e9, "y": 1.0e9}}})    # far off the sheet
    state = _prepare(d, tools)
    photos = _by_file(state)
    assert state["photo_layout"] == "open" and photos["b_broken.jpg"]["box"] is None
    assert photos["a.jpg"]["box"] is not None
    assert not any("b_broken.jpg: its spot is outside" in w for w in state["warnings"])


def test_an_odd_exif_value_never_fails_prepare(tmp_path, tools, monkeypatch):
    from app import photospot
    real = photospot.spot_for

    def odd(meta, tracks, region):
        if meta.name == "odd.jpg":
            raise TypeError("an EXIF rational with a zero denominator")
        return real(meta, tracks, region)
    monkeypatch.setattr(photospot, "spot_for", odd)
    d = _order(tmp_path)
    _make(d / "in" / "good.jpg", size=BIG, gps=NEAR_PEAK)
    _make(d / "in" / "odd.jpg", size=BIG, gps=NEAR_PEAK)
    state = _prepare(d, tools)
    odd_entry = _by_file(state)["odd.jpg"]
    assert odd_entry["spot"] is None and odd_entry["work"] is not None    # Dom can place it
    assert len(odd_entry["warnings"]) == 1
    assert odd_entry["warnings"][0].startswith("odd.jpg: its place or time could not be read")
    assert _by_file(state)["good.jpg"]["source"] == "gps"


def test_a_layout_that_fails_hangs_the_photos_in_the_band(tmp_path, tools, monkeypatch):
    from app import render

    def boom(*a, **k):
        raise ValueError("boom")
    monkeypatch.setattr(render, "occupancy", boom)
    d = _order(tmp_path)
    _make(d / "in" / "a.jpg", size=BIG, gps=NEAR_PEAK)
    state = _prepare(d, tools)
    assert state["photo_layout"] == "band" and state["band_frame"] is True
    assert op.PHOTO_LAYOUT_FAILED.format(why="boom") in state["warnings"]


def test_a_manual_frame_is_the_open_frame(tmp_path, tools):
    d = _band_order(tmp_path)
    state = _prepare(d, tools)
    f = state["open_frame"]
    moved = [f[0] + 100.0, f[1] + 100.0, f[2] + 100.0, f[3] + 100.0]
    od.set_manual(od.load(str(d)), "frame", moved)
    state = _prepare(d, tools)
    assert state["open_frame"] == pytest.approx(moved)              # never grown twice
    bh = orderspec.band_height_for(state["photo_box_in"])
    assert state["frame"] == pytest.approx(
        list(opl.band_frame(moved, state["print_in"][1], bh, "top")))


def test_a_hole_in_a_photo_orders_frame_leads_the_warnings(tmp_path, tools, monkeypatch):
    monkeypatch.setenv("STUB_DEM_HOLES", "frame")
    d = _band_order(tmp_path)
    state = _prepare(d, tools)
    assert state["warnings"][0].startswith("HOLES IN THE PRINT")
    assert state["plate"]["frame_nan_share"] > 0
    # a second Prepare (the plate is current) keeps the hole note where it was
    state = _prepare(d, tools)
    assert state["warnings"][0].startswith("HOLES IN THE PRINT")


# --- fix round 2 -----------------------------------------------------------------------

def test_a_hand_placed_unreadable_photo_inside_the_crop_is_not_placed(tmp_path, tools):
    d = _order(tmp_path)
    _make(d / "in" / "a.jpg", size=BIG, gps=NEAR_PEAK)
    (d / "in" / "b_broken.jpg").write_bytes(b"not a picture")
    state = _prepare(d, tools)
    spot = _by_file(state)["a.jpg"]["spot"]
    inside = {"x": spot["x"] + 500.0, "y": spot["y"] - 500.0}
    f = state["frame"]
    assert f[0] < inside["x"] < f[2] and f[1] < inside["y"] < f[3]
    od.set_manual(od.load(str(d)), "photos", {"b_broken.jpg": {"spot": inside}})
    state = _prepare(d, tools)
    broken = _by_file(state)["b_broken.jpg"]
    assert broken["spot"] == inside and broken["box"] is None
    assert _by_file(state)["a.jpg"]["box"] is not None
    assert "Photos: 1 placed (1 by GPS, 0 by time, 0 by hand), 1 in the tray" \
        in (d / "work" / "report.txt").read_text()


def test_a_caption_that_cannot_be_found_never_fails_prepare(tmp_path, tools, monkeypatch):
    from app import photocaption
    d = _order(tmp_path)
    _make(d / "in" / "tray.jpg", size=BIG)                     # no GPS, no time
    state = _prepare(d, tools)
    od.set_manual(od.load(str(d)), "photos",
                  {"tray.jpg": {"spot": dict(_by_file(state)["tray.jpg"]["spot"] or
                                             {"x": (state["frame"][0] + state["frame"][2]) / 2,
                                              "y": (state["frame"][1] + state["frame"][3]) / 2})}})

    def boom(*a, **k):
        raise ValueError("a labels.json feature with no coordinates")
    monkeypatch.setattr(photocaption, "nearest_name", boom)
    state = _prepare(d, tools)
    p = _by_file(state)["tray.jpg"]
    assert p["source"] == "manual" and p["caption"] == ""
    assert p["warnings"] == [op.PHOTO_NO_CAPTION.format(
        file="tray.jpg", why="ValueError: a labels.json feature with no coordinates")]
    assert p["warnings"][0] in state["warnings"]


def _record_holes(monkeypatch):
    seen = []

    def fake(tools, plate, frame, *a, **k):
        seen.append(list(frame))
        return [f"HOLES IN THE PRINT: frame {len(seen)}", f"plate note {len(seen)}"]
    monkeypatch.setattr(op, "check_holes", fake)
    return seen


def test_holes_follow_the_frame_when_the_layout_flips_on_a_current_plate(
        tmp_path, tools, monkeypatch):
    seen = _record_holes(monkeypatch)
    d = _order(tmp_path)
    _make(d / "in" / "p00.jpg", size=BIG, gps=NEAR_PEAK)
    state = _prepare(d, tools)
    assert state["photo_layout"] == "open" and seen == [state["frame"]]
    for k in range(1, opl_open_max() + 1):                  # past open ground: the band
        _make(d / "in" / f"p{k:02d}.jpg", size=BIG, gps=NEAR_PEAK)
    state = _prepare(d, tools)
    assert state["photo_layout"] == "band" and len(_builds_of(d)) == 1   # plate current
    assert seen[-1] == state["frame"] != state["open_frame"]
    assert state["warnings"][0] == "HOLES IN THE PRINT: frame 2"
    assert "plate note 2" in state["warnings"]
    assert not any(w.endswith(" 1") for w in state["warnings"])          # old notes gone
    # the frame unchanged: no new measure
    state = _prepare(d, tools)
    assert len(seen) == 2 and state["warnings"][0] == "HOLES IN THE PRINT: frame 2"


def test_a_studio_band_side_change_measures_the_new_frame(tmp_path, tools, monkeypatch):
    seen = _record_holes(monkeypatch)
    d = _band_order(tmp_path)
    state = _prepare(d, tools)
    order = od.load(str(d))
    od.set_manual(order, "band_side", "bottom")
    state = op.place_photos(order, od.read_state(order), log=lambda s: None, tools=tools)
    assert state["photo_band_side"] == "bottom" and seen[-1] == state["frame"]
    assert state["warnings"][0] == "HOLES IN THE PRINT: frame 2"


def test_a_curated_plate_is_never_measured_again(tmp_path, tools, monkeypatch):
    seen = _record_holes(monkeypatch)
    d = _band_order(tmp_path)
    state = _prepare(d, tools)
    order = od.load(str(d))
    od.write_state(order, {"plate": {**state["plate"], "kind": "curated"}})
    od.set_manual(order, "band_side", "bottom")
    op.place_photos(order, od.read_state(order), log=lambda s: None, tools=tools)
    assert len(seen) == 1


def _builds_of(d):
    return (d / "work" / "plate" / "builds.log").read_text().split()


# --- final fix I1: photos removed from in/ leave no trace on a saved spec ----------------

def test_photos_removed_from_in_leave_the_saved_spec(tmp_path, tools):
    from app.serialize import spec_to_json
    d = _order(tmp_path)
    for k in range(opl_open_max() + 1):                     # the band
        _make(d / "in" / f"p{k:02d}.jpg", size=BIG, gps=NEAR_PEAK)
    state = _prepare(d, tools)
    order = od.load(str(d))
    assert state["photo_layout"] == "band"
    saved = spec_to_json(orderspec.order_spec(order, state))
    saved["hotspots"].append({"x": 1.0, "y": 2.0, "weight": 1, "label": "a marker"})
    od.update_manual(order, {"spec": saved, "spec_inputs_hash": state["inputs_hash"]})
    for p in (d / "in").glob("p*.jpg"):
        p.unlink()
    state = _prepare(d, tools)
    assert state["photos"] == [] and od.read_state(order)["manual"].get("spec")
    s = orderspec.order_spec(order, state)
    assert not [hs for hs in s.hotspots if hs.get("photo")]
    assert [hs.get("label") for hs in s.hotspots] == ["a marker"]       # a plain marker stays
    assert s.photo_layout == "open"
    assert s.crop == pytest.approx(tuple(state["open_frame"]))
    assert s.crop == pytest.approx(tuple(state["frame"]))


# --- final fix I2: the work JPEG follows the photo's bytes, and the approval does too ----

def _replace_older(path, colour=(200, 30, 30)):
    """The same-named photo with other pixels and the same EXIF, its mtime set back a day:
    a newer work JPEG must not hide it."""
    from PIL import Image
    with Image.open(path) as im:
        exif, size = im.getexif(), im.size
    before = os.stat(path).st_mtime
    Image.new("RGB", size, colour).save(path, exif=exif)
    os.utime(path, (before - 86400, before - 86400))


def test_a_replaced_photo_with_an_older_mtime_rewrites_its_work_jpeg(tmp_path, tools):
    import hashlib
    d = _order(tmp_path)
    src = _make(d / "in" / "a.jpg", size=BIG, gps=NEAR_PEAK)
    state = _prepare(d, tools)
    (a,) = state["photos"]
    assert a["sha256"] == hashlib.sha256(open(src, "rb").read()).hexdigest()
    work = os.path.join(str(d), a["work"])
    first = open(work, "rb").read()
    _replace_older(src)
    assert os.path.getmtime(work) > os.path.getmtime(src)
    state = _prepare(d, tools)
    (a,) = state["photos"]
    assert a["sha256"] == hashlib.sha256(open(src, "rb").read()).hexdigest()
    assert open(work, "rb").read() != first


def test_a_photo_that_did_not_change_keeps_its_work_jpeg(tmp_path, tools):
    d = _order(tmp_path)
    _make(d / "in" / "a.jpg", size=BIG, gps=NEAR_PEAK)
    state = _prepare(d, tools)
    work = os.path.join(str(d), state["photos"][0]["work"])
    stamp = os.stat(work).st_mtime_ns
    _prepare(d, tools)
    assert os.stat(work).st_mtime_ns == stamp


def test_a_photo_replaced_after_approval_voids_it(tmp_path, tools):
    from app import orderstudio
    from app.serialize import spec_to_json
    d = _order(tmp_path)
    src = _make(d / "in" / "a.jpg", size=BIG, gps=NEAR_PEAK)
    state = _prepare(d, tools)
    order = od.load(str(d))
    spec = orderspec.order_spec(order, state)
    od.set_manual(order, "spec", spec_to_json(spec))
    od.write_state(order, {"approval": {"at": "x", "hash": orderspec.spec_hash(spec)}})
    assert orderstudio.approval_ok(order, od.read_state(order))
    _replace_older(src)
    state = _prepare(d, tools)
    assert state["approval"] is not None                      # the same plate: kept
    assert not orderstudio.approval_ok(order, state)          # but no longer this print
