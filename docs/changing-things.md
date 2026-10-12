# Changing things

One section per task. Each names the file to edit, the test that judges it,
the check that proves it, and the spec to read first when one governs. Before
any claim of done: the fast tier, `.venv/bin/python -m pytest -n auto -m "not slow" -q`,
and for anything that touches a render, the full suite.

## Set up a machine

1. Clone `tecopa-plateworks`. On the Mac, `python3.14 -m venv .venv`. CI installs the
   Python named in `.python-version`, 3.14, the same interpreter as the Mac venv.
2. Install in the order `.github/workflows/ci.yml` uses: `.venv/bin/pip install -r requirements-lock.txt`,
   then `.venv/bin/pip install pandas geopandas`, then `.venv/bin/pip install -r requirements-share.txt`.
   The two extras sit outside the lock on purpose, so the region-prep and MP4 tests run instead of skipping.
3. Never install `requirements-regionprep.txt` into `.venv`. Its stack pulls numpy,
   scipy and rasterio past their pins. Create the second venv for `region_prep.py`:
   `python3 -m venv .venv-prep && .venv-prep/bin/pip install -r requirements-regionprep.txt`.
   Without it `/api/regions/plan` reports `prep_ready: false` and the studio shows the
   setup command in place of a Build button. `TECOPA_PREP_PYTHON` overrides the path.
4. `.venv/bin/python -m pytest -n auto -m "not slow" -q`.
5. Start the studio: `.venv/bin/uvicorn app.main:app --reload` on port 8000.

A venv is bound to its interpreter. When `.venv/bin/python` reports "no such file or
directory" but `ls` lists it, the symlink target is gone. Rebuild in place with
`python3.14 -m venv --clear .venv`, then repeat step 2. Never rename or move a venv:
its shebangs and `pyvenv.cfg` hold the absolute path.

Every `regions/<id>/dem.tif` is gitignored. `tests/conftest.py` hydrates a small synthetic DEM per
plate, tagged `synthetic=1`, so the suite runs on a fresh clone. A synthetic plate is
useless for judging a poster by eye. Build the real DEM first (see "Build a new plate").

## Run the tests

1. Fast tier: `.venv/bin/python -m pytest -n auto -m "not slow" -q`. This is the
   pull-request tier in CI.
2. Full suite: `.venv/bin/python -m pytest -n auto -q`. It renders real posters and
   films, about three minutes on the Mac. CI runs it on every push to `main`.
3. Compare the failure set, not the totals. Totals move with every feature. The
   suite has no known Mac-only failure. `test_mp4_twin_is_tagged_bt709` failed on the
   Mac until 2026-09-24. The one `imageio-ffmpeg` pin ships ffmpeg 7.1 on macOS and
   7.0.2 on Linux. From 7.1 the encoder reads colour tags from the frames, not the
   flags, so the Mac MP4 had no `colr` box. A `setparams` filter now tags the frames.
   Seven more were blamed on fonts (Georgia on the Mac, DejaVu in CI) until
   2026-09-23. The font was not the cause: bound to DejaVu, six of the seven still
   failed. They read `regions/lassen_ca` directly, and conftest only hydrates a
   missing DEM, so on the Mac they rendered real terrain against thresholds tuned on
   the synthetic surface. They now render from `synthetic_region()` in
   `tests/conftest.py` and pass on both hosts.
4. Confirm any new failure against a clean checkout before chasing it. Most are the host.
5. A test that passes only on a synthetic plate tests the host, not the code. Two went
   red the moment a real DEM returned (commits `c81ca51`, `5c22096`), and seven more
   ran on real terrain on the Mac for weeks. Construct the condition a test needs. Do
   not inherit it from the ambient plate: use `synthetic_region("<id>")`.
6. `slow` is classified centrally in `tests/conftest.py` (`_SLOW_MODULES`,
   `_SLOW_TESTS`). After adding a heavy test, re-derive with `--durations=0` and add it
   there. `--strict-markers` is on, so a misspelled marker is an error.

## Repair an orphaned DEM

`regions/<id>/dem.tif` is gitignored and every other plate asset is committed. A plate rebuilt in a
cloud container ships its small assets to `main` and leaves the DEM behind. The next
pull pairs a new `region.json` with the old local DEM. This recurs.

1. After any pull that touched `regions/`, run `.venv/bin/python scripts/verify_regions.py`.
   It prints a geometry row per plate. Run it inside `.venv`: without the render stack the
   geometry row degrades to `skip`. `ORPHAN` is the one verdict that needs this repair. Until then every render verb answers 503 with the drift named
   (`_ready_or_503` in `app/main.py`, no override), and the asset farm skips the plate.
2. In `.venv-prep`, call `region_prep.build_dem_cog` with a plan from
   `region_prep.plan_build`. Do not call `region_prep.main`: it refetches NHD and NLCD
   too, and upstream drift turns a restoration into a new plate version.
3. `build_dem_cog` returns the path and a hole-fill record (`None` on the static
   grids every curated plate uses). It does not write `sources.json`. Run `scripts/verify_regions.py` again
   and read the sha256 verdict. What it finds is a decision, not a cleanup.
4. Match: the exact plate is back. Done.
5. Differ: USGS re-tiled and you built a new plate version. Leave the sidecar alone.
   The mismatch is the only record that the swap happened. Never re-stamp `sources.json`,
   and never re-run `write_sources_manifest`: its loop omits `playa.json` and resets
   `built` to today. `provenance.region_pack_block` hashes from disk every plate asset
   the render actually read, at final time, and refuses to trust the sidecar. No poster
   is affected.
6. To pack such a plate, `.venv/bin/python scripts/pack_region.py <id> --resync`. It
   writes the true disk hashes into the zip's copy and leaves the source folder alone.
   `tests/test_verify_regions.py` and `tests/test_plates.py` judge these paths.

Four of the five plates carry this known drift on purpose: `elko_bonneville`,
`rifle_aspen`, `susanville_reno` and `tushar_beaver_ut` (commit `f518be8`, and
`decisions.md` 2026-08-17). Do not "fix" it.

## Build a new plate

Read `superpowers/specs/2026-07-19-gpx-first-region-creation-design.md` first. The
region is an outcome, not a first step. US only.

1. In the studio, drop the tracks. When no built plate covers them, `/api/regions/plan`
   prices the job and `/api/regions/build` spawns `region_prep.py` in `.venv-prep` on a
   one-slot queue. Corridor-scale areas are refused in-app and stay a terminal run.
2. Terminal run, in `.venv-prep` only:
   `.venv-prep/bin/python region_prep.py --id <id> --name "<name>" --bbox <w> <s> <e> <n> --epsg <code>`.
   `--resolution` defaults to `auto`.
3. In `.venv`, `.venv/bin/python scripts/build_labels.py <id>` writes `labels.json` from
   GNIS. In `.venv-prep`, `.venv-prep/bin/python scripts/bake_playa.py <id>` writes
   `playa.json` from NHD. The playa bake imports `pynhd`, which only `.venv-prep` has.
4. Commit `region.json`, `overview.png`, `hydro.json`, `landcover.tif`, `labels.json`,
   `playa.json` and `sources.json`. `regions/<id>/dem.tif` stays local.
5. `.venv/bin/python scripts/verify_regions.py`, then judge the plate by eye on the real DEM.

The `tecopa` tool runs the same scripts, each in the venv that its script table names:
`tecopa plate plan`, `plate build`, `plate labels`, `plate playa`, `plate pack`,
`plate install` and `plate check`. Three rules differ from a hand run.

- `plate build`, `plate labels` and `plate playa` are tracked runs. The command returns
  a run id at once. `tecopa runs show <id>` gives the state and the end of the log, and
  `tecopa runs cancel <id>` stops the run.
- A command creates a `sources.json` entry and never replaces one (invariant 12).
  `plate build` refuses a plate that exists. `plate labels` and `plate playa` refuse
  when `sources.json` already lists their file. To bake again over a drifted asset, run
  the script by hand and read "Repair an orphaned DEM" first.
- `plate install` takes a local `.trailplate.zip` only and never passes `--replace`,
  which deletes the installed plate. `--bbox` is one word with commas:
  `--bbox -121.6,40.3,-121.2,40.6`.

Traps already paid for:

- `region_prep.py` sets `SSL_CERT_FILE` from `certifi` before importing py3dep and
  pynhd, because aiohttp captures SSL config at import. It fetches hydro before the DEM.
  Keep both orderings when adding network code.
- py3dep returns EPSG:5070 in metres, not 4326. `plan_build` sizes the job before any
  fetch so a corridor-scale bbox cannot exhaust memory (the 15.8 GB lesson).
- The static 60 m tiles cover Alaska only. Outside them `plan_build`'s auto choice
  steps 60 m down to 55 m, served dynamically, as an order plate does. An explicit
  `--resolution 60` is not stepped down.
- Region data is read by the render from the region folder. It never rides on the spec.
- For out-of-plate test coordinates use Virginia, about -79.5, 37.8. `elko_bonneville`
  is corridor-scale and swallows most western points that look outside.
- `ready: True` does not mean real terrain. Check the `synthetic` tag, not the flag.

Tests: `tests/test_region_prep.py` (the pure planner, so it runs in `.venv` and in CI),
`tests/test_hydro.py` (skips without `geopandas`), `tests/test_regionbuild.py`,
`tests/test_region_endpoints.py`.

## Run an order

Read `superpowers/specs/2026-09-24-order-pipeline-design.md` first. For a set or the
size preview, read
`superpowers/specs/2026-10-11-print-sizes-panel-sets-and-size-preview-design.md` too.
`scripts/order.py` has two commands, `preview` and `prepare`. Prepare does the plate
step only. `order finish` is not built, so a set order ends at the engine's zip of
panel files.

1. Make the order folder under `~/Tecopa Orders/` (or `$TECOPA_ORDERS_DIR`). Never
   inside the repo: it is public. Put the customer's GPX, KML or KMZ files in `in/`.
2. Write `order.toml`: `title` (required), `size` and `orientation` (`portrait`, the
   default, or `landscape`). `size` is `"11x17"` (the default), `"17x22"`, `"two"` or
   `"three"`. A single sheet has a short side of at most 17 in, the PRO-1100's width.
   `"two"` and `"three"` are a set of 17 × 22 in panels: `landscape` hangs them 22 in
   across, and `portrait` 17 in across. A set also takes `gap`: 0, 2 (the default) or
   4, the inches of wall between two panels. A gap of 0 is a cut set: every part of
   the map is printed. A gap of 2 or 4 is a window set: the map continues behind each
   gap strip, and the gap strip is not printed. A single sheet does not read `gap`.
3. To let the client choose a size, run the preview before Prepare:
   `.venv/bin/python scripts/order.py preview "<folder>"`. It needs the tracks in `in/`
   and the `title`. It does not use `size`, `orientation` or `gap`, but a wrong value
   in one of them stops it. It needs `.venv-prep`, unless a curated plate holds every
   size. It can run again safely. `tecopa order preview "<folder>"` runs the same
   script as a tracked run. The preview does these steps:
   - It frames each of the four sizes in both orientations, as Prepare frames them,
     and keeps the orientation with less wasted ground. A set is framed at a gap of 2 in.
   - It offers the two single sheets. It offers a set when the tracks span at least
     30 % of the sheet's width (`SET_MIN_FILL` in `app/orderpreview.py`) and every
     panel holds some part of a track. The frame is centred on the tracks, so in
     practice three panels need tracks across about 37 % of the width.
   - It builds one coarse plate for each projection in use, under
     `<folder>/work/preview/plate/`. A curated plate is used when it holds the frames.
   - It draws each offered size at screen size with the word PREVIEW, and writes
     `<folder>/out/preview/<title>-preview.pdf`, where `<title>` is the title as a
     slug. Page 1 shows every offered size on one wall at one scale. Then each size
     has a page with its name, its hung size and its price.
   - It writes `<folder>/work/preview/preview.json` (each size, its frame, its
     projection, and why a size is not offered), `<folder>/work/preview/report.txt`
     and `<folder>/work/preview/build.log`, and prints the report.
4. Read the preview's report and the PDF. An offered size has its price and the lines
   for `order.toml`, one key on each line. A set that is not offered has the reason,
   for example "not offered, the tracks span 24% of the sheet's width, under 30%". A
   size that the terrain data cannot hold at 2x, or that the engine cannot draw, is
   "not offered" with the engine's own reason, and the other sizes are still drawn.
   "Warning: a route end is behind gap 1" means that a window set hides the start or
   the end of a track: move the frame, use a gap of 0, or choose another size. Send
   the PDF to the client. It has no buy link: the client answers with a choice.
5. Paste the lines of the chosen size into `order.toml`. Prepare does not read the
   preview's files. It frames the chosen size again with the same rule, so with the
   lines as pasted the frame of the print is the frame of the preview. For a cut set
   or a 4 in gap, change `gap` by hand: the sheet's shape changes with the gap, so
   the frame changes a little.
6. Run `.venv/bin/python scripts/order.py prepare "<folder>"`. It needs `.venv-prep`.
   `TECOPA_PREP_PYTHON` overrides which prep interpreter it calls.
   `tecopa order prepare "<folder>"` runs the same script as a tracked run, and
   `tecopa order status "<folder>"` reads `work/state.json` and the report.
7. Read the report. For a set, the "Print" line gives the panel count, the hung size
   and the gap, and the plate's grid follows the hung width. A warning that a route
   end is behind a gap means the same as in the preview: move the frame, or use
   `gap = 0`. "Upsampling" above 1.00x means the terrain data is coarser than the
   print can show, up to the 2x limit. A widened frame means the data could not hold
   the nestled look at this size; the warning names it, but naming the exact smaller
   sheet waits for the paper table (sub-project 2). "No elevation" is the measured
   share of the plate and of the frame with no data. "Hole fill" means the dynamic
   service left holes and region_prep filled them from the static tiles. A warning
   that the plate has no elevation past what the 3DEP index expects means holes the
   fill did not close. `HOLES IN THE PRINT` leads the warnings when any are inside the
   frame: do not print; delete the plate under work/plate/ and run Prepare again.

Running Prepare again with the same tracks, size and orientation builds nothing. For a
set, the panel count and the gap count too. A
changed input, or a new manual frame in `state.json`'s `manual` key, rebuilds the plate.
`in/` is never written. The plate lives in `work/plate/<id>/`. The HyRiver request
cache is `~/Tecopa Orders/_cache/`. It holds NHD, NLCD and dynamic-service requests,
and it grows large: 880 MB after a handful of orders. Delete it any time. The static
10, 30 and 60 m tiles are read by GDAL and are not cached.

The preview and Prepare share the request cache and no other file. In the order
folder, the preview writes only under `<folder>/work/preview/` and
`<folder>/out/preview/`. It does not read or write the order's own plate, `state.json`
or `work/build.log`, so a preview after Prepare leaves the order's plate current.

The preview's sizes:

- **The override list.** A `sizes` line in `order.toml`, for example
  `sizes = ["11x17", "17x22", "three"]`, replaces the fit rule. The preview offers
  each size in the list and no other size. A listed set that the fit rule refuses is
  offered with a warning in the report. The list never overrides the terrain: a size
  that is past the 2x limit stays not offered.
- **The prices file.** `config/sizes.toml` holds the name and the price of each size.
  Dom owns it. A row has `key`, `name` and `price`, and no other field. A name and a
  price are text in quotes: `price = "$69"`, never `price = 69`. A name has at most
  40 characters and a price at most 24. The file is UTF-8. A row with no price prints
  "Price on request". The preview reads the file before any query or build, and a
  wrong file stops it. `tests/test_sizes.py` holds the two single-sheet prices to the
  prices that `tests/test_marketing_page.py` holds the live pages to.
- **A stopped run.** The command prints `preview stopped:` and the reason, and exits 1.
  It writes no new PDF and no new report. The PDF of the last good run stays. The
  causes include: a title of more than 200 characters, a wrong prices file, no track
  points, tracks outside the lower 48 states, no `.venv-prep`, a query of the 3DEP
  index that fails, a plate build that fails, no size that can be offered or drawn,
  and an output folder that cannot be written.
- **Two preview plates can be normal.** A plate has one projection (invariant 4), and
  each size is framed in the projection that Prepare gives it. An order has two plates
  when a set is wide enough for Albers and a single sheet is not, or when a curated
  plate holds a single sheet and is too coarse for a set. A plate that is built after
  the first plate is `preview_<order>_<epsg>`, and its log is `build_<epsg>.log` in
  the same folder. The report then names each plate, its projection and its sizes.

Traps already paid for:

- The 3DEP dynamic service fills a missing fine layer with resampled coarse data and
  says nothing. `scripts/dem_coverage.py` measures each layer first. Tecopa has 1 m
  lidar and no 3 m data.
- An order passes an explicit grid, fetched at that cell size. `DEM_RES_CHOICES` is
  only the in-app auto planner's list, so adding 1 m there would make small in-app
  plates enormous. Never fetch a finer layer and average it onto a coarser grid in
  slices: that design was built and removed (see `docs/decisions.md`, 2026-09-24).
  The hole fill is not that design. It reads the static tiles onto NaN cells only,
  block by block, on the one shared grid.
- The dynamic service can also answer a sub-request with an empty tile and say
  nothing: the east-west acceptance plate came back 12.1% NaN where the index expects
  5.6%. `us_share` comes from index footprints, not from the data, so it cannot see
  this. `region_prep.fill_dem_holes` fills a dynamic grid's NaN cells from the static
  10 or 30 m tiles before the overviews are built, and records the fill in
  `sources.json` as a source with role `hole fill`. It reads the tiles' overviews, not
  every full-resolution cell: a full-resolution read was 7x slower. A fill that still
  fails after the retries keeps the plate and says so. Prepare's `check_holes` then
  measures what is left.
- The index returns HTTP 500 for the full outline of a large lidar footprint.
  `layer_coverage` asks for outlines simplified to about 50 m.
- A plate counts as complete only once `landcover.tif` lands. A plate missing just
  that file gets one automatic rebuild. A second failure keeps the plate and warns
  instead of rebuilding it forever. `work/build.log` keeps every build line, to read
  after a failed build sweeps the partial plate.
- The fetch stack writes more than the HyRiver request cache under a bare `cache/`:
  pygeoogc's own HTTP cache defaults there too (`HYRIVER_CACHE_NAME_HTTP` moves it,
  set beside `HYRIVER_CACHE_NAME`), and pygeoogc's `ArcGISRESTful` (pynhd's NHD
  queries) writes a retry log to a hardcoded `cache/failed_ids*.txt` with no env
  override at all. Prepare runs the prep subprocess with its cwd at
  `~/Tecopa Orders/_cache/` instead of the repo root, so that write lands there too;
  every script path and `--out-root` it passes is already absolute, so this is safe.
  The dynamic-service DEM fetch itself already follows `HYRIVER_CACHE_NAME`.
- A query of the 3DEP index that fails is not a refused size. The first build of the
  preview read it as one, so a network fault removed a size from the client's PDF and
  nothing said so. `read_coverage` now raises `CoverageError`, and the preview stops.
  Run it again: the USGS services fail from time to time. "Too coarse for this print
  size" still refuses only that size.
- The preview must frame a size as Prepare frames it: `curated_fit` first, then
  `order_epsg` at the sheet's aspect. The first build used one projection for all
  sizes, and a map in the Sierra was 12.6 degrees off its print. `OrderGround` in
  `app/orderpreview.py` holds the rule. A test pastes the report's lines into
  `order.toml` and checks that Prepare writes the same projection and frame.
- A gap in `order.toml` is checked as one of three exact values. A gap of 2.0000000001
  and a gap of 400 digits are each an `OrderError`, and a gap of -0.0 is 0.
- The preview is not the proof. Its plate is coarse, so a place name can be in another
  position on the final map. The PDF says so on each page.

Tests: `tests/test_orderplate.py`, `tests/test_order.py`, `tests/test_orderprep.py`
(stub subprocesses, no network), `tests/test_dem_coverage.py`. For the preview:
`tests/test_orderpreview.py` (stub subprocesses, no network), `tests/test_previewpdf.py`,
`tests/test_sizes.py`, and `tests/test_orderpreview_render.py` (slow: the real painter
on a synthetic plate).

## Add a relief technique

Read `relief-passes.md` first. Its body predates the forever-contract retirement. The
two corrections in the blockquote at the end of "The three moving parts" govern where
they disagree.

1. `app/spec.py`: the new field on `CompositionSpec`, with its pre-feature default.
2. `app/render.py`: read it through `relief_extra`.
3. Register the pass with `register_relief_pass` in `app/relief.py`, at its stage.
   `app/looks.py` is the shipped template.
4. `app/static/controls.js`: one `CONTROLS` entry, so the inspector, palette, presets
   and the proof-staling rule all learn it at once.
5. Tests, per `tests/test_looks.py`: byte identity at the default (a pass must be a
   strict no-op there), a proof-versus-final MAD test if it draws anything with a size,
   a golden only once the look is settled. `tests/test_relief_passes.py` pins what ships.

## Add a spec knob or studio control

1. `app/spec.py`: the field, its default, and its range in `STYLE_BOUNDS`. Physical
   units, never pixels.
2. `app/serialize.py` emits every field. `spec_from_json` drops unknown fields and
   defaults missing ones. Keep that read tolerance.
3. `app/static/controls.js`: one `CONTROLS` entry. `tests/test_static_registry.py`
   checks the registry and the HTML as text.
4. `tests/test_spec.py` for the bound. The seven `manifest_*_v1.json` fixtures under
   `tests/fixtures/` must still load. `tests/test_provenance.py` reads three of them.
   `tests/test_editions.py`, `tests/test_oblique.py`, `tests/test_timelapse.py` and
   `tests/test_wallpaper_api.py` read the rest.
5. A knob that reaches the terrain must miss `render.base_cache_key`. A furniture knob
   must hit it. `tests/test_base_cache.py` and `tests/test_ink_cache.py` judge that.

## Change a panel set

Read `superpowers/specs/2026-10-11-print-sizes-panel-sets-and-size-preview-design.md`
first. A set is two or three panels of 17 × 22 in that hang side by side as one map.
It is one `CompositionSpec` with `panels` (2 or 3) and `panel_gap_in` (0, 2 or 4). The
sheet in the spec is the hung size, gaps included. `rasterize` paints that sheet once,
gap strips included, and the cut drops the gap strips.

1. Panel geometry: edit `app/panels.py` and no other file. It is the only place that
   works out where a panel, a gap strip or a seam is. It imports nothing from `app`.
   The cut, the wall tone of a proof, the label keep-out, the furniture and the
   studio's restore all ask it.
2. The rules of a set: `validate` in `app/spec.py`. A set has four sheets for each gap:
   two or three panels, 22 in across or 17 in across. `validate` refuses any other
   sheet, a gap that is not exactly 0, 2 or 4, a bleed, and a wallpaper.
3. Furniture: `_paint_overlays` in `app/render.py`. The title block, the compass, the
   scale bar and the elevation strip are drawn once, in panel 1. Each panel gets its
   own keyline, a panel mark such as `2 / 3` in its lower right corner, and the
   watermark. `_furniture_scale` sizes the furniture of a set as one panel.
4. Seams: `_label_keepout` in `app/render.py`. Each seam acts as a sheet edge. The
   keep-out holds each gap strip and a band `GEO_EDGE_IN` wide on both sides of it,
   and each panel mark. A place name is not cut by a seam and is not drawn behind a
   gap strip. In smart placement, the leader line and the anchor dot of a name stay
   out of a seam band. A photo box and a marker label stay in the panel that holds
   their anchor. A marker label goes left of its marker when it does not fit on the right.
5. The routes: `app/main.py`. `/api/proof` takes `panels` and `panel_gap`, and paints
   each gap strip in the wall tone. A final and a reprint go through `_encode_delivery`:
   one file for each panel, in a zip. `_refuse_set` answers 422 for a set on
   `/api/timelapse/submit` (the film) and `/api/wallpapers/submit` (the wallpaper
   bundle), and for a reprint of a film file that claims a set.
6. The zip: `<stem>_panels.zip` holds PNG panels and `<stem>_panels_pdf.zip` holds PDF
   panels. A member is `<stem>_2of3.png`. The PNG zip is the same bytes each time:
   stored members, 1980 dates, one file mode. The PDF zip is not, because Pillow's PDF
   writer is not.
7. After a change that makes the final of a set larger, run the memory gate again:
   `.venv/bin/python scripts/measure_final.py`. It needs the real `rifle_aspen` DEM.

Traps already paid for:

- Only a PNG panel carries the manifest, with a `panel` key for its number. So only a
  PNG panel can reprint or continue the set. A PDF panel is for the print shop.
- One name for both zips let a PDF final replace the PNG final of the same session,
  because the name is also the blob key. Keep the two names.
- Something tied to the ground cannot move. A marker or a route end behind a gap strip
  of a window set is not printed. The proof covers it with the wall tone, and Prepare
  and the preview warn for a route end. Move the frame, or use a gap of 0.
- The centre of a two-panel sheet is the gap, so the watermark is drawn on each panel.
- The furniture scale must come from one panel. From the sheet's area, a 74 × 17 in
  set drew its title block at 183 %.
- A long title can leave panel 1: the title block has no width limit. The proof shows it.
- `panels` and `panel_gap_in` are masked in the terrain key and the ink key, because
  the terrain and the route are painted across the whole sheet. A gap on a single
  sheet does nothing, so a test of the mask must change the gap of a real set.
- The peak memory of a final does not follow its pixel count. The gate measured 14.07
  and 15.29 GB for 116.8 megapixels in a script, and a 71 megapixel final in the
  engine's own process measured 15.0 GB. The engine's own peak for the largest set is
  not measured yet: see the plan `superpowers/plans/2026-10-11-panel-sets-and-size-preview.md`.

Tests: `tests/test_panels.py` and `tests/test_panel_furniture.py` are fast.
`tests/test_panel_render.py` is slow: it paints sets at 40 dpi. `tests/test_panel_api.py`
is fast except one test,
`test_a_real_final_of_a_set_is_a_zip_job_and_any_panel_reprints_it`: it renders a
71 megapixel final twice, one after the other, and needs about 16 GB. Keep it the
only such test in the suite: two of them can run side by side on two workers.
`tests/test_poster_furniture.py` holds the furniture scale by number, and
`tests/test_static_registry.py` holds the studio's set rules as text.

## Change the manifest or add a file-consuming verb

`MANIFEST.md` is the format doc, internal since 2026-07-27. The CC0 dedication stands
for the versions published before then and cannot be revoked, but the document is no
longer a contract for outside implementers. `provenance.spec_from_manifest` is the one
untrusted-manifest door: parse, drop non-embedded photos, bound geometry, validate. Every
new verb that turns an uploaded file into a spec goes through it. `/api/reprint/inspect`
is the deliberate exception: it reads manifest fields only, and builds no spec.
Nothing has checked those fields, so `main._inspect_fields` gives each one a type and a
fallback. Add a new key of the reply there, never as a raw read: NaN in one key made
the whole reply a 500. `tests/test_panel_api.py` holds the hostile files.
The zTXt keyword `trailprint` is frozen forever, and
`ENGINE_URL` must name the real repo. `engine_version` records drift and is never read
back. Never reintroduce omit-at-default. Tests: `tests/test_provenance.py`,
`tests/test_editions.py`.

## Bind fonts per role

Read `00_Resources/typography-standards.md`. Set `TECOPA_FONT_TITLE`, `TECOPA_FONT_POINT`,
`TECOPA_FONT_AREA`, `TECOPA_FONT_WATER`, and `TECOPA_FONT` for body and fallback.
`TECOPA_FONT_<ROLE>_CASE=mixed` for a small-caps face. `TYPE_ROLES` in `app/render.py`
owns the seam. Bindings ride in no manifest. A bound face is sized so its register
metric matches the default chain's: cap-height for caps, x-height for text
(`render._size_scale`). A binding therefore never silently changes the sheet's perceived
type size. Never commit a font: `.gitignore` blocks `*.otf`, `*.ttf`, `*.woff` and
`*.woff2` (commit `39ad08c`), and the repo is public AGPL. `tests/test_type_roles.py`
judges it.

## Work on the studio front end

There is no JS runner.

1. `node --check` each edited module under `app/static/`.
2. Cross-reference every `$('id')` against the HTML.
3. `.venv/bin/python -m pytest tests/test_static_registry.py -q`.
4. Drive the real studio in a browser. A synthetic `DragEvent` with a `DataTransfer`
   works for uploads. Click coordinates in a headless browser do not.

`app.js` routes, `viewer.js` owns proof zoom and pan, `statusbar.js` prints the truth line.

A set has two controls on the Page panel: "Two panels" and "Three panels" in the size
menu, and a gap control (None, 2 in, 4 in). `applyPrintSize` in `compose.js` makes the
hung sheet from them. Four rules hold for a set, and `tests/test_static_registry.py`
holds each: three as text, and the Auto rule by a run of the function under node.

- With Auto orientation, a set takes the sheet whose shape is nearer the journey's
  (`setAutoIsLandscape` in `store.js`). Both sheets of a set are wider than tall, so
  the single-sheet rule cannot choose.
- A change of the set shape frames the journey afresh, as Reset frame does: one sheet
  to a set, a set to one sheet, two panels to three, a new gap. Orientation and the
  two single sizes re-fit the frame in place.
- A set hides the bleed control and sends no bleed. The proof call sends `panels` and
  `panel_gap` only for a set.
- A set stops the share kit, the film and the wall-art mockup with a message, before
  anything is submitted. A new place that submits a job must decide what a set does.

The final of a set downloads as one zip, and the library card of a panel file names
the set and the panel, for example "3 panels, 70×17 in" and "Panel 2 of 3".

`debug.js` reports the studio's state and errors to the engine for the `tecopa` tool.
Three rules hold for it, and `tests/test_static_registry.py` checks each as text. It
reads the store only as its eight fields. It has one `fetch`, to `/api/debug/studio`.
It writes nothing to the browser log. A new state key goes into `snapshot()` in
`debug.js` and into `STATE_KEYS` in `app/debug.py` in the same change. Never add a key
that holds journey data: tracks, markers, filenames, the crop or the title.

## Add a region to the farm and publish its relief images

The Tecopa pages are Ghost pages on www.plateworks.org since 2026-09-26. Their images
are engine renders under `assets/` (gitignored), exported for the web and uploaded to
Ghost by the blog folder's ghost-tecopa-pages script.

1. `.venv/bin/python scripts/render_asset_farm.py --regions <ids>` on real DEMs. The
   farm stamps the terrain it opened into `assets/index.json`.
   `elko_bonneville` needs its own run with `--dpi 250`: at the default 300 dpi its
   poster is 160 MP and the 120 MP output ceiling refuses it.
2. `.venv/bin/python scripts/export_relief.py <ids>` writes each region's web images to
   `assets/<region>/relief/`. It runs the terrain guard in `marketing/build_deploy.py`
   and refuses any region whose record is synthetic or missing. Never weaken the guard:
   a synthetic plate renders cleanly, so nothing else can tell.
3. Copy the images into the Ghost media folder, named `<region>-coin.webp`,
   `<region>-coin-h.png` and so on, as the script's header lists them.
4. Run the script on local Ghost, read the pages, then run it with `--live` and the
   live site. It uploads only new or changed files.
5. `.venv/bin/python -m pytest -m live tests/test_marketing_page.py`. A new region
   without a coin on the page turns `test_every_built_plate_is_on_the_page` red.

Tests: `tests/test_terrain_provenance.py`, `tests/test_asset_farm_gate.py`,
`tests/test_export_relief.py`. The Netlify landing retired on 2026-09-26 (tag
`landing-final-2026-09-26`); `marketing/DEPLOY.md` keeps the farm and the guard.

## Edit landing or privacy copy

Read `superpowers/specs/2026-08-16-target-customer-profile-design.md` first. Customer
copy answers to the Collector register, and `tests/test_marketing_page.py` enforces it:
`BUILDER_REGISTER` bans the builder's vocabulary and three customer anchors are pinned.

1. The copy lives in the blog folder's ghost-tecopa-pages script: `landing()`,
   `order()` and `privacy()`. Edit it there, not in Ghost Admin: a re-run replaces the
   page and backs up the old one.
2. Run the script on local Ghost and read the page. Then run it with `--live`.
3. Run the live tests: `.venv/bin/python -m pytest -m live tests/test_marketing_page.py`.
   They fetch the published pages. Keep every pinned phrase intact.
4. A change to what a page loads turns `test_privacy_page_names_every_host_the_pages_load`
   red until the privacy copy names the new host. Bump `PRIVACY_DATE` in the script
   whenever the privacy facts change.
5. Every marketing image is an engine render, and every claim has a test. A deleted
   test is a deleted claim. Plates are free, always. The name is always the full
   compound Tecopa Plateworks.

## Rebuild the macOS launcher

Only when the repo moves or the launcher itself changes. A `git pull` updates the app
with no rebuild, because it runs the engine from this repo's `.venv` on port 8848.

1. `scripts/macos/build_app.sh --install` builds `dist/` and copies the app to
   `/Applications`. Bundle id `guide.badwater.tecopa` is name-neutral. Keep it, or macOS
   treats the build as a new app and re-prompts.
2. `scripts/macos/smoke_test.sh` needs a human: it raises one-time Documents and
   Automation prompts, and port 8848 must be free. Logs are at
   `~/Library/Logs/TecopaPlateworks.log`.

Design: `superpowers/specs/2026-07-18-macos-launcher-app-design.md`.

## Build the tecopa tool

Only when the repo moves or the Swift code under `tools/tecopa/` changes.

1. `swift test --package-path tools/tecopa` must pass. It needs no engine.
2. `tools/tecopa/build.sh --install` builds the release binary and copies it to
   `~/.local/bin/tecopa`. It bakes this repo's path into the binary.
3. `tools/tecopa/smoke_test.sh` is the end-to-end check. Port 8848 must be free. The
   first quit from a new calling app raises a macOS Automation prompt. It renders two
   finals of the fixture track and compares their bytes. Its panel-set block then
   renders two finals of a two-panel set, 71 megapixels each, and compares the two
   zips. So it needs the real `lassen_ca` DEM and about ten minutes.
4. `tecopa doctor` checks the repo, both venvs, the launcher, the port and the log. Its
   `repo` row reads `app/main.py`, so it fails when macOS refuses the Documents folder.
   Run it first when the engine does not start.
5. To give Claude the tool, run `claude mcp add --scope user tecopa -- ~/.local/bin/tecopa mcp`.
   It registers the MCP server for every Claude Code session on this Mac.
6. The Claude desktop app reads its own file,
   `~/Library/Application Support/Claude/claude_desktop_config.json`. Quit the app, then
   run `tools/tecopa/register_desktop.sh` from Terminal, then start the app. The script
   adds `tecopa` under `mcpServers` and keeps a copy of the file. It refuses while the
   app runs: a running app writes its own copy of the file about once a minute, and that
   copy drops an entry added from outside.
7. The desktop app starts each server through its helper, so the binary answers for its
   own access to `~/Documents`. To test that access, run
   `/Applications/Claude.app/Contents/Helpers/disclaimer --pgroup -- ~/.local/bin/tecopa doctor`.
   The `repo` row must be `ok`. The binary is ad-hoc signed, so macOS can ask again
   after a rebuild.

Global options (`--json`, `--repo`, `--port`) go after the subcommand, for example
`tecopa doctor --json` and `tecopa regions verify lassen_ca --repo <path>`.
`tecopa engine start` waits up to 160 seconds. The launcher can wait 90 seconds on the
macOS Documents prompt and then 60 seconds for the engine to answer.
`tecopa engine stop` and `tecopa engine restart` refuse while a job is running or
queued, and `--force` overrides that.

A tracked run keeps its files under
`~/Library/Application Support/TecopaPlateworks/runs/`: the record, the log, the exit
code, and a marker if it was cancelled. The log has no size limit. No command deletes
them: remove old ones by hand when the folder grows. The record of an `order prepare`
or `order preview` run holds the order folder's name, and its log holds the report.
`order preview` is a tracked run, as `order prepare` is: it reads the network and takes
minutes. `order status` reads what Prepare wrote, not the preview's files.

The debug commands (`jobs`, `sessions`, `caches`, `studio state`, `studio errors`) need
`TECOPA_DEBUG=1` on the engine. The launcher sets it. For a development engine, set it
by hand. An engine that started before a debug route was added answers 404 for it, and
the tool reads that as a closed gate: run `tecopa engine restart` after a pull.

The render commands are `render proof`, `render final`, `render wallpaper`,
`render film` and `render fetch`, then `reprint`, `reprint inspect` and `continue`.

- `--set key=value` is one `/api/proof` form field: the picture. `--opt key=value` is
  one field of the output route: `format` and `embed_spec` for a final, the pacing
  fields for a film. The tool sends each value unchanged and has no default of its own.
- The tool refuses a field name that the engine does not have. It reads the names from
  `/api/debug/forms`, so a render with `--set`, `--spec` or `--opt` needs the gate. So
  does a change to a session, `render proof --session`, and a print size that is not
  the default.
- `--session <id>` renders a session that exists, for example the one open in the
  studio. A change to it starts from the session's own fields, so one `--set` keeps
  the rest of the look.
- `--out` is never overwritten. `--no-wait` returns the job id at once, and
  `render fetch --job <id> --out <path>` saves the result later.
- A path argument is absolute at the MCP level. The command line also takes a relative
  path and a leading `~`.
- A render result carries the engine's own warnings: journeys outside the plate,
  dropped points, skipped duplicates, and how far each wallpaper frame grew.
- A set of panels is written as one zip, with a file for each panel. Send the set's
  own fields, for example `--set panels=2 --set panel_gap=2 --set print_w=36 --set print_h=22`,
  and give `--out` a `.zip` name: the tool writes the reply's bytes unchanged and
  does not choose a name. `render fetch` does the same. `reprint` of one PNG panel
  file gives the whole set, as a zip.

Design: `superpowers/specs/2026-10-09-tecopa-cli-and-mcp-design.md`.

## Add a tecopa command

A command is one `CatalogEntry`. The CLI and the MCP server both read the catalog.

1. Write the operation in `tools/tecopa/Sources/TecopaKit/` as a `CatalogEntry`, and
   add it to `Catalog.all`. Set `readOnly` to false if it writes or controls anything.
   Give each argument an `EntryParameter`: `Catalog.call` refuses an argument that the
   entry does not declare.
2. Add a thin struct in `tools/tecopa/Sources/tecopa/Commands.swift` that calls
   `execute` with the entry's name. The command's words are the name with a space
   for each underscore.
3. A command that runs a Python script adds a row to `ScriptRunner.table` in the same
   change. The key is the script's path, or a module's name for `python -m`. The row
   names the venv. A script with no row does not run. `ScriptRunner.run` waits for the
   script. `ScriptRunner.start` starts it as a tracked run, for a script that reads the
   network or can take minutes.
4. Add the name to one of the two sets in `tools/tecopa/Tests/TecopaKitTests/MCPServerTests.swift`,
   `readOnly` or `writes`. The tools/list test in that file also pins the number of
   tools as a literal, so change that count too.
5. The tool holds no render logic, no coordinate math and no spec rule. It sends
   values to the engine unchanged and reports the engine's answer unchanged.

## Render a hero plate

Operator-only. Blender 4.2 LTS or newer is a separate install, found by `--blender`,
`TECOPA_BLENDER`, or `PATH`. `.venv/bin/python scripts/hero_plate.py poster.png --samples 128`
first to check the framing, then `--samples 512`. Minutes on Apple Silicon, hours on CPU.
Cycles is a sampler, so the output is not deterministic and carries the source manifest
unchanged.

`check_supported` in `scripts/hero_plate.py` refuses three shapes of poster, because hero
v1 renders the flat trim sheet only: a wallpaper spec, a spec with `bleed_in > 0`, and a
spec with `oblique > 0`. Re-export the poster without bleed rather than working around it.
It then re-asks `spec.validate` at the target dpi, before Cycles runs, so a rejected
`--dpi` does not cost hours. The remaining flags are `--z` (vertical exaggeration), `--dpi`, `--out`, and
`--allow-plate-mismatch`.

`tests/test_hero_plate.py` judges it. Assessment:
`superpowers/assessments/2026-08-10-blender-render-viability.md`.

## Record a decision or write a spec

- A durable choice gets a row in `decisions.md` with the date, the reason, and the
  commit or spec section that carries it. Never delete a row. Mark it superseded and
  add the new one under its own date. A Notion Decisions record gets a row here too.
- A new spec goes in `docs/superpowers/specs/` with an index row in `README.md` and,
  when it governs behavior, a row in the guide's "Read this before changing that" table.
- A handoff goes in `docs/superpowers/handoffs/` with an index row. Dated files there,
  and under `docs/superpowers/plans/`, `docs/superpowers/assessments/` and
  `docs/superpowers/quality/`, are history and are never edited. When you port UI copy
  out of one, substitute the current name.
- `tests/test_docs.py` runs `scripts/docs_check.py`. It fails when a doc is not indexed,
  a quoted path does not exist, or `../CLAUDE.md` outgrows its budget. Canon outside this
  repo is quoted as `00_Resources/<file>`.
- When Notion is unreachable, append the session to `../SESSION_LOG.md`, newest first,
  and say so in the closing summary.
