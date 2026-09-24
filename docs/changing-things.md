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
3. `build_dem_cog` does not write `sources.json`. Run `scripts/verify_regions.py` again
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

Traps already paid for:

- `region_prep.py` sets `SSL_CERT_FILE` from `certifi` before importing py3dep and
  pynhd, because aiohttp captures SSL config at import. It fetches hydro before the DEM.
  Keep both orderings when adding network code.
- py3dep returns EPSG:5070 in metres, not 4326. `plan_build` sizes the job before any
  fetch so a corridor-scale bbox cannot exhaust memory (the 15.8 GB lesson).
- Region data is read by the render from the region folder. It never rides on the spec.
- For out-of-plate test coordinates use Virginia, about -79.5, 37.8. `elko_bonneville`
  is corridor-scale and swallows most western points that look outside.
- `ready: True` does not mean real terrain. Check the `synthetic` tag, not the flag.

Tests: `tests/test_region_prep.py` (the pure planner, so it runs in `.venv` and in CI),
`tests/test_hydro.py` (skips without `geopandas`), `tests/test_regionbuild.py`,
`tests/test_region_endpoints.py`.

## Run an order

Read `superpowers/specs/2026-09-24-order-pipeline-design.md` first. Sub-project 1 ships
Prepare's plate step only.

1. Make the order folder under `~/Tecopa Orders/` (or `$TECOPA_ORDERS_DIR`). Never
   inside the repo: it is public. Put the customer's GPX, KML or KMZ files in `in/`.
2. Write `order.toml`: `title` (required), `size` such as `"12x18"` (short side at most
   17 in, the PRO-1100's width), `orientation` (`portrait` or `landscape`).
3. Run `.venv/bin/python scripts/order.py prepare "<folder>"`. It needs `.venv-prep`.
   `TECOPA_PREP_PYTHON` overrides which prep interpreter it calls.
4. Read the report. "Upsampling" above 1.00x means the terrain data is coarser than the
   print can show, up to the 2x limit. A widened frame means the data could not hold
   the nestled look at this size; the warning names it, but naming the exact smaller
   sheet waits for the paper table (sub-project 2).

Running Prepare again with the same tracks, size and orientation builds nothing. A
changed input, or a new manual frame in `state.json`'s `manual` key, rebuilds the plate.
`in/` is never written. The plate lives in `work/plate/<id>/`. The HyRiver request
cache is `~/Tecopa Orders/_cache/`. It holds NHD, NLCD and dynamic-service requests,
and it grows large: 880 MB after a handful of orders. Delete it any time. The static
10, 30 and 60 m tiles are read by GDAL and are not cached.

Traps already paid for:

- The 3DEP dynamic service fills a missing fine layer with resampled coarse data and
  says nothing. `scripts/dem_coverage.py` measures each layer first. Tecopa has 1 m
  lidar and no 3 m data.
- An order passes an explicit grid, fetched at that cell size. `DEM_RES_CHOICES` is
  only the in-app auto planner's list, so adding 1 m there would make small in-app
  plates enormous. Never fetch a finer layer and average it onto a coarser grid in
  slices: that design was built and removed (see `docs/decisions.md`, 2026-09-24).
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

Tests: `tests/test_orderplate.py`, `tests/test_order.py`, `tests/test_orderprep.py`
(stub subprocesses, no network), `tests/test_dem_coverage.py`.

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

## Change the manifest or add a file-consuming verb

`MANIFEST.md` is the format doc, internal since 2026-07-27. The CC0 dedication stands
for the versions published before then and cannot be revoked, but the document is no
longer a contract for outside implementers. `provenance.spec_from_manifest` is the one
untrusted-manifest door: parse, drop non-embedded photos, bound geometry, validate. Every
new verb that turns an uploaded file into a spec goes through it. `/api/reprint/inspect`
is the deliberate exception: it reads manifest fields only, and builds no spec.
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

## Add a region to the farm and deploy the landing page

The runbook is `../marketing/DEPLOY.md`. The page deploys by hand from a staged root,
never from git, because its images are engine renders under `assets/` (gitignored).

1. `.venv/bin/python scripts/render_asset_farm.py --regions <ids>` on real DEMs. The
   farm stamps the terrain it opened into `assets/index.json`.
   `elko_bonneville` needs its own run with `--dpi 250`: at the default 300 dpi its
   poster is 160 MP and the 120 MP output ceiling refuses it.
2. `python3 marketing/build_deploy.py` writes the staged root. The terrain guard refuses
   any published region whose record is synthetic or missing. Never weaken it: a
   synthetic plate renders cleanly, so nothing else can tell. The guard does carry an
   `--allow-synthetic` override, and `../marketing/DEPLOY.md` says not to reach for it.
   Re-render the plate from real terrain instead.
3. `netlify deploy --prod --dir=<staged root> --site=1902a58d-74a9-4def-8b4e-d93793f81ac4`
   with `NETLIFY_AUTH_TOKEN` exported.
4. Verify: `curl -sI https://tecopa.plateworks.org` and `/privacy/` both answer 200,
   and every `/assets/...` reference in the deployed page answers 200.

Tests: `tests/test_terrain_provenance.py`, `tests/test_asset_farm_gate.py`. The Mac's
local netlify.toml, under its gitignored .netlify folder, still names `Badwater Trails`
as the publish path. It is machine state, not a repo file, and the deploy passes `--dir`.

## Edit landing or privacy copy

Read `superpowers/specs/2026-08-16-target-customer-profile-design.md` first. Customer
copy answers to the Collector register, and `tests/test_marketing_page.py` enforces it:
`BUILDER_REGISTER` bans the builder's vocabulary and four customer anchors are pinned.

1. Edit `marketing/landing.html` or `marketing/privacy.html`.
2. Keep every pinned phrase on one line. The tests match literal substrings against the
   raw file, so a wrap inside an anchor makes it unsatisfiable.
3. Count `2.6` with `grep -cF`. The bare dot matches `236px` in the CSS.
4. A landing-page change turns `test_privacy_page_describes_what_the_landing_page_actually_does`
   red until the privacy copy follows. The `Last updated YYYY-MM-DD.` line is only checked
   for its shape, so bump its date by hand.
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
