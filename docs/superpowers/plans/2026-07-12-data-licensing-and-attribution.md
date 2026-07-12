# TrailPrint — Data Licensing & Attribution (verdict + hardening plan)

_2026-07-12 · Status: **verdict is clear for today's four plates; the hardening below is
proposed.** Answers the direct question "can I sell posters made from this data?" and turns
the answer into durable practice. Companion: `2026-07-12-reprint-forever-continuity.md`
(the engine `LICENSE` this plan specifies)._

> **This document is an engineering/product plan, not legal advice.** The conclusion below
> is well-supported for the specific datasets in use, but a commercial launch warrants a
> one-time confirmation from a lawyer. The good news: the facts are simple.

---

## The verdict — yes, you can sell them (for the current four plates)

**Every dataset every region uses is a work of the U.S. federal government**, verified
across all four `regions/*/sources.json` plus the labels builder:

| Data | Source | In code | License |
|---|---|---|---|
| Elevation (relief) | USGS 3DEP 10 m / 30 m DEM | `region_prep.py` (`py3dep`) | Public domain (USGS) |
| Water | USGS NHD waterbodies + flowlines | `region_prep.py` (`pynhd`) | Public domain (USGS) |
| Land cover (biome tint) | NLCD 2021 (30 m) | `region_prep.py` (`pygeohydro`) | Public domain (USGS/MRLC) |
| Place names (labels) | USGS GNIS Landforms | `scripts/build_labels.py` (nationalmap.gov) | Public domain (USGS) |

Under **17 U.S.C. § 105**, a work prepared by an officer or employee of the U.S. Government
as part of their official duties is **not eligible for copyright** — it is public domain.
Public-domain data may be used for **any purpose, including commercial resale**, without a
license, royalty, or permission. So: **selling posters, wallpapers, and films rendered from
this data is permitted.** There is no rights-holder to license from because there is no
copyright to license.

The Python libraries (`py3dep`, `pynhd`, `pygeohydro` — the HyRiver stack) are just *access
tools*; their MIT/BSD licenses govern the **code**, never the public-domain **data** they
fetch. Their servers' rate limits govern *fetching*, not *reselling the result*.

## The five caveats (none blocks selling today; all worth handling)

1. **Attribution is courtesy, not law — but do it anyway.** USGS *requests* citation and
   forbids implying government **endorsement**; neither is legally required for public-domain
   data, but both are cheap, and the moment you add any non-federal source (caveat 4) some
   attribution becomes *mandatory*. Building the habit now costs one line on the poster.
2. **§105 is U.S.-only in theory.** U.S. government works *can* be copyrighted in some other
   countries. In practice USGS data is treated as free worldwide and this is essentially
   never enforced, but if you sell internationally at scale it's worth a lawyer's glance.
   Not a blocker for a U.S. launch.
3. **The font is the one proprietary-adjacent element.** `render.py:335` tries
   `TRAILPRINT_FONT` → **`Georgia.ttf`** → `DejaVuSerif.ttf` → `DejaVuSans.ttf`. Georgia is
   a Microsoft-licensed typeface. Two facts keep you clear: (a) in the U.S., **typeface
   designs aren't copyrightable and a rendered raster image is not a derivative of the font
   software**, so *selling a poster that used Georgia to draw text is generally fine*; (b)
   what you must **not** do is **redistribute the `Georgia.ttf` file itself** — so don't
   bundle it into an installer (relevant to Fork A in the strategy plan). DejaVu (the
   fallback) is freely redistributable; a licensed display face via `TRAILPRINT_FONT` is the
   clean path. **Action: confirm no build ships `Georgia.ttf`; pick a redistributable poster
   face for any packaged app.**
4. **Going global breaks the clean story — gate it.** The red-team roadmap's v2 geo rock
   names non-federal sources whose licenses are *not* public domain:
   - **Copernicus GLO-30 DEM** — free, but **attribution required**.
   - **OpenStreetMap water** — **ODbL**: attribution **and share-alike**; the share-alike can
     obligate you to publish derived data. This is the genuinely dangerous one for a
     commercial product.
   - **SRTM** — public domain; **HydroSHEDS** — check the version, some carry
     **non-commercial** terms.
   **Action: no non-USGS source enters a plate without clearing its license first.** Today's
   four plates are entirely federal PD; keep that property until a source is explicitly
   cleared.
5. **You still need an engine `LICENSE`** (from the continuity plan). That's about the
   *code*, not the data — but "your file reprints itself" requires publishing a runnable,
   legally-usable engine, so the two plans meet here.

## Hardening work (turn the verdict into durable practice)

- **Render attribution onto the deliverable.** A small, tasteful credit line ("Terrain:
  USGS 3DEP · Water: USGS NHD · Land cover: NLCD · Names: USGS GNIS") in the cartouche or
  a `tEXt`/`zTXt` chunk. Courtesy today; mandatory the day a Copernicus/OSM plate ships.
  The manifest is the natural machine-readable home; the poster face is the human one.
- **Promote `sources.json` to a real license record.** It already lists dataset + `via` +
  `license` per region; make it the single source of truth the attribution line renders
  *from*, so a future non-PD plate automatically carries its required credit instead of
  relying on memory.
- **Resolve the font** (caveat 3): confirm shipping posture, choose a redistributable face.
- **A source-license checklist** in `region_prep` docs: no dataset joins a plate without a
  recorded, resale-compatible license — the gate that keeps caveat 4 from ever silently
  entering.
- **Add the engine `LICENSE`** (continuity plan) — pick a license consistent with the
  chosen product fork (permissive for Fork A/C).

## Bottom line

**Today: yes — every plate is built from U.S. federal public-domain data, and you may sell
what you render from it.** Keep it that way by (1) adding a courtesy attribution line now,
(2) not shipping the Georgia font file, and (3) treating "is this source resale-compatible?"
as a hard gate the day you add any non-USGS data — which is exactly the moment the current
clean answer would otherwise quietly stop being true.
