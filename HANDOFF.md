# TrailPrint — Session Handoff

_Last updated: 2026-06-29 · HEAD `1e7aaa6` on `main` · 41 tests green · pushed to `git@github.com:domalhambra/badwatertrails.git`_

Read this first to continue in a fresh session. It captures state, how to run, the invariants you must protect, the gotchas already paid for, and what's next.

---

## What TrailPrint is

A single **local** app (FastAPI, no DB/queue/hosting) that imports GPX/KML/KMZ tracks and renders a **shaded-relief poster** of where someone has been within one curated region. One process serves a thin browser "aim" view and the render engine. Three fidelity tiers come from **one** engine: the live aim view (cheap, in-browser), a mid-fidelity **proof** (96 dpi), and the full **final** (300 dpi). **The point of v1 is to settle the map style, not to scale.**

The render engine splits at one seam: **`compose`** decides the picture once in ground coordinates and emits a `CompositionSpec`; **`rasterize`** paints that spec at any resolution. Proof and final are the *same spec* painted at two pixel sizes.

---

## Current state

**v1 is architecturally complete.** Built across this session: the coordinate spine, ingest, density, the spec + zoom cap, the relief engine, rasterize, the web app, region prep, **KML/KMZ import, multi-file drag-drop upload, and baked hydrography (lakes + rivers)**. The flagship region is rebuilt clean and sized for an 18×24 print.

- **Region:** `lassen_ca` — Lassen County, CA, framed on the Susanville→Eagle Lake corridor. EPSG:32610 (UTM 10N), 10 m, **63×78 km**, NaN-trimmed. `hydro.json` carries 116 lakes + 307 rivers (NHD, order ≥ 3).
- **Tests:** 41 passing (`./.venv/bin/python -m pytest tests/ -q`). Integration tests skip cleanly if the DEM is absent.
- **Dummy data:** `tests/fixtures/sample.gpx` is **synthetic** (5 dated Susanville↔Eagle Lake trips via `scripts/make_dummy_gpx.py`). Swap in a real OnX/Avenza export when available.

---

## How to run / dev setup

```bash
cd "Badwater Trails"
source .venv/bin/activate            # Python 3.14; or call ./.venv/bin/python directly
pytest -q                            # 41 passing
uvicorn app.main:app --reload        # http://127.0.0.1:8000 — drop GPX/KML/KMZ, crop, proof, accept
```

**Rebuild the region** (offline, ~4 min, ~190 MB DEM, needs network — SSL is handled in-script):
```bash
python region_prep.py --id lassen_ca --name "Lassen County, California" \
  --bbox -121.06 40.16 -120.34 40.85 --epsg 32610
```

To **render a poster ad hoc**, build a `CompositionSpec` and call `render.rasterize(spec, dpi, region_dir)` — see `tests/test_render.py` for the pattern. A finalized 18×24 crop is `crop = (cx-27000, cy-36000, cx+27000, cy+36000)` centered on the region (54×72 km → exactly 10 m/px at 18×24 @ 300, which the zoom cap requires).

---

## Architecture & invariants — PROTECT THESE

1. **One spec, painted at many sizes.** Proof and final come from the identical `CompositionSpec`. Never compute the picture twice.
2. **Physical units, never pixels, for anything visual.** Line widths in points, marker/grain in inches, blur radii in ground-metres. Convert to px at the target DPI at paint time. (A pixel-sized element looks bold in the proof and vanishes in the final — this bug class has bitten twice; the relief radii and the lake shoreline both had to be de-pixelized.)
3. **Determinism.** Same spec + seed → identical image. Grain/jitter are seeded.
4. **One projection throughout.** DEM, overview, tracks, crop, hydro all in the region CRS metres. Tracks arrive lon/lat and are reprojected first (`always_xy`).
5. **Registration is correctness.** Prove the coordinate chain (a control point) before tuning aesthetics. `app/geo.py` is the single source of truth for coordinate conversions.
6. **The zoom cap.** Never request finer ground detail than the data holds (10 m → ~3 km of ground per print-inch at 300 dpi). `CompositionSpec.validate(dpi)` enforces it; the web app validates at the **final** DPI (300) at proof time.

**Region-level data (DEM, `hydro.json`) is read from the region dir by `render` — it is NOT carried on the spec** (same as the DEM). The spec holds the picture *decisions* (crop, print size, tracks, hotspots, style values, seed).

---

## File map

```
region_prep.py          OFFLINE one-time: fetch 3DEP DEM + NHD water, build COG + overview + region.json + hydro.json
scripts/make_dummy_gpx.py  deterministic synthetic GPX generator (Susanville<->Eagle Lake)
app/
  geo.py        every coordinate conversion (overview px <-> CRS metres <-> crop windows)
  ingest.py     GPX/KML/KMZ -> reproject -> drop non-finite -> simplify -> Track. load_tracks() auto-detects format
  density.py    projected tracks -> visitation-weighted hotspots (counts distinct days/tracks, not points)
  spec.py       CompositionSpec: the compose/rasterize contract; physical style values; zoom-cap validate()
  relief.py     pure-numpy relief passes: hillshade, hypsometric tint, texture, valley, grain. THE TUNING SURFACE
  render.py     rasterize(spec, dpi, region_dir): read DEM window -> relief -> water -> tracks -> markers. Also water/track style constants
  session.py    in-memory single-user session store (no DB in v1)
  main.py       FastAPI: /api/upload (multi-file accumulate), /api/proof (96dpi), /api/final (300dpi)
  static/       index.html, app.js, style.css — drag-drop aim-view UI
regions/lassen_ca/  dem.tif (gitignored, ~190MB), overview.png, region.json, hydro.json
docs/superpowers/   specs/ and plans/ — the design + implementation plan for the v1 architecture work
```

---

## Environment gotchas (already paid for — don't rediscover)

- **Python 3.14 only** on this Mac (no pyenv, no 3.11/3.12). All scientific wheels (rasterio, pyproj, scipy, geopandas, pynhd) install cleanly on 3.14.
- **USGS NHD SSL:** python.org Python on macOS ships **no system CA bundle**, so `api.water.usgs.gov` fails cert verification. `region_prep.py` sets `SSL_CERT_FILE` from `certifi` **at the very top, before importing py3dep/pynhd** (aiohttp captures its SSL config at import — setting it later races onto the empty store and large concurrent fetches fail). It also fetches hydro **before** the DEM (a prior large py3dep fetch leaves SSL dirty). If you add new network code, keep this ordering.
- **py3dep returns EPSG:5070 (CONUS Albers), in metres — not 4326.** `to_cog` reprojects from the DataArray's own CRS via rioxarray, then clips to the bbox UTM box to kill NaN corners.
- **`cache/`** (requests-cache from NHD/3DEP) and **`regions/*/dem.tif`, `final_*.png`, `tune.png`, `poster.png`, `comparison.png`** are gitignored. `region.json` / `overview.png` / `hydro.json` ARE committed; the DEM is regenerated via `region_prep.py`.

---

## Conventions used this session (keep them)

- **TDD:** failing test → see it fail → minimal implementation → green → commit. Every module was built this way.
- **Adversarial review per component** via the `Workflow` tool (review each changed file, then independently *verify* each finding before acting). This caught **~15 real bugs** across the session — including a critical 90°-rotated hillshade, a stale-spec silent-data-loss bug, and the NaN-`streamorde` crash. **Strongly recommend continuing this after each substantial component.**
- **Granular commits**, present-tense subject, body explains the *why*, ending with the `Co-Authored-By: Claude Opus 4.8` trailer. Direct to `main` (solo repo, each task committed only when green so `main` stays shippable).

---

## Open threads / what's next (priority order)

1. **Style tuning by eye — the v1 finish line.** Every aesthetic lever is a named constant:
   - Relief palette / light / texture / valley: top of `app/relief.py` (`HYPSO_STOPS`, `TEXTURE_*`, `VALLEY_*`, `HILLSHADE_GAMMA`, `TEXTURE_RADIUS_M`, `VALLEY_RADIUS_M`).
   - Track ink / casing / markers: top of `app/render.py` (`TRACK_INK`, `TRACK_CASING`, `CASING_*`, `INK_*`, marker fill/size).
   - Water: `WATER_FILL`, `WATER_SHORELINE`, `SHORELINE_PT`, `RIVER_COLOR`, `RIVER_BASE_PT`/`RIVER_STEP_PT`.
   The success criterion (from Dom's original build plan): a render that reads as belonging in the same family as the two reference maps (Utah shaded-relief; Matanuska-Susitna hydrographic), judged by eye, with a real track on the terrain.
2. **Real GPX fixture.** Replace the synthetic `sample.gpx` with a real OnX/Avenza export and re-verify the by-eye look on real tracks.
3. **Title/legend treatment is bare** (`render.rasterize` draws a small bottom-left title). A finished poster likely wants a real title block / margin / legend — partly aesthetic, decide with Dom.
4. **Roadmap beyond v1** (each names the seam it already uses, so none is a teardown): v1.1 photos + richer/emoji markers (hotspots already on the spec); v1.2 more regions + soul-pass baked layers (region_prep already writes per-region config; KML already done); v1.3 server — job queue + Postgres + object storage (the compose→rasterize split is the queue boundary; `session.py` is the only file that becomes a DB); v1.4 accounts + payment + print fulfillment (final render already gated behind explicit accept).

---

## Key documents

- `docs/superpowers/specs/2026-06-29-trailprint-v1-architecture-design.md` — the approved design for the architecture-completion work.
- `docs/superpowers/plans/2026-06-29-trailprint-v1-architecture.md` — the TDD implementation plan (all tasks checked off).
- Dom's **original build plan** (`~/Downloads/trailprint-mvp-build-plan.md`) — the source of the invariants, the file map, and the v1.1–v1.4 roadmap. Worth re-reading before large changes.
