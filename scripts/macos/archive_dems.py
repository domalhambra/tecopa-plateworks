#!/usr/bin/env python3
"""The write-once Dropbox DEM archive (native Mac app, phase 1 spec 6).

  <archive-root>/<id>/index.json            generations, and which one is "current"
  <archive-root>/<id>/<sha256>/dem.tif
  <archive-root>/<id>/<sha256>/RECORD.json

Keyed by the DEM's own sha256, so a rebuild never overwrites an original. A restore
targets index.json "current" or a poster's region_pack sha, never the sources.json sha
(invariant 12: sources.json is never re-stamped, so after the Lanczos swap it names the
striped pre-Lanczos DEM).

Stdlib only.

  archive_dems.py --archive-root DIR --label LABEL [--dem-root regions]
                  [--meta-root regions] [--current] [--git-commit SHA] [--dry-run] [id ...]

Exit 0 when clean, 1 when any plate failed (after trying them all), 2 on a usage error."""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

INTAKE_MARKER = "Apps/Plateworks Lab"
DEM = "dem.tif"
PARTIAL = "dem.tif.partial"
RECORD = "RECORD.json"
INDEX = "index.json"


class ArchiveError(Exception):
    pass


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha_or_none(path: Path) -> str | None:
    return _sha256(path) if path.is_file() else None


def _copy(src, dst) -> None:
    """The one byte copy; a test patches it to simulate a torn copy."""
    shutil.copyfile(src, dst)


def _check_root(archive_root: Path) -> None:
    resolved = Path(os.path.abspath(archive_root)).as_posix()
    if INTAKE_MARKER in resolved:
        raise ArchiveError(f"refusing an archive root inside the intake ({INTAKE_MARKER}): "
                           f"{archive_root}")


def _check_id(rid: str) -> None:
    if not rid or rid.startswith(".") or "/" in rid or "\\" in rid:
        raise ArchiveError(f"not a plate id: {rid!r}")


def read_index(archive_root, rid: str) -> dict:
    """The plate's index.json, or an empty one when the plate has no archive yet."""
    path = Path(archive_root) / rid / INDEX
    if not path.is_file():
        return {"id": rid, "current": None, "generations": []}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json_new(path: Path, obj: dict) -> None:
    with open(path, "x", encoding="utf-8") as f:
        json.dump(obj, f, indent=2)
        f.write("\n")


def _replace_json(path: Path, obj: dict) -> None:
    tmp = path.with_name(path.name + ".partial")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def archive_dem(rid: str, dem_path, archive_root, *, label: str, meta_dir, git_commit,
                make_current: bool, now: str) -> dict:
    """Archive one DEM under its sha. Returns {"id", "sha256", "status"}, where status is
    "archived" when the bytes were written and "already" when they were there."""
    archive_root, dem_path, meta_dir = Path(archive_root), Path(dem_path), Path(meta_dir)
    _check_root(archive_root)
    _check_id(rid)
    if not label:
        raise ArchiveError("a label is required")
    if not dem_path.is_file():
        raise ArchiveError(f"{rid}: no DEM at {dem_path}")

    sha = _sha256(dem_path)
    size = dem_path.stat().st_size
    plate = archive_root / rid
    folder = plate / sha
    dem, partial, record = folder / DEM, folder / PARTIAL, folder / RECORD

    status = "already"
    if dem.exists():
        if _sha256(dem) != sha:
            raise ArchiveError(f"{rid}: {dem} does not match its folder's sha256; "
                               "leaving it untouched")
    else:
        status = "archived"
        folder.mkdir(parents=True, exist_ok=True)
        _copy(dem_path, partial)  # replaces any leftover partial
        got = _sha256(partial)
        if got != sha:
            partial.unlink()
            try:
                folder.rmdir()
            except OSError:
                pass
            raise ArchiveError(f"{rid}: the copy's sha256 {got} is not the source's {sha}")
        os.rename(partial, dem)

    if record.exists():
        rec = json.loads(record.read_text(encoding="utf-8"))
        if rec.get("sha256") != sha:
            raise ArchiveError(f"{rid}: {record} names sha256 {rec.get('sha256')}, not {sha}")
    else:
        rec = {
            "id": rid,
            "sha256": sha,
            "bytes": size,
            "label": label,
            "archived_at": now,
            "git_commit": git_commit,
            "region_json_sha256": _sha_or_none(meta_dir / "region.json"),
            "sources_json_sha256": _sha_or_none(meta_dir / "sources.json"),
        }
        _write_json_new(record, rec)

    index = read_index(archive_root, rid)
    changed = False
    if not any(g.get("sha256") == sha for g in index["generations"]):
        index["generations"].append({"sha256": sha, "label": rec["label"],
                                     "bytes": rec["bytes"], "archived_at": rec["archived_at"]})
        changed = True
    if make_current and index.get("current") != sha:
        index["current"] = sha
        changed = True
    if changed:
        _replace_json(plate / INDEX, index)
    return {"id": rid, "sha256": sha, "status": status}


def _default_ids(dem_root: Path) -> list[str]:
    if not dem_root.is_dir():
        return []
    return sorted(p.name for p in dem_root.iterdir()
                  if p.is_dir() and not p.name.startswith(".") and (p / DEM).is_file())


def _git_head() -> str | None:
    try:
        r = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True,
                           cwd=Path(__file__).resolve().parent, check=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    return r.stdout.strip() or None


def _free_bytes(path: Path) -> int:
    p = Path(os.path.abspath(path))
    while not p.exists() and p != p.parent:
        p = p.parent
    return shutil.disk_usage(p).free


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="archive_dems.py",
                                 description="Archive plate DEMs, write-once, by sha256.")
    ap.add_argument("--archive-root", required=True, type=Path)
    ap.add_argument("--label", required=True)
    ap.add_argument("--dem-root", default=Path("regions"), type=Path)
    ap.add_argument("--meta-root", default=Path("regions"), type=Path)
    ap.add_argument("--current", action="store_true",
                    help="move index.json current to these bytes")
    ap.add_argument("--git-commit", default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("ids", nargs="*")
    args = ap.parse_args(argv)
    if not args.label.strip():
        ap.error("--label must not be empty")

    try:
        _check_root(args.archive_root)
    except ArchiveError as e:
        print(f"archive_dems: {e}", file=sys.stderr)
        return 1

    ids = args.ids or _default_ids(args.dem_root)
    failed = False
    todo: list[tuple[str, Path]] = []
    for rid in ids:
        dem = args.dem_root / rid / DEM
        if rid.startswith(".") or "/" in rid or not dem.is_file():
            print(f"{rid}  FAILED  no {DEM} under {args.dem_root}", file=sys.stderr)
            failed = True
            continue
        todo.append((rid, dem))

    total = sum(dem.stat().st_size for _, dem in todo)
    if args.dry_run:
        for rid, dem in todo:
            print(f"{rid}  {dem.stat().st_size} B  {dem}")
        print(f"total {total} B")
        return 1 if failed else 0

    free = _free_bytes(args.archive_root)
    if free < total:
        print(f"archive_dems: the batch needs {total} B and {args.archive_root} has "
              f"{free} B free", file=sys.stderr)
        return 1

    git_commit = args.git_commit or _git_head()
    now = _now()
    for rid, dem in todo:
        try:
            out = archive_dem(rid, dem, args.archive_root, label=args.label,
                              meta_dir=args.meta_root / rid, git_commit=git_commit,
                              make_current=args.current, now=now)
        except (ArchiveError, OSError) as e:
            print(f"{rid}  FAILED  {e}", file=sys.stderr)
            failed = True
            continue
        print(f"{rid}  {out['status']}  {out['sha256']}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
