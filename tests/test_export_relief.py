# The relief exporter turns a region's finished renders into the images the Ghost
# landing page's relief viewer draws: a surface image and a height map per coin, the
# same pair for the hero poster, plus the wall and close-up stills. The spec is
# docs/superpowers/specs/2026-09-24-ghost-landing-page-design.md, section 5.
#
# What these pin: each output's pixel size and mode, byte-identical reruns, the coin
# being the GLB coin's own texture crop and height field (so the web preview and the
# GLB show the same relief), and the terrain gate refusing what build_deploy refuses
# (invariant 11: every marketing image is an engine render of real country).
import json
import os

import numpy as np
import pytest
from PIL import Image

from marketing import build_deploy
from scripts import export_relief as er
from scripts.render_mockups import _height_field
from scripts.render_model import TEXTURE_PX, _centered_square, _sample_height

RID = "lassen_ca"
REAL = {"synthetic": False, "sha256": "0" * 64, "bytes": 1}

# poster is portrait (like lassen_ca); the band above and below the centred square is
# pure red, so a coin that leaked past the square would carry red
POSTER_W, POSTER_H = 1600, 2000
BAND = (POSTER_H - POSTER_W) // 2
RED = (255, 0, 0)


def _terrain(w, h, seed=3):
    """Plausible, deterministic ground: smooth ridges plus fine grain."""
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    ridge = (np.sin(xx / 57.0) * np.cos(yy / 83.0) + 1.0) * 0.5
    grain = rng.random((h, w), dtype=np.float32) * 0.15
    lum = np.clip(ridge * 0.85 + grain, 0.0, 1.0)
    rgb = np.stack([lum * 200 + 30, lum * 180 + 40, lum * 150 + 50], axis=2)
    return Image.fromarray(rgb.astype(np.uint8), "RGB")


def _region(tmp_path, terrain=REAL):
    """A farm output root with one rendered region and its index.json."""
    assets = tmp_path / "assets"
    src = assets / RID
    src.mkdir(parents=True)
    poster = Image.new("RGB", (POSTER_W, POSTER_H), RED)
    poster.paste(_terrain(POSTER_W, POSTER_W), (0, BAND))
    poster.save(src / "poster.png", "PNG")
    _terrain(1400, 1050, seed=5).save(src / "detail.png", "PNG")
    entry = {"name": "Lassen", "assets": []}
    if terrain is not None:
        entry["terrain"] = terrain
    (assets / "index.json").write_text(json.dumps({RID: entry}))
    return assets


def _export(assets, out):
    index = er.load_index(str(assets))
    return er.export_region(str(assets / RID), str(out), RID, index)


# ---- sizes and modes ------------------------------------------------------------

def _long_edge_size(src_w, src_h, long_edge):
    s = long_edge / max(src_w, src_h)
    return (round(src_w * s), round(src_h * s))


EXPECTED = {
    "coin.webp": ((1024, 1024), "RGB", "WEBP"),
    "coin-h.png": ((256, 256), "L", "PNG"),
    "poster-relief.webp": (_long_edge_size(POSTER_W, POSTER_H, 1400), "RGB", "WEBP"),
    "poster-relief-h.png": (_long_edge_size(POSTER_W, POSTER_H, 320), "L", "PNG"),
    "wall.webp": (_long_edge_size(POSTER_W, POSTER_H, 840), "RGB", "WEBP"),
    "detail.webp": (_long_edge_size(1400, 1050, 1200), "RGB", "WEBP"),
}


def test_every_output_has_its_spec_size_and_mode(tmp_path):
    out = tmp_path / "out"
    made = _export(_region(tmp_path), out)
    assert sorted(os.path.basename(p) for p in made) == sorted(EXPECTED)
    for name, (size, mode, fmt) in EXPECTED.items():
        im = Image.open(out / name)
        assert (im.size, im.mode, im.format) == (size, mode, fmt), name


def test_the_webp_quality_table_matches_the_spec():
    assert er.OUTPUTS == {
        "coin.webp": 82, "poster-relief.webp": 84, "wall.webp": 80, "detail.webp": 84,
    }
    assert (er.COIN_PX, er.COIN_HEIGHT_PX) == (1024, 256)
    assert (er.POSTER_PX, er.POSTER_HEIGHT_PX, er.WALL_PX, er.DETAIL_PX) == \
        (1400, 320, 840, 1200)


# ---- determinism ----------------------------------------------------------------

def test_two_runs_give_identical_bytes(tmp_path):
    assets = _region(tmp_path)
    a, b = tmp_path / "a", tmp_path / "b"
    _export(assets, a)
    _export(assets, b)
    for name in EXPECTED:
        assert (a / name).read_bytes() == (b / name).read_bytes(), name


def test_webp_outputs_carry_no_metadata(tmp_path):
    out = tmp_path / "out"
    _export(_region(tmp_path), out)
    for name in EXPECTED:
        if name.endswith(".webp"):
            data = (out / name).read_bytes()
            for chunk in (b"EXIF", b"XMP ", b"ICCP"):
                assert chunk not in data, (name, chunk)


# ---- the coin is the GLB coin ---------------------------------------------------

def test_coin_is_the_centred_square_the_glb_textures(tmp_path):
    assets = _region(tmp_path)
    out = tmp_path / "out"
    _export(assets, out)
    coin = np.asarray(Image.open(out / "coin.webp").convert("RGB"), np.int16)
    poster = Image.open(assets / RID / "poster.png").convert("RGB")
    glb_tex = np.asarray(_centered_square(poster, TEXTURE_PX), np.int16)
    assert coin.shape == glb_tex.shape
    assert np.abs(coin - glb_tex).mean() < 4.0          # lossy, but the same picture
    # the crop is the square inside the sheet: none of the red margin leaks in
    red = (coin[..., 0] > 200) & (coin[..., 1] < 60) & (coin[..., 2] < 60)
    assert not red.any()


def test_coin_height_is_the_glb_height_field(tmp_path):
    assets = _region(tmp_path)
    out = tmp_path / "out"
    _export(assets, out)
    poster = Image.open(assets / RID / "poster.png").convert("RGB")
    want = np.round(_sample_height(poster) * 255.0).astype(np.uint8)
    got = np.asarray(Image.open(out / "coin-h.png"))
    assert np.array_equal(got, want)


def test_poster_height_is_the_same_height_field_at_320(tmp_path):
    assets = _region(tmp_path)
    out = tmp_path / "out"
    _export(assets, out)
    poster = Image.open(assets / RID / "poster.png").convert("RGB")
    small = poster.resize(EXPECTED["poster-relief-h.png"][0], Image.LANCZOS)
    art = np.asarray(small, np.float32) / 255.0
    want = np.round(_height_field(art) * 255.0).astype(np.uint8)
    assert np.array_equal(np.asarray(Image.open(out / "poster-relief-h.png")), want)


# ---- the terrain gate -----------------------------------------------------------

def test_the_gate_is_build_deploys_own():
    assert er.terrain_guard is build_deploy.terrain_guard


@pytest.mark.parametrize("terrain", [
    {"synthetic": True, "sha256": "0" * 64, "bytes": 1},      # a stand-in DEM
    None,                                                     # never recorded
    {"synthetic": "false", "sha256": "0" * 64, "bytes": 1},   # hand-edited
    {"synthetic": None, "sha256": None, "bytes": 1},          # uncharacterised
])
def test_a_region_without_real_terrain_is_refused_and_nothing_is_written(tmp_path, terrain):
    assets = _region(tmp_path, terrain=terrain)
    out = tmp_path / "out"
    with pytest.raises(er.ReliefRefused):
        _export(assets, out)
    assert not out.exists()


def test_a_region_missing_from_the_index_is_refused(tmp_path):
    assets = _region(tmp_path)
    (assets / "index.json").write_text("{}")
    with pytest.raises(er.ReliefRefused):
        _export(assets, tmp_path / "out")


def test_a_missing_or_corrupt_index_is_refused(tmp_path):
    assets = _region(tmp_path)
    (assets / "index.json").write_text("not json")
    with pytest.raises(er.ReliefRefused):
        _export(assets, tmp_path / "out")
    (assets / "index.json").unlink()
    with pytest.raises(er.ReliefRefused):
        _export(assets, tmp_path / "out")


def test_the_cli_refuses_with_a_nonzero_exit(tmp_path):
    assets = _region(tmp_path, terrain={"synthetic": True, "sha256": "0" * 64, "bytes": 1})
    out = tmp_path / "out"
    assert er.main(["--assets", str(assets), "--out", str(out), RID]) == 1
    assert not out.exists()


def test_the_cli_writes_one_folder_per_region(tmp_path):
    assets = _region(tmp_path)
    out = tmp_path / "out"
    assert er.main(["--assets", str(assets), "--out", str(out), RID]) == 0
    assert sorted(os.listdir(out / RID)) == sorted(EXPECTED)


def test_a_missing_source_render_is_an_error_and_writes_nothing(tmp_path):
    assets = _region(tmp_path)
    (assets / RID / "detail.png").unlink()
    out = tmp_path / "out"
    with pytest.raises(er.ReliefError):
        _export(assets, out)
    assert not out.exists()


# ---- the asset farm calls it for every region -------------------------------------

from scripts import render_asset_farm as farm  # noqa: E402


def test_relief_is_a_default_farm_tier():
    assert "relief" in farm.DEFAULT_TIERS
    assert "relief" in farm.RESTAGE_TIERS      # it restages renders: no DEM needed


def test_the_farm_writes_relief_into_a_subfolder_and_keeps_the_coin_film(tmp_path):
    assets = _region(tmp_path)
    src = assets / RID
    (src / "coin.webp").write_bytes(b"the coin-spin film")    # the farm's own coin.webp
    made = farm._relief(str(src), RID, er.load_index(str(assets)))
    assert sorted(os.path.basename(p) for p in made) == sorted(EXPECTED)
    assert all(os.path.dirname(p) == str(src / "relief") for p in made)
    assert (src / "coin.webp").read_bytes() == b"the coin-spin film"


def test_the_farm_skips_a_refused_region_without_failing_it(tmp_path, capsys):
    assets = _region(tmp_path, terrain={"synthetic": True, "sha256": "0" * 64, "bytes": 1})
    src = assets / RID
    assert farm._relief(str(src), RID, er.load_index(str(assets))) == []
    assert not (src / "relief").exists()
    assert "relief" in capsys.readouterr().out


def test_the_gate_sees_the_terrain_this_run_stamped():
    real = {"synthetic": False, "sha256": "a" * 64, "bytes": 1}
    fake = {"synthetic": True, "sha256": "b" * 64, "bytes": 1}
    prior = {RID: {"name": "Lassen", "assets": [], "terrain": real}}
    # a run that opened a synthetic DEM overrides yesterday's real record
    assert farm._gate_index(prior, RID, fake)[RID]["terrain"] == fake
    # a restage-only run opens no DEM and carries the prior record forward
    assert farm._gate_index(prior, RID, None)[RID]["terrain"] == real
    # a first render has no prior record: this run's stamp is the only one
    assert farm._gate_index({}, RID, real)[RID]["terrain"] == real
    assert farm._gate_index({}, RID, None).get(RID, {}).get("terrain") is None


def test_farm_only_relief_exports_every_asked_region(tmp_path, monkeypatch):
    assets = _region(tmp_path)
    monkeypatch.setattr("sys.argv", ["render_asset_farm", "--regions", RID,
                                     "--out", str(assets), "--only", "relief"])
    assert farm.main() == 0
    assert sorted(os.listdir(assets / RID / "relief")) == sorted(EXPECTED)
    index = json.loads((assets / "index.json").read_text())
    assert index[RID]["terrain"] == REAL                     # carried, not clobbered
    recorded = {os.path.basename(p) for p in index[RID]["assets"]}
    assert set(EXPECTED) <= recorded


# ---- a showcase plate's story: the new outputs (Pick-a-plate phase B, task 6) ----------
# A plate with a story in marketing/stories.toml also exports one web image per story
# section: story-<n>.webp (1200 px long edge, q84, like detail.webp), the Journey Light
# pair journey-before.webp and journey-after.webp (1200 px), edition-<n>.webp at wall
# size (840 px), and the film copied through as film.mp4. A plate with no story writes
# exactly the six outputs above.

STORY = {"name": "Test plate", "look": {}, "sections": [
    {"heading": "One", "variant": "poster"},
    {"heading": "Two", "variant": "poster"},
    {"heading": "Light", "variant": "poster_journey"},
    {"heading": "Film", "variant": "film"},
    {"heading": "Editions", "variant": "editions"},
]}
FILM = b"\x00\x00\x00\x18ftypmp42 the film, copied through"
STORY_SIZES = {1: (1500, 1000), 2: (800, 1200), 3: (1400, 1400)}      # crops of any shape


_STORY_FILES = {}


def _story_files():
    """The farm's story sources, built once per process: noise at these sizes is the
    slow part of every test here."""
    if not _STORY_FILES:
        for n, size in STORY_SIZES.items():
            _STORY_FILES[f"story_{n}.png"] = _terrain(*size, seed=10 + n)
        _STORY_FILES["story_3_before.png"] = _terrain(1400, 1400, seed=20)
        for ed in (1, 2, 3):
            _STORY_FILES[f"edition_{ed}.png"] = _terrain(900, 1125, seed=30 + ed)
    return _STORY_FILES


def _story_region(tmp_path, terrain=REAL, story=STORY):
    assets = _region(tmp_path, terrain=terrain)
    src = assets / RID
    for name, img in _story_files().items():
        img.save(src / name, "PNG", compress_level=1)
    (src / "film.mp4").write_bytes(FILM)
    return assets


def _export_story(assets, out, story=STORY):
    index = er.load_index(str(assets))
    return er.export_region(str(assets / RID), str(out), RID, index, story=story)


STORY_EXPECTED = {
    # section 1 and 2 are plain crops; section 3 is the pair, so it has no story-3
    "story-1.webp": (_long_edge_size(1500, 1000, 1200), "RGB", "WEBP"),
    "story-2.webp": (_long_edge_size(800, 1200, 1200), "RGB", "WEBP"),
    "journey-before.webp": (_long_edge_size(1400, 1400, 1200), "RGB", "WEBP"),
    "journey-after.webp": (_long_edge_size(1400, 1400, 1200), "RGB", "WEBP"),
    "edition-1.webp": (_long_edge_size(900, 1125, 840), "RGB", "WEBP"),
    "edition-2.webp": (_long_edge_size(900, 1125, 840), "RGB", "WEBP"),
    "edition-3.webp": (_long_edge_size(900, 1125, 840), "RGB", "WEBP"),
}


def test_each_story_output_has_its_size_and_mode(tmp_path):
    out = tmp_path / "out"
    _export_story(_story_region(tmp_path), out)
    for name, (size, mode, fmt) in STORY_EXPECTED.items():
        im = Image.open(out / name)
        assert (im.size, im.mode, im.format) == (size, mode, fmt), name


def test_a_story_section_is_the_crop_resized_only(tmp_path):
    assets = _story_region(tmp_path)
    out = tmp_path / "out"
    _export_story(assets, out)
    src = Image.open(assets / RID / "story_1.png").convert("RGB")
    want = np.asarray(er._long_edge(src, er.STORY_PX), np.int16)
    got = np.asarray(Image.open(out / "story-1.webp").convert("RGB"), np.int16)
    assert np.abs(got - want).mean() < 4.0               # lossy, but the same picture


def test_the_journey_pair_is_the_before_and_the_after_crops(tmp_path):
    assets = _story_region(tmp_path)
    out = tmp_path / "out"
    _export_story(assets, out)
    for name, src in (("journey-before.webp", "story_3_before.png"),
                      ("journey-after.webp", "story_3.png")):
        want = np.asarray(er._long_edge(Image.open(assets / RID / src).convert("RGB"),
                                        er.STORY_PX), np.int16)
        got = np.asarray(Image.open(out / name).convert("RGB"), np.int16)
        assert np.abs(got - want).mean() < 4.0, name
    assert not (out / "story-3.webp").exists()


def test_an_edition_is_the_edition_sheet_at_wall_size(tmp_path):
    assets = _story_region(tmp_path)
    out = tmp_path / "out"
    _export_story(assets, out)
    for ed in (1, 2, 3):
        want = np.asarray(er._long_edge(
            Image.open(assets / RID / f"edition_{ed}.png").convert("RGB"), er.EDITION_PX),
            np.int16)
        got = np.asarray(Image.open(out / f"edition-{ed}.webp").convert("RGB"), np.int16)
        assert np.abs(got - want).mean() < 4.0, ed


def test_the_film_is_copied_through_as_film_mp4(tmp_path):
    out = tmp_path / "out"
    made = _export_story(_story_region(tmp_path), out)
    assert (out / "film.mp4").read_bytes() == FILM
    assert str(out / "film.mp4") in made


def test_a_story_export_writes_the_six_and_the_story_set(tmp_path):
    out = tmp_path / "out"
    made = _export_story(_story_region(tmp_path), out)
    assert sorted(os.path.basename(p) for p in made) == \
        sorted([*EXPECTED, *STORY_EXPECTED, "film.mp4"])


def test_story_widths_and_qualities_are_the_specs():
    assert (er.STORY_PX, er.EDITION_PX) == (1200, 840)
    assert (er.STORY_QUALITY, er.EDITION_QUALITY) == (84, 80)


def test_a_plate_with_no_story_writes_exactly_the_six(tmp_path):
    out = tmp_path / "out"
    assets = _story_region(tmp_path)            # story files lying about change nothing
    made = _export_story(assets, out, story=None)
    assert sorted(os.path.basename(p) for p in made) == sorted(EXPECTED)
    assert sorted(os.listdir(out)) == sorted(EXPECTED)


def test_a_story_export_is_byte_identical_across_two_runs(tmp_path):
    assets = _story_region(tmp_path)
    a, b = tmp_path / "a", tmp_path / "b"
    _export_story(assets, a)
    _export_story(assets, b)
    assert sorted(os.listdir(a)) == sorted(os.listdir(b))
    for name in os.listdir(a):
        assert (a / name).read_bytes() == (b / name).read_bytes(), name


def test_story_webps_carry_no_metadata(tmp_path):
    out = tmp_path / "out"
    _export_story(_story_region(tmp_path), out)
    for name in STORY_EXPECTED:
        data = (out / name).read_bytes()
        for chunk in (b"EXIF", b"XMP ", b"ICCP"):
            assert chunk not in data, (name, chunk)


def test_the_terrain_guard_refuses_before_any_story_file_is_written(tmp_path):
    assets = _story_region(tmp_path, terrain={"synthetic": True, "sha256": "0" * 64,
                                              "bytes": 1})
    out = tmp_path / "out"
    with pytest.raises(er.ReliefRefused):
        _export_story(assets, out)
    assert not out.exists()


@pytest.mark.parametrize("gone", ["story_2.png", "story_3_before.png", "edition_2.png",
                                  "film.mp4"])
def test_a_missing_story_source_is_an_error_and_writes_nothing(tmp_path, gone):
    assets = _story_region(tmp_path)
    (assets / RID / gone).unlink()
    out = tmp_path / "out"
    with pytest.raises(er.ReliefError, match=gone):
        _export_story(assets, out)
    assert not out.exists()


def test_a_missing_film_names_the_film_the_page_needs(tmp_path):
    assets = _story_region(tmp_path)
    (assets / RID / "film.mp4").unlink()
    with pytest.raises(er.ReliefError, match="film"):
        _export_story(assets, tmp_path / "out")


def test_the_cli_reads_the_plates_story(tmp_path, monkeypatch):
    assets = _story_region(tmp_path)
    monkeypatch.setattr(er, "story_for", lambda rid: STORY)
    out = tmp_path / "out"
    assert er.main(["--assets", str(assets), "--out", str(out), RID]) == 0
    assert "story-1.webp" in os.listdir(out / RID)


def test_the_farm_hands_the_relief_tier_the_plates_story(tmp_path, monkeypatch):
    assets = _story_region(tmp_path)
    monkeypatch.setattr(farm, "story_for", lambda rid: STORY)
    made = farm._relief(str(assets / RID), RID, er.load_index(str(assets)))
    names = {os.path.basename(p) for p in made}
    assert {"story-1.webp", "journey-after.webp", "edition-3.webp", "film.mp4"} <= names


# ---- a story crop is never upscaled; a missing source fails the farm run ----------------

@pytest.mark.parametrize("name,size", [
    ("story_1.png", (600, 450)),                  # a 2 x 1.5 in window at 300 dpi
    ("story_3_before.png", (1100, 900)),          # the journey pair's before
    ("story_3.png", (1000, 1199)),                # and its after, one pixel short
    ("edition_2.png", (700, 839)),                # an edition under its 840 px
])
def test_a_story_source_smaller_than_its_output_is_refused_not_upscaled(tmp_path, name, size):
    assets = _story_region(tmp_path)
    _terrain(*size, seed=99).save(assets / RID / name, "PNG")
    out = tmp_path / "out"
    with pytest.raises(er.ReliefError, match=name):
        _export_story(assets, out)
    assert not out.exists()


def test_a_story_source_exactly_the_output_size_is_taken_as_it_is(tmp_path):
    assets = _story_region(tmp_path)
    _terrain(1200, 800, seed=98).save(assets / RID / "story_1.png", "PNG")
    out = tmp_path / "out"
    _export_story(assets, out)
    assert Image.open(out / "story-1.webp").size == (1200, 800)


def test_the_six_old_outputs_still_resize_either_way(tmp_path):
    # the poster and the detail crop keep their old behaviour: a small sheet is scaled
    assets = _region(tmp_path)
    _terrain(500, 600, seed=4).save(assets / RID / "poster.png", "PNG")
    out = tmp_path / "out"
    _export(assets, out)
    assert Image.open(out / "poster-relief.webp").size == _long_edge_size(500, 600, 1400)


def _farm_main(monkeypatch, assets, *args):
    monkeypatch.setattr("sys.argv", ["render_asset_farm", "--regions", RID,
                                     "--out", str(assets), *args])
    return farm.main()


@pytest.mark.parametrize("gone", ["edition_2.png", "film.mp4", "story_2.png"])
def test_a_missing_story_source_fails_the_farm_run(tmp_path, monkeypatch, capsys, gone):
    assets = _story_region(tmp_path)
    (assets / RID / gone).unlink()
    monkeypatch.setattr(farm, "story_for", lambda rid: STORY)
    assert _farm_main(monkeypatch, assets, "--only", "relief") == 1
    assert gone in capsys.readouterr().out
    assert not (assets / RID / "relief").exists()          # as the exporter CLI leaves it


def test_a_refused_terrain_still_only_skips_the_relief_tier(tmp_path, monkeypatch):
    assets = _story_region(tmp_path, terrain={"synthetic": True, "sha256": "0" * 64,
                                              "bytes": 1})
    monkeypatch.setattr(farm, "story_for", lambda rid: STORY)
    assert _farm_main(monkeypatch, assets, "--only", "relief") == 0
    assert not (assets / RID / "relief").exists()


def test_the_exporter_cli_and_the_farm_agree_on_a_missing_source(tmp_path, monkeypatch):
    assets = _story_region(tmp_path)
    (assets / RID / "film.mp4").unlink()
    monkeypatch.setattr(er, "story_for", lambda rid: STORY)
    assert er.main(["--assets", str(assets), "--out", str(tmp_path / "o"), RID]) == 1
