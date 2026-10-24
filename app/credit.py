# app/credit.py
"""The cartouche's data-credit line (spec.credit_text), derived from a plate's
sources.json. The studio's proof (app.main) and an order's default spec
(app.orderspec) both take it from here, so the spec Prepare proofs is the spec the
studio proofs with no change.

This module never imports app.main (plan decision P8)."""
from __future__ import annotations

import json
import os

from app.spec import CREDIT_MAX_CHARS

# The dataset strings region_prep records in sources.json, mapped to short credits.
# Substring match, so a wording tweak ("USGS 3DEP 10 m DEM" vs "3DEP 1/3 arc-second")
# still lands on the canonical short credit.
CREDIT_DATASETS = (("3DEP", "Terrain USGS 3DEP"),
                   ("NHD", "Water USGS NHD"),
                   ("NLCD", "Land cover NLCD 2021"),
                   ("GNIS", "Names USGS GNIS"))


def credit_text(plate_dir: str) -> str:
    """The attribution sentence for spec.credit_text, derived from the plate's
    sources.json at proof time -- derived truth, not a client style knob. Known USGS
    datasets map to short credits; an UNRECOGNIZED dataset passes through verbatim,
    so a future non-public-domain plate automatically carries its *required* credit
    instead of relying on memory (courtesy today, load-bearing later). Joined with an
    ASCII " - " -- validate() gates credit_text to printable ASCII, and the gate and
    this builder decide the charset once. Clamped to that same gate by construction
    (drop non-ASCII, cap the length) so a plate's own metadata can never 422 a proof.
    No sources.json, or none that name datasets -> "" (no credit row painted)."""
    try:
        with open(os.path.join(plate_dir, "sources.json")) as f:
            sources = json.load(f).get("sources", [])
    except Exception:
        return ""
    parts = []
    for s in sources if isinstance(sources, list) else []:
        ds = s.get("dataset") if isinstance(s, dict) else None
        if not (isinstance(ds, str) and ds.strip()):
            continue
        for token, credit in CREDIT_DATASETS:
            if token in ds:
                part = credit
                break
        else:
            part = ds.strip()
        # a hole-filled dynamic grid records 3DEP twice; the credit names it once
        if part not in parts:
            parts.append(part)
    line = "".join(c for c in " - ".join(parts) if " " <= c <= "~")
    return line[:CREDIT_MAX_CHARS]


def credit_line(region) -> str:
    """credit_text of a Region (anything with a .dir)."""
    return credit_text(region.dir)
