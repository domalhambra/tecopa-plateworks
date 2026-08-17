# The landing page's footer promises every image on it is the engine's own render. A
# synthetic stand-in DEM (tests/conftest.py hydrates one for any plate missing its real
# 3DEP terrain) renders *cleanly* -- correct hillshade, palette, place labels, route ink.
# Nothing in the picture betrays that the landforms are invented, so nothing downstream
# could tell either: a container that could not download 700 MB of DEM would deploy
# happily and publish country that does not exist.
#
# The record has to be stamped where the DEM is actually opened, not read back at deploy
# time -- a machine can render from a stand-in and obtain the real DEM afterwards, at
# which point the file on disk says "real" while the posters are still invented (the same
# shape as the documented lassen_ca orphan bug). So: the farm stamps the DEM it consumed
# into assets/index.json, and build_deploy refuses to publish what that record does not
# vouch for.
import hashlib
import json
import os
import pathlib

import numpy as np
import pytest
import rasterio
from PIL import Image
from rasterio.transform import from_bounds

from marketing import build_deploy
from scripts import render_asset_farm as farm

REPO = pathlib.Path(__file__).resolve().parent.parent


# --- fixtures: real files, no mocks -------------------------------------------------

def _dem(path, synthetic: bool, fill: float = 100.0) -> str:
    """A tiny real GeoTIFF, tagged synthetic=1 or not."""
    data = np.full((8, 10), fill, "float32")
    profile = dict(driver="GTiff", dtype="float32", count=1, height=8, width=10,
                   crs="EPSG:5070", transform=from_bounds(0, 0, 100, 80, 10, 8))
    with rasterio.open(str(path), "w", **profile) as ds:
        ds.write(data, 1)
        if synthetic:
            ds.update_tags(synthetic="1")
    return str(path)


# --- 1. the farm stamps what it consumed --------------------------------------------

def test_terrain_record_reports_a_synthetic_dem_as_synthetic(tmp_path):
    rec = farm._terrain_record(_dem(tmp_path / "dem.tif", synthetic=True))
    assert rec["synthetic"] is True


def test_terrain_record_reports_a_real_dem_as_not_synthetic(tmp_path):
    rec = farm._terrain_record(_dem(tmp_path / "dem.tif", synthetic=False))
    assert rec["synthetic"] is False


def test_terrain_record_hashes_the_dem_bytes(tmp_path):
    path = _dem(tmp_path / "dem.tif", synthetic=False)
    rec = farm._terrain_record(path)
    raw = pathlib.Path(path).read_bytes()
    assert rec["sha256"] == hashlib.sha256(raw).hexdigest()
    assert rec["bytes"] == len(raw)


def test_terrain_record_distinguishes_two_dems(tmp_path):
    a = farm._terrain_record(_dem(tmp_path / "a.tif", synthetic=False, fill=100.0))
    b = farm._terrain_record(_dem(tmp_path / "b.tif", synthetic=False, fill=900.0))
    assert a["sha256"] != b["sha256"]


def test_terrain_record_is_none_when_no_dem_was_consulted(tmp_path):
    # a restage-only tier opens no DEM; there is nothing honest to record
    assert farm._terrain_record(str(tmp_path / "absent.tif")) is None


# --- 2. the merge keeps a known-good record it cannot re-derive ----------------------

def test_merge_preserves_a_prior_terrain_record_when_the_run_stamped_none():
    prior = {"lassen_ca": {"name": "Lassen", "assets": [],
                           "terrain": {"synthetic": False, "sha256": "abc", "bytes": 7}}}
    fresh = {"lassen_ca": {"name": "Lassen", "assets": ["assets/lassen_ca/detail.png"]}}
    merged = farm._merge_index(fresh, prior)
    assert merged["lassen_ca"]["terrain"] == prior["lassen_ca"]["terrain"]


def test_merge_prefers_the_terrain_this_run_actually_rendered_from():
    prior = {"lassen_ca": {"name": "Lassen", "assets": [],
                           "terrain": {"synthetic": True, "sha256": "old", "bytes": 1}}}
    fresh = {"lassen_ca": {"name": "Lassen", "assets": [],
                           "terrain": {"synthetic": False, "sha256": "new", "bytes": 2}}}
    assert farm._merge_index(fresh, prior)["lassen_ca"]["terrain"]["sha256"] == "new"


def test_merge_invents_no_record_for_a_region_that_never_had_one():
    fresh = {"rifle_aspen": {"name": "Rifle", "assets": []}}
    assert "terrain" not in farm._merge_index(fresh, {})["rifle_aspen"]


def test_merge_still_preserves_a_prior_regions_untouched_entry():
    prior = {"elko_bonneville": {"name": "Elko", "assets": [],
                                 "terrain": {"synthetic": False, "sha256": "e", "bytes": 3}}}
    merged = farm._merge_index({"rifle_aspen": {"name": "Rifle", "assets": []}}, prior)
    assert merged["elko_bonneville"] == prior["elko_bonneville"]


def test_a_restage_only_farm_run_keeps_the_terrain_record_it_could_not_stamp(tmp_path, monkeypatch):
    """The subtle one, end to end: `--only detail` opens no DEM (needs_render is False),
    so it must carry yesterday's record forward rather than dropping the region's only
    proof of real terrain. Driven through main(), not the merge helper, because the drop
    would happen in main's index assembly."""
    out = tmp_path / "assets"
    (out / "lassen_ca").mkdir(parents=True)
    Image.new("RGB", (600, 500), (118, 110, 98)).save(out / "lassen_ca" / "poster.png")
    known = {"synthetic": False, "sha256": "20cec75c", "bytes": 192087365}
    (out / "index.json").write_text(json.dumps(
        {"lassen_ca": {"name": "Lassen County, California",
                       "assets": ["assets/lassen_ca/poster.png"], "terrain": known}}))

    monkeypatch.setattr("sys.argv", ["farm", "--regions", "lassen_ca",
                                     "--only", "detail", "--out", str(out)])
    monkeypatch.chdir(REPO)
    farm.main()

    entry = json.loads((out / "index.json").read_text())["lassen_ca"]
    assert entry["terrain"] == known, "a restage-only run dropped the terrain record"
    assert any(p.endswith("detail.png") for p in entry["assets"])


# --- 3. the deploy refuses what the record does not vouch for ------------------------

REAL = {"synthetic": False, "sha256": "20cec75c", "bytes": 192087365}
SYNTH = {"synthetic": True, "sha256": "deadbeef", "bytes": 4096}

DERIVED = ["poster.png", "edition_1.png", "edition_2.png", "edition_3.png",
           "wallpaper_iphone.png", "detail.png"]
COPIED = ["film.webp", "mockup_plate.glb", "mockup_plate_1080x1080.jpg"]

PAGE = """<html><body>
{imgs}
<video src="../assets/lassen_ca/film.png"></video>
<div data-plate="lassen_ca"><model-viewer
  src="../assets/lassen_ca/mockup_plate.glb"></model-viewer></div>
<div data-plate="tushar_beaver_ut"><model-viewer
  src="../assets/tushar_beaver_ut/mockup_plate.glb"></model-viewer></div>
</body></html>"""


def _fake_repo(tmp_path, index: dict, coin_regions=("tushar_beaver_ut",)) -> pathlib.Path:
    """A minimal repo root the real build_deploy can run against end to end."""
    repo = tmp_path / "repo"
    (repo / "marketing" / "vendor").mkdir(parents=True)
    (repo / "marketing" / "favicon.svg").write_text("<svg/>")
    (repo / "marketing" / "landing.html").write_text(PAGE.format(
        imgs="\n".join(f'<img src="../assets/lassen_ca/{n}">' for n in DERIVED)))
    lassen = repo / "assets" / "lassen_ca"
    lassen.mkdir(parents=True)
    for name in DERIVED:
        Image.new("RGB", (60, 40), (118, 110, 98)).save(lassen / name)
    for name in COPIED:
        (lassen / name).write_bytes(b"asset-bytes")
    for rid in coin_regions:
        (repo / "assets" / rid).mkdir(parents=True, exist_ok=True)
        (repo / "assets" / rid / "mockup_plate.glb").write_bytes(b"glb")
    (repo / "assets" / "index.json").write_text(json.dumps(index))
    return repo


def _run(repo, tmp_path, monkeypatch, *extra):
    monkeypatch.setattr(build_deploy, "REPO", repo)
    monkeypatch.setattr("sys.argv", ["build_deploy", "--out",
                                     str(tmp_path / "out"), *extra])
    return build_deploy.main()


def test_deploy_refuses_a_region_rendered_from_synthetic_terrain(tmp_path, monkeypatch, capsys):
    repo = _fake_repo(tmp_path, {"lassen_ca": {"name": "L", "assets": [], "terrain": SYNTH},
                                 "tushar_beaver_ut": {"name": "T", "assets": [], "terrain": REAL}})
    assert _run(repo, tmp_path, monkeypatch) == 1
    err = capsys.readouterr().err
    assert "lassen_ca" in err and "synthetic" in err.lower()


def test_deploy_refuses_a_region_with_no_terrain_record_at_all(tmp_path, monkeypatch, capsys):
    repo = _fake_repo(tmp_path, {"lassen_ca": {"name": "L", "assets": []},
                                 "tushar_beaver_ut": {"name": "T", "assets": [], "terrain": REAL}})
    assert _run(repo, tmp_path, monkeypatch) == 1
    err = capsys.readouterr().err
    assert "lassen_ca" in err
    assert "render_asset_farm.py" in err, "the refusal must name the re-render command"


def test_deploy_refuses_when_the_index_is_missing_entirely(tmp_path, monkeypatch, capsys):
    repo = _fake_repo(tmp_path, {})
    (repo / "assets" / "index.json").unlink()
    assert _run(repo, tmp_path, monkeypatch) == 1
    assert "lassen_ca" in capsys.readouterr().err


def test_the_guard_covers_a_region_that_only_contributes_a_coin(tmp_path, monkeypatch, capsys):
    # --region lassen_ca is clean; tushar_beaver_ut is published ONLY as a plate-card GLB
    repo = _fake_repo(tmp_path, {"lassen_ca": {"name": "L", "assets": [], "terrain": REAL},
                                 "tushar_beaver_ut": {"name": "T", "assets": [], "terrain": SYNTH}})
    assert _run(repo, tmp_path, monkeypatch) == 1
    err = capsys.readouterr().err
    assert "tushar_beaver_ut" in err


def test_a_stripped_coin_is_not_guarded(tmp_path, monkeypatch):
    # a plate card whose GLB was never rendered gets its <model-viewer> stripped, so
    # nothing of that region is published -- guarding it would block a clean deploy
    repo = _fake_repo(tmp_path, {"lassen_ca": {"name": "L", "assets": [], "terrain": REAL}},
                      coin_regions=())
    assert _run(repo, tmp_path, monkeypatch) == 0


def test_a_clean_index_deploys(tmp_path, monkeypatch):
    repo = _fake_repo(tmp_path, {"lassen_ca": {"name": "L", "assets": [], "terrain": REAL},
                                 "tushar_beaver_ut": {"name": "T", "assets": [], "terrain": REAL}})
    assert _run(repo, tmp_path, monkeypatch) == 0
    assert (tmp_path / "out" / "index.html").is_file()
    assert (tmp_path / "out" / "assets" / "lassen_ca" / "poster.jpg").is_file()


# --- 4. the overrides open the door, loudly -----------------------------------------

def test_allow_synthetic_publishes_and_warns(tmp_path, monkeypatch, capsys):
    repo = _fake_repo(tmp_path, {"lassen_ca": {"name": "L", "assets": [], "terrain": SYNTH},
                                 "tushar_beaver_ut": {"name": "T", "assets": [], "terrain": REAL}})
    assert _run(repo, tmp_path, monkeypatch, "--allow-synthetic") == 0
    err = capsys.readouterr().err
    assert "WARNING" in err and "lassen_ca" in err
    assert (tmp_path / "out" / "index.html").is_file()


def test_allow_unverified_terrain_publishes_and_warns(tmp_path, monkeypatch, capsys):
    repo = _fake_repo(tmp_path, {"lassen_ca": {"name": "L", "assets": []},
                                 "tushar_beaver_ut": {"name": "T", "assets": [], "terrain": REAL}})
    assert _run(repo, tmp_path, monkeypatch, "--allow-unverified-terrain") == 0
    err = capsys.readouterr().err
    assert "WARNING" in err and "lassen_ca" in err


def test_each_override_opens_only_its_own_door(tmp_path, monkeypatch):
    # --allow-unverified-terrain must not wave through a KNOWN-synthetic plate
    repo = _fake_repo(tmp_path, {"lassen_ca": {"name": "L", "assets": [], "terrain": SYNTH},
                                 "tushar_beaver_ut": {"name": "T", "assets": [], "terrain": REAL}})
    assert _run(repo, tmp_path, monkeypatch, "--allow-unverified-terrain") == 1
    repo2 = _fake_repo(tmp_path / "b", {"lassen_ca": {"name": "L", "assets": []},
                                        "tushar_beaver_ut": {"name": "T", "assets": [],
                                                             "terrain": REAL}})
    assert _run(repo2, tmp_path / "b", monkeypatch, "--allow-synthetic") == 1


def test_the_guard_runs_before_anything_is_written(tmp_path, monkeypatch):
    repo = _fake_repo(tmp_path, {"lassen_ca": {"name": "L", "assets": [], "terrain": SYNTH}},
                      coin_regions=())
    assert _run(repo, tmp_path, monkeypatch) == 1
    assert not (tmp_path / "out").exists(), "a refused deploy left a partial root behind"
