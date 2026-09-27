# The Tecopa pages promise every image on them is the engine's own render. A
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
# into assets/index.json, and build_deploy.terrain_guard refuses to publish what that
# record does not vouch for.
import hashlib
import json
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


def test_terrain_record_of_an_unreadable_dem_claims_nothing_rather_than_nothing_at_all(tmp_path):
    """"No DEM was consulted" and "a DEM was consulted and could not be characterized"
    are different answers. The first may inherit yesterday's record; the second must not,
    or a stale claim of real terrain gets attached to pixels from an unknown file."""
    bad = tmp_path / "dem.tif"
    bad.write_bytes(b"not a geotiff at all")
    rec = farm._terrain_record(str(bad))
    assert rec is not None, "a present-but-unreadable DEM is not the same as no DEM"
    assert rec["synthetic"] is None, "it must not claim the DEM is real"
    assert rec["sha256"] is None


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


def test_merge_does_not_inherit_a_real_record_over_an_uncharacterized_dem():
    # the run DID open a DEM and could not read it -- the prior "real" claim describes
    # different bytes than the ones these pixels came from, so it must not carry forward
    prior = {"lassen_ca": {"name": "L", "assets": [],
                           "terrain": {"synthetic": False, "sha256": "real", "bytes": 9}}}
    fresh = {"lassen_ca": {"name": "L", "assets": [],
                           "terrain": {"synthetic": None, "sha256": None, "bytes": 20}}}
    assert farm._merge_index(fresh, prior)["lassen_ca"]["terrain"]["synthetic"] is None


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


# --- 3. the guard refuses what the record does not vouch for -------------------------
# terrain_guard is called directly: the Netlify deploy that once wrapped it retired on
# 2026-09-26, and scripts/export_relief.py now calls it the same way, with the index it
# read and the regions it is about to publish.

REAL = {"synthetic": False, "sha256": "20cec75c", "bytes": 192087365}
SYNTH = {"synthetic": True, "sha256": "deadbeef", "bytes": 4096}


def _index(**terrain) -> dict:
    """An index.json dict: region -> its terrain record, or no record for None."""
    out = {}
    for rid, rec in terrain.items():
        entry = {"name": rid, "assets": []}
        if rec is not None:
            entry["terrain"] = rec
        out[rid] = entry
    return out


def _guard(index, regions=("lassen_ca",), **overrides):
    return build_deploy.terrain_guard(index, set(regions), **overrides)


def test_the_guard_refuses_a_region_rendered_from_synthetic_terrain(capsys):
    assert _guard(_index(lassen_ca=SYNTH)) == 1
    err = capsys.readouterr().err
    assert "lassen_ca" in err and "synthetic" in err.lower()


def test_the_guard_refuses_a_region_with_no_terrain_record_at_all(capsys):
    assert _guard(_index(lassen_ca=None)) == 1
    err = capsys.readouterr().err
    assert "lassen_ca" in err
    assert "render_asset_farm.py" in err, "the refusal must name the re-render command"


def test_the_guard_refuses_when_the_index_is_missing_entirely(tmp_path, capsys):
    # the reader export_relief uses: an absent index.json reads as {}, which vouches
    # for nothing
    from scripts import export_relief as er
    index = er.load_index(str(tmp_path))
    assert index == {}
    assert _guard(index) == 1
    assert "lassen_ca" in capsys.readouterr().err


def test_the_guard_covers_every_region_it_is_given_not_only_the_first(capsys):
    # lassen_ca is clean; tushar_beaver_ut goes out only as a coin, and is synthetic
    index = _index(lassen_ca=REAL, tushar_beaver_ut=SYNTH)
    assert _guard(index, ("lassen_ca", "tushar_beaver_ut")) == 1
    err = capsys.readouterr().err
    assert "tushar_beaver_ut" in err and "lassen_ca" not in err


# A malformed record must route to the UNVERIFIED refusal, never read as a promise of
# real terrain. Everything except a literal JSON `false` was already refusing; a dict
# whose `synthetic` was absent, empty, or not a bool was the one shape that published.
# Strict: the farm only ever writes a real bool, so anything else means the file was
# hand-edited or corrupted, and a corrupted provenance record is exactly the thing this
# guard exists not to trust. `0` is a legitimate JSON encoding of false but is not what
# the farm writes, so it refuses too -- pinned deliberately, not by accident.
MALFORMED_TERRAIN = [
    pytest.param({}, id="empty-record"),
    pytest.param({"sha256": "abc", "bytes": 7}, id="no-synthetic-key"),
    pytest.param({"synthetic": None, "sha256": None, "bytes": 7}, id="uncharacterized-dem"),
    pytest.param({"synthetic": 0, "sha256": "abc", "bytes": 7}, id="int-zero-not-a-bool"),
    pytest.param({"synthetic": "false", "sha256": "abc", "bytes": 7}, id="string-false"),
]


@pytest.mark.parametrize("bad", MALFORMED_TERRAIN)
def test_a_malformed_terrain_record_is_not_a_promise_of_real_terrain(bad, capsys):
    assert _guard(_index(lassen_ca=bad, tushar_beaver_ut=REAL),
                  ("lassen_ca", "tushar_beaver_ut")) == 1
    err = capsys.readouterr().err
    assert "lassen_ca" in err and "UNVERIFIED" in err


@pytest.mark.parametrize("bad", MALFORMED_TERRAIN)
def test_a_malformed_terrain_record_is_waved_through_by_the_unverified_override(bad):
    # it refuses as UNVERIFIED, so that is the override that must open it -- not
    # allow_synthetic, which is a different admission
    index = _index(lassen_ca=bad, tushar_beaver_ut=REAL)
    regions = ("lassen_ca", "tushar_beaver_ut")
    assert _guard(index, regions, allow_synthetic=True) == 1
    assert _guard(index, regions, allow_unverified=True) == 0


def test_a_clean_index_passes_silently(capsys):
    assert _guard(_index(lassen_ca=REAL, tushar_beaver_ut=REAL),
                  ("lassen_ca", "tushar_beaver_ut")) == 0
    assert capsys.readouterr().err == ""


# --- 4. the overrides open the door, loudly -----------------------------------------

def test_allow_synthetic_publishes_and_warns(capsys):
    assert _guard(_index(lassen_ca=SYNTH), allow_synthetic=True) == 0
    err = capsys.readouterr().err
    assert "WARNING" in err and "lassen_ca" in err


def test_allow_unverified_publishes_and_warns(capsys):
    assert _guard(_index(lassen_ca=None), allow_unverified=True) == 0
    err = capsys.readouterr().err
    assert "WARNING" in err and "lassen_ca" in err


def test_each_override_opens_only_its_own_door():
    # allow_unverified must not wave through a KNOWN-synthetic plate, and
    # allow_synthetic must not wave through an unrecorded one
    assert _guard(_index(lassen_ca=SYNTH), allow_unverified=True) == 1
    assert _guard(_index(lassen_ca=None), allow_synthetic=True) == 1
