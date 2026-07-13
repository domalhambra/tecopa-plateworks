# tests/test_build_labels.py
"""The labels bake keeps sources.json honest: labels.json joins the hashed-assets
record and GNIS joins the source list (idempotently), with every other field byte-
preserved -- the plate manifest must account for EVERY asset a reprint depends on."""
import hashlib
import json
import os

from scripts.build_labels import update_sources_manifest


def _seed_region(tmp_path):
    """A minimal region dir: a labels.json plus the sources.json shape region_prep
    writes (a couple of assets, the three build-time source datasets)."""
    labels = {"crs": "EPSG:32610", "features": [{"name": "Test Peak", "kind": "summit",
                                                 "rank": 70, "coords": [[1.0, 2.0]]}]}
    with open(tmp_path / "labels.json", "w") as f:
        json.dump(labels, f)
    sources = {
        "id": "testland",
        "built": "2026-07-03",
        "fetch_bbox_4326": [-121.0, 40.0, -120.5, 40.5],
        "crs": "EPSG:32610",
        "rebuild": "python region_prep.py --id testland ...",
        "assets": {"dem.tif": {"sha256": "ab" * 32, "bytes": 12345}},
        "sources": [{"dataset": "USGS 3DEP 10 m DEM", "via": "py3dep.get_dem",
                     "license": "Public domain (USGS)"}],
    }
    with open(tmp_path / "sources.json", "w") as f:
        json.dump(sources, f, indent=2)
    return sources


def test_update_sources_manifest_adds_labels_asset_and_gnis_source(tmp_path):
    before = _seed_region(tmp_path)
    update_sources_manifest(str(tmp_path))
    got = json.load(open(tmp_path / "sources.json"))
    # the labels asset entry matches the file on disk exactly
    raw = open(tmp_path / "labels.json", "rb").read()
    assert got["assets"]["labels.json"] == {
        "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
    # GNIS appended to the source datasets
    gnis = [s for s in got["sources"] if "GNIS" in s["dataset"]]
    assert len(gnis) == 1
    assert gnis[0]["license"] == "Public domain (USGS)"
    # every pre-existing field is preserved verbatim
    assert got["assets"]["dem.tif"] == before["assets"]["dem.tif"]
    for k in ("id", "built", "fetch_bbox_4326", "crs", "rebuild"):
        assert got[k] == before[k]
    assert got["sources"][:len(before["sources"])] == before["sources"]


def test_update_sources_manifest_is_idempotent(tmp_path):
    _seed_region(tmp_path)
    update_sources_manifest(str(tmp_path))
    once = open(tmp_path / "sources.json", "rb").read()
    update_sources_manifest(str(tmp_path))
    twice = open(tmp_path / "sources.json", "rb").read()
    assert once == twice                                   # no duplicate GNIS entry
    got = json.loads(twice)
    assert sum("GNIS" in s["dataset"] for s in got["sources"]) == 1
