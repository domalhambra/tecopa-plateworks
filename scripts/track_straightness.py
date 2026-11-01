#!/usr/bin/env python3
"""Print how straight each plate's demo trips run: one row per plate.

    ./.venv/bin/python scripts/track_straightness.py                # every cached plate
    ./.venv/bin/python scripts/track_straightness.py lassen_ca tecopa_ca

Run from the repo root. A plate is read when `cache/networks/<id>.json` exists.
The share is taken on the ROUTED paths, before densify and jitter, resampled
every 100 m: the part of all heading changes under 3 degrees (spec section 7,
docs/superpowers/specs/2026-11-01-showcase-plates-and-pick-a-plate-landing-design.md).
Changes pool over every trip on the plate, so a long trip counts for more."""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.regions import discover                                   # noqa: E402
from scripts.track_network import (load_network, network_tracks,   # noqa: E402
                                   straight_counts)

NETWORK_CACHE = os.path.join("cache", "networks")


def plate_straightness(region, ways: list[dict]) -> tuple[int, int, int]:
    """(trips, straight changes, all changes) for one plate's seeded year."""
    raw: list = []
    network_tracks(region, ways, raw_out=raw)
    counts = [straight_counts(p) for p in raw]
    return (len(raw), sum(s for s, _ in counts), sum(t for _, t in counts))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("plates", nargs="*", help="plate ids (default: every plate with a cache)")
    args = ap.parse_args()

    regions = discover()
    ids = args.plates or sorted(
        f[:-5] for f in os.listdir(NETWORK_CACHE) if f.endswith(".json"))
    print(f"{'plate':<20} {'trips':>5} {'changes':>8} {'straight':>9}")
    status = 0
    for rid in ids:
        cache = os.path.join(NETWORK_CACHE, f"{rid}.json")
        if rid not in regions or not os.path.exists(cache):
            print(f"{rid:<20} (no plate or no cache at {cache})")
            status = 1
            continue
        trips, straight, total = plate_straightness(regions[rid], load_network(cache))
        share = f"{100.0 * straight / total:.1f}%" if total else "n/a"
        print(f"{rid:<20} {trips:>5} {total:>8} {share:>9}")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
