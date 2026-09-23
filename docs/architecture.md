# Architecture

Read this to learn which file owns which behavior. For the rules that must
not break, read `../CLAUDE.md`. For step-by-step changes, read
`changing-things.md`. For the goal, read `scope.md`.

## The shape

One FastAPI process serves a browser studio and the render engine. All real
rendering happens server-side in Python. There is no account, no database by
default, and no cloud. The public site is one static marketing page on a
separate host.

```
GPX / KML / KMZ ──▶ app/ingest.py ──▶ tracks in the region CRS ──▶ app/density.py ──▶ hotspots
                                                  │
regions/<id>/  (region.json, dem.tif, hydro.json, │  labels.json, landcover.tif, playa.json)
   built offline by region_prep.py                │      read by render, never carried on the spec
   or in-app by app/regionbuild.py (subprocess in .venv-prep)
                                                  ▼
                       compose ──▶ CompositionSpec (app/spec.py: crop, sheet, tracks, style, seed)
                                                  │
                                    rasterize (app/render.py) at any dpi
                                    relief passes (app/relief.py, app/looks.py, docs/relief-passes.md)
                                    terrain and ink caches (app/basecache.py) for the proof loop
                                                  │
        ┌─────────────────┬───────────────────────┼──────────────────────┬────────────────────┐
        ▼                 ▼                       ▼                      ▼                    ▼
   96 dpi draft     200 dpi refine          300 dpi final PNG/PDF    wallpaper bundle     time-lapse film
   (proof)          (proof)                 manifest in a zTXt       (app/wallpaper.py)   (app/timelapse.py)
                                            chunk (app/provenance.py)                     APNG + WebP/MP4 twins
                                                  │
                          /api/reprint and /api/continue read the file back through
                          provenance.spec_from_manifest, the one untrusted-manifest door.
                          /api/reprint/inspect reads manifest fields only, and builds no spec.

app/main.py: the endpoints, three ThreadJobQueue instances (render, region build, proof refine)
app/static/: the single-window studio, 22 ES modules, no build step
scripts/render_asset_farm.py ──▶ assets/ (gitignored) ──▶ marketing/build_deploy.py ──▶ Netlify, by hand
```

## Module map

| File | Owns | Tested by |
|---|---|---|
| `app/geo.py` | Every coordinate conversion: overview pixels, CRS metres, crop windows. `starter_crop`. The registration source of truth. | `tests/test_geo.py`, `tests/test_registration.py`, `tests/test_starter_crop.py` |
| `app/ingest.py` | GPX, KML and KMZ parsing, reprojection into the region CRS, simplification, track-level dedup. | `tests/test_ingest.py`, `tests/test_real_exports.py` |
| `app/density.py` | Visitation-weighted hotspots. Counts distinct visit days per cell, and a day-less track as its own visit. Never points. | `tests/test_density.py` |
| `app/spec.py` | `CompositionSpec`, `STYLE_BOUNDS`, `pixel_size`, `final_dpi`, and `validate` (aspect, the 120 MP ceiling, the zoom cap). | `tests/test_spec.py` |
| `app/relief.py` | The relief passes: hillshade, hypsometric tint, texture, valley, terrain depth, cast shadow, sky occlusion, grain. The pass registry and `_blur`. The concurrent fan-out. | `tests/test_relief.py`, `tests/test_relief_passes.py` |
| `app/looks.py` | Soft light and atmospheric haze, the seam's first shipped passes. | `tests/test_looks.py` |
| `app/render.py` | `rasterize`. Paints relief, water, biome, contours, tracks, markers, photos, labels, furniture in physical units. `TYPE_ROLES`, the font chain, the cache keys. | `tests/test_render.py`, `tests/test_labels.py`, `tests/test_smart_labels_and_weave.py`, `tests/test_water.py`, `tests/test_biome.py`, `tests/test_track_style.py`, `tests/test_type_roles.py`, `tests/test_oblique.py`, `tests/test_bleed.py`, `tests/test_poster_furniture.py`, `tests/test_markers.py`, `tests/test_credit_and_names.py`, `tests/test_journey_light.py`, `tests/test_hot_paths.py` |
| `app/basecache.py` | The byte-budgeted LRU behind the terrain and route-ink caches. | `tests/test_base_cache.py`, `tests/test_ink_cache.py` |
| `app/provenance.py` | The manifest: embed, extract, `spec_from_manifest`, `region_pack_block`, editions and lineage, embedded photos. `ENGINE`, `ENGINE_VERSION`, `MANIFEST_KEY`. | `tests/test_provenance.py`, `tests/test_editions.py` |
| `app/serialize.py` | Session and spec to JSON and back. `spec_from_json` drops unknown fields and defaults missing ones. | `tests/test_server_foundation.py`, `tests/test_wallpaper.py` |
| `app/solar.py` | NOAA/Meeus solar position and the journey's summit moment, for Journey Light. | `tests/test_journey_light.py` |
| `app/wallpaper.py` | Device and social presets, `spec_for_preset`, `SOCIAL_PPI`. | `tests/test_wallpaper.py`, `tests/test_wallpaper_api.py` |
| `app/timelapse.py` | The film: frames, pacing, APNG, the WebP and MP4 share twins. | `tests/test_timelapse.py`, `tests/test_mockups_api.py` |
| `app/mockups.py` | In-app mockup renders behind `/api/mockups/submit`. | `tests/test_mockups_api.py` (through the endpoint) |
| `app/regions.py` | `discover` over `regions/`, `Region.meta()`, `Region.readiness()`. Auto-detect from track points is `_best_region` in `app/main.py`. | `tests/test_regions.py`, `tests/test_readyz.py` |
| `app/regionbuild.py` | GPX-first planning (bbox, UTM zone, US coverage) and the `region_prep.py` subprocess behind `/api/regions/build`. | `tests/test_regionbuild.py`, `tests/test_region_endpoints.py` |
| `app/plates.py` | `.venv/bin/python -m app.plates install` places a `.trailplate.zip`. `verify` checks a poster PNG against the installed plate. | `tests/test_plates.py` |
| `app/store.py` | Session persistence: `MemoryStore` by default, `SqliteStore` with `TECOPA_STORE=sqlite`. | `tests/test_server_foundation.py` |
| `app/session.py` | The four-call session API the endpoints use (`create`, `has`, `get`, `update`). A thin delegate over the store chosen by `TECOPA_STORE`. | `tests/test_main.py` |
| `app/blobs.py` | Render output storage behind `LocalBlobs`. | `tests/test_server_foundation.py` |
| `app/jobs.py` | `ThreadJobQueue`, the async render queue at the compose to rasterize boundary. | `tests/test_server_foundation.py` |
| `app/logconfig.py` | Logging configuration. | `tests/test_logconfig.py` |
| `app/main.py` | The endpoints, the three queues, `_ready_or_503`, the pre-enqueue checks, the auto-docs switch-off. | `tests/test_main.py`, `tests/test_region_endpoints.py`, `tests/test_geometry_gate.py`, `tests/test_markers_move.py`, `tests/test_proof_refine.py`, `tests/test_region_recovery.py`, `tests/test_output_fitness.py` |
| `app/static/app.js` | The studio bootstrap and router over target and view. | `tests/test_static_registry.py` (text checks only) |
| `app/static/controls.js` | The declarative registry of every user-settable option. One entry drives the inspector, the palette, presets and the proof-staling rule. | `tests/test_static_registry.py` |
| `app/static/viewer.js`, `proof.js`, `statusbar.js`, `jobs.js` | Proof zoom and pan, the progressive proof, the status strip, the shared job poll loop. | not covered. No JS runner: drive the browser. |
| `app/static/library.js`, `compose.js`, `create.js`, `films.js`, `social.js`, `exports.js` | The Library home, the Compose workspace, the GPX-first creation card, the Film and Social targets, the Exports center. | not covered |
| `app/static/store.js`, `api.js`, `ui.js`, `inspector.js`, `palette.js`, `presets.js`, `markers.js`, `canvas.js`, `guided.js`, `sunDial.js` | State and prefs, fetch wrappers, DOM helpers, the inspector, the command palette, presets, the marker list, map drawing, the first-run guide, the sun dial. | not covered |
| `app/static/help.html` | The in-app help page. | not covered |
| `region_prep.py` | The offline plate bake: `plan_build`, the 3DEP fetch, `build_dem_cog`, `bake_hydro`, NLCD, `write_sources_manifest`. Sets `SSL_CERT_FILE` before importing the fetch stack. Runs in `.venv-prep`. | `tests/test_region_prep.py` (the pure planner, so it runs in the core venv and in CI), `tests/test_hydro.py` (skips without `geopandas`) |
| `scripts/build_labels.py` | GNIS terrain names to `labels.json`. Needs only the standard library and `pyproj`, so it runs in `.venv`. | `tests/test_build_labels.py` |
| `scripts/bake_playa.py` | NHD playas to `playa.json`. Imports `pynhd`, so it runs in `.venv-prep`. | not covered. `tests/test_water.py` covers the renderer's playa path, not the bake script. |
| `scripts/pack_region.py` | A deterministic `.trailplate.zip` from a built region. `--resync` writes true disk hashes into the zip's copy. | `tests/test_plates.py` |
| `scripts/verify_regions.py` | Every plate's assets against its `sources.json`, plus a geometry row. A script on purpose, not a test. | `tests/test_verify_regions.py` |
| `scripts/render_asset_farm.py` | The marketing asset farm: poster, editions, wallpapers, film, detail crop, mockups, model, coin. Stamps the `terrain` record. | `tests/test_asset_farm_detail.py`, `tests/test_asset_farm_frame.py`, `tests/test_asset_farm_gate.py`, `tests/test_terrain_provenance.py` |
| `scripts/track_network.py` | Pure routing over the cached OSM network: graph, Dijkstra, destinations, journey composer. | `tests/test_track_network.py` |
| `scripts/fetch_track_network.py` | Overpass fetch into the gitignored cache. Network access. | `tests/test_track_network.py` covers the pure half: the bbox transposition, the tiling arithmetic, the classifier, the retry loop. The fetch itself is hand-verified. |
| `scripts/render_mockups.py`, `scripts/render_lightsweep.py` | The object mockups and the light-sweep turntable. | `tests/test_mockups.py` |
| `scripts/render_model.py`, `scripts/render_coinspin.py` | The orbitable GLB plate and the coin spin. | `tests/test_coinspin.py` |
| `scripts/hero_plate.py`, `scripts/hero_scene.py` | The Blender hero plate CLI and the script that runs inside Blender. | `tests/test_hero_plate.py` |
| `scripts/render_poster.py`, `scripts/make_dummy_gpx.py` | By-eye poster render and the synthetic GPX generator behind `tests/fixtures/sample.gpx`. | not covered |
| `scripts/macos/build_app.sh`, `TecopaPlateworksLauncher.swift`, `Info.plist.template`, `make_icon.py`, `smoke_test.sh` | The macOS launcher: build, the Swift launcher on port 8848, the plist with bundle id `guide.badwater.tecopa`, the icon, the manual smoke test. | not covered. `smoke_test.sh` is a manual check. |
| `marketing/landing.html`, `marketing/privacy.html` | The landing page and the privacy page. | `tests/test_marketing_page.py` |
| `marketing/build_deploy.py` | The staged deploy root and the terrain guard. | `tests/test_terrain_provenance.py` |
| `marketing/vendor/model-viewer.min.js` | The vendored `<model-viewer>` for the orbitable plate. | none |
| `tests/conftest.py` | Synthetic DEM hydration, per-worker stores, the central `slow` classification. | none. It is the harness itself. |
| `tests/fixtures/` | `sample.gpx` and the seven `manifest_*_v1.json` read-tolerance inputs. | none |

## Runtime behavior worth knowing

- **Three fidelity tiers, one spec.** The studio renders a 96 dpi draft, then swaps in a 200 dpi refine from `PROOF_QUEUE`. The final is 300 dpi, or the device ppi. All three paint the same `CompositionSpec`.
- **The proof loop caches.** `base_cache_key` masks the fields that cannot reach the terrain. `ink_cache_key` does the same one layer up. A terrain knob misses, a furniture knob hits. Budgets: `TECOPA_BASE_CACHE_MB`, `TECOPA_INK_CACHE_MB`.
- **The geometry gate.** `_ready_or_503` runs on every verb that hands a plate to a render. A DEM whose geometry drifts from `region.json` gets a 503 naming the drift. There is no override.
- **The untrusted door.** `provenance.spec_from_manifest` is the one place a PNG becomes a spec: parse, drop non-embedded photos, bound geometry, validate.
- **Plate identity is checked outside the door.** `main._manifest_region_or_422` compares the file's `pack_version` against the server's. It refuses with a 422 that names both plates, and warns and proceeds only on `allow_plate_mismatch=true`. Availability and plate identity are per-server capability checks, so they do not belong in `provenance.spec_from_manifest`.
- **Pixel honesty bounds the plate hash.** `provenance.region_pack_block` hashes only the plate assets the sheet actually draws. It skips `overview.png` always, `labels.json` unless the spec draws labels, `landcover.tif` unless the biome tint is on, and `playa.json` unless dry lakes draw. Baking a new sidecar onto a plate therefore cannot make an already printed poster report a mismatch.
- **Every manifest carries `engine_version`.** Cross-build drift is recorded, not prevented. Within one build, same spec plus seed gives identical bytes.
- **Share copies carry nothing.** `embed_spec=false` writes no text chunk at all. PDF finals never carry a manifest.
- **Relief runs concurrently.** Four passes fan out on threads and merge in submission order. `TECOPA_RELIEF_WORKERS=1` restores the serial order.
- **Type is bound per role by the operator.** `TECOPA_FONT_TITLE`, `_POINT`, `_AREA`, `_WATER`, and `TECOPA_FONT` for body and fallback. The default chain is Georgia, then DejaVu. Bindings ride in no manifest, so the same file renders differently on a host with different bindings.
- **Region builds are subprocesses.** `POST /api/regions/build` spawns `region_prep.py` in `.venv-prep` on `BUILD_QUEUE` (one slot). Without that venv `/api/regions/plan` reports `prep_ready: false`.
- **Auto-docs are off.** `app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)`, so the studio never fetches from jsDelivr.
- **`ready: True` does not mean real terrain.** `tests/conftest.py` builds a synthetic DEM tagged `synthetic=1` for any plate that lacks one. Check the tag before judging a poster by eye.

## Environment

| Variable | Used by | Note |
|---|---|---|
| `TECOPA_REGIONS` | `app/main.py`, `tests/conftest.py` | The plates root. Default `regions`. |
| `TECOPA_BLOBS`, `TECOPA_UPLOADS` | `app/main.py`, `tests/conftest.py` | Output and upload folders. The test harness points both at temp folders, one per xdist worker. |
| `TECOPA_STORE`, `TECOPA_DB` | `app/store.py`, `app/session.py` | `sqlite` persists sessions to `TECOPA_DB`. Unset means in-memory. |
| `TECOPA_TTL_SECONDS`, `TECOPA_RENDER_CONCURRENCY` | `app/main.py` | Job retention and the render queue's width. |
| `TECOPA_BASE_CACHE_MB`, `TECOPA_INK_CACHE_MB` | `app/basecache.py`, `app/main.py` | Cache budgets. |
| `TECOPA_RELIEF_WORKERS` | `app/relief.py` | Fan-out width. `1` is the serial order. |
| `TECOPA_FONT`, `TECOPA_FONT_TITLE`, `TECOPA_FONT_POINT`, `TECOPA_FONT_AREA`, `TECOPA_FONT_WATER`, `TECOPA_FONT_<ROLE>_CASE` | `app/render.py`, `scripts/render_mockups.py` | Per-role faces. `TECOPA_FONT_AREA_CASE=mixed` for a small-caps face. Tested by `tests/test_type_roles.py`. |
| `TECOPA_ENGINE_VERSION` | `app/provenance.py` | Overrides the git commit as `engine_version` in packaged builds. |
| `TECOPA_PREP_PYTHON`, `TECOPA_PREP_SCRIPT`, `TECOPA_LABELS_SCRIPT` | `app/main.py` | The interpreter and scripts the in-app region build spawns. |
| `TECOPA_LOG_LEVEL`, `TECOPA_LOG_FORMAT` | `app/logconfig.py` | Logging. |
| `TECOPA_BLENDER` | `scripts/hero_plate.py` | The Blender binary, when not on `PATH`. |
| `TECOPA_COIN_FRAMES`, `TECOPA_MOCKUP_FRAMES` | `scripts/render_asset_farm.py`, `scripts/render_coinspin.py`, `scripts/render_mockups.py` | Frame counts for the social assets. |
| `NETLIFY_AUTH_TOKEN` | the manual deploy | Read from `~/.config/netlify/token`. See `../marketing/DEPLOY.md`. |

No environment variable changes the picture a given spec paints, except the
font bindings, which is by design.

## Delivery

| Surface | How |
|---|---|
| The studio | `uvicorn app.main:app --reload` on port 8000 for development. The macOS launcher runs the engine from this repo's `.venv` on port 8848 and logs to `~/Library/Logs/TecopaPlateworks.log`. Build it with `scripts/macos/build_app.sh --install`. A `git pull` updates it with no rebuild. |
| Plates | Five committed under `regions/`: `lassen_ca`, `susanville_reno`, `elko_bonneville`, `rifle_aspen`, `tushar_beaver_ut`. Each `dem.tif` is gitignored and rebuilt with `region_prep.py`. Packing and publishing plates has never run. |
| The landing page | `tecopa.plateworks.org`, Netlify site `tecopa-plateworks`, Cloudflare zone `plateworks.org`. Deployed by hand: render the farm, run `../marketing/build_deploy.py`, then `netlify deploy --prod`. The terrain guard refuses a region with no real terrain record in `assets/index.json`. The runbook is `../marketing/DEPLOY.md`. Plausible analytics, no CSP. |
| The privacy page | `/privacy/`, copied verbatim into the staged root. |
| Python | The Mac venv is Python 3.14. CI installs the version in `.python-version`, which is 3.11. A thread records the mismatch. |
| Dependencies | `requirements-lock.txt` is what CI installs, then `pandas geopandas`, then `requirements-share.txt`. `requirements.txt` holds the unpinned core minimums and `requirements-dev.txt` the test dependencies; the lock is what a machine actually installs. `requirements-regionprep.txt` goes only into `.venv-prep`. |

## The verification harness

- `.venv/bin/python -m pytest -n auto -m "not slow" -q` is the fast tier. On 2026-09-08 it ran 616 tests on this Mac in under a minute: 615 passed and one failed, the documented font failure in `tests/test_bleed.py`.
- `.venv/bin/python -m pytest -n auto -q` is the full suite, about 3 minutes on this Mac. Its one Mac-only failure is an MP4 test, because the bundled ffmpeg writes no `colr` box on macOS. CI is green on Ubuntu. Compare the failure set, not the totals. `changing-things.md` under Run the tests has the history of the seven tests once blamed on fonts.
- `tests/conftest.py` classifies `slow` tests centrally from measured durations. Re-derive after adding heavy tests with `--durations=0`.
- The studio has no JS runner. `tests/test_static_registry.py` checks `controls.js` and the HTML as text. Everything else is a browser drive.
- `.venv/bin/python scripts/verify_regions.py` reports every plate's hash and geometry state. Run it after any pull that touched `regions/`. Outside `.venv` the render stack is absent and the geometry row degrades to `skip`.
- `scripts/macos/smoke_test.sh` drives the launcher end to end and needs a human for two macOS prompts.
- The marketing page is gated by `tests/test_marketing_page.py` (the Collector register, the privacy claims) and the deploy by the terrain guard in `../marketing/build_deploy.py`.

## Cross-repo dependencies

| Dependency | Used by | Note |
|---|---|---|
| USGS 3DEP, NHD, NLCD, GNIS | `region_prep.py`, `scripts/build_labels.py`, `scripts/bake_playa.py` | All U.S. federal public domain. A non-federal source is a hard gate. |
| OpenStreetMap via Overpass | `scripts/fetch_track_network.py` | ODbL. Lives only in the gitignored cache, never in a plate. Attributed on the landing page. |
| Blender 4.2 LTS or newer | `scripts/hero_plate.py` | A separate install. Operator-only. |
| `00_Resources/typography-standards.md` | the type roles | The MB Type slate the role seam was built to ship. The faces themselves never enter this repo. |
| `00_Resources/voice-principles.md` | customer-facing copy | Layered under the Collector profile spec. |
| `00_Resources/documentation-standard.md` | this folder | The shape of these docs. |

Nothing in this repo reads another Plateworks repo. The landing page carries no
Plateworks branding beyond the four-ring favicon.
