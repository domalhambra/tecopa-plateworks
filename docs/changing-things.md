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
For an order from the intake form, the preview email or a price, read
`superpowers/specs/2026-10-12-tecopa-client-intake-and-payment-design.md`.
`scripts/order.py` has four commands: `new`, `preview`, `prepare` and `finish`. Prepare
builds the plate and writes the client's proof. The studio's Order panel saves and
approves the proof. Finish writes the print TIFFs and the note that tells you how to
print them. The steps run in this order: `new`, `preview`, `prepare`, the proof, the
approval, `finish`, the printer.

1. Make the order folder under `~/Tecopa Orders/` (or `$TECOPA_ORDERS_DIR`). Never
   inside the repo: it is public. For an order from the intake, run
   `.venv/bin/python scripts/order.py new TP-26-001`, or `tecopa order new TP-26-001`.
   For an order by email, make the folder by hand and put the customer's GPX, KML or
   KMZ files in `in/`. `order new` does these steps:
   - It finds the job folder `TP-26-001 <name>` in `~/Dropbox/Apps/Plateworks Lab/Tecopa/`,
     the folder that Dropbox syncs to the Mac. `TECOPA_INTAKE_DIR` names another place.
     It reads Dropbox and never writes, moves or deletes there.
   - It copies each file of `<job>/01_received/` into `in/` of the order folder
     `TP-26-001-<name>`, and writes `order.toml` with `title`, `order_number`,
     `returning` and, when the intake has them, `client` and `email`, from
     `<job>/order.md`. It writes no size.
   - It prints what it copied: tracks, photos, and files of a type it does not know.
     It names each file it did not copy, and why.
   - Run it again when more files arrive. It copies only the new files, replaces no
     file in `in/`, and leaves `order.toml` alone. It finds the order folder by its
     number, also after a rename.
   - The files come from a stranger. Each name is cleaned (a letter, a digit, a space
     or `. _ - ( )`, and `_` for any other character). A link or a folder is never
     followed. A file over 200 MB is not copied. No file is opened: the engine reads
     the tracks later, as for any order. Each value of `<job>/order.md` is cleaned before it
     becomes the folder's name or a line of `order.toml`.
   - It stops before it copies anything when a file is not on the disk: Dropbox lists
     an online-only file with its size and no data. In Finder, right-click
     `01_received` and choose Make available offline, then run it again. A copy that is
     shorter than the size Dropbox lists is removed, and the run stops.
   - It stops when the `returning` of `<job>/order.md` is not yes or no, or its `order_id` is
     not the number asked for. It warns, and writes the title as it is, when the
     title is empty or longer than a map holds.
2. Write `order.toml`: `title` (required), `size` and `orientation` (`portrait`, the
   default, or `landscape`). `size` is `"11x17"` (the default), `"17x22"`, `"two"` or
   `"three"`. A single sheet has a short side of at most 17 in, the PRO-1100's width.
   `"two"` and `"three"` are a set of 17 × 22 in panels: `landscape` hangs them 22 in
   across, and `portrait` 17 in across. A set also takes `gap`: 0, 2 (the default) or
   4, the inches of wall between two panels. A gap of 0 is a cut set: every part of
   the map is printed. A gap of 2 or 4 is a window set: the map continues behind each
   gap strip, and the gap strip is not printed. A single sheet does not read `gap`.
   `order new` writes four more keys, and the reader checks each one: `order_number`
   (like `"TP-26-001"`), `returning` (`true` for a next-year order: the next-year
   prices and links), `client` (the name, at most 80 characters) and `email`. The
   reader ignores any other key, so a misspelled key is lost without a word. An order
   with photos also takes `band_side`: `"top"` (the default) or `"bottom"`, the end of
   the sheet the photo band takes when the order uses a band. The studio can change it.
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
     A plate whose maps need more than 60 m of ground for each pixel is built at 30 m
     from the static 3DEP tiles when its grid has at most 60 million cells: a route of
     up to about 125 km on its longer side. This build can take 5 minutes. A larger
     plate is built at its coarse grid from the dynamic service. The log line
     `Preview plate` gives the grid, its source and the reason.
   - It draws each offered size at screen size with the word PREVIEW, and writes
     `<folder>/out/preview/<title>-preview.pdf`, where `<title>` is the title as a
     slug. Page 1 shows every offered size on one wall at one scale. Then each size
     has a page with its name, its hung size and its price.
   - It writes `<folder>/out/preview/email.txt`, the email to the client: a line for
     each offered size and a last line for the digital poster, each with its price,
     its shipping and its Payment Link ending in `?client_reference_id=TP-26-001`, then
     the refund promise and, when a set is offered, the gap. A returning client gets
     the next-year prices and links, in the email and in the PDF. With no
     `order_number`, or with a link missing in `config/sizes.toml` for an offered size
     or the digital poster, it writes no email, removes an old one, and the report's
     `Email:` line says what is missing.
   - It writes `<folder>/work/preview/preview.json` (each size, its frame, its
     projection, and why a size is not offered), `<folder>/work/preview/report.txt`
     and `<folder>/work/preview/build.log`, and prints the report.
4. Read the preview's report and the PDF. An offered size has its price and the lines
   for `order.toml`, one key on each line. A set that is not offered has the reason,
   for example "not offered, the tracks span 24% of the sheet's width, under 30%". A
   size that the terrain data cannot hold at 2x, or that the engine cannot draw, is
   "not offered" with the engine's own reason, and the other sizes are still drawn.
   "Warning: a route end is behind gap 1" means that a window set hides the start or
   the end of a track: move the frame, use a gap of 0, or choose another size. Paste
   `<folder>/out/preview/email.txt` into a new email in HEY, attach the PDF, read it,
   and send it. Nothing sends it for you. The client pays with the link of a size:
   read the size from Stripe's email or from the order log's row. An order made by
   hand, with no `order_number`, gets the PDF alone, and the client answers by email.
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
   the nestled look at this size; the warning names the largest menu size below it
   that would hold the look. "No elevation" is the measured
   share of the plate and of the frame with no data. "Hole fill" means the dynamic
   service left holes and region_prep filled them from the static tiles. A warning
   that the plate has no elevation past what the 3DEP index expects means holes the
   fill did not close. `HOLES IN THE PRINT` leads the warnings when any are inside the
   frame: do not print; delete the plate under work/plate/ and run Prepare again.
   An order with photos also has a `Photos:` line and photo warnings. Read
   "An order's photos" below.
8. Read the proof lines of the report. Prepare writes the proof after the plate. The
   report then has a `Proof:` line that names `out/proof/<stem>-proof.jpg` and
   `.pdf`, and a `Soft proof:` line. `<stem>` is the title as a slug, or `poster` when
   the title has no letter or digit. The soft proof is `work/softproof.png`: the proof
   as the Red River paper would show it on an sRGB screen, through the paper's profile
   and intent. Open it and judge the paper's colour there.
   `Soft proof: skipped` and its reason mean the paper's profile is not installed in
   `/Library/ColorSync/Profiles/` on this Mac. The proof is still written. Install the
   profile and run Prepare again to get the soft proof. `PROOF NOT RENDERED:` with a
   reason is a warning, not a stop: the plate stays and no proof file is written. Fix
   the reason, then run Prepare again (it builds nothing) or use Save to order in the
   studio. Two warnings say that Prepare set the studio edits you saved aside:
   - "The order changed (size, orientation or tracks) since the studio save" means
     `order.toml` or `in/` changed after Save to order. The saved spec still holds the
     old size, frame and tracks.
   - "The plate's projection changed" means Prepare rebuilt the plate in another
     projection.
   Prepare keeps the edits in `state.json` as `manual.spec_set_aside`, removes the
   approval, and proofs the order as it is now. Open the order in the studio and make
   the edits again.
9. Open the order in the studio. Start the studio, find the Order panel in the
   inspector (it shows only when the engine lists an order) and choose the order in the Customer
   order list. Press Open. The studio loads the order's plate and its spec: the spec
   that Prepare proofed, or the one you saved last. Nothing is printed or approved yet.
10. Render a proof in the studio. Change the poster as for any proof, for example the
    title or the labels, and render again. The Order panel says "Edited since the last
    proof" until you render again.
11. Press Save to order. The studio writes the proofed spec into the order and writes
    the client's proof again from it: `out/proof/<stem>-proof.jpg` and
    `out/proof/<stem>-proof.pdf`. The PDF is one page marked PROOF, with the title,
    the map and two lines for the client. Both files show the print as it will print,
    with the word PROOF across it. A set shows its gap strips in the wall tone. Saving
    a spec that is not the approved one removes the approval. If the proof files
    cannot be written, the save still holds and the panel says why; the client files of
    the earlier save are removed, so a stale proof cannot go out. Fix the reason and
    save again. Save refuses a wallpaper proof, and a proof of another size, panel count
    or gap than the order: change the size in `order.toml` and run Prepare, never in
    the studio.
12. Send the proof. Reply in the client's existing HEY thread (do not start a new
    email), attach the JPG and the PDF, read the reply, and send it. Nothing sends it
    for you. The order is not
    approved yet: nothing prints before the client approves.
13. When the client approves, press Approve in the studio. Approve works on a proof
    that you saved in this studio session and have not changed since. If you closed the
    studio or the order, Open the order again, render a proof, press Save to order
    (the files come out the same if you changed nothing), then press Approve.
    Approve records the time and the hash of the saved spec in `state.json`. "The
    client proof was not written: save again before approving." means the last save
    could not write the client files: fix the reason, press Save to order, then
    Approve. If the
    client asks for a change, change the poster, press Save to order (this removes the
    approval), send the new proof, and approve after the client agrees.
14. Run `.venv/bin/python scripts/order.py finish "<folder>"`, or
    `tecopa order finish "<folder>"` as a tracked run. It runs in `.venv`, needs no
    network, and takes minutes. The command stops when it has nothing to print. The
    reason follows `finish stopped:`:
    - "Approve the proof in the studio first." The order has no approval. Do step 13.
    - "The order changed after approval: approve it again." The saved spec, the plate
      or `state.json` is not the approved one. Open the order, render a proof, save
      it, and press Approve again. Prepare also clears the approval when it builds a
      plate. A pull that adds a spec field changes the hash of every spec, so every
      approved order reads "changed after approval" after it. Approve each one again.
    - "The saved studio spec is not this order's size: open the order, proof, save
      and approve again." The size, panel count or gap in `state.json` is not the
      saved spec's. Do what it says.
    - "<n> photo(s) on the approved proof can no longer be read: open the order,
      attach them again, save and approve." Finish could not read a photo of the spec
      when it built the record. The studio keeps a photo that you attach there for 24
      hours: attach it again, save, send the new proof, and approve. For an order's
      own photo, run Prepare again, which writes a missing work JPEG, or drop the photo
      in the studio. Then save and approve again.
    - "<n> photos have no spot: place or drop them in the studio." A photo waits in the
      tray. Open the order, place or drop it, save and approve again.
    - "<n> photos cannot be read: drop them in the studio." A photo has a spot you gave
      it and no work JPEG, because Prepare could not read the file. Drop it in the
      studio, or replace the file in `in/` and run Prepare. Then save and approve again.
    - "<n> photos: the band holds 12. Drop some in the studio." Drop photos until 12 or
      fewer stay, then save and approve again.
    - "The reprint record cannot hold the photos within its 1 MB limit: drop some photos
      in the studio." A photo would have to shrink below 16 px to fit. Drop photos.
    - "The record could not be read back: ... Nothing was put in place; run Finish
      again." The staged record did not open with plain PIL. Run Finish again.
    - "Run Prepare first: work/state.json has no plate." Run Prepare.
    - A `config/papers.toml` message. The paper table is wrong or has no enabled row,
      or the piece has no side that fits the roll. Fix the file; the message names the
      row and the field.
    - "The render is ... a print with bleed cannot go to the roll as it is." The spec
      has a bleed, and an order prints without one. Remove the bleed from the spec,
      then save and approve again.
    - "The print file cannot be written to ...". Make room on the disk or fix the
      folder's permissions, then run it again.
    - "The print file of an earlier Finish cannot be removed: ...". Remove the file
      that it names, then run it again.
    Finish prints the spec that the client approved, once, at 300 ppi, with no
    watermark. It makes every check before the render. The approval checks come first.
    The next three read the photos in `state.json` alone, in this order: a photo in the
    tray, a photo that cannot be read, and a band over 12. Then it paints the print
    from the work JPEGs in the order folder, at full resolution. It builds the manifest
    of `work/record.png` apart, with each photo sized to keep the manifest under 900,000
    bytes, and reads the staged record back before any rename. Then it writes every file
    under a temporary name, renames them all, removes the print files of an earlier
    Finish, and writes `PRINT.txt` last. A run that fails before the renames deletes its
    temporary files, so it keeps the files of the last run.
15. Read `out/print/PRINT.txt`. It names the paper, the profile, the intent and the
    preset, and lists each file with its size in inches, its size in pixels and how it
    is fed. Finish writes these files:
    - `out/print/<stem>-<size>.tif` for a single sheet, or
      `out/print/<stem>-<size>-<k>of<n>.tif` for each panel of a set. Each TIFF is
      the print at exactly its size, 8-bit RGB, uncompressed, with the sRGB profile
      embedded. It has no border. The gap strips of a set are never printed.
    - `out/print/PRINT.txt`.
    - `work/record.png`, the render with the reprint record, for Edition N+1.
    Finish turns each piece so that its 17 in side goes across the roll. A piece 17 in
    wide prints as it is. A piece 17 in tall (an 11 × 17 portrait, a 22 × 17 panel)
    turns 90° counter-clockwise. The `Feed:` line of each file in `PRINT.txt` says
    which.
16. Print each TIFF at 100 %, centred, from Canon Professional Print & Layout. Choose the
    preset that `PRINT.txt` names, and confirm that Print & Layout uses the intent that
    `PRINT.txt` names. Print the panels of a set in hang order, panel 1
    first, and hang them left to right with the gap that `PRINT.txt` gives.

Finish removes every other `.tif` in `out/print/`. A print file of an earlier Finish
(another title, another size) must not stand beside the new print. Each removed file
gets a `Removed: <name>` line in the output of Finish and at the end of `PRINT.txt`.
Keep nothing by hand in `out/print/`.

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
- **The prices file.** `config/sizes.toml` holds each size's name, first-poster
  `price`, `next_price`, `shipping`, and its two Stripe Payment Links, `link` and
  `next_link`, and a row `digital` for the digital poster, which ships nothing and is
  never in the PDF. Dom owns it. A row has these fields and no other, and only `key`
  and `name` are required. A name, a price and shipping are text in quotes:
  `price = "$69"`, never `price = 69`. A name has at most 40 characters and a price at
  most 24. A link is `https://buy.stripe.com/` and the link's id, with no query: the
  email adds the order number. The file is UTF-8. A row with no price prints "Price on
  request". The preview reads the file before any query or build, and a wrong file
  stops it. `tests/test_sizes.py` holds each price that the live pages show to the
  prices that `tests/test_marketing_page.py` holds the pages to, and names the prices
  the pages do not show yet (the sets and shipping).
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
- A preview map is small, so its plate needs a coarse grid: 125 m for each pixel on a
  route of 120 km. `choose_grid` sends a need above 60 m to the dynamic service. On
  2026-10-11 that service answered "Service is currently not available" through all
  its retries, on two tries three hours apart, and the preview of the north-south
  route stopped each time. The static tiles did not fail. A preview plate with a need
  above 60 m is now built at 30 m from the static tiles when its grid has at most
  `PREVIEW_STATIC_MAX_CELLS` cells (60 million, a first value; `preview_grid` in
  `app/orderpreview.py`). The cell count is that of the grid the build makes, which is
  larger than the plate: 5 to 10 % in UTM and more than twice in Albers. The
  north-south plate has 53.6 million cells. For that grid `region_prep.py` plans a DEM
  file of about 214 MB, two slices, a peak of about 1.0 GB and land cover at 30 m, and
  the 30 m plate of the same route built in 286 s on 2026-09-24. The 120 m grid was a
  DEM file of 13 MB. A plate above the limit still needs the dynamic service: a route
  of more than about 125 km on its longer side, and every Albers plate. When that
  service is down, such a preview stops. Run it again later. A plate that the 30 m
  layer does not cover keeps its coarse grid too. Prepare is not changed.
- A preview plate for a route of many hundred km used to stop before the build, in
  the query of the 3DEP index: "more footprints than one query returns". The service
  cuts an answer by transfer size, not by count, so `_index_features` in
  `region_prep.py` now asks in pages (`INDEX_PAGE_SIZE`, ordered by OBJECTID) and joins
  them. It stops, with an error, past `INDEX_MAX_PAGES` pages or on an empty page that
  claims more. It never returns part of the list.

Tests: `tests/test_orderplate.py`, `tests/test_order.py`, `tests/test_orderprep.py`
(stub subprocesses, no network), `tests/test_dem_coverage.py`. For `order new`:
`tests/test_ordernew.py` (hostile names and a hostile order.md, a sparse file for the size limit
and for a file not on the disk). For the preview:
`tests/test_orderpreview.py` (stub subprocesses, no network), `tests/test_previewpdf.py`,
`tests/test_sizes.py`, `tests/test_orderemail.py`, and `tests/test_orderpreview_render.py`
(slow: the real painter on a synthetic plate). For the proof, the paper table and Finish:
`tests/test_papers.py`, `tests/test_orderspec.py`, `tests/test_orderproof.py`,
`tests/test_softproof.py`, `tests/test_order_routes.py` (Open, Save, Approve),
`tests/test_orderfinish.py`, and `tests/test_orderprep.py` for the proof lines of the report.
For the photos: `tests/test_photos.py`, `tests/test_photospot.py`,
`tests/test_photocaption.py`, `tests/test_photolayout.py`, `tests/test_photo_band.py`,
`tests/test_photo_spec.py`, `tests/test_orderprep_photos.py`, and the photo cases of
`tests/test_orderspec.py`, `tests/test_order_routes.py` and `tests/test_orderfinish.py`.

### An order's photos

Read `superpowers/plans/2026-10-24-order-photos.md` before you change them. Its planning
decisions B1 to B9 are in `docs/decisions.md`, 2026-10-24 (order photos).

A photo is a marker with a photo. It is a hotspot with the optional keys `box`, `crop`
and `source`. `docs/MANIFEST.md` has the fields.

How photos get on the map:

1. Put the customer's photos in `in/`. `order new` copies them there with the tracks.
   Prepare picks up files that end in `.jpg`, `.jpeg`, `.png`, `.heic`, `.heif`, `.tif`,
   `.tiff`, `.webp`, `.gif` or `.dng`, in file-name order. It never writes to `in/`.
2. Run Prepare. It writes an upright JPEG of each photo to `work/photos/<file>.jpg`, where
   `<file>` is the whole file name (`IMG_1.heic.jpg`), at most 4,000 px on the long side. A photo with an embedded profile other than sRGB
   (an iPhone photo is Display P3) is converted to sRGB, so it does not print dull.
3. Read the `Photos:` line of the report. It counts the photos placed by GPS, by time
   and by hand, those in the tray, and those dropped, and names the layout.
4. Read the photo warnings. Most name the photo. The band, layout and moved-box warnings
   cover all the photos.

Prepare finds a photo's spot in this order:

- **GPS.** The photo's EXIF position, taken from lon/lat to the plate's CRS through
  `app/geo.py`. A GPS spot is used as it is, even outside the frame.
- **Time.** The photo's `DateTimeOriginal` against the tracks' times. It needs the
  photo's `OffsetTimeOriginal`: without the offset the time is not used, even if it
  looks right. A time inside a track's first-to-last time has no limit: the spot is
  interpolated between the two surviving track points around it. A time outside every
  track's span is placed at the nearest track end only when it is within 10 minutes of
  it. Otherwise the photo gets no spot.
- **The tray.** A photo with neither waits there. You place it in the studio.

The caption starts as the name of the nearest place in the plate's `labels.json` within
2,000 m of the spot. It is empty when none is near. You can write your own.

The box is a square cut from the middle of the photo. Its side is 2.25 in on a 12 × 18
sheet and scales with the sheet's area: 2.09 in on 11 × 17 and 2.96 in on 17 × 22. On a
set it follows one panel. `crop` moves the cut away from the middle.

The layout has two forms. They never mix on one poster.

- **Open ground.** Each box sits beside its spot with one straight leader. A box keeps
  clear of the routes, the furniture, the other boxes and the other leaders. Open
  ground takes 8 photos at most.
- **The band.** A row of numbered boxes across the top or the bottom of the map, with
  the captions under them and a numbered mark at each spot. It takes over when more
  than 8 photos are placed, when a photo has no clear spot, or when the layout fails
  (the report says why). It holds 12 photos at most. The title, compass and credit
  take the other end of the sheet.

A plate for an order with photos is planned around a frame grown by the band's height at
both ends, so it holds either layout. That is about 5 times the area on a landscape
11 × 17, so Prepare takes longer for an order with photos. When the band is used,
Prepare grows the frame toward the band's end by the band's height, so the tracks keep
their share of the map.

The layout is computed on the crop that prints: the studio's live crop in the studio, the
saved spec's crop in Prepare. A reframe followed by a proof lays out again the boxes you
have not moved. A box you moved never moves.

The studio's photo controls:

1. Open the order and render a proof. The Order panel lists every photo with its spot's
   source (GPS, Time, By hand, Tray, Dropped or Unreadable).
2. To place a tray photo, press Place, then click the proof where it was taken. Press
   Move spot to do the same for a placed photo. Esc cancels. Place needs a fresh proof.
3. To move a box, drag its outline on the proof, or focus it and press the arrow keys.
   An arrow moves it 0.1 in, Shift 0.5 in. Auto box puts a moved box back.
4. To frame a photo, move its Across and Down sliders. They move the cut of the square.
5. To caption a photo, type in its Caption field. It holds 60 characters.
6. To leave a photo off the poster, press Drop. Press Restore to bring it back.
7. To move the band, press Top or Bottom in Photo band. It shows when the layout is the
   band.
8. Render the proof again. Save to order, send the proof, and approve.

The marker list shows an order's photo as locked. Edit it in the Order panel.

Every photo edit goes to `POST /api/order/photo`. It clears the approval and the proof,
and the studio renders a proof again. A drop onto a route, the furniture or another box is
kept and warned: the box stays where you put it. Your edits live in `work/state.json`
under `manual.photos` and `manual.band_side`, never in the saved spec. A field you edited
wins over Prepare's, and Prepare run again keeps it. When you save the spec, the
photo fields (`hotspots`, `photo_layout`, `photo_band_side`, `photo_box_in`) are set
again from this state, so a photo edit always reaches the proof, the approval and the
print.

The photo warnings:

- "its spot is outside the frame." Widen the frame or drop the photo.
- "<w>×<h> px is small for a <box> in box at 300 ppi." The photo is under 300 ppi at its
  box. Ask the client for a larger file, or accept it.
- "Photo <file> is behind gap <k>." The spot is under a gap strip of a window set.
- "<n> photos: the band holds 12." Drop photos in the studio.
- "its box is over a route / the poster's furniture / <file>'s box / <file>'s spot / a
  seam between panels. It stays where you put it."
- "its box runs past the sheet's edge, so the poster pulls it inside."
- "The moved boxes leave no open ground for the other photos, so all of them hang in the
  band."
- "The photos could not be laid out in open ground (...): they hang in the band."
- "the photo could not be read (...)": the photo stays in the tray. Replace it in `in/`
  or drop it.
- "its place or time could not be read (...)": place it in the studio.
- "its caption could not be found (...)": write one in the studio.

Finish refuses a photo order in three cases before any render: a photo in the tray, a
photo with a spot and no work JPEG, and more than 12 photos placed. The steps of Finish
above give the words.

The print is painted from the work JPEGs in the order folder at full resolution, so its
sharpness does not depend on the record. The manifest of `work/record.png` holds each
photo as an embedded JPEG. PIL refuses a PNG whose manifest passes 1 MiB, so the whole
manifest is held to 900,000 bytes, and each photo gets an equal share of what the rest
leaves. A square-cut photo is embedded with its short side at the box side times the
print's ppi, capped by the source and the pixel guard. If that is too big for its share,
the JPEG quality goes down (82, 72, 62, 52), then the size shrinks by 15 % a step. A photo
whose short side would fall below 16 px stops Finish. Finish reads the staged record back before any
rename. When a photo went below the print's resolution, `PRINT.txt` says "record.png
carries reduced photos (the 1 MB record limit); reprint from this order folder for full
resolution." There is no fitted-copy fallback.

Known limits:

- The box outlines and the layout ignore High relief (oblique) displacement. The order
  look has oblique 0.
- On a panel set, the studio holds a box outline inside the sheet, not inside the panel.
  The renderer keeps the box in its panel.
- A reframe made without a proof is lost when an edit flips the layout or moves the
  band's end. Render a proof after each reframe.

### The test sheet

The first print on the roll settles two things the code cannot: the rendering intent
and whether a print needs a border. Run it once, before the first order for a client.

1. Make an order folder of your own tracks, as for any order (step 1 and 2), with a
   title like "Test sheet". Use `size = "17x22"`.
2. Prepare it. Save to order in the studio, press Approve, and run Finish. These are
   steps 6 to 14. The order is yours, so the "client" is you.
3. Print the TIFF twice from Canon Professional Print & Layout on the Red River
   Premium Matte 230 roll, at 100 %, centred, with the preset that `PRINT.txt` names.
   Print the first copy with `intent = "perceptual"` in `config/papers.toml`. Change the
   line to `intent = "relative"`, run Finish again (the note names the new intent), and
   print the second copy. Use the intent that the note names in Print & Layout.
4. Put the two prints side by side in the light you will hang them in. Choose the one
   with the better shadows and the cleaner colour.
5. Set `intent` in `config/papers.toml` to the winner. Add a row to `docs/decisions.md`
   with the date, the intent that won, and why.
6. Look at the edge of the print. If the keyline sits too close to the trim, or the
   edge needs a white margin, the poster needs a border: record that in
   `docs/decisions.md` (it settles plan decision P5) and plan the border as a separate
   change. Until then Finish writes the print at exactly its size, with no border.

The test sheet is an order, not a feature: no code makes it.

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
   `photo_layout` and `photo_band_side` change the overlay only, so both sit in
   `BASE_KEY_MASK_ALWAYS` and `INK_KEY_MASK_ALWAYS`. `tests/test_photo_spec.py` judges
   them and the hotspot keys `box`, `crop` and `source`.

## Change a panel set

Read `superpowers/specs/2026-10-11-print-sizes-panel-sets-and-size-preview-design.md`
first. A set is two or three panels of 17 × 22 in that hang side by side as one map.
It is one `CompositionSpec` with `panels` (2 or 3) and `panel_gap_in` (0, 2 or 4). The
sheet in the spec is the hung size, gaps included. `rasterize` paints that sheet once,
gap strips included, and the cut drops the gap strips.

1. Panel geometry: edit `app/panels.py` first. The engine asks only it where a panel,
   a gap strip or a seam is: the cut, the wall tone of a proof, the label keep-out and
   the furniture. It imports nothing from `app`. Four places hold their own copy of
   the same arithmetic, because they run before a spec exists or in the browser.
   Change them with it: `print_in` in `app/order.py`; `candidates`,
   `panels_with_track` and `gaps_hiding_ends` in `app/orderpreview.py`; the sheet
   size in `app/static/compose.js` and `app/static/store.js`; the gap strips in
   `app/static/canvas.js`. The copies agree today for each count, gap and orientation.
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
   `/usr/bin/time -l .venv/bin/python scripts/measure_final.py`. It needs the real
   `rifle_aspen` DEM. Judge the line "peak memory footprint", which is in bytes. Do
   not judge the script's own `pass`: it reads resident memory, and that is too low
   on macOS. Run it three times, because the number moves from run to run.

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
- Resident memory is the wrong measure on macOS. The first gate read 14.07 and
  15.29 GB for the largest sheet, and its peak memory footprint was 22.8 GB. After the
  trim of the relief the footprint of that sheet is 14.5 to 16.5 GB (10^9 bytes),
  against a limit of 16: under it in units of 2^30 bytes, and at it in units of 10^9.
  A two-panel set is 10.8 GB and a 17 × 22 in sheet is 5.4 GB. The numbers and Dom's
  decision to accept them are in the plan `superpowers/plans/2026-10-11-panel-sets-and-size-preview.md`,
  "Open before a merge", item 2.
- The label and the photo box of a marker behind a gap are still printed, at the edge
  of the nearest panel, and the marker is not. Two tests hold this. An order has no
  markers yet.

Tests: `tests/test_panels.py` and `tests/test_panel_furniture.py` are fast.
`tests/test_panel_render.py` is slow: it paints sets at 40 dpi. `tests/test_panel_api.py`
is fast except one test,
`test_a_real_final_of_a_set_is_a_zip_job_and_any_panel_reprints_it`: it renders a
71 megapixel final twice, one after the other, and needs about 11 GB. Keep it the
only such test in the suite: two of them can run side by side on two workers.
`tests/test_poster_furniture.py` holds the furniture scale by number, and
`tests/test_static_registry.py` holds the studio's set rules as text.

## Change the manifest or add a file-consuming verb

`MANIFEST.md` is the format doc, internal since 2026-07-27. The CC0 dedication stands
for the versions published before then and cannot be revoked, but the document is no
longer a contract for outside implementers. `provenance.spec_from_manifest` is the one
untrusted-manifest door: parse, drop non-embedded photos, bound geometry, validate,
then bound the photo keys (`provenance.bound_photo_keys`: a hotspot's `box`, `crop` and
`source`; a malformed key is dropped from its hotspot, never an error). Every
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

The Tecopa pages are pages on www.plateworks.org since 2026-09-26, held in
plateworks-site since the 2026-10-13 switch. Their images are engine renders under
`assets/` (gitignored), exported for the web. Steps 3 and 4 below are the Ghost-era
publish path (the blog folder's ghost-tecopa-pages script, retired with Ghost on
2026-10-15): the renders now go into plateworks-site with the pages.

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

1. The copy lived in the blog folder's ghost-tecopa-pages script: `landing()`,
   `order()` and `privacy()`. Since the 2026-10-13 switch it lives in plateworks-site
   (its src/content/pages folder): edit it there. The script steps below are the retired
   Ghost-era path (Ghost retired 2026-10-15).
2. Run the script on local Ghost and read the page. Then run it with `--live`. (Retired: see step 1.)
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
them: remove old ones by hand when the folder grows. The record of an `order prepare`,
`order preview` or `order finish` run holds the order folder's name, and its log holds
the report. `order preview` is a tracked run, as `order prepare` is: it reads the network
and takes minutes. `order finish` is a tracked run too: it takes minutes and reads no
network. `order new` runs in the call and returns its report: it copies files and
reads no network. `order status` reads what Prepare wrote, not the preview's files.

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
