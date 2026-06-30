# TrailPrint — Session Handoff

_Last updated: 2026-06-30 · branch `claude/handoff-continuation-vinei8` (PR #1) · 64 tests green · pushed to `git@github.com:domalhambra/badwatertrails.git`_

Read this first to continue in a fresh session. It captures state, how to run, the invariants you must protect, the gotchas already paid for, and what's next.

---

## What TrailPrint is

A single **local** app (FastAPI, no DB/queue/hosting) that imports GPX/KML/KMZ tracks and renders a **shaded-relief poster** of where someone has been within one curated region. One process serves a thin browser "aim" view and the render engine. Three fidelity tiers come from **one** engine: the live aim view (cheap, in-browser), a mid-fidelity **proof** (96 dpi), and the full **final** (300 dpi). **The point of v1 is to settle the map style, not to scale.**

The render engine splits at one seam: **`compose`** decides the picture once in ground coordinates and emits a `CompositionSpec`; **`rasterize`** paints that spec at any resolution. Proof and final are the *same spec* painted at two pixel sizes.

---

## Current state

**v1 is architecturally complete, and the v1.1/v1.2/v1.3 foundations are now in** (this session). The base engine: the coordinate spine, ingest, density, the spec + zoom cap, the relief engine, rasterize, the web app, region prep, KML/KMZ import, multi-file drag-drop upload, and baked hydrography. On top of that, this session added:

- **Style (by-eye, approved):** the track is now a pronounced **desert-gold** line (alpha-blended, dark-umber casing) and the synthetic GPX **meanders organically** instead of straight rays. `scripts/render_poster.py` renders the flagship 18×24 (full proof + 300-dpi detail tile) for by-eye judging.
- **v1.2 Multi-region:** `app/regions.py` registry discovers every `regions/<id>`; the app is no longer pinned to one region. `GET /api/regions`, `region_id` on upload (explicit, sole-region default, or auto-detect from track points), threaded through proof/final; UI region-picker gallery.
- **v1.1 Rich markers:** hotspots carry optional `label`/`icon`/`photo`. Render draws **vector** icons (peak/camp/water/flag/camera/star — NOT emoji, for determinism), cream label plates, and pinned photo thumbnails. `POST /api/markers`, `POST /api/photo`; UI marker editor.
- **v1.3 Server foundation:** `app/serialize.py` (session↔JSON), `app/store.py` (`MemoryStore` default + `SqliteStore` persistence, `TRAILPRINT_STORE=sqlite`), `app/blobs.py` (object store), `app/jobs.py` (render queue). Async final: `POST /api/final/submit` → `GET /api/jobs/{id}` → `/result`. Sync `/api/final` retained.

- **Region:** `lassen_ca` — Lassen County, CA, framed on the Susanville→Eagle Lake corridor. EPSG:32610 (UTM 10N), 10 m, **63×78 km**, NaN-trimmed. `hydro.json` carries 116 lakes + 307 rivers (NHD, order ≥ 3).
- **Tests:** 64 passing (`./.venv/bin/python -m pytest tests/ -q`). Integration tests skip cleanly if the DEM is absent; most new v1.1/1.2/1.3 tests are DEM-free.
- **Dummy data:** `tests/fixtures/sample.gpx` is **synthetic** (5 dated Susanville↔Eagle Lake trips via `scripts/make_dummy_gpx.py`, now organically meandered). Swap in a real OnX/Avenza export when available.

---

## How to run / dev setup

```bash
cd "Badwater Trails"
source .venv/bin/activate            # Python 3.14; or call ./.venv/bin/python directly
pytest -q                            # 41 passing
uvicorn app.main:app --reload        # http://127.0.0.1:8000 — pick region, drop GPX/KML/KMZ, name/icon/photo markers, crop, proof, accept
```

**Optional env (default = v1 behavior):** `TRAILPRINT_STORE=sqlite` persists sessions to `TRAILPRINT_DB` (default `trailprint.db`) so work survives a restart; `TRAILPRINT_BLOBS` sets the render-output dir (default `blobs/`). Both unset → in-memory + filesystem, unchanged.

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
  regions.py    region registry: discover regions/<id>, Region(cfg+geo+dir), lon/lat bbox, detect_region()
  ingest.py     GPX/KML/KMZ -> reproject -> drop non-finite -> simplify -> Track. load_tracks() auto-detects format
  density.py    projected tracks -> visitation-weighted hotspots (counts distinct days/tracks, not points)
  spec.py       CompositionSpec: the compose/rasterize contract; physical style values (incl. label_pt/photo_box_in); zoom-cap validate()
  relief.py     pure-numpy relief passes: hillshade, hypsometric tint, texture, valley, grain. THE TUNING SURFACE
  render.py     rasterize(spec, dpi, region_dir): relief -> water -> tracks -> markers (icons/labels/photos). Track/water/marker style constants
  serialize.py  session payload (Track ndarrays + spec) <-> plain JSON (shared by store + jobs)
  store.py      SessionStore: MemoryStore (default) + SqliteStore (TRAILPRINT_STORE=sqlite). "the file that becomes a DB"
  blobs.py      object storage for render outputs: LocalBlobs now, S3/GCS behind the same interface later
  jobs.py       ThreadJobQueue: async render at the compose->rasterize boundary (spec is the job payload)
  session.py    thin delegate over the configured store (was the in-memory dict)
  main.py       FastAPI: /api/regions, /api/upload, /api/proof, /api/final (+ /api/final/submit async), /api/markers, /api/photo, /api/jobs/{id}
  static/       index.html, app.js, style.css — region picker + drag-drop aim-view + marker editor
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

1. **Build a second region** to exercise multi-region for real (the registry/picker/auto-detect are in, but only `lassen_ca` exists). Just run `region_prep.py` with a new `--id/--bbox/--epsg` (network, ~4 min). The picker and auto-detect light up automatically.
2. **Real GPX fixture.** Replace the synthetic `sample.gpx` with a real OnX/Avenza export and re-verify the by-eye look + marker auto-placement on real tracks.
3. **Wire the async render path into the UI.** Backend is done (`/api/final/submit` → `/api/jobs/{id}` → `/result`); the Accept button still calls the sync `/api/final`. Swap it to submit+poll with a progress indicator when desired.
4. **Title/legend treatment is bare** (`render.rasterize` draws a small bottom-left title). A finished poster likely wants a real title block / margin / legend — partly aesthetic, decide with Dom.
5. **Promote the v1.3 foundations to a real server when scaling** (each is a local impl behind an interface, so no teardown): swap `SqliteStore`→Postgres, `ThreadJobQueue`→Redis/Celery + worker pool, `LocalBlobs`→S3/GCS. Then v1.4 accounts + payment + print fulfillment (final render already gated behind explicit accept).

**Style levers** (approved by eye this session, but still the tuning surface): relief palette/light/texture/valley at the top of `app/relief.py` (`HYPSO_STOPS`, `TEXTURE_*`, `VALLEY_*`, `HILLSHADE_GAMMA`); track/marker/water constants at the top of `app/render.py` (`TRACK_INK`, `TRACK_CASING`, `MARKER_FILL`, `ICON_INK`, `WATER_FILL`, `RIVER_*`).

---

## Key documents

- `docs/superpowers/specs/2026-06-29-trailprint-v1-architecture-design.md` — the approved design for the architecture-completion work.
- `docs/superpowers/plans/2026-06-29-trailprint-v1-architecture.md` — the TDD implementation plan (all tasks checked off).
- Dom's **original build plan** (`~/Downloads/trailprint-mvp-build-plan.md`) — the source of the invariants, the file map, and the v1.1–v1.4 roadmap. Worth re-reading before large changes.
