#!/usr/bin/env python3
"""The checks that build_bundle.sh runs on the Mac app bundle, kept here so they
are tested (native Mac app, phase 1 spec 4.1, 5.1, 5.2, 7).

Stdlib only: the build runs it as `.venv/bin/python -I -B bundle_checks.py <cmd>`.

  fonts <root> [--allow FILE]     no font file outside the allowlist (invariant 10)
  imports <engine>                every repo-local module app/ imports is bundled
  table <ScriptRunner.swift> <engine>   every .script row of the tool's table is bundled
  macho <root> [--exclude-suffix S ...]   Mach-O files, NUL-separated, for signing
  pyc <file>                      the .pyc is an unchecked-hash pyc
  pins <lock> <bundle_lock>       the bundle lock keeps every runtime pin
  lock <pins_file> <wheelhouse> <out>   write a hashed lock from pins and wheels

Exit 0 when clean, 1 on a finding, 2 on a usage error."""
from __future__ import annotations

import argparse
import ast
import hashlib
import os
import re
import sys
from pathlib import Path

ENGINE_PATHS = ("app", "config", "region_prep.py", "scripts/order.py",
                "scripts/build_labels.py", "scripts/dem_coverage.py",
                "scripts/bake_playa.py", "scripts/render_mockups.py",
                "scripts/verify_regions.py", "scripts/pack_region.py")
FONT_SUFFIXES = (".otf", ".ttf", ".ttc", ".otc", ".dfont", ".woff", ".woff2")
MACHO_MAGICS = frozenset({b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe", b"\xfe\xed\xfa\xcf",
                          b"\xfe\xed\xfa\xce", b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca"})
TEST_STACK = frozenset({"pytest", "pytest-xdist", "execnet", "iniconfig", "pluggy",
                        "pyflakes", "pygments"})


def _walk_files(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for name in sorted(filenames):
            yield Path(dirpath) / name


def font_files(root: Path) -> list[str]:
    root = Path(root)
    return sorted(str(p.relative_to(root)) for p in _walk_files(root)
                  if p.suffix.lower() in FONT_SUFFIXES)


def fonts_not_allowed(root: Path, allow: set[str]) -> list[str]:
    return [f for f in font_files(root) if f not in allow]


def _module_exists(engine: Path, dotted: str) -> bool:
    base = engine.joinpath(*dotted.split("."))
    return base.with_suffix(".py").is_file() or (base / "__init__.py").is_file()


def _is_package(engine: Path, dotted: str) -> bool:
    # `scripts` is a namespace package (no __init__.py), so a bare folder counts.
    return dotted == "scripts" or engine.joinpath(*dotted.split(".")).is_dir()


def missing_repo_imports(engine: Path, local_roots=("app", "scripts", "region_prep")) -> list[str]:
    """Every level-0 import of a repo-local module, anywhere in the bundled .py
    files, inside functions too, whose module is not in the bundle."""
    engine = Path(engine)
    missing = set()
    for path in _walk_files(engine):
        if path.suffix != ".py":
            continue
        rel = str(path.relative_to(engine))
        tree = ast.parse(path.read_bytes(), filename=rel)
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                mod = node.module
                if _module_exists(engine, mod):
                    names = []
                elif _is_package(engine, mod):
                    # `from pkg import x`: x is a submodule unless pkg/__init__ defines it
                    names = [f"{mod}.{a.name}" for a in node.names
                             if not (engine.joinpath(*mod.split("."), "__init__.py")).is_file()]
                else:
                    names = [mod]
            for name in names:
                if name.split(".")[0] not in local_roots:
                    continue
                if not _module_exists(engine, name):
                    missing.add(f"{name} ({rel})")
    return sorted(missing)


_SCRIPT_ROW = re.compile(r'^\s*"([^"]+)"\s*:\s*\.script\(', re.MULTILINE)


def script_rows(swift: Path) -> list[str]:
    """The keys of the `.script(` rows in ScriptRunner.table: the files the tool runs."""
    return sorted(_SCRIPT_ROW.findall(Path(swift).read_text()))


def table_rows_missing(swift: Path, engine: Path) -> list[str]:
    return [k for k in script_rows(swift) if not (Path(engine) / k).is_file()]


def macho_files(root: Path) -> list[Path]:
    out = []
    for p in _walk_files(Path(root)):
        if os.path.islink(p) or not p.is_file():
            continue
        with open(p, "rb") as f:
            if f.read(4) in MACHO_MAGICS:
                out.append(p)
    return out


def is_unchecked_hash_pyc(path: Path) -> bool:
    data = Path(path).read_bytes()
    return int.from_bytes(data[4:8], "little") == 1


def sys_path_offenders(paths: list[str], app_support: str) -> list[str]:
    a = app_support.rstrip("/")
    return [p for p in paths if p == "" or p == a or p.startswith(a + "/")]


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _pins(path: Path) -> dict[str, str]:
    pins = {}
    for line in Path(path).read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        spec = line.split()[0]
        if "==" in spec:
            name, ver = spec.split("==", 1)
            pins[_norm(name)] = ver
    return pins


def lock_pin_mismatches(lock: Path, bundle_lock: Path, exempt: frozenset[str]) -> list[str]:
    want, have = _pins(lock), _pins(bundle_lock)
    out = []
    for name, ver in sorted(want.items()):
        if name in {_norm(e) for e in exempt}:
            continue
        if name not in have:
            out.append(f"{name}: lock {ver}, bundle missing")
        elif have[name] != ver:
            out.append(f"{name}: lock {ver}, bundle {have[name]}")
    return out


def write_hashed_lock(pins: list[str], wheelhouse: Path, out: Path) -> None:
    wheels = list(Path(wheelhouse).glob("*.whl"))
    lines = []
    for pin in pins:
        name, ver = pin.split("==", 1)
        match = [w for w in wheels
                 if _norm(w.name.split("-")[0]) == _norm(name) and w.name.split("-")[1] == ver]
        if len(match) != 1:
            raise ValueError(f"{pin}: {len(match)} wheels in {wheelhouse}, need exactly 1")
        digest = hashlib.sha256(match[0].read_bytes()).hexdigest()
        lines.append(f"{name}=={ver} --hash=sha256:{digest}")
    Path(out).write_text("\n".join(lines) + "\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="bundle_checks.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("fonts"); p.add_argument("root"); p.add_argument("--allow")
    p = sub.add_parser("imports"); p.add_argument("engine")
    p = sub.add_parser("table"); p.add_argument("swift"); p.add_argument("engine")
    p = sub.add_parser("macho"); p.add_argument("root")
    p.add_argument("--exclude-suffix", nargs="*", default=[])
    p = sub.add_parser("pyc"); p.add_argument("file")
    p = sub.add_parser("pins"); p.add_argument("lock"); p.add_argument("bundle_lock")
    p = sub.add_parser("lock"); p.add_argument("pins_file"); p.add_argument("wheelhouse")
    p.add_argument("out")
    a = ap.parse_args(argv)

    if a.cmd == "fonts":
        allow = set()
        if a.allow:
            allow = {l.strip() for l in Path(a.allow).read_text().splitlines()
                     if l.strip() and not l.startswith("#")}
        bad = fonts_not_allowed(Path(a.root), allow)
        for f in bad:
            print(f"font file in the bundle: {f}")
        return 1 if bad else 0
    if a.cmd == "imports":
        bad = missing_repo_imports(Path(a.engine))
        for m in bad:
            print(f"not bundled: {m}")
        return 1 if bad else 0
    if a.cmd == "table":
        if not script_rows(Path(a.swift)):
            print(f"no .script rows found in {a.swift}")
            return 1
        bad = table_rows_missing(Path(a.swift), Path(a.engine))
        for k in bad:
            print(f"the tool runs {k}, which the bundle lacks")
        return 1 if bad else 0
    if a.cmd == "macho":
        files = [p for p in macho_files(Path(a.root))
                 if not any(str(p).endswith(s) for s in a.exclude_suffix)]
        sys.stdout.write("".join(f"{p}\0" for p in files))
        return 0
    if a.cmd == "pyc":
        ok = is_unchecked_hash_pyc(Path(a.file))
        if not ok:
            print(f"not an unchecked-hash pyc: {a.file}")
        return 0 if ok else 1
    if a.cmd == "pins":
        bad = lock_pin_mismatches(Path(a.lock), Path(a.bundle_lock), TEST_STACK)
        for m in bad:
            print(m)
        return 1 if bad else 0
    if a.cmd == "lock":
        pins = [l.strip() for l in Path(a.pins_file).read_text().splitlines()
                if l.strip() and not l.startswith("#")]
        write_hashed_lock(pins, Path(a.wheelhouse), Path(a.out))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
