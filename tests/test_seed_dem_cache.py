"""seed_dem_cache.sh fills the Mac app's DEM cache once from the checkout
(native Mac app phase 1 spec 5.6, plan task 20)."""
import hashlib
import os
import subprocess

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(REPO, "scripts", "macos", "seed_dem_cache.sh")


def run(*args):
    return subprocess.run(["bash", SCRIPT, *args], capture_output=True, text=True)


def plate(root, rid, dem=None, region=b'{"id":"x"}'):
    d = root / rid
    d.mkdir(parents=True, exist_ok=True)
    (d / "region.json").write_bytes(region)
    if dem is not None:
        (d / "dem.tif").write_bytes(dem)
    return d


def _roots(tmp_path):
    base = tmp_path / "Application Support"      # a space, as on the Mac
    return base / "src", base / "Tecopa Plateworks" / "regions"


def test_copies_each_dem_and_checks_its_sha(tmp_path):
    src, dst = _roots(tmp_path)
    plate(src, "lassen_ca", dem=b"DEM-L")
    plate(dst, "lassen_ca")
    out = run("--from", str(src), "--to", str(dst))
    assert out.returncode == 0, out.stderr
    assert (dst / "lassen_ca" / "dem.tif").read_bytes() == b"DEM-L"
    assert f"lassen_ca  ok  {hashlib.sha256(b'DEM-L').hexdigest()}" in out.stdout
    assert not list(dst.rglob("*.partial"))


def test_refuses_a_plate_the_app_has_not_seeded(tmp_path):
    src, dst = _roots(tmp_path)
    plate(src, "lassen_ca", dem=b"D")
    dst.mkdir(parents=True)
    out = run("--from", str(src), "--to", str(dst))
    assert out.returncode == 1
    assert "lassen_ca: not seeded" in out.stderr
    assert not (dst / "lassen_ca" / "dem.tif").exists()


def test_refuses_when_region_json_differs(tmp_path):
    src, dst = _roots(tmp_path)
    plate(src, "lassen_ca", dem=b"D", region=b"A")
    plate(dst, "lassen_ca", region=b"B")
    out = run("--from", str(src), "--to", str(dst))
    assert out.returncode == 1
    assert "region.json differs" in out.stderr
    assert not (dst / "lassen_ca" / "dem.tif").exists()


def test_never_overwrites_a_different_dem(tmp_path):
    src, dst = _roots(tmp_path)
    plate(src, "lassen_ca", dem=b"NEW")
    plate(dst, "lassen_ca", dem=b"OLD")
    out = run("--from", str(src), "--to", str(dst))
    assert out.returncode == 1
    assert (dst / "lassen_ca" / "dem.tif").read_bytes() == b"OLD"
    assert "differs" in out.stderr


def test_an_identical_dem_already_there_is_ok(tmp_path):
    src, dst = _roots(tmp_path)
    plate(src, "lassen_ca", dem=b"SAME")
    plate(dst, "lassen_ca", dem=b"SAME")
    out = run("--from", str(src), "--to", str(dst))
    assert out.returncode == 0, out.stderr
    assert "lassen_ca  already" in out.stdout


def test_a_source_plate_with_no_dem_fails_and_the_rest_still_run(tmp_path):
    src, dst = _roots(tmp_path)
    plate(src, "zion_ut")
    plate(dst, "zion_ut")
    plate(src, "lassen_ca", dem=b"D")
    plate(dst, "lassen_ca")
    out = run("--from", str(src), "--to", str(dst))
    assert out.returncode == 1
    assert "zion_ut: no dem.tif" in out.stderr
    assert (dst / "lassen_ca" / "dem.tif").read_bytes() == b"D"


def test_skips_dot_folders_in_source(tmp_path):
    src, dst = _roots(tmp_path)
    (src / ".seed-tmp").mkdir(parents=True)
    plate(src, "lassen_ca", dem=b"D")
    plate(dst, "lassen_ca")
    out = run("--from", str(src), "--to", str(dst))
    assert out.returncode == 0, out.stderr
    assert ".seed-tmp" not in out.stdout + out.stderr


def test_bad_arguments_exit_2():
    out = run("--bogus")
    assert out.returncode == 2
    assert out.stderr.startswith("usage: seed_dem_cache.sh")
