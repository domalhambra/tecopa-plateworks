# The marketing farm renders with the look a customer's poster carries by default
# (orderspec.ORDER_LOOK), so the page shows what an order ships. A plate may override
# one field of the look; the rest stays the customer's.
import json
import os
import shutil

from conftest import synthetic_region
from app import render
from app.orderspec import ORDER_LOOK
from app.regions import Region
from scripts.render_asset_farm import _base_spec


def _region(rid="lassen_ca"):
    plate = synthetic_region(rid)
    return Region(rid, root=os.path.dirname(plate))


def test_farm_renders_the_order_look():
    spec = _base_spec(_region(), [], [])
    for k, v in ORDER_LOOK.items():
        assert getattr(spec, k) == v


def test_a_plate_look_overrides_one_field_only():
    spec = _base_spec(_region(), [], [], look={"haze_strength": 0.4})
    assert spec.haze_strength == 0.4
    assert spec.soft_light == ORDER_LOOK["soft_light"]
    assert spec.biome is True


def test_full_look_renders_on_a_plate_with_no_landcover_labels_or_playa(tmp_path):
    src = synthetic_region("lassen_ca")
    with open(os.path.join(src, "region.json")) as f:
        cfg = json.load(f)
    dst = tmp_path / "bare_plate"
    dst.mkdir()
    shutil.copy(os.path.join(src, "region.json"), dst / "region.json")
    dem = cfg.get("dem_path", "dem.tif")
    shutil.copy(os.path.join(src, dem), dst / dem)
    assert sorted(os.listdir(dst)) == sorted(["region.json", dem])
    region = Region("bare_plate", root=str(tmp_path))
    spec = _base_spec(region, [], [])
    img = render.rasterize(spec, dpi=40, region_dir=region.dir, watermark=False,
                           cfg=region.cfg)
    assert img.size[0] > 0 and img.size[1] > 0


# ---- pinned photos (Pick-a-plate phase B, task 5) ----
# The marketing farm pins one demo photo on each poster. Without a story it pins
# spots[0], as it always has. A story's `photo_at` names the spot that carries the
# photo, and `photo_file` makes it a real photograph instead of the gradient.
import numpy as np
import pytest
from PIL import Image

import scripts.render_asset_farm as farm
from app.ingest import Track
from scripts.track_network import PinError


def _spots():
    return [{"x": 1.0, "y": 2.0, "weight": 1, "label": "Near Summit"},
            {"x": 3.0, "y": 4.0, "weight": 1, "label": "Mount Tallac"},
            {"x": 5.0, "y": 6.0, "weight": 1, "label": "Road Lake"}]


def _pinned(spots):
    return [s["label"] for s in spots if "photo" in s]


def test_no_story_pins_spots_0_as_today(tmp_path):
    out = farm._annotate(_spots(), str(tmp_path))
    assert _pinned(out) == ["Near Summit"]


def test_a_story_with_photo_at_pins_that_spot_only(tmp_path):
    out = farm._annotate(_spots(), str(tmp_path), story={"photo_at": "Mount Tallac"})
    assert _pinned(out) == ["Mount Tallac"]


def test_a_story_with_no_photo_at_pins_nothing(tmp_path):
    out = farm._annotate(_spots(), str(tmp_path), story={"destinations": ["Near Summit"]})
    assert _pinned(out) == []


def test_a_photo_at_matching_no_spot_raises_pin_error(tmp_path):
    with pytest.raises(PinError, match="Nowhere Peak"):
        farm._annotate(_spots(), str(tmp_path), story={"photo_at": "Nowhere Peak"})


def test_photo_file_wins_over_the_gradient(tmp_path):
    real = tmp_path / "tallac.jpg"
    Image.new("RGB", (30, 20), (9, 8, 7)).save(real)
    out_dir = tmp_path / "out"
    out = farm._annotate(_spots(), str(out_dir),
                         story={"photo_at": "Mount Tallac", "photo_file": str(real)})
    assert next(s for s in out if s["label"] == "Mount Tallac")["photo"] == str(real)
    assert not (out_dir / "_demo_photo.png").exists()


def test_photo_at_with_no_photo_file_falls_back_to_the_gradient(tmp_path):
    out = farm._annotate(_spots(), str(tmp_path), story={"photo_at": "Mount Tallac"})
    assert os.path.basename(
        next(s for s in out if s["label"] == "Mount Tallac")["photo"]) == "_demo_photo.png"


def test_a_missing_photo_file_raises_pin_error(tmp_path):
    with pytest.raises(PinError, match="gone.jpg"):
        farm._annotate(_spots(), str(tmp_path),
                       story={"photo_at": "Mount Tallac",
                              "photo_file": str(tmp_path / "gone.jpg")})


class _EdRegion:
    id = "stub"
    dir = ""
    cfg = {"bounds": [0, 0, 1, 1]}


def _ed_tracks(*names):
    return [Track(track_id=f"summit:{n}", coords=np.zeros((4, 2)), day="2024-07-01")
            for n in names]


def test_an_edition_without_the_photo_at_spot_pins_nothing_and_does_not_raise(tmp_path):
    story = {"photo_at": "Mount Tallac"}
    sub = _ed_tracks("Near Summit")            # edition 1 has not reached Tallac
    eds = farm._edition_spots(sub, _spots(), _EdRegion(), str(tmp_path), story=story)
    assert [s["label"] for s in eds] == ["Near Summit"]
    assert _pinned(eds) == []


def test_an_edition_that_reached_the_photo_at_spot_pins_it(tmp_path):
    story = {"photo_at": "Mount Tallac"}
    sub = _ed_tracks("Near Summit", "Mount Tallac")
    spots = farm._annotate(_spots(), str(tmp_path), story=story)    # the poster pinned it
    eds = farm._edition_spots(sub, spots, _EdRegion(), str(tmp_path), story=story)
    assert _pinned(eds) == ["Mount Tallac"]


def test_a_pin_error_escapes_demo_journeys(tmp_path, monkeypatch):
    # _demo_journeys catches OSError, ValueError and KeyError around the network
    # build; a story that pins a place the plate lacks must still stop the run.
    cache = tmp_path / "cache" / "networks"
    cache.mkdir(parents=True)
    (cache / "stub.json").write_text("{}")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(farm, "story_for", lambda rid: {"photo_at": "Nowhere Peak"})
    monkeypatch.setattr(farm, "load_network", lambda p: {})
    monkeypatch.setattr(farm, "network_tracks",
                        lambda region, net, story=None: ([], _spots()))
    with pytest.raises(PinError, match="Nowhere Peak"):
        farm._demo_journeys(_EdRegion(), str(tmp_path / "out"))


def test_the_photos_folder_is_gitignored():
    import subprocess
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    r = subprocess.run(["git", "check-ignore", "-q", "marketing/photos/x.jpg"], cwd=repo)
    assert r.returncode == 0


def test_tahoe_and_zion_name_their_photo_spot_and_the_others_name_none():
    from scripts.story_config import load_stories
    stories = load_stories()
    assert stories["tahoe_ca"]["photo_at"] == "Mount Tallac"
    assert stories["zion_ut"]["photo_at"] == "Angels Landing"
    for rid in ("canyonlands_ut", "eastern_sierra_ca", "ruby_mountains_nv"):
        assert "photo_at" not in stories[rid] and "photo_file" not in stories[rid]
