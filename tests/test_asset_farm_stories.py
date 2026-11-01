# The farm's `stories` and `journey` tiers (Pick-a-plate phase B, task 6). Each showcase
# plate tells a three-section story on the landing page. The `stories` tier cuts each
# section's crop from print pixels (never upscaled), the `journey` tier renders the
# poster a second time lit by the plate's own sun, and the exporter (see
# test_export_relief.py) turns the crops into web images.
#
# What these pin: the window maths (exact print size, shifted not shrunk at the sheet's
# edge, a known ground point on a known pixel, tied to a real render), the journey pair
# differing only in light, a plate looking the same in every image, a section with no
# window failing by its heading, a plate with no story writing nothing, and the
# ship-check naming the plates that still carry the demo photo.
import dataclasses
import os

import numpy as np
import pytest
from PIL import Image

from conftest import synthetic_region
from app.geo import RegionGeo, crs_to_overview_px
from app.ingest import Track
from app.orderspec import ORDER_LOOK
from app.regions import Region
from app.render import TRACK_INK
import scripts.render_asset_farm as farm
from scripts import story_config
from scripts.story_config import StoryError

DPI = 100


def _region(rid="lassen_ca"):
    plate = synthetic_region(rid)
    return Region(rid, root=os.path.dirname(plate))


# a 600 x 800 px sheet that covers 6 km x 8 km: one pixel is 10 m
CROP = (1000.0, 2000.0, 7000.0, 10000.0)
SIZE = (600, 800)


# ---- crop_window --------------------------------------------------------------------

def test_crop_window_keeps_print_pixels():
    # 3.3 in at 300 dpi is 990 px; the float product is 990.0000000000001
    x0, y0, x1, y1 = farm.crop_window((4000.0, 6000.0), (3.3, 2.0), CROP, SIZE, 100)
    assert (x1 - x0, y1 - y0) == (330, 200)
    x0, y0, x1, y1 = farm.crop_window((4000.0, 6000.0), (2.0, 2.0), CROP, (1800, 2400), 300)
    assert (x1 - x0, y1 - y0) == (600, 600)


def test_a_known_ground_point_lands_on_a_known_pixel():
    # (4000, 6000) m is 3 km east and 4 km south of the sheet's corner (1000, 10000)
    # minus 8 km: 300 px across and 400 px down, so a 200 px window centres on it
    assert farm.crop_window((4000.0, 6000.0), (2.0, 2.0), CROP, SIZE, 100) == \
        (200, 300, 400, 500)
    geo = RegionGeo("EPSG:32610", CROP, SIZE)
    assert crs_to_overview_px(geo, 4000.0, 6000.0) == (300.0, 400.0)


def test_crop_window_shifts_inside_the_sheet_and_keeps_its_size():
    # a point 50 px from the left edge and 20 px from the top would centre a 200 px
    # window past both; the window slides in and keeps 200 x 200
    cx, cy = 1000.0 + 50 * 10, 10000.0 - 20 * 10
    assert farm.crop_window((cx, cy), (2.0, 2.0), CROP, SIZE, 100) == (0, 0, 200, 200)
    # and the far corner
    cx, cy = 7000.0 - 30 * 10, 2000.0 + 10 * 10
    assert farm.crop_window((cx, cy), (2.0, 2.0), CROP, SIZE, 100) == \
        (400, 600, 600, 800)


def test_crop_window_bigger_than_the_sheet_refuses():
    with pytest.raises(StoryError, match="sheet"):
        farm.crop_window((4000.0, 6000.0), (7.0, 2.0), CROP, SIZE, 100)
    with pytest.raises(StoryError, match="sheet"):
        farm.crop_window((4000.0, 6000.0), (2.0, 9.0), CROP, SIZE, 100)


def test_a_centre_off_the_sheet_refuses():
    # a window that quietly slid to the edge would show the wrong country
    with pytest.raises(StoryError, match="off the sheet"):
        farm.crop_window((9000.0, 6000.0), (2.0, 2.0), CROP, SIZE, 100)


def test_foot_anchor_takes_the_bottom_of_the_sheet():
    # the elevation strip sits in the lower left of the sheet
    x0, y0, x1, y1 = farm.crop_window(None, (4.0, 2.0), CROP, SIZE, 100, anchor="foot")
    assert (x0, y0, x1, y1) == (0, 600, 400, 800)
    with pytest.raises(StoryError, match="anchor"):
        farm.crop_window(None, (4.0, 2.0), CROP, SIZE, 100, anchor="roof")


def test_a_ground_point_lands_on_its_pixel_in_a_real_render(tmp_path):
    # the window maths and the painter must agree: draw a route with known ground
    # corners and find its ink on the sheet
    region = _region()
    crop, _pw, _ph = farm._frame(region)
    cx = crop[0] + 0.3 * (crop[2] - crop[0])
    cy = crop[1] + 0.7 * (crop[3] - crop[1])
    corners = np.array([[cx - 3000, cy], [cx + 3000, cy], [cx + 3000, cy + 3000]])
    track = Track(track_id="probe", coords=corners, day="2024-07-01")
    path, size = farm._poster(region, [track], [], str(tmp_path), 40)
    sheet = np.asarray(Image.open(path).convert("RGB"), np.int16)
    # the profile strip, lower left, is gold too: look above it
    top = sheet[: int(size[1] * 0.8)]
    ys, xs = np.nonzero(np.abs(top - np.array(TRACK_INK, np.int16)).max(axis=2) <= 24)
    assert len(xs) > 20
    geo = RegionGeo(region.cfg["crs"], crop, size)
    want = [crs_to_overview_px(geo, x, y) for x, y in corners]
    assert abs(xs.min() - min(p[0] for p in want)) <= 3
    assert abs(xs.max() - max(p[0] for p in want)) <= 3
    assert abs(ys.min() - min(p[1] for p in want)) <= 3
    assert abs(ys.max() - max(p[1] for p in want)) <= 3
    # and a window centred on the route's east end holds that end's ink
    x0, y0, x1, y1 = farm.crop_window((cx + 3000, cy), (1.0, 1.0), crop, size, 40)
    assert (x1 - x0, y1 - y0) == (40, 40)
    near = np.abs(sheet[y0:y1, x0:x1] - np.array(TRACK_INK, np.int16)).max(axis=2) <= 24
    assert near.sum() > 5


# ---- the config's windows -----------------------------------------------------------

def _story(sections, **extra):
    return {"name": "Test plate", "look": {}, "sections": sections, **extra}


def _sheet_sizes(region, dpi):
    crop, pw, ph = farm._frame(region)
    return crop, (round(pw * dpi), round(ph * dpi))


def _write_sheet(path, size, seed):
    rng = np.random.default_rng(seed)
    arr = rng.integers(0, 255, (size[1], size[0], 3), dtype=np.uint8)
    Image.fromarray(arr, "RGB").save(path, "PNG")
    return arr


def test_a_section_with_no_window_fails_with_its_heading(tmp_path):
    region = _region()
    story = _story([
        {"heading": "Every wall throws its shadow", "variant": "poster"},
    ])
    with pytest.raises(StoryError, match="Every wall throws its shadow"):
        farm._stories(str(tmp_path), region, story, DPI)
    assert os.listdir(tmp_path) == []


def test_a_section_with_a_centre_and_no_size_fails_with_its_heading(tmp_path):
    story = _story([{"heading": "No size here", "variant": "poster",
                     "crop_center_m": [1.0, 2.0]}])
    with pytest.raises(StoryError, match="No size here"):
        farm._stories(str(tmp_path), _region(), story, DPI)


def test_an_unknown_variant_fails_with_its_heading(tmp_path):
    story = _story([{"heading": "Odd one", "variant": "glow", "crop_in": [1, 1],
                     "crop_center_m": [1.0, 2.0]}])
    with pytest.raises(StoryError, match="Odd one"):
        farm._stories(str(tmp_path), _region(), story, DPI)


def test_film_and_editions_sections_need_no_window(tmp_path):
    story = _story([{"heading": "The film", "variant": "film"},
                    {"heading": "Three editions", "variant": "editions"}])
    assert farm._stories(str(tmp_path), _region(), story, DPI) == []
    assert os.listdir(tmp_path) == []


def test_the_check_runs_before_any_render_can_start():
    # main() calls this first, so a missing window never costs a poster render
    story = _story([{"heading": "Bare", "variant": "poster"}])
    with pytest.raises(StoryError, match="Bare"):
        farm.check_story_windows(story)
    farm.check_story_windows(None)
    farm.check_story_windows(_story([{"heading": "Film", "variant": "film"}]))


def test_a_plate_with_no_story_writes_no_story_files(tmp_path):
    region = _region()
    assert farm._stories(str(tmp_path), region, None, DPI) == []
    assert farm._journey(region, [], [], str(tmp_path), DPI, None) == []
    assert os.listdir(tmp_path) == []


def test_stories_cuts_each_window_from_the_sheet_pixels(tmp_path):
    region = _region()
    crop, size = _sheet_sizes(region, DPI)
    arr = _write_sheet(tmp_path / "poster.png", size, 1)
    cx = crop[0] + 0.4 * (crop[2] - crop[0])
    cy = crop[1] + 0.6 * (crop[3] - crop[1])
    story = _story([
        {"heading": "A", "variant": "poster", "crop_center_m": [cx, cy], "crop_in": [3, 2]},
        {"heading": "B", "variant": "poster", "crop_anchor": "foot", "crop_in": [4, 1.5]},
        {"heading": "C", "variant": "film"},
    ])
    made = farm._stories(str(tmp_path), region, story, DPI)
    assert [os.path.basename(p) for p in made] == ["story_1.png", "story_2.png"]
    x0, y0, x1, y1 = farm.crop_window((cx, cy), (3, 2), crop, size, DPI)
    one = np.asarray(Image.open(made[0]))
    assert one.shape == (200, 300, 3)                          # print pixels, exactly
    assert np.array_equal(one, arr[y0:y1, x0:x1])
    two = np.asarray(Image.open(made[1]))
    assert np.array_equal(two, arr[size[1] - 150:, 0:400])


def test_a_journey_section_writes_the_before_and_the_after(tmp_path):
    region = _region()
    crop, size = _sheet_sizes(region, DPI)
    plain = _write_sheet(tmp_path / "poster.png", size, 2)
    lit = _write_sheet(tmp_path / "poster_journey.png", size, 3)
    cx = (crop[0] + crop[2]) / 2
    cy = (crop[1] + crop[3]) / 2
    story = _story([{"heading": "Light", "variant": "poster_journey",
                     "crop_center_m": [cx, cy], "crop_in": [2, 2]}])
    made = farm._stories(str(tmp_path), region, story, DPI)
    assert sorted(os.path.basename(p) for p in made) == ["story_1.png", "story_1_before.png"]
    x0, y0, x1, y1 = farm.crop_window((cx, cy), (2, 2), crop, size, DPI)
    assert np.array_equal(np.asarray(Image.open(tmp_path / "story_1_before.png")),
                          plain[y0:y1, x0:x1])           # the plain poster is the before
    assert np.array_equal(np.asarray(Image.open(tmp_path / "story_1.png")),
                          lit[y0:y1, x0:x1])             # the lit one is the after


def test_a_missing_sheet_skips_the_tier_with_a_message(tmp_path, capsys):
    story = _story([{"heading": "A", "variant": "poster",
                     "crop_center_m": [1.0, 2.0], "crop_in": [1, 1]}])
    assert farm._stories(str(tmp_path), _region(), story, DPI) == []
    assert "poster.png" in capsys.readouterr().out


def test_the_window_reads_the_crop_the_sheet_was_rendered_with(tmp_path):
    # a restage-only run opens no DEM, so the sheet's own manifest carries its frame
    region = _region()
    path, size = farm._poster(region, [], [], str(tmp_path), 24)
    assert farm._sheet_crop(path, region) == tuple(farm._frame(region)[0])
    bare = tmp_path / "bare.png"
    Image.new("RGB", (10, 10)).save(bare)               # no manifest: fall back to the frame
    assert farm._sheet_crop(str(bare), region) == tuple(farm._frame(region)[0])


# ---- the journey pair ---------------------------------------------------------------

SUN = {"sun_azimuth_deg": 250.0, "sun_altitude_deg": 22.0, "golden_strength": 0.9}


def _capture(monkeypatch):
    seen = []
    monkeypatch.setattr(farm, "_write_final",
                        lambda spec, region, dpi, out, **kw: seen.append((out, spec)) or
                        (out, (1, 1)))
    return seen


def test_journey_pair_differs_only_in_light(tmp_path, monkeypatch):
    story = _story([], look={"haze_strength": 0.4}, journey=SUN)
    monkeypatch.setattr(farm, "story_for", lambda rid: story)
    seen = _capture(monkeypatch)
    region = _region()
    farm._poster(region, [], [], str(tmp_path), DPI)
    made = farm._journey(region, [], [], str(tmp_path), DPI, story)
    assert made == [os.path.join(str(tmp_path), "poster_journey.png")]
    (_, plain), (out, lit) = seen
    assert os.path.basename(out) == "poster_journey.png"
    assert plain.light_mode == "archival" and lit.light_mode == "journey"
    differ = {f.name for f in dataclasses.fields(plain)
              if getattr(plain, f.name) != getattr(lit, f.name)}
    assert differ == {"light_mode", "sun_azimuth_deg", "sun_altitude_deg", "golden_strength"}
    assert (lit.sun_azimuth_deg, lit.sun_altitude_deg, lit.golden_strength) == (250.0, 22.0, 0.9)
    assert plain.haze_strength == lit.haze_strength == 0.4     # the pair shares the look


def test_a_story_with_no_sun_writes_no_journey_poster(tmp_path, monkeypatch):
    seen = _capture(monkeypatch)
    story = _story([])                                   # no `journey` table
    assert farm._journey(_region(), [], [], str(tmp_path), DPI, story) == []
    assert seen == []


def test_a_half_given_sun_fails_naming_the_missing_field(tmp_path):
    story = _story([], journey={"sun_azimuth_deg": 250.0})
    with pytest.raises(StoryError, match="sun_altitude_deg"):
        farm._journey(_region(), [], [], str(tmp_path), DPI, story)


# ---- one look per plate -------------------------------------------------------------

def test_every_image_of_a_plate_shares_its_look(tmp_path, monkeypatch):
    story = _story([], look={"haze_strength": 0.4, "soft_light": 0.6})
    monkeypatch.setattr(farm, "story_for", lambda rid: story)
    seen = _capture(monkeypatch)
    region = _region()
    tracks = [Track(track_id=f"summit:Peak {i}", coords=np.zeros((4, 2)), day="2024-07-01")
              for i in range(3)]
    farm._poster(region, tracks, [], str(tmp_path), DPI)
    farm._editions(region, tracks, [], str(tmp_path), DPI)
    assert len(seen) == 4                                    # the poster, three editions
    for _out, spec in seen:
        assert (spec.haze_strength, spec.soft_light) == (0.4, 0.6)
        assert spec.water_depth == ORDER_LOOK["water_depth"]  # the rest stays the customer's


def test_the_film_renders_with_the_plates_look(tmp_path, monkeypatch):
    story = _story([], look={"haze_strength": 0.4})
    monkeypatch.setattr(farm, "story_for", lambda rid: story)
    specs = []
    monkeypatch.setattr(farm.provenance, "build_final_spec",
                        lambda spec, box: specs.append(spec) or (_ for _ in ()).throw(
                            RuntimeError("stop here")))
    with pytest.raises(RuntimeError, match="stop here"):
        farm._film(_region(), [], [], str(tmp_path), 40, 4)
    assert specs[0].haze_strength == 0.4


def test_a_plate_with_no_story_renders_the_order_look(tmp_path, monkeypatch):
    monkeypatch.setattr(farm, "story_for", lambda rid: None)
    seen = _capture(monkeypatch)
    farm._poster(_region(), [], [], str(tmp_path), DPI)
    spec = seen[0][1]
    for k, v in ORDER_LOOK.items():
        assert getattr(spec, k) == v


# ---- the tiers ----------------------------------------------------------------------

def test_stories_and_journey_are_farm_tiers():
    assert {"stories", "journey"} <= farm.DEFAULT_TIERS
    assert "stories" in farm.RESTAGE_TIERS        # it cuts crops from yesterday's sheets
    assert "journey" not in farm.RESTAGE_TIERS    # it renders: it needs the DEM


def test_only_accepts_the_two_new_tiers(monkeypatch, tmp_path):
    # lassen has no story: both tiers are no-ops, and argparse takes the names
    monkeypatch.setattr("sys.argv", ["render_asset_farm", "--regions", "lassen_ca",
                                     "--out", str(tmp_path), "--synthetic-tracks",
                                     "--only", "stories", "journey"])
    assert farm.main() == 0
    assert not os.path.exists(tmp_path / "lassen_ca" / "poster_journey.png")


def test_a_story_with_no_windows_stops_the_run_before_it_renders(tmp_path, monkeypatch):
    # Task 7 fills the windows; until then the real plates must fail at the start,
    # not after a poster
    story = _story([{"heading": "Bare section", "variant": "poster"}])
    monkeypatch.setattr(farm, "story_for", lambda rid: story)
    rendered = []
    monkeypatch.setattr(farm, "_poster", lambda *a, **k: rendered.append(a) or ("x", (1, 1)))
    monkeypatch.setattr("sys.argv", ["render_asset_farm", "--regions", "lassen_ca",
                                     "--out", str(tmp_path), "--synthetic-dem",
                                     "--synthetic-tracks", "--only", "poster", "stories"])
    assert farm.main() == 1
    assert rendered == []


# ---- the ship check -----------------------------------------------------------------

def test_demo_photo_plates_names_tahoe_and_zion_until_a_photo_is_set():
    assert story_config.demo_photo_plates() == ["tahoe_ca", "zion_ut"]


def test_a_plate_with_a_photo_file_is_not_a_demo_photo_plate(tmp_path):
    cfg = tmp_path / "stories.toml"
    cfg.write_text(
        'status = "ready"\n'
        '[a_plate]\nphoto_at = "Peak"\nphoto_file = "marketing/photos/peak.jpg"\n'
        '[b_plate]\nphoto_at = "Lake"\n'
        '[c_plate]\nname = "No photo"\n')
    assert story_config.demo_photo_plates(str(cfg)) == ["b_plate"]


def test_ship_check_prints_the_plates_and_exits_1_while_any_remain(capsys):
    assert story_config.main(["--ship-check"]) == 1
    out = capsys.readouterr().out
    assert "tahoe_ca" in out and "zion_ut" in out


def test_ship_check_exits_0_when_every_photo_is_real(tmp_path, capsys):
    cfg = tmp_path / "stories.toml"
    cfg.write_text('status = "ready"\n[a_plate]\nphoto_at = "Peak"\nphoto_file = "p.jpg"\n')
    assert story_config.main(["--ship-check", "--config", str(cfg)]) == 0
    assert capsys.readouterr().out.strip() == "ok: no plate ships the demo photo"
