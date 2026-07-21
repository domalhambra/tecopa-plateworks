# CLAUDE.md — Badwater Trails / Tecopa Plateworks

Operator manual for Claude. Human entry point is `README.md`; the product's reason for existing is `docs/scope.md`; the file format's normative spec is `docs/MANIFEST.md`. For current state, read `git log` before any dated handoff — the handoffs describe the state at their date and `main` has moved past them more than once.

## What this project is

A single **local** app that turns GPX/KML/KMZ tracks into a **self-archiving chronicle of a life outdoors** — a shaded-relief poster of where you've been inside one curated region, performed as a print, a wallpaper, a film, or a social canvas. One FastAPI process serves a browser studio and the render engine; all real rendering happens server-side in Python. No account, no database, no cloud: **the artifact is the archive, and the poster on the wall is the save file.**

Three pillars, stated fully in `docs/scope.md`:

1. **One score, many performances** — the composition is decided once in ground coordinates, then performed at any size (print), any pixel density (wallpaper), and along its own time axis (film).
2. **The file is the whole record** — picture, geometry, source hashes, and pinned photos all travel inside the PNG.
3. **The record is alive** — last year's poster plus this year's GPX renders the next edition (`POST /api/continue`), lineage carried in the file itself.

This is a **commercial** property (concierge press: prints, editions, plate commissions) and the only Badwater project with a public license stance. It is not safety-relevant — that's Ignition.

## Naming

The product is **Tecopa Plateworks**. Several layers carry different names on purpose; collapsing them breaks either the brand or the forever-contract.

| Layer | Value | Rule |
|---|---|---|
| Product brand | **Tecopa Plateworks** | Full compound always. Never bare "Plateworks" — a Minnesota flexographic-plate maker (Plateworks Plus) operates under it. |
| Folder | `Badwater Trails/` | Pre-rebrand, deliberately not renamed on disk. |
| GitHub repo | `domalhambra/tecopa-plateworks` | Renamed 2026-07-21. The old `badwatertrails` name survives only as a 301. |
| `ENGINE` | `"tecopa-plateworks"` | Stamped into every manifest, **never read back** — `LEGACY_ENGINES` records the old values and nothing gates on any of them. |
| `ENGINE_URL` | the repo URL | Must be the repo's **real** name, never a redirect: it's the pointer a stranger follows to resurrect a poster years from now, and GitHub frees a renamed repo's old name for reuse. |
| `MANIFEST_KEY` / `NOTE_KEY` | `"trailprint"` / `"trailprint-note"` | **Frozen v1 format keywords.** Changing either orphans every poster ever printed. Never touch — these are the genuinely frozen ones. |
| Env vars, `localStorage`, bundle id, download prefix | `TECOPA_*`, `'tecopa'`, `guide.badwater.tecopa`, `tecopa_<region>` | Name-neutral by design. A rebrand touches none of them, so no saved preference is orphaned and macOS never sees a new app. |

**Naming history:** `trailprint` → `tecopa-printworks` (2026-07-19 to 07-21, an accidental name) → `tecopa-plateworks`. `docs/MANIFEST.md` requires readers to accept all three and not reject an unrecognized fourth. Dated files under `docs/superpowers/` keep their original wording as historical record — if you port UI copy out of one, substitute the current name.

**Before renaming again, know the cost:** the resurrection note is a pure function of the manifest *plus these constants*, so changing `ENGINE` or `ENGINE_URL` means a poster printed before the change and reprinted after gets different note bytes. Within a version everything stays byte-identical (the orphan drill proves it), but cross-version note identity is already broken by the two renames above. That was acceptable pre-launch. Once posters are in customers' hands it isn't — treat these two constants as frozen from first sale.

## Architecture — the one seam

The engine splits at exactly one seam: **compose** decides the picture once in ground coordinates and emits a `CompositionSpec`; **rasterize** paints that spec at any resolution. The proof and the final are the *same spec* painted at two pixel sizes. Region-level data (DEM, `hydro.json`, labels) is read from the region dir by `render` — it is **not** carried on the spec. The spec holds the picture *decisions*: crop, print size, tracks, hotspots, style values, seed.

The front end is a **single-window studio** (no wizard, no gated section rail — both were replaced): a top output-target switcher (Poster / Wallpaper / Film / Social), a project sidebar left, an always-present appearance sidebar right, and a center stage that adapts to the target. `app.js` is the router over target × view; each target's behaviour lives in its own module. The proof stage is **progressive** — an instant draft swaps to a background high-dpi refine while `viewer.js` keeps the zoom/pan transform stable across the swap.

## Invariants — protect these

1. **One spec, painted at many sizes.** Never compute the picture twice.
2. **Physical units (points / inches), never pixels,** for anything visual. This bug class has bitten more than once: a pixel-sized element looks bold in the proof and vanishes in the final.
3. **Determinism.** Same spec + seed → identical image. Grain and jitter are seeded.
4. **One projection throughout.** DEM, overview, tracks, crop, hydro all in the region CRS metres; tracks arrive lon/lat and are reprojected first.
5. **Registration is correctness.** Prove the coordinate chain before tuning aesthetics. `app/geo.py` is the single source of truth for coordinate conversions.
6. **The zoom cap.** Never request finer ground detail than the data holds. `CompositionSpec.validate(dpi)` enforces it at the *final* dpi. A 422 on a large print of a small plate is the invariant working, not a bug.

## The forever-contract (the hardest rule here)

A poster printed today must reprint byte-identically after any future upgrade. That rests entirely on **additive defaults**: every new spec or animation key must be omitted at its pre-feature default — for encoders as much as for the painter. No engine *version* rides the file, so discipline is the only mechanism.

- `MANIFEST_VERSION` stays **1**. New blocks are purely additive.
- The frozen `manifest_*_v1.json` fixtures in `tests/fixtures/` (base, animation, photo, edition, wallpaper, oblique, region_pack) are the executable form of the promise. If a change makes one fail, the change is wrong until proven otherwise.
- **One door for untrusted manifests:** `provenance.spec_from_manifest` is the single place a crafted PNG becomes a render-ready spec (parse → drop non-embedded photos → bound geometry → validate). Any new file-consuming verb funnels through it and inherits the hardening. Don't re-derive the guard chain at a new call site.
- The **orphan drill** (`tests/test_orphan_drill.py`) packs a plate, installs it into an empty regions root, and reprints a golden poster byte-identically. It runs in CI — but only against a *synthetic* DEM. Before any release, run it by hand against the real plates.

## Build & test

```bash
source .venv/bin/activate                 # Python 3.14
pip install -r requirements-lock.txt      # pinned set — what CI installs
pytest -q                                 # ~640 tests; renders real posters/films, ~22 min
uvicorn app.main:app --reload             # http://127.0.0.1:8000
```

- `requirements.txt` core · `-dev` test stack · `-lock` pinned (determinism/CI) · `-regionprep` the heavy offline build stack · `-share` imageio-ffmpeg for MP4 twins. To match CI exactly, add `pandas geopandas` and `-r requirements-share.txt` on top of the lock — CI installs them deliberately outside the lock so the region-prep and MP4 tests run instead of skipping.
- `.venv-prep` is a **separate** venv for `region_prep.py`, spawned as a subprocess by in-app region builds. Without it, `/api/regions/plan` returns `prep_ready: false` and the UI shows the setup command instead of a Build button. Override with `TECOPA_PREP_PYTHON`.
- **The venvs are interpreter-bound — check that first when Python breaks.** Both were originally built against the python.org 3.14 framework, which is no longer on this Mac; the live interpreter is Homebrew's `/opt/homebrew/bin/python3.14`. A dead venv reads as `no such file or directory` running `.venv/bin/python` even though `ls` lists it — the symlink resolves to a missing target. Rebuild with `python3.14 -m venv --clear .venv`.
- Real 3DEP DEMs are gitignored; `tests/conftest.py` hydrates a tiny synthetic DEM per region so the suite runs on a fresh clone. **A synthetic DEM is useless for judging a poster by eye** — rebuild the real one first.
- There is **no JS test runner.** For front-end work: `node --check` each edited module, cross-reference every `$('id')` against the HTML, then drive the real UI in a browser (synthetic `DragEvent` + `DataTransfer` works; click coordinates in headless don't).

## Known local failures (green in CI, red on this Mac)

Verified 2026-07-21 against `d24a009`. Confirm any new failure against a clean checkout before chasing it — most of these are the host, not the code.

- `test_readyz_ok_with_hydrated_regions`, `test_orphan_drill` — `regions/lassen_ca/dem.tif` is the **real** 188 MB 3DEP DEM whose bounds have drifted **1860 m** from `region.json`, so `/readyz` reports `bounds_match: false` and returns 503. Every other region carries a conftest-hydrated synthetic DEM matching to 0.0 m. CI never hits this because it has no real DEM. Note the drill fails *before* reaching its byte-identical assertion, so the forever-contract claim is untested here until the plate is rebuilt.
- Six label / bleed / oblique tests — all *marginally* over a MAD threshold (3.53 / 3.49 / 3.07 vs a limit of 3.0). `render.py`'s font chain prefers `Georgia.ttf`, which **is** installed here but absent on CI's Ubuntu, where it falls back to DejaVu; the thresholds appear tuned to DejaVu metrics. Set `TECOPA_FONT` to test it.
- `test_mp4_twin_is_tagged_bt709` — no `colr` box. Not version drift: `imageio-ffmpeg` is pinned at 0.6.0 and that exact version is installed. The bundled ffmpeg **binary** is platform-specific.

## macOS app

`scripts/macos/build_app.sh --install` builds a double-clickable **Tecopa Plateworks.app** into `/Applications`. It runs the engine *from this repo's* `.venv` on port 8848, so `git pull` updates it with no rebuild — rebuild only if the repo moves or the launcher itself changes. Logs to `~/Library/Logs/TecopaPlateworks.log`; verify with `scripts/macos/smoke_test.sh` (needs a human: it raises one-time Documents and Automation prompts). `CFBundleIdentifier` is `guide.badwater.tecopa` — name-neutral, so rebrands don't make macOS see a new app or re-prompt.

## Regions ("plates")

Five built: `lassen_ca`, `susanville_reno`, `elko_bonneville`, `rifle_aspen`, `tushar_beaver_ut`. The region is an **outcome, not a first step** — tracks are dropped first, and if no built plate covers them, `/api/regions/plan` → `/api/regions/build` bakes one from USGS 3DEP on a dedicated single-slot queue. US-only, and corridor-scale areas are refused honestly in-app.

Gotchas already paid for:

- **Python 3.14 only** on this Mac.
- **NHD SSL:** `region_prep.py` sets `SSL_CERT_FILE` from `certifi` at the very top, *before* importing py3dep/pynhd (aiohttp captures SSL config at import), and fetches hydro **before** the DEM. Keep that ordering if you add network code.
- **py3dep returns EPSG:5070 in metres, not 4326.** `plan_build` sizes the job before any fetch so a corridor-scale bbox can't OOM the build (the 15.8 GB lesson).
- `regions/*/dem.tif` and `cache/` are gitignored; `region.json` / `overview.png` / `hydro.json` / `landcover.tif` **are** committed.
- For out-of-plate test coordinates use Virginia (~-79.5, 37.8) — `elko_bonneville` is corridor-scale and swallows most "obviously outside" western points.

## Guardrails

- **Deliberately out of scope** (`docs/scope.md`): social features, cloud sync and accounts, fitness metrics, route planning or live tracking, and track editing. The app looks backward and renders what happened; it does not revise it.
- **Licensing:** code is **AGPL-3.0-or-later**; region plates and the manifest schema are **CC0-1.0**; the name and branding are covered by neither. Keep relicensing power intact — the first outside contribution needs a DCO sign-off or CLA.
- **Marketing honesty:** every marketing image is rendered by the engine (`scripts/render_asset_farm.py`), never a mockup. Every claim must have a test behind it — the claims register in the branding plan is the whitelist. Plates are free, always.
- **Vocabulary:** plate (not region/dataset), proof (not preview), edition (not update), share copy (not privacy mode), the save file (not your data).
- **Workflow:** TDD, granular present-tense commits explaining the *why*, and an adversarial review pass after each substantial component — that practice caught ~15 real bugs in one session, including a 90°-rotated hillshade. Cloud sessions land on `claude/*` branches and reach `main` by squash-merged PR; the Mac commits to `main` directly, only when green. Session work is logged to the PKM `SESSION_LOG.md` via the session-log skill, not a repo-local log.

## Map of the repo

| Path | What |
|---|---|
| `app/geo.py` | every coordinate conversion — the registration source of truth |
| `app/ingest.py` | GPX/KML/KMZ → reproject → simplify → clean polylines |
| `app/density.py` | visitation-weighted hotspots (distinct tracks, not points) |
| `app/spec.py` | the `CompositionSpec` contract + zoom-cap validation |
| `app/relief.py` | pure-numpy relief passes — **the tuning surface** |
| `app/render.py` | paint relief + water + tracks + markers + labels in physical units |
| `app/provenance.py` | the manifest; `spec_from_manifest` is the one untrusted door |
| `app/solar.py` | NOAA/Meeus solar position for Journey Light |
| `app/timelapse.py`, `app/wallpaper.py`, `app/mockups.py` | the film, device/social presets, marketing renders |
| `app/regionbuild.py`, `app/regions.py`, `app/plates.py` | GPX-first region creation, the registry, the plate installer/verifier |
| `app/main.py` | the FastAPI endpoints |
| `app/static/` | the single-window studio (~22 ES modules; `app.js` routes, `viewer.js` owns proof zoom/pan, `statusbar.js` the truth line) |
| `region_prep.py` | offline DEM/hydro/landcover bake — run in `.venv-prep` |
| `docs/scope.md`, `docs/MANIFEST.md`, `docs/marketing.md` | the goal, the CC0 file format, the story |
| `docs/superpowers/` | `specs/` `plans/` `assessments/` `handoffs/` `quality/golden/` — the design record |
