# tests/test_orderpreview_render.py
# The preview's real map painter, once, on the synthetic lassen_ca plate. The stub
# plates of tests/test_orderpreview.py cannot be rendered.
import json
import os

import numpy as np
from PIL import Image

from app import orderpreview as opv
from app import panels
from app.ingest import Track
from tests.conftest import synthetic_region

REGION_DIR = synthetic_region("lassen_ca")


def _tracks():
    b = json.load(open(os.path.join(REGION_DIR, "region.json")))["bounds"]
    cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
    coords = np.array([[cx - 15000.0, cy - 2000.0], [cx, cy + 2000.0], [cx + 15000.0, cy - 2000.0]])
    return [Track("t-0", coords, "2024-06-01")]


def test_each_offered_size_is_drawn_at_screen_size_with_its_gaps(tmp_path, monkeypatch):
    from app import render
    real, words = render.rasterize, []

    def spy(spec, **kw):                    # the real painter, and what it was asked for
        words.append((kw.get("watermark"), kw.get("watermark_text")))
        return real(spec, **kw)
    monkeypatch.setattr(render, "rasterize", spy)
    tracks = _tracks()
    pts = tracks[0].coords
    bounds = (pts[:, 0].min(), pts[:, 1].min(), pts[:, 0].max(), pts[:, 1].max())
    entries = opv.plan_sizes(bounds, [t.coords for t in tracks])
    by_key = {e["key"]: e for e in entries}
    assert by_key["three"]["offered"] and by_key["three"]["orientation"] == "landscape"
    opv.render_maps(entries, tracks, REGION_DIR, "Lassen walk", str(tmp_path))
    for e in entries:
        if not e["offered"]:
            assert "image" not in e
            continue
        img = Image.open(e["image"])
        w_in, h_in = e["print_in"]
        if e["panels"] == 1:
            assert max(img.size) == 1600
        else:
            assert img.size == (round(w_in * 50), round(h_in * 50))
        assert abs(img.size[0] / img.size[1] - w_in / h_in) < 0.01
    three = np.asarray(Image.open(by_key["three"]["image"]).convert("RGB"))
    assert three.shape == (850, 3500, 3)
    assert (three[:, 1100:1200] == panels.WALL_TONE).all()      # 22 in, then a 2 in strip
    assert (three[:, 2300:2400] == panels.WALL_TONE).all()      # and the second strip
    assert not (three[:, 1000:1100] == panels.WALL_TONE).all()
    assert not (three[:, 2400:2500] == panels.WALL_TONE).all()
    assert words == [(True, "PREVIEW")] * 4                     # every map says PREVIEW
    plain = np.asarray(Image.open(by_key["17x22"]["image"]).convert("RGB"))
    assert len(np.unique(plain.reshape(-1, 3), axis=0)) > 500   # a real picture, not a flat fill


def test_a_frame_past_the_terrain_is_left_out_and_the_rest_is_drawn(tmp_path):
    # the real painter refuses a frame with too much no-data (OffDemError): one size
    # lost that way must not lose the whole preview after the plate is built
    b = json.load(open(os.path.join(REGION_DIR, "region.json")))["bounds"]
    cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
    coords = np.array([[cx - 10000.0, cy - 10000.0], [cx + 10000.0, cy + 10000.0]])
    tracks = [Track("t-0", coords, "2024-06-01")]
    entries = opv.plan_sizes((cx - 10000.0, cy - 10000.0, cx + 10000.0, cy + 10000.0),
                             [coords], forced=("11x17", "three"))
    by_key = {e["key"]: e for e in entries}
    wide = by_key["three"]["frame"]
    assert wide[2] - wide[0] > b[2] - b[0]                  # the set is wider than the plate
    opv.render_maps(entries, tracks, REGION_DIR, "Lassen walk", str(tmp_path))
    assert not by_key["three"]["offered"] and "image" not in by_key["three"]
    assert by_key["three"]["why"].startswith("The selected frame extends past the available "
                                             "elevation data")
    assert by_key["11x17"]["offered"]
    assert sorted(p.name for p in tmp_path.iterdir()) == ["11x17.png"]
    assert max(Image.open(by_key["11x17"]["image"]).size) == 1600


def test_a_title_past_the_specs_limit_refuses_every_size(tmp_path):
    # preview() stops such a title before any plate (tests/test_orderpreview.py); here
    # the painter's own refusal is held as a reason, like any other SpecError
    from app.spec import TITLE_MAX_CHARS
    tracks = _tracks()
    pts = tracks[0].coords
    bounds = (pts[:, 0].min(), pts[:, 1].min(), pts[:, 0].max(), pts[:, 1].max())
    entries = opv.plan_sizes(bounds, [t.coords for t in tracks])
    assert all(e["offered"] for e in entries)
    opv.render_maps(entries, tracks, REGION_DIR, "x" * (TITLE_MAX_CHARS + 1), str(tmp_path))
    for e in entries:
        assert not e["offered"] and "image" not in e
        assert e["why"] == f"title_text must be at most {TITLE_MAX_CHARS} characters"
    assert list(tmp_path.iterdir()) == []                   # no map was written


# ---- the wash: with the key, a second map of each size (viewshed wash, decision 20) ----

def _waypoints():
    """Three waypoints on the Lassen plate, in its CRS, two near the track."""
    b = json.load(open(os.path.join(REGION_DIR, "region.json")))["bounds"]
    cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
    return [{"x": cx - 9000.0, "y": cy - 1500.0, "weight": 3, "label": "Camp",
             "icon": "flag", "mark": True},
            {"x": cx + 1000.0, "y": cy + 2500.0, "weight": 3, "label": "",
             "icon": "flag", "mark": True},
            {"x": cx + 11000.0, "y": cy - 900.0, "weight": 3, "label": "Spring",
             "icon": "water", "mark": True}]


def _entries(tracks):
    pts = tracks[0].coords
    bounds = (pts[:, 0].min(), pts[:, 1].min(), pts[:, 0].max(), pts[:, 1].max())
    return opv.plan_sizes(bounds, [t.coords for t in tracks], forced=("11x17", "three"))


def test_preview_shows_both_with_the_key(tmp_path, monkeypatch):
    from app import render
    real, asked = render.rasterize, []

    def spy(spec, **kw):
        asked.append((spec.viewshed, len(spec.hotspots), kw.get("watermark_text")))
        return real(spec, **kw)
    monkeypatch.setattr(render, "rasterize", spy)
    tracks = _tracks()
    entries = _entries(tracks)
    opv.render_maps(entries, tracks, REGION_DIR, "Lassen walk", str(tmp_path),
                    waypoints=_waypoints(), viewshed=0.6)
    for e in entries:
        if not e["offered"]:                        # forced: only these two are drawn
            assert "image" not in e and "wash_image" not in e
            continue
        assert e["image"] == str(tmp_path / f"{e['key']}.png")
        assert e["wash_image"] == str(tmp_path / f"{e['key']}-wash.png")
        plain, wash = Image.open(e["image"]), Image.open(e["wash_image"])
        assert plain.size == wash.size             # one picture, two looks
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "11x17-wash.png", "11x17.png", "three-wash.png", "three.png"]
    # the plain map is what it always was: no marks, no wash. The second has both.
    assert asked == [(0.0, 0, "PREVIEW"), (0.6, 3, "PREVIEW")] * 2
    one = {e["key"]: e for e in entries}["11x17"]
    a = np.asarray(Image.open(one["image"]).convert("RGB")).astype(int)
    b = np.asarray(Image.open(one["wash_image"]).convert("RGB")).astype(int)
    assert (a != b).any()                       # pins and the quieted ground are drawn


def test_the_plain_map_is_the_same_with_the_key_as_without(tmp_path):
    tracks = _tracks()
    with_key, without = tmp_path / "with", tmp_path / "without"
    entries = _entries(tracks)
    opv.render_maps(entries, tracks, REGION_DIR, "Lassen walk", str(with_key),
                    waypoints=_waypoints(), viewshed=0.6)
    opv.render_maps(_entries(tracks), tracks, REGION_DIR, "Lassen walk", str(without))
    for key in ("11x17", "three"):
        assert (with_key / f"{key}.png").read_bytes() == (without / f"{key}.png").read_bytes()


def test_preview_shows_one_without_the_key(tmp_path):
    tracks = _tracks()
    for kw in ({}, dict(waypoints=_waypoints()), dict(waypoints=_waypoints(), viewshed=0.0),
               dict(viewshed=0.6), dict(waypoints=[], viewshed=0.6)):
        out = tmp_path / str(len(list(tmp_path.iterdir())))
        entries = _entries(tracks)
        opv.render_maps(entries, tracks, REGION_DIR, "Lassen walk", str(out), **kw)
        assert all("wash_image" not in e for e in entries)      # nothing to show, no second map
        assert sorted(p.name for p in out.iterdir()) == ["11x17.png", "three.png"]


def test_a_refused_size_leaves_neither_map(tmp_path):
    b = json.load(open(os.path.join(REGION_DIR, "region.json")))["bounds"]
    cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
    coords = np.array([[cx - 10000.0, cy - 10000.0], [cx + 10000.0, cy + 10000.0]])
    tracks = [Track("t-0", coords, "2024-06-01")]
    entries = opv.plan_sizes((cx - 10000.0, cy - 10000.0, cx + 10000.0, cy + 10000.0),
                             [coords], forced=("11x17", "three"))
    opv.render_maps(entries, tracks, REGION_DIR, "Lassen walk", str(tmp_path),
                    waypoints=_waypoints(), viewshed=0.6)
    by_key = {e["key"]: e for e in entries}
    assert not by_key["three"]["offered"]
    assert "image" not in by_key["three"] and "wash_image" not in by_key["three"]
    assert sorted(p.name for p in tmp_path.iterdir()) == ["11x17-wash.png", "11x17.png"]
