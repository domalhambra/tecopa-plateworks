"""The build checks of the Mac app bundle (native Mac app phase 1 plan, task 8)."""
import hashlib
import os
import py_compile
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.macos import bundle_checks as bc

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "macos" / "bundle_checks.py"


def _write(p: Path, data: bytes = b"x") -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


def test_engine_paths_are_the_spec_list():
    assert bc.ENGINE_PATHS == ("app", "config", "region_prep.py", "scripts/order.py",
                               "scripts/build_labels.py", "scripts/dem_coverage.py",
                               "scripts/bake_playa.py", "scripts/render_mockups.py",
                               "scripts/verify_regions.py", "scripts/pack_region.py")


def test_font_files_finds_every_suffix_case_insensitively(tmp_path):
    for rel in ("a/x.OTF", "b/y.ttc", "c/z.dfont", "d/w.woff2", "e/ok.txt"):
        _write(tmp_path / rel)
    assert bc.font_files(tmp_path) == ["a/x.OTF", "b/y.ttc", "c/z.dfont", "d/w.woff2"]


def test_fonts_outside_the_allowlist(tmp_path):
    _write(tmp_path / "site-packages" / "pkg" / "f.ttf")
    assert bc.fonts_not_allowed(tmp_path, {"site-packages/pkg/f.ttf"}) == []
    assert bc.fonts_not_allowed(tmp_path, set()) == ["site-packages/pkg/f.ttf"]


def test_missing_repo_imports_flags_an_absent_scripts_module(tmp_path):
    eng = tmp_path / "engine"
    _write(eng / "app" / "__init__.py", b"")
    _write(eng / "app" / "m.py", b"from scripts.render_mockups import x\n")
    assert bc.missing_repo_imports(eng) == ["scripts.render_mockups (app/m.py)"]
    _write(eng / "scripts" / "render_mockups.py", b"x = 1\n")
    assert bc.missing_repo_imports(eng) == []


def test_missing_repo_imports_sees_lazy_imports(tmp_path):
    eng = tmp_path / "engine"
    _write(eng / "app" / "__init__.py", b"")
    _write(eng / "app" / "m.py",
           b"def f():\n    from scripts import dem_candidate\n    import region_prep\n")
    assert bc.missing_repo_imports(eng) == ["region_prep (app/m.py)",
                                            "scripts.dem_candidate (app/m.py)"]


def test_missing_repo_imports_on_the_real_tree(tmp_path):
    arch = subprocess.run(["git", "-C", str(REPO), "archive", "--format=tar", "HEAD", "--",
                           *bc.ENGINE_PATHS], capture_output=True, check=True).stdout
    subprocess.run(["tar", "-xf", "-", "-C", str(tmp_path)], input=arch, check=True)
    assert bc.missing_repo_imports(tmp_path) == []


SWIFT_TABLE = b'''    static let table: [String: Row] = [
        "scripts/verify_regions.py": .script(.app),     // regions verify
        "region_prep.py": .script(.prep),               // plate build
        "app.plates": .module(.app),                    // plate install
    ]
'''


def test_script_rows_reads_only_the_script_keys(tmp_path):
    swift = _write(tmp_path / "ScriptRunner.swift", SWIFT_TABLE)
    assert bc.script_rows(swift) == ["region_prep.py", "scripts/verify_regions.py"]


def test_table_rows_missing_from_the_engine(tmp_path):
    swift = _write(tmp_path / "ScriptRunner.swift", SWIFT_TABLE)
    eng = tmp_path / "engine"
    _write(eng / "region_prep.py")
    assert bc.table_rows_missing(swift, eng) == ["scripts/verify_regions.py"]
    _write(eng / "scripts" / "verify_regions.py")
    assert bc.table_rows_missing(swift, eng) == []


def test_table_check_on_the_real_tree(tmp_path):
    arch = subprocess.run(["git", "-C", str(REPO), "archive", "--format=tar", "HEAD", "--",
                           *bc.ENGINE_PATHS], capture_output=True, check=True).stdout
    subprocess.run(["tar", "-xf", "-", "-C", str(tmp_path)], input=arch, check=True)
    swift = REPO / "tools" / "tecopa" / "Sources" / "TecopaKit" / "ScriptRunner.swift"
    assert "scripts/pack_region.py" in bc.script_rows(swift)
    assert bc.table_rows_missing(swift, tmp_path) == []


def test_macho_files_by_magic(tmp_path):
    a = _write(tmp_path / "lib" / "a.so", b"\xcf\xfa\xed\xfe" + b"\0" * 12)
    _write(tmp_path / "bin" / "fat", b"\xca\xfe\xba\xbe" + b"\0" * 12)
    _write(tmp_path / "bin" / "tool.sh", b"#!/bin/sh\n")
    os.symlink(a, tmp_path / "lib" / "link.so")
    assert [p.name for p in bc.macho_files(tmp_path)] == ["fat", "a.so"]


def test_unchecked_hash_pyc(tmp_path):
    src = _write(tmp_path / "m.py", b"x = 1\n")
    modes = py_compile.PycInvalidationMode
    got = {}
    for mode in modes:
        out = tmp_path / f"{mode.name}.pyc"
        py_compile.compile(str(src), cfile=str(out), invalidation_mode=mode)
        got[mode.name] = bc.is_unchecked_hash_pyc(out)
    assert got == {"TIMESTAMP": False, "CHECKED_HASH": False, "UNCHECKED_HASH": True}


def test_sys_path_offenders():
    assert bc.sys_path_offenders(["", "/B/engine", "/A S/x", "/A S"], app_support="/A S") \
        == ["", "/A S/x", "/A S"]


def test_lock_pins_exempt_the_test_stack_only(tmp_path):
    lock = _write(tmp_path / "lock.txt", b"# c\nnumpy==2.4.6\npytest==9.0.0\nPillow==12.0\n")
    bundle = _write(tmp_path / "bundle.txt",
                    b"numpy==2.4.5 --hash=sha256:" + b"0" * 64 + b"\n"
                    b"pillow==12.0 --hash=sha256:" + b"1" * 64 + b"\n")
    assert bc.lock_pin_mismatches(lock, bundle, bc.TEST_STACK) == [
        "numpy: lock 2.4.6, bundle 2.4.5"]


def test_write_hashed_lock(tmp_path):
    wh = tmp_path / "wh"
    w1 = _write(wh / "numpy-2.4.6-cp314-cp314-macosx_14_0_arm64.whl", b"N")
    w2 = _write(wh / "python_dateutil-2.9.0.post0-py2.py3-none-any.whl", b"D")
    out = tmp_path / "lock.txt"
    bc.write_hashed_lock(["numpy==2.4.6", "python-dateutil==2.9.0.post0"], wh, out)
    assert out.read_text().splitlines() == [
        f"numpy==2.4.6 --hash=sha256:{hashlib.sha256(b'N').hexdigest()}",
        f"python-dateutil==2.9.0.post0 --hash=sha256:{hashlib.sha256(b'D').hexdigest()}"]
    with pytest.raises(ValueError, match="scipy==1.0"):
        bc.write_hashed_lock(["scipy==1.0"], wh, out)


def test_cli_exit_codes(tmp_path):
    def run(*args):
        return subprocess.run([sys.executable, "-I", "-B", str(SCRIPT), *args],
                              capture_output=True, text=True)
    clean = tmp_path / "clean"
    _write(clean / "a.txt")
    assert run("fonts", str(clean)).returncode == 0
    _write(clean / "f.otf")
    bad = run("fonts", str(clean))
    assert bad.returncode == 1 and "f.otf" in bad.stdout
    swift = _write(tmp_path / "ScriptRunner.swift", SWIFT_TABLE)
    missing = run("table", str(swift), str(clean))
    assert missing.returncode == 1
    assert "scripts/verify_regions.py" in missing.stdout and "region_prep.py" in missing.stdout
    empty = _write(tmp_path / "Empty.swift", b"let x = 1\n")
    assert run("table", str(empty), str(clean)).returncode == 1
    usage = run("--bogus")
    assert usage.returncode == 2
    assert usage.stderr.startswith("usage: bundle_checks.py")
