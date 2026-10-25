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
                                            a set: one sheet, painted once, then cut
                                            by app/panels.py into a zip of panel files
                                                  │
                          /api/reprint and /api/continue read the file back through
                          provenance.spec_from_manifest, the one untrusted-manifest door.
                          /api/reprint/inspect reads manifest fields only, and builds no spec.

app/main.py: the endpoints, three ThreadJobQueue instances (render, region build, proof refine)
app/static/: the single-window studio, 23 ES modules, no build step
scripts/order.py: new (app/ordernew.py, from the intake's Dropbox job folder), preview (app/orderpreview.py,
                  app/previewpdf.py, app/orderemail.py), prepare (app/orderprep.py, with the proof of app/orderproof.py)
                  and finish (app/orderfinish.py), on an order folder outside the repo
scripts/render_asset_farm.py ──▶ assets/ (gitignored) ──▶ scripts/export_relief.py ──▶ www.plateworks.org, by the site repo's pages
```

## Module map

| File | Owns | Tested by |
|---|---|---|
| `app/geo.py` | Every coordinate conversion: overview pixels, CRS metres, crop windows. `starter_crop`. The registration source of truth. | `tests/test_geo.py`, `tests/test_registration.py`, `tests/test_starter_crop.py` |
| `app/ingest.py` | GPX, KML and KMZ parsing, reprojection into the region CRS, simplification, track-level dedup. | `tests/test_ingest.py`, `tests/test_real_exports.py` |
| `app/density.py` | Visitation-weighted hotspots. Counts distinct visit days per cell, and a day-less track as its own visit. Never points. | `tests/test_density.py` |
| `app/spec.py` | `CompositionSpec`, `STYLE_BOUNDS`, `pixel_size`, `final_dpi`, and `validate` (aspect, the 120 MP ceiling, the zoom cap). The two fields of a set, `panels` and `panel_gap_in`, and their rules: the count, the gap, the four sheets for each gap, no bleed, no wallpaper. | `tests/test_spec.py`, `tests/test_panels.py` |
| `app/panels.py` | Panel geometry for a set: the sheets, the panel rectangles, the gap strips, the seam bands, the cut, the wall tone. The one source of where a seam is. Imports nothing from `app`, so `app/spec.py` can use it in `validate`. | `tests/test_panels.py`, `tests/test_panel_render.py`, `tests/test_panel_furniture.py`, `tests/test_panel_api.py` |
| `app/relief.py` | The relief passes: hillshade, hypsometric tint, texture, valley, terrain depth, cast shadow, sky occlusion, grain. The pass registry and `_blur`. The concurrent fan-out. | `tests/test_relief.py`, `tests/test_relief_passes.py` |
| `app/looks.py` | Soft light and atmospheric haze, the seam's first shipped passes. | `tests/test_looks.py` |
| `app/render.py` | `rasterize`. Paints relief, water, biome, contours, tracks, markers, photos, labels, furniture in physical units. `TYPE_ROLES`, the font chain, the cache keys. `_furniture_scale`: the furniture is designed on 17 × 22 in, and a set is sized as one panel. On a set: the seam keep-outs, the furniture in panel 1, and a keyline, a mark and the watermark on each panel. | `tests/test_render.py`, `tests/test_panel_render.py`, `tests/test_panel_furniture.py`, `tests/test_labels.py`, `tests/test_smart_labels_and_weave.py`, `tests/test_water.py`, `tests/test_biome.py`, `tests/test_track_style.py`, `tests/test_type_roles.py`, `tests/test_oblique.py`, `tests/test_bleed.py`, `tests/test_poster_furniture.py`, `tests/test_markers.py`, `tests/test_credit_and_names.py`, `tests/test_journey_light.py`, `tests/test_hot_paths.py` |
| `app/basecache.py` | The byte-budgeted LRU behind the terrain and route-ink caches. | `tests/test_base_cache.py`, `tests/test_ink_cache.py` |
| `app/provenance.py` | The manifest: embed, extract, `spec_from_manifest`, `region_pack_block`, editions and lineage, embedded photos. `ENGINE`, `ENGINE_VERSION`, `MANIFEST_KEY`. | `tests/test_provenance.py`, `tests/test_editions.py` |
| `app/serialize.py` | Session and spec to JSON and back. `spec_from_json` drops unknown fields and defaults missing ones. | `tests/test_server_foundation.py`, `tests/test_wallpaper.py` |
| `app/solar.py` | NOAA/Meeus solar position and the journey's summit moment, for Journey Light. | `tests/test_journey_light.py` |
| `app/wallpaper.py` | Device and social presets, `spec_for_preset`, `SOCIAL_PPI`. | `tests/test_wallpaper.py`, `tests/test_wallpaper_api.py` |
| `app/timelapse.py` | The film: frames, pacing, APNG, the WebP and MP4 share twins. | `tests/test_timelapse.py`, `tests/test_mockups_api.py` |
| `app/mockups.py` | In-app mockup renders behind `/api/mockups/submit`. | `tests/test_mockups_api.py` (through the endpoint) |
| `app/regions.py` | `discover` over `regions/`, `Region.meta()`, `Region.readiness()`. Auto-detect from track points is `_best_region` in `app/main.py`. | `tests/test_regions.py`, `tests/test_readyz.py` |
| `app/order.py` | One order folder: `order.toml` (the title, the size, the orientation, the `gap` of a set, the `sizes` list of the preview, and the intake's `order_number`, `returning`, `client` and `email`), the track files in `in/`, `work/state.json` and its `manual` key. `orders_root`, `cache_path`. | `tests/test_order.py` |
| `app/orderplate.py` | Pure plate planning for an order: nestled framing, projection, `choose_grid` from 3DEP coverage, widening, curated reuse. `track_shares`, and `CoverageError` for a query of the 3DEP index that fails. | `tests/test_orderplate.py` |
| `app/orderprep.py` | Prepare: reuse or build the order's plate through `.venv-prep` subprocesses, measure a built plate's holes (`check_holes`), write state and the report. For a window set, the warning that a route end is behind a gap. `cache_env` and `_build`, which the preview shares. `place_photos`: read the photos in `in/`, find their spots and captions, lay them out and settle the frame in use (open, or grown for the band). | `tests/test_orderprep.py` |
| `app/orderpreview.py` | The size preview of an order: the two orientations of each size, each framed as Prepare frames it (`OrderGround`), the fit rule (`SET_MIN_FILL`), one coarse preview plate for each projection, the screen-size maps, the preview's JSON record and report. In the order folder it writes only in the two preview folders. | `tests/test_orderpreview.py` (stub subprocesses, no network), `tests/test_orderpreview_render.py` |
| `app/previewpdf.py` | The preview PDF: a wall page with every offered size at one scale, then a page for each offered size. Written with Pillow at 300 dpi. Each page is laid out as boxes first and drawn second. | `tests/test_previewpdf.py` |
| `app/sizes.py` | The name, the first-poster and next-year prices, the shipping and the Payment Links of each size and of the digital poster, read strictly from `config/sizes.toml`. Dom owns that file. | `tests/test_sizes.py` |
| `app/ordernew.py` | `order new`: copy the intake's job folder from Dropbox into a new order folder and write its `order.toml`. It never writes to Dropbox, cleans every name, refuses a file over 200 MB, and stops on a file that is not on the disk. | `tests/test_ordernew.py` |
| `app/orderemail.py` | The preview email, `<folder>/out/preview/email.txt`: a Payment Link for each offered size and the digital poster, each ending with the order number. No email when a link is missing. Nothing sends it. | `tests/test_orderemail.py` |
| `config/papers.toml`, `app/papers.py` | The paper table: the roll width, the ICC profile, the rendering intent and the Print & Layout preset of each paper, with exactly one row enabled. `load_papers` reads it strictly. `feed_rotation` returns 0 or 90, the turn that puts a piece's 17 in side across the roll. Dom owns the file. | `tests/test_papers.py` |
| `app/icc.py` | The sRGB profile bytes (one fixed creation date), the profile finder (`find_profile`) and the soft proof (`soft_proof`) through a paper's profile and intent. It never imports `app.main`. | `tests/test_srgb_profile.py`, `tests/test_softproof.py` |
| `app/orderspec.py` | The one spec of an order, `order_spec`: the saved studio spec if any, else the default, rebound to the plate on disk. `plate_dir`, `spec_hash`, `file_stem`, and `matches_order` (the spec's size, panels and gap against `state.json`, asked by Save and Finish). The proof, the studio and Finish all paint this spec. For photos: `effective_photos` (the state's photos with the studio's edits over them), the photo fields of the default spec, `crop_for_layout` and `ground_to_sheet_in`. | `tests/test_orderspec.py` |
| `app/photolayout.py` | Where order photos go, as pure geometry on a `render.Occupancy`. `layout` puts each photo's frame (photo plus mat, `frame=render._photo_frame_fracs(style)`) in open ground on the shortest clear leader, ring of 8 directions at 3 distances, leaders never crossing, or sends every photo to the gallery band (more than `OPEN_MAX`, or any photo with no clear spot). A fixed (dragged) box is kept as given. No randomness. | `tests/test_photolayout.py` |
| `app/photos.py` | A customer's photo: `read_meta` (EXIF position, `taken_utc` only with its offset, the upright size) and `write_work_jpeg` (upright, capped at 4,000 px, converted to sRGB from another embedded profile). `PHOTO_EXTS`. It registers the HEIC opener (pillow-heif). It never writes in `in/`. | `tests/test_photos.py` |
| `app/photospot.py` | A photo's spot on the plate: `spot_for` takes the GPS position through `geo.lonlat_to_crs`, else the photo's time on a track's surviving points (`PHOTO_TIME_TOLERANCE_S`, 600), else none. | `tests/test_photospot.py` |
| `app/photocaption.py` | A photo's default caption: `nearest_name`, the nearest `labels.json` feature within `CAPTION_RADIUS_M` (2,000 m), else empty. | `tests/test_photocaption.py` |
| `app/credit.py` | The cartouche's data-credit line (`credit_text`, `credit_line`) from a plate's `sources.json`. `/api/proof` and an order's default spec both take it from here. It never imports `app.main`. | `tests/test_credit_and_names.py`, `tests/test_orderspec.py` |
| `app/orderproof.py`, `app/proofpdf.py` | The proof of an order, written by Prepare and by Save to order: `work/proof.png`, `work/softproof.png`, and the client's `out/proof/<stem>-proof.jpg` and `.pdf` (one page marked PROOF). | `tests/test_orderproof.py` |
| `app/orderstudio.py` | The studio's side of an order: `list_orders`, `save_spec` (Save to order: refuses a wallpaper or another size, records the inputs hash and the proof it wrote), `approve` (needs the client proof of the saved spec) and `approval_ok`. The approval is the hash of the saved spec. Behind the routes `/api/orders` and `/api/order/open`, `/save` and `/approve` in `app/main.py`; the front end is `app/static/order.js`. `photo_view` and `edit_photo` are the photo panel and its edits, behind `POST /api/order/photo`. | `tests/test_order_routes.py` |
| `app/orderfinish.py` | `order finish`: refuses, before the render, an order that is not approved, changed after approval, with a photo in the tray (no spot, not dropped) or a band over 12 photos, not the order's size, with a bleed or with a photo it cannot read. Then it writes the print TIFFs (`out/print/`), `work/record.png` and `PRINT.txt` under temporary names and renames them, so a failed write keeps the last run. It removes any other `.tif` in `out/print/`. | `tests/test_orderfinish.py` |
| `scripts/order.py` | The command line of an order. It has four commands: `new` (`app/ordernew.py`), `preview` (`app/orderpreview.py`), `prepare` (`app/orderprep.py`) and `finish` (`app/orderfinish.py`). A command that stops prints one line that starts with its own name, and exits 1. | `tests/test_orderpreview.py`, `tests/test_orderprep.py` |
| `app/regionbuild.py` | GPX-first planning (bbox, UTM zone, US coverage) and the `region_prep.py` subprocess behind `/api/regions/build`. | `tests/test_regionbuild.py`, `tests/test_region_endpoints.py` |
| `app/plates.py` | `.venv/bin/python -m app.plates install` places a `.trailplate.zip`. `verify` checks a poster PNG against the installed plate. | `tests/test_plates.py` |
| `app/store.py` | Session persistence: `MemoryStore` by default, `SqliteStore` with `TECOPA_STORE=sqlite`. | `tests/test_server_foundation.py` |
| `app/session.py` | The four-call session API the endpoints use (`create`, `has`, `get`, `update`). A thin delegate over the store chosen by `TECOPA_STORE`. | `tests/test_main.py` |
| `app/blobs.py` | Render output storage behind `LocalBlobs`. | `tests/test_server_foundation.py` |
| `app/jobs.py` | `ThreadJobQueue`, the async render queue at the compose to rasterize boundary. | `tests/test_server_foundation.py` |
| `app/logconfig.py` | Logging configuration. | `tests/test_logconfig.py` |
| `app/debug.py` | The debug routes under `/api/debug/`. Read-only: engine, jobs, sessions, caches, `forms` (the form-field names of each render route), and for one session its `starter_crop` and its `proof_form`. One route writes: `POST /api/debug/studio` adds a studio report to a buffer in memory, and `GET /api/debug/studio` returns the buffer. `enabled()` is the `TECOPA_DEBUG` gate. `build_router` takes the queues, the caches, the route functions and two helpers as arguments, so it never imports `app/main.py`. | `tests/test_debug.py` |
| `app/main.py` | The endpoints, the three queues, `_ready_or_503`, the pre-enqueue checks, the auto-docs switch-off. For a set: the wall tone in a proof, the zip of panel files (`_encode_delivery`, `_delivery_name`), the refusal of a film and a wallpaper bundle (`_refuse_set`). `_inspect_fields` types each field of the inspect reply. | `tests/test_main.py`, `tests/test_panel_api.py`, `tests/test_region_endpoints.py`, `tests/test_geometry_gate.py`, `tests/test_markers_move.py`, `tests/test_proof_refine.py`, `tests/test_region_recovery.py`, `tests/test_output_fitness.py` |
| `app/static/app.js` | The studio bootstrap and router over target and view. | `tests/test_static_registry.py` (text checks only) |
| `app/static/controls.js` | The declarative registry of every user-settable option. One entry drives the inspector, the palette, presets and the proof-staling rule. | `tests/test_static_registry.py` |
| `app/static/viewer.js`, `proof.js`, `statusbar.js`, `jobs.js` | Proof zoom and pan, the progressive proof, the status strip, the shared job poll loop. | not covered. No JS runner: drive the browser. |
| `app/static/library.js`, `compose.js`, `create.js`, `films.js`, `social.js`, `exports.js` | The Library home, the Compose workspace, the GPX-first creation card, the Film and Social targets, the Exports center. `compose.js` holds the size menu of a set and its gap control (`applyPrintSize`, `reframe`). | `tests/test_static_registry.py` holds the set's rules as text: the field names on the wire, no bleed, the fresh frame, the jobs a set stops, the card's escaping. The rest is not covered. |
| `app/static/store.js`, `api.js`, `ui.js`, `inspector.js`, `palette.js`, `presets.js`, `markers.js`, `canvas.js`, `guided.js`, `sunDial.js` | State and prefs, fetch wrappers, DOM helpers, the inspector, the command palette, presets, the marker list, map drawing, the first-run guide, the sun dial. `store.js` holds `setAutoIsLandscape`, the Auto orientation of a set. `canvas.js` draws the gap strips in the frame tool. | `tests/test_static_registry.py` runs `setAutoIsLandscape` under node and compares it with the preview's choice. It skips without node. The rest is not covered. |
| `app/static/debug.js` | The studio's report to its own engine. Each 2 seconds it posts eight state values and the page's errors to `/api/debug/studio`. It stops for the page load when the engine refuses the post, which is the gate-off case. It never reads journey data and it can never break the studio. | `tests/test_static_registry.py` (text checks), then a browser drive |
| `app/static/help.html` | The in-app help page. | not covered |
| `region_prep.py` | The offline plate bake: `plan_build`, the 3DEP fetch, `build_dem_cog` and its `fill_dem_holes` (a dynamic grid's holes, from the static tiles), `bake_hydro`, NLCD, `write_sources_manifest`. Sets `SSL_CERT_FILE` before importing the fetch stack. Runs in `.venv-prep`. | `tests/test_region_prep.py` (the pure planner, so it runs in the core venv and in CI), `tests/test_hydro.py` (skips without `geopandas`) |
| `scripts/build_labels.py` | GNIS terrain names to `labels.json`. Needs only the standard library and `pyproj`, so it runs in `.venv`. | `tests/test_build_labels.py` |
| `scripts/bake_playa.py` | NHD playas to `playa.json`. Imports `pynhd`, so it runs in `.venv-prep`. | not covered. `tests/test_water.py` covers the renderer's playa path, not the bake script. |
| `scripts/pack_region.py` | A deterministic `.trailplate.zip` from a built region. `--resync` writes true disk hashes into the zip's copy. | `tests/test_plates.py` |
| `scripts/verify_regions.py` | Every plate's assets against its `sources.json`, plus a geometry row. A script on purpose, not a test. | `tests/test_verify_regions.py` |
| `scripts/measure_final.py` | The memory gate for panel sets: it renders the largest sheet of a set (59 × 22 in, 116.8 megapixels) on a real plate and prints the peak resident memory as one JSON line. Run it under `/usr/bin/time -l` and judge "peak memory footprint": resident memory reads too low on macOS. Run it again after any change that makes the final of a set larger. | `tests/test_measure_final.py` (the pure parts. The render is a hand run.) |
| `scripts/render_asset_farm.py` | The marketing asset farm: poster, editions, wallpapers, film, detail crop, mockups, model, coin, relief. Stamps the `terrain` record. | `tests/test_asset_farm_detail.py`, `tests/test_asset_farm_frame.py`, `tests/test_asset_farm_gate.py`, `tests/test_terrain_provenance.py`, `tests/test_export_relief.py` |
| `scripts/track_network.py` | Pure routing over the cached OSM network: graph, Dijkstra, destinations, journey composer. | `tests/test_track_network.py` |
| `scripts/fetch_track_network.py` | Overpass fetch into the gitignored cache. Network access. | `tests/test_track_network.py` covers the pure half: the bbox transposition, the tiling arithmetic, the classifier, the retry loop. The fetch itself is hand-verified. |
| `scripts/render_mockups.py`, `scripts/render_lightsweep.py` | The object mockups and the light-sweep turntable. | `tests/test_mockups.py` |
| `scripts/render_model.py`, `scripts/render_coinspin.py` | The orbitable GLB plate and the coin spin. | `tests/test_coinspin.py` |
| `scripts/export_relief.py` | The landing page's relief-viewer images: surface and height map for each coin and the hero poster, plus the wall and close-up stills. The coin uses the GLB's own crop and height field. Gated by `build_deploy.terrain_guard`. Writes `<region>/relief/`. | `tests/test_export_relief.py` |
| `scripts/hero_plate.py`, `scripts/hero_scene.py` | The Blender hero plate CLI and the script that runs inside Blender. | `tests/test_hero_plate.py` |
| `scripts/render_poster.py`, `scripts/make_dummy_gpx.py` | By-eye poster render and the synthetic GPX generator behind `tests/fixtures/sample.gpx`. | not covered |
| `scripts/macos/build_app.sh`, `TecopaPlateworksLauncher.swift`, `Info.plist.template`, `make_icon.py`, `smoke_test.sh` | The macOS launcher: build, the Swift launcher on port 8848, the plist with bundle id `guide.badwater.tecopa`, the icon, the manual smoke test. | not covered. `smoke_test.sh` is a manual check. |
| `tools/tecopa/` | The `tecopa` tool: one Swift binary that is a command line and an MCP server. `tools/tecopa/Sources/TecopaKit/Catalog.swift` lists every operation once, and the CLI and `tecopa mcp` both call it. `tools/tecopa/Sources/TecopaKit/ScriptRunner.swift` holds the script table that decides a script's venv. `tools/tecopa/Sources/TecopaKit/Render.swift` and `tools/tecopa/Sources/TecopaKit/Reprint.swift` hold the render, reprint and continue commands: they send the caller's values to the engine unchanged and never overwrite a file. `tools/tecopa/Sources/TecopaKit/Studio.swift` reads the studio reports. `tools/tecopa/Sources/TecopaKit/Runs.swift` starts a long script detached and keeps its record, and `tools/tecopa/Sources/TecopaKit/Plates.swift` and `tools/tecopa/Sources/TecopaKit/Orders.swift` hold the plate and order commands. `Orders.swift` holds five: `order new`, which runs in the call, `order prepare`, `order preview` and `order finish` as tracked runs, and `order status`. The catalog has 36 entries. The tool has no format logic: the zip of a set is written to `--out` unchanged. | `swift test --package-path tools/tecopa`, Mac only. `tools/tecopa/smoke_test.sh` is the manual end-to-end check. |
| `marketing/build_deploy.py` | `terrain_guard` alone: refuses any region whose images were rendered from synthetic or unrecorded terrain. `scripts/export_relief.py` runs it per region. The name is kept from the retired Netlify builder (tag `landing-final-2026-09-26`). | `tests/test_terrain_provenance.py`, `tests/test_export_relief.py` |
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
- **A set is one sheet.** A set of two or three panels is one `CompositionSpec`. Its sheet is the hung size, gaps included. `rasterize` paints that sheet once, and `app/panels.py` cuts it. A proof shows each gap strip in the wall tone. A final is a zip with one file for each panel: `<stem>_panels.zip` for PNG and `<stem>_panels_pdf.zip` for PDF. The zoom cap and the 120 MP ceiling apply to the whole sheet.
- **Any PNG panel is the whole set.** Each PNG panel carries the spec of the set and a `panel` key with its number. `/api/reprint` of one panel returns the zip of all panels, and `/api/continue` of one panel restores the set. A PDF panel carries no manifest. `docs/MANIFEST.md` has the fields.
- **A set is a print.** `validate` refuses a set as a wallpaper, and a set with a bleed. `/api/timelapse/submit` and `/api/wallpapers/submit` answer 422 for a set.
- **Share copies carry nothing.** `embed_spec=false` writes no text chunk at all. PDF finals never carry a manifest.
- **Relief runs concurrently.** Four passes fan out on threads and merge in submission order. A window above 60 million pixels, which is every set, runs two at a time: the passes at once are the memory peak of a final. `TECOPA_RELIEF_WORKERS` sets the width at every size, and `1` restores the serial order. No width changes a pixel.
- **Type is bound per role by the operator.** `TECOPA_FONT_TITLE`, `_POINT`, `_AREA`, `_WATER`, and `TECOPA_FONT` for body and fallback. The default chain is Georgia, then DejaVu. Bindings ride in no manifest, so the same file renders differently on a host with different bindings.
- **Region builds are subprocesses.** `POST /api/regions/build` spawns `region_prep.py` in `.venv-prep` on `BUILD_QUEUE` (one slot). Without that venv `/api/regions/plan` reports `prep_ready: false`.
- **Auto-docs are off.** `app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)`, so the studio never fetches from jsDelivr.
- **The debug routes are gated.** `/api/debug/*` exists only under `TECOPA_DEBUG=1`, which the macOS launcher sets. With the gate off `app/main.py` never includes the router, so each path is a plain 404, and a POST gets the static mount's 405. With the gate on, the routes also refuse any request whose Host header is not local, with a 403. No debug route changes a session, a job, a cache or a plate, and none writes to disk. One route changes anything at all: the studio post adds to a report buffer of fixed size in memory. That post needs a JSON content type and refuses an Origin header that is not local, so a page on another website cannot fill the buffer.
- **Photos flow through the order's state.** Prepare's `place_photos` reads the photos in `in/` and writes each as a work JPEG, `work/photos/<file>.jpg`. `photos.read_meta` gives the position and the time, `photospot.spot_for` the spot (GPS, then time, else the tray), `photocaption.nearest_name` the caption and `photolayout.layout` the box on the crop that prints. The result is `state.photos`. The studio's edits are `manual.photos`, and `orderspec.effective_photos` lays them over Prepare's, field by field. `default_spec` turns them into hotspots with `box`, `crop` and `source`. `order_spec` sets those photo fields again on a saved spec, so the proof, the approval hash and Finish see one set of photos. `orderfinish` checks the state for a tray photo or a band over 12 before it renders.
- **The size preview is not the proof.** `scripts/order.py preview` draws each offered size on a coarse plate at screen size, with the word PREVIEW. It frames each size as Prepare does, so the ground is the ground of the print. A place name can be in another position on the final map. Prepare does not read the preview's record: it frames the chosen size again.
- **`ready: True` does not mean real terrain.** `tests/conftest.py` builds a synthetic DEM tagged `synthetic=1` for any plate that lacks one. Check the tag before judging a poster by eye.

## Environment

| Variable | Used by | Note |
|---|---|---|
| `TECOPA_REGIONS` | `app/main.py`, `tests/conftest.py` | The plates root. Default `regions`. |
| `TECOPA_BLOBS`, `TECOPA_UPLOADS` | `app/main.py`, `tests/conftest.py` | Output and upload folders. The test harness points both at temp folders, one per xdist worker. |
| `TECOPA_STORE`, `TECOPA_DB` | `app/store.py`, `app/session.py` | `sqlite` persists sessions to `TECOPA_DB`. Unset means in-memory. |
| `TECOPA_TTL_SECONDS`, `TECOPA_RENDER_CONCURRENCY` | `app/main.py` | Job retention and the render queue's width. |
| `TECOPA_BASE_CACHE_MB`, `TECOPA_INK_CACHE_MB` | `app/basecache.py`, `app/main.py` | Cache budgets. |
| `TECOPA_RELIEF_WORKERS` | `app/relief.py` | Fan-out width at every sheet size. `1` is the serial order. Unset means four, and two on a window above 60 million pixels. |
| `TECOPA_FONT`, `TECOPA_FONT_TITLE`, `TECOPA_FONT_POINT`, `TECOPA_FONT_AREA`, `TECOPA_FONT_WATER`, `TECOPA_FONT_<ROLE>_CASE` | `app/render.py`, `scripts/render_mockups.py` | Per-role faces. `TECOPA_FONT_AREA_CASE=mixed` for a small-caps face. Tested by `tests/test_type_roles.py`. |
| `TECOPA_ENGINE_VERSION` | `app/provenance.py` | Overrides the git commit as `engine_version` in packaged builds. |
| `TECOPA_PREP_PYTHON`, `TECOPA_PREP_SCRIPT`, `TECOPA_LABELS_SCRIPT` | `app/main.py` | The interpreter and scripts the in-app region build spawns. |
| `TECOPA_ORDERS_DIR` | `app/order.py` | The root of the order folders and of the request cache that Prepare and the preview share. Default `~/Tecopa Orders`. It must be outside this repo. |
| `TECOPA_INTAKE_DIR` | `app/ordernew.py` | The folder `order new` reads the intake's job folders from. Default `~/Dropbox/Apps/Plateworks Lab/Tecopa`. The orders root must not be inside it. |
| `TECOPA_LOG_LEVEL`, `TECOPA_LOG_FORMAT` | `app/logconfig.py` | Logging. |
| `TECOPA_DEBUG` | `app/debug.py`, `app/main.py` | `1` includes the debug routes. Any other value, and unset, leaves them out. The launcher sets it. `tests/conftest.py` removes it. |
| `TECOPA_REPO` | `tools/tecopa/Sources/TecopaKit/RepoLocator.swift` | The repo path for the `tecopa` tool, after `--repo` and before the path baked at build time. |
| `TECOPA_BLENDER` | `scripts/hero_plate.py` | The Blender binary, when not on `PATH`. |
| `TECOPA_COIN_FRAMES`, `TECOPA_MOCKUP_FRAMES` | `scripts/render_asset_farm.py`, `scripts/render_coinspin.py`, `scripts/render_mockups.py` | Frame counts for the social assets. |
| `NETLIFY_AUTH_TOKEN` | the manual deploy | Read from `~/.config/netlify/token`. See `../marketing/DEPLOY.md`. |

No environment variable changes the picture a given spec paints, except the
font bindings, which is by design.

One data file is configuration: `config/sizes.toml` holds the name, the prices, the
shipping and the Payment Links of each size that a preview can offer, and of the
digital poster. `app/sizes.py` reads it, and a wrong file stops
the preview before any build.

## Delivery

| Surface | How |
|---|---|
| The studio | `uvicorn app.main:app --reload` on port 8000 for development. The macOS launcher runs the engine from this repo's `.venv` on port 8848 and logs to `~/Library/Logs/TecopaPlateworks.log`. Build it with `scripts/macos/build_app.sh --install`. A `git pull` updates it with no rebuild. |
| The `tecopa` tool | `tools/tecopa/build.sh --install` builds the release binary and copies it to `~/.local/bin/tecopa`, with this repo's path baked in. Register it in Claude Code at user scope as the MCP server `tecopa`. `tools/tecopa/register_desktop.sh` registers it in the Claude desktop app, with the app quit. Rebuild after the repo moves or the Swift code changes. |
| Plates | Five committed under `regions/`: `lassen_ca`, `susanville_reno`, `elko_bonneville`, `rifle_aspen`, `tushar_beaver_ut`. Each `dem.tif` is gitignored and rebuilt with `region_prep.py`. Packing and publishing plates has never run. |
| The landing page | Pages on www.plateworks.org since 2026-09-26: `/tecopa/`, `/tecopa-build/` and `/tecopa-privacy-policy/`, built by the blog folder's ghost-tecopa-pages script in the Ghost era and held in plateworks-site since 2026-10-13. `tecopa.plateworks.org` is a Cloudflare 301 to `/tecopa/` with the path kept. The Netlify site `tecopa-plateworks` still holds the last deploy as the rollback: delete the Cloudflare rule to serve it again. |
| The privacy page | `/tecopa-privacy-policy/`. The site's redirects (carried over from Ghost's redirects file) send `/tecopa/privacy/` there. |
| Python | 3.14 on the Mac and in CI, which installs the version in `.python-version`. Every pin in `requirements-lock.txt` has a 3.14 wheel for `ubuntu-latest` (checked 2026-09-23). |
| Dependencies | `requirements-lock.txt` is what CI installs, then `pandas geopandas`, then `requirements-share.txt`. `requirements.txt` holds the unpinned core minimums and `requirements-dev.txt` the test dependencies; the lock is what a machine actually installs. `requirements-regionprep.txt` goes only into `.venv-prep`. |

## The verification harness

- `.venv/bin/python -m pytest -n auto -m "not slow" -q` is the fast tier. On 2026-09-08 it ran 616 tests on this Mac in under a minute: 615 passed and one failed, the documented font failure in `tests/test_bleed.py`.
- `.venv/bin/python -m pytest -n auto -q` is the full suite, about 3 minutes on this Mac. It has no known Mac-only failure. Compare the failure set, not the totals. `changing-things.md` under Run the tests has the history of the seven tests once blamed on fonts.
- `tests/conftest.py` classifies `slow` tests centrally from measured durations. Re-derive after adding heavy tests with `--durations=0`.
- The studio has no JS runner. `tests/test_static_registry.py` checks `controls.js`, the HTML and the report module `debug.js` as text. Everything else is a browser drive.
- The panel-set tests that render are slow: all of `tests/test_panel_render.py` and `tests/test_orderpreview_render.py`, one test of `tests/test_panel_api.py`, which renders a final of 71 megapixels twice, and `tests/test_render_memory.py`, which measures the live bytes of a final. No test of a set or of the preview reads the network: the preview's tests use stub subprocesses.
- `.venv/bin/python scripts/verify_regions.py` reports every plate's hash and geometry state. Run it after any pull that touched `regions/`. Outside `.venv` the render stack is absent and the geometry row degrades to `skip`.
- `scripts/macos/smoke_test.sh` drives the launcher end to end and needs a human for two macOS prompts.
- `swift test --package-path tools/tecopa` runs the tool's tests with no engine and no network. `tools/tecopa/smoke_test.sh` drives the real launcher and needs port 8848 free and the real `lassen_ca` DEM. Its panel-set block renders two finals of 71 megapixels each, so allow about ten minutes. Neither runs in CI.
- The published pages are gated by `tests/test_marketing_page.py` (the Collector register, the prices, the privacy claims), run with `-m live`, and the relief images by the terrain guard in `../marketing/build_deploy.py`.

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
