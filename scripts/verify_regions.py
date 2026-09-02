#!/usr/bin/env python3
"""Check every built region's assets against the sha256 its sources.json records.

A SCRIPT, deliberately not a test. `regions/*/dem.tif` is gitignored while every
other plate asset is committed, and `tests/conftest.py` hydrates a synthetic
stand-in for any DEM that is missing -- so on CI and on a fresh clone EVERY region
reads as drifted, correctly. A pytest asserting no drift would be red in exactly
the environments it runs in most, which is the trap `tests/test_plates.py` already
learned (see its `_region_copy` docstring: a drift test must CONSTRUCT drift, never
inherit it from the host). Run this on demand instead, the way the workspace runs
`allowlist_audit.py` -- after a pull that touched `regions/`, after repairing a
DEM, and before packing a plate.

What drift means depends on which asset moved, and the answer is never automatic:

  * dem.tif drifted, everything else clean -> a DEM was REBUILT rather than
    restored. Expected after the CLAUDE.md orphan repair, which calls
    `region_prep.build_dem_cog` directly and so never re-runs the sidecar writer.
    USGS re-tiles 3DEP, so a rebuild cannot reproduce the original bytes. Leave
    the sidecar alone -- the mismatch IS the record that the plate was swapped --
    and pack with `pack_region --resync`, which writes the true disk hashes into
    the ZIP's copy without mutating the source dir.

  * a committed asset drifted (hydro/labels/landcover/overview/region/playa) ->
    something rewrote a file git is tracking. Check `git status` first; this is
    much more likely to be a real mistake than the DEM case.

  * MISSING -> the region is not built, or a pull orphaned the DEM.

  * ORPHAN (the geometry row) -> the DEM on disk does not cover region.json's bounds
    or CRS. This is the pull orphan: a plate rebuilt elsewhere shipped its region.json
    to main and this machine's gitignored DEM stayed behind. Repair it (CLAUDE.md,
    the orphan repair). The engine refuses to render such a plate with a 503.

  The decisive rule: dem.tif DRIFT with geometry ok is a REBUILT plate, known and
  left alone. dem.tif DRIFT with geometry ORPHAN needs the repair.

This does NOT decide anything or write anything. Re-stamping a sidecar is a
deliberate act with a reason recorded next to it, never a script's side effect:
a manifest that silently re-syncs itself can no longer detect the swap it exists
to detect.

Stdlib-only, matching scripts/pack_region.py -- verification must work on a
machine that never installed the render stack. It therefore reports drift by
bytes alone and cannot read the `synthetic=1` GeoTIFF tag; use
`regions.discover()` -> `readiness()` when you need to tell a synthetic stand-in
from real terrain.

Usage:  python scripts/verify_regions.py [region_id ...] [--regions-root regions]
Exit 1 if anything drifted or is missing, 0 if every listed asset matches.
"""
from __future__ import annotations
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.pack_region import _sha256_file   # noqa: E402  one hasher, one verdict

# The geometry row needs the render stack (rasterio via app.regions). The script stays
# stdlib-first: without it the row says "not checked" and everything else still runs.
try:
    from app.regions import Region as _Region   # noqa: E402

    def _readiness(region_dir: str) -> dict:
        root, rid = os.path.split(os.path.abspath(region_dir))
        return _Region(rid, root=root).readiness()
except Exception:                                # ImportError, or a broken venv
    _readiness = None


def geometry_verdict(region_dir: str) -> tuple[str, str]:
    """(verdict, detail) for the DEM's geometry against region.json.
    ok | ORPHAN | MISSING | skip. `skip` means the render stack is not installed here."""
    if _readiness is None:
        return ("skip", "not checked (render stack not installed; run from .venv)")
    if not os.path.exists(os.path.join(region_dir, "region.json")):
        return ("MISSING", "no region.json")
    rep = _readiness(region_dir)
    if not rep.get("dem_present"):
        return ("MISSING", "dem.tif absent")
    if rep.get("error"):
        return ("ORPHAN", f"DEM could not be opened: {rep['error']}")
    if rep.get("ready"):
        return ("ok", f"bounds drift {rep['bounds_drift_m']:.2f} m, CRS matches")
    why = (f"bounds drift {rep.get('bounds_drift_m', 0.0):.2f} m"
           if not rep.get("bounds_match", True) else "CRS differs from region.json")
    return ("ORPHAN", f"{why} -- the DEM on disk is not this plate's; "
                      f"run the orphan repair in CLAUDE.md")


def verify_region(region_dir: str) -> list[tuple[str, str, str]]:
    """[(asset, verdict, detail)] for one region. verdict is ok | DRIFT | MISSING.
    Raises nothing: an unbuilt region is a finding, not an error."""
    try:
        with open(os.path.join(region_dir, "sources.json")) as f:
            src = json.load(f)
    except OSError:
        return [("sources.json", "MISSING", "not built by region_prep.py")]

    rows = []
    for name in sorted(src.get("assets", {})):
        rec = src["assets"][name]
        path = os.path.join(region_dir, name)
        if not os.path.exists(path):
            rows.append((name, "MISSING", "listed in sources.json, absent on disk"))
            continue
        size = os.path.getsize(path)
        disk = _sha256_file(path)
        if disk == rec.get("sha256"):
            rows.append((name, "ok", f"{size:,} B"))
        else:
            rows.append((name, "DRIFT",
                         f"{rec.get('bytes', 0):,} -> {size:,} B "
                         f"({size - rec.get('bytes', 0):+,})\n"
                         f"      recorded {rec.get('sha256')}\n"
                         f"      on disk  {disk}"))
    return rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("region_id", nargs="*",
                    help="regions to check (default: every region on disk)")
    ap.add_argument("--regions-root", default="regions")
    args = ap.parse_args(argv)

    root = args.regions_root
    if not os.path.isdir(root):
        print(f"no regions root at {root!r}", file=sys.stderr)
        return 2
    ids = args.region_id or sorted(
        d for d in os.listdir(root) if os.path.isdir(os.path.join(root, d)))

    bad = 0
    for rid in ids:
        rows = verify_region(os.path.join(root, rid))
        flags = [r for r in rows if r[1] != "ok"]
        bad += len(flags)
        print(f"\n{rid}  --  {len(rows) - len(flags)}/{len(rows)} ok")
        for name, verdict, detail in rows:
            if verdict == "ok":
                print(f"  ok     {name}  {detail}")
            else:
                print(f"  {verdict:<6} {name}  {detail}")

        verdict, detail = geometry_verdict(os.path.join(root, rid))
        if verdict == "ok":
            print(f"  ok     geometry  {detail}")
        elif verdict == "skip":
            print(f"  --     geometry  {detail}")
        else:
            print(f"  {verdict:<6} geometry  {detail}")
            bad += 1

    if bad:
        print(f"\n{bad} drifted, missing, or orphaned finding(s). This is a finding to "
              f"READ, not a failure to clear -- see this script's docstring for what "
              f"each kind means. ORPHAN is the one that needs repair. Do not re-stamp "
              f"a sidecar to make it quiet.")
    else:
        print(f"\nevery listed asset in {len(ids)} region(s) matches its sources.json.")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
