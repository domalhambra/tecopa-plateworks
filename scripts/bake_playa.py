#!/usr/bin/env python3
# scripts/bake_playa.py
"""Bake `regions/<id>/playa.json` -- the plate's dry lakes -- from NHD.

Separate from region_prep's main build on purpose. The playa sidecar is ADDITIVE: it
is written beside a plate that already exists, and nothing else on that plate is
touched, so re-running this can never drift the DEM, the hydrography or the labels the
plate's identity is built from. That matters here more than usual -- NHD has already
moved under these plates (this region's committed hydro.json holds 109 lakes where the
service now returns 116 waterbodies), so a full re-prep to pick up dry lakes would have
quietly become a new plate version and made every printed poster report a mismatch.

    source .venv/bin/activate            # needs the -regionprep stack (pynhd)
    python scripts/bake_playa.py                 # every built plate
    python scripts/bake_playa.py lassen_ca ...   # named plates only

Writes nothing when a plate has no playa, so a mountain plate stays exactly as it is.
"""
import os
import sys

import certifi

# aiohttp captures its SSL config at import, so this must precede pynhd (region_prep.py
# carries the same note -- the NHD service fails verification otherwise).
os.environ.setdefault("SSL_CERT_FILE", certifi.where())
os.environ.setdefault("SSL_CERT_DIR", "")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json

import region_prep as rp
from app import regions


def _register_asset(region_dir, name):
    """Record the sidecar in sources.json's asset list with its hash and size.

    `provenance.region_pack_block` reads that list to know what a plate is made of, so
    an unregistered file is invisible to plate identity -- a rebaked playa would never
    be detected. Registering it is safe for existing posters precisely because the
    block SKIPS playa.json unless the sheet draws dry lakes: sources.json is the list,
    not an asset, so it is not hashed itself."""
    import hashlib
    path = os.path.join(region_dir, name)
    src_path = os.path.join(region_dir, "sources.json")
    try:
        with open(src_path) as f:
            src = json.load(f)
    except OSError:
        return                                   # hand-built plate: nothing to register
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    src.setdefault("assets", {})[name] = {"sha256": h.hexdigest(),
                                          "bytes": os.path.getsize(path)}
    with open(src_path, "w") as f:                # insertion order, NOT sort_keys: these
        json.dump(src, f, indent=2)               # files are read by humans and this is
        f.write("\n")                             # an append, so it must diff as one


def bake_one(region):
    import pynhd
    wb = pynhd.WaterData("nhdwaterbody").bybox(region.lonlat_bbox)
    baked = rp.bake_playa(wb, region.cfg["crs"])
    n = len(baked["playas"])
    if not n:
        print(f"{region.id}: no playa -- nothing written")
        return 0
    path = os.path.join(region.dir, "playa.json")
    with open(path, "w") as f:
        json.dump(baked, f, separators=(",", ":"))
    _register_asset(region.dir, "playa.json")
    named = sorted({p["name"] for p in baked["playas"] if p["name"]})
    print(f"{region.id}: {n} playa ring(s) -> {path}"
          + (f"  [{', '.join(named[:4])}]" if named else ""))
    return n


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    found = regions.discover()
    wanted = argv or sorted(found)
    missing = [r for r in wanted if r not in found]
    if missing:
        raise SystemExit(f"not a built plate: {', '.join(missing)}")
    for rid in wanted:
        try:
            bake_one(found[rid])
        except Exception as ex:                     # one plate's outage is not fatal
            print(f"{rid}: FAILED {type(ex).__name__}: {ex}")


if __name__ == "__main__":
    main()
