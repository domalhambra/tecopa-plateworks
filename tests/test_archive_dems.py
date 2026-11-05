"""The write-once Dropbox DEM archive (native Mac app phase 1 plan, task 21; spec 6)."""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.macos import archive_dems as ad

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "macos" / "archive_dems.py"
NOW = "2026-11-05T12:00:00Z"
LATER = "2026-11-06T09:30:00Z"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write(p: Path, data: bytes) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


@pytest.fixture
def roots(tmp_path):
    """A plate with a DEM and its metadata, and an archive root, all under paths with a space."""
    base = tmp_path / "Tecopa Plateworks work"
    regions = base / "the regions"
    _write(regions / "tecopa_ca" / "dem.tif", b"DEM-ONE")
    _write(regions / "tecopa_ca" / "region.json", b'{"id": "tecopa_ca"}')
    _write(regions / "tecopa_ca" / "sources.json", b'{"dem": "sidecar"}')
    archive = base / "Dropbox" / "Tecopa Plateworks" / "Plates"
    return regions, archive


def _archive(regions, archive, data_path=None, **kw):
    args = dict(label="current-2026-11-01", meta_dir=regions / "tecopa_ca",
                git_commit="abc1234", make_current=True, now=NOW)
    args.update(kw)
    return ad.archive_dem("tecopa_ca", data_path or regions / "tecopa_ca" / "dem.tif",
                          archive, **args)


def _snapshot(root: Path) -> dict:
    return {str(p.relative_to(root)): (p.read_bytes(), p.stat().st_mtime_ns)
            for p in sorted(root.rglob("*")) if p.is_file()}


def test_archives_into_a_sha_folder_with_record_and_index(roots):
    regions, archive = roots
    sha = _sha(b"DEM-ONE")
    assert _archive(regions, archive) == {"id": "tecopa_ca", "sha256": sha, "status": "archived"}

    folder = archive / "tecopa_ca" / sha
    assert (folder / "dem.tif").read_bytes() == b"DEM-ONE"
    assert not (folder / "dem.tif.partial").exists()
    assert json.loads((folder / "RECORD.json").read_text()) == {
        "id": "tecopa_ca",
        "sha256": sha,
        "bytes": 7,
        "label": "current-2026-11-01",
        "archived_at": NOW,
        "git_commit": "abc1234",
        "region_json_sha256": _sha(b'{"id": "tecopa_ca"}'),
        "sources_json_sha256": _sha(b'{"dem": "sidecar"}'),
    }
    assert ad.read_index(archive, "tecopa_ca") == {
        "id": "tecopa_ca",
        "current": sha,
        "generations": [{"sha256": sha, "label": "current-2026-11-01", "bytes": 7,
                         "archived_at": NOW}],
    }
    assert json.loads((archive / "tecopa_ca" / "index.json").read_text()) == \
        ad.read_index(archive, "tecopa_ca")
    assert sorted(p.name for p in (archive / "tecopa_ca").iterdir()) == [sha, "index.json"]


def test_the_same_bytes_twice_rewrite_nothing(roots):
    regions, archive = roots
    _archive(regions, archive)
    before = _snapshot(archive)
    out = _archive(regions, archive, now=LATER, label="other", git_commit="fff0000")
    assert out == {"id": "tecopa_ca", "sha256": _sha(b"DEM-ONE"), "status": "already"}
    assert _snapshot(archive) == before


def test_a_new_generation_appends_and_current_moves_only_on_request(roots):
    regions, archive = roots
    one, two, three = _sha(b"DEM-ONE"), _sha(b"DEM-TWO"), _sha(b"DEM-THREE")
    _archive(regions, archive)
    old = _write(regions.parent / "backup" / "tecopa_ca" / "dem.tif", b"DEM-TWO")
    _archive(regions, archive, data_path=old, label="sidecar-original",
             make_current=False, now=LATER)
    idx = ad.read_index(archive, "tecopa_ca")
    assert idx["current"] == one
    assert idx["generations"] == [
        {"sha256": one, "label": "current-2026-11-01", "bytes": 7, "archived_at": NOW},
        {"sha256": two, "label": "sidecar-original", "bytes": 7, "archived_at": LATER},
    ]
    newer = _write(regions.parent / "rebuild" / "tecopa_ca" / "dem.tif", b"DEM-THREE")
    _archive(regions, archive, data_path=newer, label="rebuild", make_current=True, now=LATER)
    idx = ad.read_index(archive, "tecopa_ca")
    assert idx["current"] == three
    assert [g["sha256"] for g in idx["generations"]] == [one, two, three]


def test_a_sha_folder_whose_dem_does_not_match_its_name_is_refused(roots):
    regions, archive = roots
    sha = _sha(b"DEM-ONE")
    _write(archive / "tecopa_ca" / sha / "dem.tif", b"CORRUPTED")
    with pytest.raises(ad.ArchiveError, match="does not match"):
        _archive(regions, archive)
    assert (archive / "tecopa_ca" / sha / "dem.tif").read_bytes() == b"CORRUPTED"
    assert not (archive / "tecopa_ca" / sha / "RECORD.json").exists()
    assert not (archive / "tecopa_ca" / "index.json").exists()


def test_a_copy_that_hashes_wrong_leaves_no_dem(roots, monkeypatch):
    regions, archive = roots

    def torn(src, dst):
        Path(dst).write_bytes(Path(src).read_bytes()[:3])

    monkeypatch.setattr(ad, "_copy", torn)
    with pytest.raises(ad.ArchiveError, match="sha256"):
        _archive(regions, archive)
    folder = archive / "tecopa_ca" / _sha(b"DEM-ONE")
    assert not (folder / "dem.tif").exists()
    assert not (folder / "dem.tif.partial").exists()
    assert not (folder / "RECORD.json").exists()
    assert not (archive / "tecopa_ca" / "index.json").exists()


def test_a_leftover_partial_is_replaced(roots):
    regions, archive = roots
    folder = archive / "tecopa_ca" / _sha(b"DEM-ONE")
    _write(folder / "dem.tif.partial", b"HALF")
    assert _archive(regions, archive)["status"] == "archived"
    assert (folder / "dem.tif").read_bytes() == b"DEM-ONE"
    assert not (folder / "dem.tif.partial").exists()


def test_refuses_an_archive_root_inside_the_intake(roots):
    regions, archive = roots
    intake = regions.parent / "Dropbox" / "Apps" / "Plateworks Lab" / "Plates"
    with pytest.raises(ad.ArchiveError, match="Plateworks Lab"):
        _archive(regions, intake)
    assert not intake.exists()
    rc = ad.main(["--archive-root", str(intake), "--label", "x",
                  "--dem-root", str(regions), "--meta-root", str(regions)])
    assert rc == 1
    assert not intake.exists()


def test_main_dry_run_writes_nothing(roots, capsys):
    regions, archive = roots
    _write(regions / "lassen_ca" / "dem.tif", b"LASSEN-DEM")
    (regions / "plain_no_dem").mkdir()
    _write(regions / ".hidden" / "dem.tif", b"NOPE")
    rc = ad.main(["--archive-root", str(archive), "--label", "current-2026-11-01",
                  "--dem-root", str(regions), "--meta-root", str(regions),
                  "--git-commit", "abc1234", "--dry-run"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "lassen_ca" in out and "tecopa_ca" in out
    assert ".hidden" not in out and "plain_no_dem" not in out
    assert out.strip().splitlines()[-1] == f"total {len(b'LASSEN-DEM') + len(b'DEM-ONE')} B"
    assert not archive.exists()


def test_main_a_plate_with_no_dem_exits_1(roots, capsys):
    regions, archive = roots
    (regions / "lassen_ca").mkdir()
    rc = ad.main(["--archive-root", str(archive), "--label", "current-2026-11-01",
                  "--dem-root", str(regions), "--meta-root", str(regions),
                  "--git-commit", "abc1234", "tecopa_ca", "lassen_ca"])
    assert rc == 1
    assert "lassen_ca" in capsys.readouterr().err
    # The good plate is still archived: every plate is tried.
    assert ad.read_index(archive, "tecopa_ca")["current"] is None


def test_cli_bad_arguments_exit_2(tmp_path):
    for args in ([], ["--label", "x"], ["--archive-root", str(tmp_path)],
                 ["--archive-root", str(tmp_path), "--label", "x", "--bogus"]):
        r = subprocess.run([sys.executable, str(SCRIPT), *args],
                           capture_output=True, text=True, cwd=REPO)
        assert r.returncode == 2, args
        assert "usage: archive_dems.py" in r.stderr
