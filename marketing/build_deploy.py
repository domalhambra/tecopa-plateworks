#!/usr/bin/env python3
"""The terrain guard: no marketing image of invented country reaches a page.

Every image on the Tecopa pages is the engine's own render of real country
(CLAUDE.md invariant 11). `terrain_guard` enforces it: it refuses any region whose
assets were rendered from a synthetic stand-in DEM, or whose terrain the farm never
recorded in `assets/index.json`. `scripts/export_relief.py` runs it before it writes
a single web image for the Ghost pages.

The module keeps its name from the Netlify landing it once built. That staged-root
builder retired with the landing on 2026-09-26; it is at tag
`landing-final-2026-09-26`, along with `landing.html` and `privacy.html`.
"""
from __future__ import annotations

import sys

FARM_CMD = "./.venv/bin/python scripts/render_asset_farm.py --regions"


def terrain_guard(index: dict, regions, allow_synthetic: bool = False,
                  allow_unverified: bool = False) -> int:
    """Refuse (1) to publish regions the farm's index does not vouch for; else 0.

    The pages promise every image on them is the engine's own render. A synthetic
    stand-in DEM renders *cleanly* — correct hillshade, palette, place labels, route
    ink — so the picture itself never gives it away. Without this check a container
    that could not download 700 MB of real terrain would publish pictures of country
    that does not exist.

    Fail-closed, and per region: pass every region whose images are about to go out.
    `index` is the parsed `assets/index.json`; {} (absent or unreadable) vouches for
    nothing. The two overrides each open only their own door, and warn when they do.
    """
    def record(rid):
        """The region's terrain record, or None if it does not vouch for anything.

        `synthetic` must be a real bool. The farm writes nothing else, so any other
        shape — absent, `{}`, `null`, `0`, `"false"` — means the file was hand-edited
        or corrupted, and a corrupted provenance record is precisely what this guard
        exists not to believe. Reading it as "not synthetic" would be the one way a
        malformed index could fail OPEN; routing it here sends it to the unverified
        refusal with every other malformed shape.
        """
        entry = index.get(rid)
        rec = entry.get("terrain") if isinstance(entry, dict) else None
        if isinstance(rec, dict) and isinstance(rec.get("synthetic"), bool):
            return rec
        return None

    synthetic = sorted(r for r in regions if (record(r) or {}).get("synthetic"))
    unrecorded = sorted(r for r in regions if record(r) is None)

    if synthetic and not allow_synthetic:
        print("\nerror: SYNTHETIC terrain — these regions' images were rendered from a "
              "test stand-in DEM,\n       not real 3DEP terrain, so their landforms are "
              "invented:", file=sys.stderr)
        for rid in synthetic:
            print(f"  {rid}", file=sys.stderr)
        print("The pages promise every image is the engine's own render. Rebuild the "
              "plate from real\nterrain (see docs/changing-things.md, \"Repair an orphaned DEM\"), then "
              "re-render:", file=sys.stderr)
        print(f"  {FARM_CMD} {' '.join(synthetic)}", file=sys.stderr)
        print("Only a caller passing allow_synthetic=True publishes them anyway.", file=sys.stderr)
        return 1
    if unrecorded and not allow_unverified:
        print("\nerror: UNVERIFIED terrain — assets/index.json carries no terrain record "
              "for these\n       regions, so what their images were rendered from is "
              "unknown:", file=sys.stderr)
        for rid in unrecorded:
            print(f"  {rid}", file=sys.stderr)
        print("The record is stamped when the farm opens a DEM; a restage-only run "
              "(--only\ndetail/model/mockups/coin) opens none and stamps nothing. "
              "Re-render:", file=sys.stderr)
        print(f"  {FARM_CMD} {' '.join(unrecorded)}", file=sys.stderr)
        print("Only a caller passing allow_unverified=True publishes them anyway.", file=sys.stderr)
        return 1

    if synthetic:
        print(f"\nWARNING: allow_synthetic — publishing INVENTED landforms as the "
              f"engine's own\n         render of real country: {', '.join(synthetic)}",
              file=sys.stderr)
    if unrecorded:
        print(f"\nWARNING: allow_unverified — publishing images whose source "
              f"terrain is\n         unrecorded; they may not be real country: "
              f"{', '.join(unrecorded)}", file=sys.stderr)
    return 0
