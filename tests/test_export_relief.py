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
