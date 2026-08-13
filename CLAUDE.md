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

The product is **Tecopa Plateworks**. Several layers carry different names on purpose; collapsing them breaks either the brand or old files' readability.

| Layer | Value | Rule |
|---|---|---|
| Product brand | **Tecopa Plateworks** | Full compound always. Never bare "Plateworks" — a Minnesota flexographic-plate maker (Plateworks Plus) operates under it. |
| Folder | `Badwater Trails/` | Pre-rebrand, deliberately not renamed on disk. |
| GitHub repo | `domalhambra/tecopa-plateworks` | Renamed 2026-07-21. The old `badwatertrails` name survives only as a 301. |
| `ENGINE` | `"tecopa-plateworks"` | Stamped into every manifest, **never read back** — `LEGACY_ENGINES` records the old values and nothing gates on any of them. |
| `ENGINE_URL` | the repo URL | Must be the repo's **real** name, never a redirect — GitHub frees a renamed repo's old name for reuse. |
| `MANIFEST_KEY` | `"trailprint"` | **Frozen v1 format keyword.** Changing it orphans every poster ever printed — the one genuinely frozen name. (`NOTE_KEY` / the resurrection note retired 2026-07-27; files already printed keep theirs.) |
| Env vars, `localStorage`, bundle id, download prefix | `TECOPA_*`, `'tecopa'`, `guide.badwater.tecopa`, `tecopa_<region>` | Name-neutral by design. A rebrand touches none of them, so no saved preference is orphaned and macOS never sees a new app. |

**Type roles.** The sheet sets type by role — `body`, `point`, `area`, `water`, `title` (`render.TYPE_ROLES`) — and the operator binds faces per role via `TECOPA_FONT_<ROLE>` (see README's font table). Faces are operator-side because MB Type is licensed and this repo is public (`.gitignore` blocks `*.otf`/`*.ttf`/`*.woff*` — commit `39ad08c`, never weaken it). Bound faces are auto-normalised on register metrics; `TECOPA_FONT_AREA_CASE=mixed` is required when binding a small-caps face like Advocate. The bindings ride in no manifest: a render on a host with different bindings looks different, by design.

**Naming history:** `trailprint` → `tecopa-printworks` (2026-07-19 to 07-21, an accidental name) → `tecopa-plateworks`. `docs/MANIFEST.md` requires readers to accept all three and not reject an unrecognized fourth. Dated files under `docs/superpowers/` keep their original wording as historical record — if you port UI copy out of one, substitute the current name.

**Before renaming again:** `ENGINE` and `ENGINE_URL` ride in every manifest as provenance. Renaming changes what new files record — harmless now that cross-build byte-identity is retired, but the strings in files already printed are permanent, so readers must keep accepting every historical value.

## Architecture — the one seam

The engine splits at exactly one seam: **compose** decides the picture once in ground coordinates and emits a `CompositionSpec`; **rasterize** paints that spec at any resolution. The proof and the final are the *same spec* painted at two pixel sizes. Region-level data (DEM, `hydro.json`, labels) is read from the region dir by `render` — it is **not** carried on the spec. The spec holds the picture *decisions*: crop, print size, tracks, hotspots, style values, seed.

The front end is a **single-window studio** (no wizard, no gated section rail — both were replaced): a top output-target switcher (Poster / Wallpaper / Film / Social), a project sidebar left, an always-present appearance sidebar right, and a center stage that adapts to the target. `app.js` is the router over target × view; each target's behaviour lives in its own module. The proof stage is **progressive** — an instant draft swaps to a background high-dpi refine while `viewer.js` keeps the zoom/pan transform stable across the swap.

## Invariants — protect these

1. **One spec, painted at many sizes.** Never compute the picture twice.
2. **Physical units (points / inches), never pixels,** for anything visual. This bug class has bitten more than once: a pixel-sized element looks bold in the proof and vanishes in the final.
3. **Determinism.** Same spec + seed → identical image. Grain and jitter are seeded. Note that the four heavy relief passes run **concurrently** (`relief._fan_out`, 2026-08-13) — this does not weaken the invariant: results merge in submission order and each task combines its own pass with the same expressions in the same order, so the sheet is bit-identical however the threads interleave. `TECOPA_RELIEF_WORKERS=1` forces the old serial call order, which is what the test pins.
4. **One projection throughout.** DEM, overview, tracks, crop, hydro all in the region CRS metres; tracks arrive lon/lat and are reprojected first.
5. **Registration is correctness.** Prove the coordinate chain before tuning aesthetics. `app/geo.py` is the single source of truth for coordinate conversions.
6. **The zoom cap.** Never request finer ground detail than the data holds. `CompositionSpec.validate(dpi)` enforces it at the *final* dpi. A 422 on a large print of a small plate is the invariant working, not a bug.

## Versioned drift (the forever-contract is retired)

The old rule — a poster printed today must reprint byte-identically after any future upgrade — was **retired on 2026-07-27** (`docs/superpowers/specs/2026-07-27-retire-the-forever-contract-design.md`). What replaced it:

- **`engine_version` rides every manifest** (`provenance.ENGINE_VERSION`: the git commit, or `TECOPA_ENGINE_VERSION` in packaged builds). Cross-build drift is recorded, not prevented — when a reprint stops matching, the file says which build painted it. **No new revs, ever**; a pixel-moving improvement just ships.
- **Determinism (invariant 3) is unchanged and still load-bearing**: same spec + seed + build → identical image. That is what makes the proof predict the print and a same-day reorder trustworthy. Do not confuse the retired *cross-build* promise with this *within-build* one.
- **Read-tolerance is the promise that remains**: `serialize.spec_from_json` drops unknown fields and defaults missing ones, so any old file opens. `spec_to_json` always emits every field — the omit-at-default dance is gone; never reintroduce it.
- **One door for untrusted manifests:** `provenance.spec_from_manifest` is the single place a crafted PNG becomes a render-ready spec (parse → drop non-embedded photos → bound geometry → validate). Any new file-consuming verb funnels through it and inherits the hardening. This guards against hostile files, not drift — it survives the retirement untouched.
- **A plate mismatch warns, it does not refuse**: `/api/reprint` and `/api/continue` surface a rebuilt plate honestly and proceed on `allow_plate_mismatch=true`. A customer reorder is never blocked because USGS re-flew the terrain.
- `MANIFEST_VERSION` stays **1** and `docs/MANIFEST.md` is now an **internal** format doc (the CC0 dedication on previously published versions stands and cannot be revoked).

## Build & test

```bash
source .venv/bin/activate                 # Python 3.14
pip install -r requirements-lock.txt      # pinned set — what CI installs
pytest -q                                 # ~793 tests; renders real posters/films, ~10 min
uvicorn app.main:app --reload             # http://127.0.0.1:8000
```

- `requirements.txt` core · `-dev` test stack · `-lock` pinned (determinism/CI) · `-regionprep` the heavy offline build stack · `-share` imageio-ffmpeg for MP4 twins. To match CI exactly, add `pandas geopandas` and `-r requirements-share.txt` on top of the lock — CI installs them deliberately outside the lock so the region-prep and MP4 tests run instead of skipping. **`pandas` + `geopandas` are already installed here** (3.0.3 / 1.1.4), so the region-prep and hydro tests do run on this Mac; `imageio-ffmpeg` is still absent, which is the whole of the 6 skips (verified 2026-08-13).
- `.venv-prep` is a **separate** venv for `region_prep.py`, spawned as a subprocess by in-app region builds. Without it, `/api/regions/plan` returns `prep_ready: false` and the UI shows the setup command instead of a Build button. Override with `TECOPA_PREP_PYTHON`.
- **The venvs are interpreter-bound — check that first when Python breaks.** A dead venv reads as `no such file or directory` running `.venv/bin/python` even though `ls` lists it — the symlink resolves to a missing target. Rebuild with `python3.14 -m venv --clear .venv`. As of 2026-08-13 `.venv` is healthy and bound to the **python.org framework** build (`.venv/bin/python` → `/Library/Frameworks/Python.framework/Versions/3.14/bin/python3.14`, Python 3.14.2) — that framework had gone missing once, which is what this bullet was originally written about, and it is present again. Homebrew's `/opt/homebrew/bin/python3.14` is the other candidate; check which one the symlink actually resolves to rather than assuming either.
- Real 3DEP DEMs are gitignored; `tests/conftest.py` hydrates a tiny synthetic DEM per region so the suite runs on a fresh clone. **A synthetic DEM is useless for judging a poster by eye** — rebuild the real one first.
- There is **no JS test runner.** For front-end work: `node --check` each edited module, cross-reference every `$('id')` against the HTML, then drive the real UI in a browser (synthetic `DragEvent` + `DataTransfer` works; click coordinates in headless don't).

## Known local failures (green in CI, red on this Mac)

Re-verified 2026-08-13 against `c76a0c5`, on the real `lassen_ca` plate: **7 failed, 780 passed, 6 skipped** in 10:21, and all seven are the font item below. Confirm any new failure against a clean checkout before chasing it — most of these are the host, not the code. **Compare the failure set, not the totals** — the 07-27 run recorded 815 tests against 793 here, and that delta has not been explained; the named failures are the stable signal.

A warning the 07-27 run earned: two tests were coupled to the local plate being *wrong*, and both went red the moment the real DEM was restored — the pack-gate drift test inherited its drift from the ambient synthetic DEM instead of constructing it, and `label_place` turned out inert on real terrain at 13 pt type. Both fixed (`c81ca51`, `5c22096`). If a test only passes on a synthetic plate, it is testing the host.

- **The `lassen_ca` DEM goes orphan on a pull — this recurs, it is not a past incident.**
  `regions/*/dem.tif` is gitignored, every other plate asset is committed. A plate rebuilt
  in a cloud container therefore ships its small assets to `main` and leaves the DEM
  behind, and the next pull here pairs a NEW `region.json` with the OLD local DEM.
  Happened on 2026-07-21 (`3e2b5e7`), and again on 2026-07-27 when pulling
  `a6a93c2 → 5a0094e` re-orphaned it at 509.83 m drift. **After any pull touching
  `regions/`, run `regions.discover()` → `readiness()` before trusting a render.**
  To repair, call `region_prep.build_dem_cog` directly (with `plan_build`) rather than
  `region_prep.main` — main refetches NHD/NLCD too, and upstream drift turns a
  restoration into a new *plate version* (NHD already went 116 → 109 lakes once). Then
  check the sha256 against `sources.json`; a match proves the exact plate is back. Done
  2026-07-27: `20cec75c…`, 192,087,365 B, drift 0.0 m, every committed asset untouched.
- **`ready: True` does not mean real terrain.** `tests/conftest.py` hydrates a tiny
  synthetic DEM (tagged `synthetic=1`, 170–2000 m) for any plate lacking one, and those
  match their own bounds exactly. Check the tag, not the flag, before judging a poster by
  eye. As of 2026-08-13 **two** plates carry real terrain here — `lassen_ca`
  (192.1 MB, 6200×7719) and `susanville_reno` (257.2 MB, 6459×9977, `synthetic=0`) —
  while `elko_bonneville`, `rifle_aspen` and `tushar_beaver_ut` are the 240×300 synthetic
  stand-ins. `susanville_reno` was still synthetic in the 07-27 record; it is not now.
- ~~the orphan drill~~ — deleted 2026-07-27 with the forever-contract (its last run on
  real terrain, 2026-07-27, passed). The `serial` pytest tier died with it.
- **Seven** label / bleed / oblique tests — all *marginally* over a MAD threshold (3.53 / 3.49 / 3.07 vs a limit of 3.0). `render.py`'s font chain prefers `Georgia.ttf`, which **is** installed here but absent on CI's Ubuntu, where it falls back to DejaVu; the thresholds appear tuned to DejaVu metrics. Set `TECOPA_FONT` to test it. The exact set as of 2026-08-13, so a future run can diff against it rather than re-derive it:
  ```
  test_base_cache.py::test_phase2_serves_the_knobs_phase1_could_not[label_place-anchor]
  test_bleed.py::test_full_bleed_render_keeps_furniture_off_the_bleed_band
  test_labels.py::test_label_placement_is_a_faithful_scale_across_dpi
  test_labels.py::test_diagonal_range_is_dpi_stable
  test_oblique.py::test_oblique_proof_is_a_faithful_scale_of_final
  test_oblique.py::test_oblique_summit_marker_stays_glued
  test_smart_labels_and_weave.py::test_smart_labels_are_dpi_stable
  ```
  The `label_place-anchor` case is the seventh and arrived with the 2026-08-10 pull; it was confirmed pre-existing by re-running all seven against `c44415c` with `app/relief.py` reverted, where they fail identically.
- `test_mp4_twin_is_tagged_bt709` — no `colr` box when it runs. Not version drift: the bundled ffmpeg **binary** is platform-specific. It still does not run here — `imageio_ffmpeg` is not installed in `.venv`, and that single missing package is **all 6 skips**: three in `test_timelapse.py` / `test_output_fitness.py` and three `importorskip`s in `test_mockups.py`. Install `-r requirements-share.txt` to see them (verified 2026-08-13).

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
| `app/basecache.py` | the proof loop's byte-budgeted LRU, backing two layers — what may be reused is `render.base_cache_key` (terrain) and `render.ink_cache_key` (route ink) |
| `app/provenance.py` | the manifest; `spec_from_manifest` is the one untrusted door |
| `app/solar.py` | NOAA/Meeus solar position for Journey Light |
| `app/timelapse.py`, `app/wallpaper.py`, `app/mockups.py` | the film, device/social presets, marketing renders |
| `app/regionbuild.py`, `app/regions.py`, `app/plates.py` | GPX-first region creation, the registry, the plate installer/verifier |
| `app/main.py` | the FastAPI endpoints |
| `app/static/` | the single-window studio (~22 ES modules; `app.js` routes, `viewer.js` owns proof zoom/pan, `statusbar.js` the truth line) |
| `region_prep.py` | offline DEM/hydro/landcover bake — run in `.venv-prep` |
| `docs/scope.md`, `docs/MANIFEST.md`, `docs/marketing.md` | the goal, the CC0 file format, the story |
| `docs/superpowers/` | `specs/` `plans/` `assessments/` `handoffs/` `quality/golden/` — the design record |

## Session logging

Log sessions to the Notion **Session Log** database. This is written here, in the repo, on purpose: a cloud container clones only this repo, so a convention that lives in the workspace CLAUDE.md or a Mac-local skill never reaches it. Everything needed is below — no other file required.

- Parent: `{"type": "data_source_id", "data_source_id": "60f3ea17-4424-4815-8a4b-6a4d4de61c4f"}`
- `Session Title` (title) and `date:Date:start` (ISO date — note the expanded property name, not `Date`)
- `Repo` — relation. **This repo is** `["https://app.notion.com/p/3a44f171f472818782c1c9dbb2b6547a"]`
- `Activity` — build | fix | research | write | ops | plan
- `Status` — Complete | In Progress | Blocked
- `Shipped` — checkbox (`"__YES__"`) for deploys and launches
- `Tags` — JSON array **encoded as a string**, not a native array
- `Quarter` computes itself from Date. Never set it by hand.

Body sections: What We Did / Open Threads / Next Steps / Notes.

Also open a **Threads** record for work deliberately left unfinished, and a **Decisions** record for any durable choice that will constrain future work.

**If Notion is unreachable** — no connector attached in this container, or offline — append the entry to this repo's own `SESSION_LOG.md` (newest first, append-only, never rewrite history) and say so plainly in the closing summary. Confirm the Notion write returned a page ID before reporting the log as done. A log that silently doesn't happen is the failure this fallback exists to prevent.
