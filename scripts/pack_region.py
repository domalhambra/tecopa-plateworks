#!/usr/bin/env python3
"""Pack a built region into a distributable terrain plate: <id>-<hash>.trailplate.zip.

The plate is the archive of everything a reprint depends on -- every asset the
region's sources.json lists, plus sources.json itself and a generated PLATE.txt
(what this is, the per-asset hashes, the public-domain credits, the CC0 dedication,
the rebuild recipe). The manifest's region_pack block names plates by asset hash
(app/provenance.region_pack_block), so the pack must be honest about its bytes:

  * DRIFT GATE -- before packing, every listed asset is re-hashed from disk. A
    disk-vs-sidecar mismatch (a re-prep that crashed before the sidecar write, a
    clone whose DEM is a synthetic stand-in) REFUSES by default: shipping the
    recorded hash would stamp a plate the bytes don't match, and verification
    downstream would either lie or break. --resync packs the TRUE disk hashes into
    the zip's COPY of sources.json instead -- the source dir is never mutated, and
    the emitted plate never carries a lying sidecar. (--resync is also how CI packs
    a synthetic-DEM test region.)

  * BYTE-STABLE ZIP -- sorted entry order, DOS-epoch timestamps, STORED members
    (no deflate: compressed output is a property of the zlib BUILD -- zlib-ng and
    classic zlib emit different streams for the same input -- and the zip's sha256
    is the plate's published identity, so it must not fork across pack hosts),
    fixed file mode, no extra fields. Pack twice -- on ANY machine -- ->
    byte-identical file, so the zip itself is hash-addressable: the file is named
    by its own sha256 prefix and plates/index.json records the full digest per
    plate. (Size cost is small: the heavy assets are deflate-compressed GeoTIFFs
    already.)

Usage:  python scripts/pack_region.py <region_id> [--regions-root regions]
                                      [--out plates] [--resync]

Stdlib-only on purpose (like the app/plates.py installer): packing must work on a
machine that never installed the render stack.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import shutil
import sys
import zipfile

# Every entry carries the DOS epoch: the pack's identity is its CONTENT, never the
# wall clock of the machine that zipped it (determinism is a hard invariant here --
# the tests byte-compare two packs of the same region).
DOS_EPOCH = (1980, 1, 1, 0, 0, 0)
CC0_URL = "https://creativecommons.org/publicdomain/zero/1.0/"


class DriftError(RuntimeError):
    """The region dir's bytes don't match what its sources.json records (or a listed
    asset is missing) -- packing would emit a plate whose sidecar lies about it."""


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _effective_sources(region_dir: str, resync: bool) -> tuple[dict, bytes]:
    """(sources dict, the exact sources.json bytes to pack). The drift gate lives
    here: every listed asset is re-hashed from disk. No drift -> the on-disk sidecar
    bytes are packed verbatim. Drift + --resync -> the RETURNED COPY carries the true
    disk hashes/sizes and is re-serialized (indent=2, the sidecar's own style); the
    source dir is never written. Drift without --resync, or a missing asset (which
    --resync can't invent) -> DriftError naming every offender and the fix."""
    src_path = os.path.join(region_dir, "sources.json")
    try:
        raw = open(src_path, "rb").read()
    except OSError:
        raise DriftError(f"{region_dir} has no sources.json — only regions built by "
                         f"region_prep.py (which records every asset hash) can be packed")
    src = json.loads(raw)
    missing, drifted = [], []
    for name in sorted(src.get("assets", {})):
        path = os.path.join(region_dir, name)
        if not os.path.exists(path):
            missing.append(name)
            continue
        disk = _sha256_file(path)
        if disk != src["assets"][name].get("sha256"):
            drifted.append((name, disk, os.path.getsize(path)))
    if missing:
        raise DriftError(
            "refusing to pack: " + ", ".join(missing) + " listed in sources.json but "
            "missing from " + region_dir + " — rebuild the region (region_prep.py) "
            "before packing")
    if drifted and not resync:
        lines = "\n".join(
            f"  {name} — disk sha256 {disk[:12]}… != recorded "
            f"{(src['assets'][name].get('sha256') or '')[:12]}…"
            for name, disk, _ in drifted)
        raise DriftError(
            f"refusing to pack {os.path.basename(region_dir)}: assets have drifted "
            f"from sources.json:\n{lines}\nrerun the region build (region_prep.py) or "
            f"scripts/build_labels.py to resync the sidecar, or pass --resync to pack "
            f"the true disk hashes into the plate's copy")
    if drifted:                                     # --resync: the COPY tells the truth
        for name, disk, size in drifted:
            src["assets"][name] = {"sha256": disk, "bytes": size}
        raw = json.dumps(src, indent=2).encode()    # sidecar style; never written back
    return src, raw


def _plate_txt(rid: str, src: dict, name: str) -> str:
    """The human-readable face of the pack. A pure function of sources.json content
    (plus the region display name, itself a hashed pack asset) -- no wall clock, no
    machine state -- so the zip stays byte-stable. The asset table shows the hashes
    the pack's own sources.json copy carries (post-resync truth)."""
    assets = src.get("assets", {})
    width = max(len(n) for n in assets) if assets else 0
    lines = [
        f"Tecopa Plateworks terrain plate: {rid}",
        "=" * (26 + len(rid)),
        "",
        "This archive is a Tecopa Plateworks terrain plate: every asset the engine reads",
        "to paint (and re-paint, byte-for-byte) posters for one region. A poster's",
        "embedded manifest names this plate by these same asset hashes, so a reprint",
        "can verify it runs against the exact terrain the poster was painted on.",
        "",
        "Install it next to the engine with:",
        "",
        "    python -m app.plates install <this file>",
        "",
        "Region",
        "------",
        f"id   : {rid}",
        f"name : {name}",
        f"crs  : {src.get('crs', 'unknown')}",
        "bbox : " + " ".join(repr(v) for v in src.get("fetch_bbox_4326", []))
        + "  (EPSG:4326 west south east north)",
    ]
    if src.get("built"):
        lines.append(f"built: {src['built']}")     # the sidecar's own record; no new dates
    lines += ["", "Assets (sha256)", "---------------"]
    lines += [f"{n.ljust(width)}  {assets[n].get('sha256', '')}" for n in sorted(assets)]
    lines += ["", "Data sources", "------------"]
    lines += [f"- {s.get('dataset', '?')} (via {s.get('via', '?')}) — "
              f"{s.get('license', '?')}" for s in src.get("sources", [])]
    lines += [
        "",
        "License",
        "-------",
        "Every dataset above is US-federal public domain work. This plate as a",
        "whole — the baked assets, this note, and the sources.json record — is",
        f"dedicated to the public domain under CC0-1.0 ({CC0_URL}).",
        "",
        "Rebuild",
        "-------",
        src.get("rebuild", "(no rebuild recipe recorded)"),
        "",
    ]
    return "\n".join(lines)


def _add_entry(zf: zipfile.ZipFile, arcname: str, src_path=None, data=None):
    """One byte-stable zip member: DOS-epoch date, unix create system, 0644 mode,
    STORED (deflate output varies per zlib build, and the zip's sha256 is the
    plate's cross-machine identity), no extra field. Streams from disk so a 700 MB
    DEM never sits whole in memory."""
    zi = zipfile.ZipInfo(arcname, date_time=DOS_EPOCH)
    zi.create_system = 3
    zi.external_attr = 0o644 << 16
    zi.compress_type = zipfile.ZIP_STORED
    with zf.open(zi, "w") as dst:
        if data is not None:
            dst.write(data)
        else:
            with open(src_path, "rb") as f:
                shutil.copyfileobj(f, dst, 1 << 20)


def _update_index(out_dir: str, entry: dict) -> str:
    """Insert/update this plate's row in plates/index.json ({"schema": 1, "plates":
    [...]}, sorted by (id, file)). The index is the committed record of every
    published plate's hash -- the packs themselves are release assets, so the hashes
    must live in repo history even if the zips move hosts. Keyed by id: repacking a
    region replaces its row instead of accumulating stale ones."""
    path = os.path.join(out_dir, "index.json")
    plates = []
    if os.path.exists(path):
        with open(path) as f:
            plates = [p for p in json.load(f).get("plates", [])
                      if p.get("id") != entry["id"]]
    plates.append(entry)
    plates.sort(key=lambda p: (p["id"], p["file"]))
    with open(path, "w") as f:
        json.dump({"schema": 1, "plates": plates}, f, indent=2, sort_keys=True)
    return path


def pack_region(region_id: str, regions_root: str = "regions",
                out_dir: str = "plates", resync: bool = False) -> str:
    """Pack regions_root/<region_id> into out_dir/<id>-<ziphash12>.trailplate.zip and
    update out_dir/index.json. Returns the pack's path. Raises DriftError when the
    drift gate refuses (nothing is written in that case)."""
    region_dir = os.path.join(regions_root, region_id)
    src, src_bytes = _effective_sources(region_dir, resync)
    try:                                     # display name: region.json is a pack asset
        with open(os.path.join(region_dir, "region.json")) as f:
            display = json.load(f).get("name", region_id)
    except Exception:
        display = region_id
    plate_txt = _plate_txt(region_id, src, display).encode()
    members = {f"{region_id}/{n}": (os.path.join(region_dir, n), None)
               for n in src.get("assets", {})}
    members[f"{region_id}/sources.json"] = (None, src_bytes)
    members[f"{region_id}/PLATE.txt"] = (None, plate_txt)

    os.makedirs(out_dir, exist_ok=True)
    tmp = os.path.join(out_dir, f".pack-{region_id}.tmp")
    try:
        with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_STORED) as zf:
            for arcname in sorted(members):
                path, data = members[arcname]
                _add_entry(zf, arcname, src_path=path, data=data)
        zip_sha = _sha256_file(tmp)
        final = os.path.join(out_dir, f"{region_id}-{zip_sha[:12]}.trailplate.zip")
        os.replace(tmp, final)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    _update_index(out_dir, {
        "id": region_id,
        "file": os.path.basename(final),
        "sha256": zip_sha,
        "bytes": os.path.getsize(final),
        "assets": {n: a["sha256"] for n, a in sorted(src.get("assets", {}).items())},
    })
    return final


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Pack a built region into a "
                                             "deterministic .trailplate.zip")
    ap.add_argument("region_id")
    ap.add_argument("--regions-root", default="regions")
    ap.add_argument("--out", default="plates")
    ap.add_argument("--resync", action="store_true",
                    help="on disk-vs-sidecar drift, pack the true disk hashes into "
                         "the zip's copy of sources.json (the source dir is never "
                         "mutated) instead of refusing")
    a = ap.parse_args(argv)
    try:
        path = pack_region(a.region_id, a.regions_root, a.out, resync=a.resync)
    except (DriftError, OSError, KeyError, ValueError) as e:
        print(str(e), file=sys.stderr)
        return 2
    print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
