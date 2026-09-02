# tests/test_verify_regions.py
# verify_regions.py separates the two kinds of DEM drift. A hash mismatch alone is a
# REBUILT plate (four of five on this Mac, deliberate, CLAUDE.md § Known local
# failures). A geometry mismatch is the pull ORPHAN, and it is the only kind that needs
# repair. Before this row the script printed the same DRIFT line for both.
import json
import os

from scripts import verify_regions as vr
from tests.test_readyz import _write_region

GOOD = (600000.0, 4400000.0, 610000.0, 4410000.0)
SHIFTED = (605000.0, 4405000.0, 615000.0, 4415000.0)


def _with_sidecar(root, rid, cfg_bounds, dem_bounds, with_dem=True):
    """A plate plus a sources.json that records region.json truthfully and the DEM
    with a deliberately wrong hash -- the rebuilt-plate shape."""
    d = _write_region(root, rid, cfg_bounds, dem_bounds, with_dem=with_dem)
    src = {"assets": {"region.json": {
        "sha256": vr._sha256_file(os.path.join(d, "region.json")),
        "bytes": os.path.getsize(os.path.join(d, "region.json"))}}}
    if with_dem:
        src["assets"]["dem.tif"] = {"sha256": "0" * 64, "bytes": 1}
    with open(os.path.join(d, "sources.json"), "w") as f:
        json.dump(src, f)
    return d


def test_geometry_ok_when_dem_matches(tmp_path):
    d = _with_sidecar(str(tmp_path), "rebuilt", GOOD, GOOD)
    verdict, detail = vr.geometry_verdict(d)
    assert verdict == "ok"
    assert "0.00 m" in detail


def test_geometry_orphan_when_dem_drifts(tmp_path):
    d = _with_sidecar(str(tmp_path), "orphan", GOOD, SHIFTED)
    verdict, detail = vr.geometry_verdict(d)
    assert verdict == "ORPHAN"
    assert "5000.00 m" in detail and "not this plate's" in detail


def test_geometry_missing_dem_is_not_orphan(tmp_path):
    d = _with_sidecar(str(tmp_path), "nodem", GOOD, GOOD, with_dem=False)
    verdict, _ = vr.geometry_verdict(d)
    assert verdict == "MISSING"


def test_main_prints_orphan_and_exits_1(tmp_path, capsys):
    _with_sidecar(str(tmp_path), "orphan", GOOD, SHIFTED)
    rc = vr.main(["--regions-root", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 1
    assert "ORPHAN geometry" in out
    assert "DRIFT  dem.tif" in out            # the hash row still prints beside it


def test_main_rebuilt_plate_reads_drift_but_not_orphan(tmp_path, capsys):
    _with_sidecar(str(tmp_path), "rebuilt", GOOD, GOOD)
    rc = vr.main(["--regions-root", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 1                            # the hash drift is still a finding
    # no ORPHAN *row*; the closing summary names the word while explaining it, which
    # is why this asserts the row shape rather than the bare word.
    assert "ORPHAN geometry" not in out
    assert "ok     geometry" in out


def test_geometry_row_degrades_when_render_stack_is_absent(tmp_path, monkeypatch):
    """The script is stdlib-first by contract. Without app.regions it says so, once."""
    d = _with_sidecar(str(tmp_path), "any", GOOD, GOOD)
    monkeypatch.setattr(vr, "_readiness", None)
    verdict, detail = vr.geometry_verdict(d)
    assert verdict == "skip"
    assert "not checked" in detail
