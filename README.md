# Tecopa Printworks

A single local app that turns your GPX tracks into a **self-archiving chronicle of a
life outdoors**: a shaded-relief poster of where you've been within one curated
region, performed as a print, a wallpaper, or a time-lapse film — every file carrying
everything needed to reproduce it, continue it, and hand it to the future. No
account, no database, no cloud: the artifact is the archive, and the poster on your
wall is the save file. One FastAPI process serves a thin browser aim view and the
render engine; all real rendering happens server-side in Python.

The scope rests on three pillars (see `docs/scope.md` for the full statement and the
engineering commitments behind it):

1. **One score, many performances** — the composition is decided once in ground
   coordinates, then performed at any size (print), any pixel density (wallpaper),
   and along its own time axis (film).
2. **The file is the whole record** — the picture, the geometry, the source hashes,
   and the memories pinned to it all travel inside the PNG.
3. **The record is alive** — last year's poster plus this year's GPX renders the next
   edition (`POST /api/continue`), lineage carried in the file itself.

The engine is split at one seam: **compose** decides the picture once in ground
coordinates and emits a `CompositionSpec`; **rasterize** paints that spec at any
resolution. The proof and the final are the same spec painted at two pixel sizes.

## Setup

```
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-lock.txt        # pinned core + test stack (what CI installs)
python -c "import rasterio, pyproj, numpy, scipy, shapely, gpxpy, PIL; print('ok')"
```

- `requirements.txt` — core runtime (unpinned minimums); `requirements-dev.txt` adds the
  test deps; `requirements-lock.txt` is the exact pinned set (determinism / CI).
- `requirements-regionprep.txt` — the heavy offline build stack for `region_prep.py`
  (py3dep/pynhd/pandas/geopandas). Only needed to build a new region.
- To **build new regions from the app** (drop tracks anywhere in the US and the wizard
  offers to fetch the terrain — see "GPX-first" below), create the separate prep venv
  once: `python3 -m venv .venv-prep && .venv-prep/bin/pip install -r
  requirements-regionprep.txt`. Without it the app still works against already-built
  plates and shows the setup command on the build card; oversized (corridor-scale)
  areas are refused in-app and remain a deliberate `region_prep.py` terminal run.

On Apple Silicon, rasterio / pyproj / Pillow ship native wheels — no Homebrew GDAL
required.

## macOS app (Tecopa Printworks.app)

Build a double-clickable launcher that starts the engine and opens the UI:

```
scripts/macos/build_app.sh --install     # builds dist/ and copies to /Applications
```

Double-click **Tecopa Printworks** in `/Applications`: the engine starts from this repo's
`.venv` on port 8848 and the UI opens in your default browser. Quit the app (Cmd-Q)
to stop the engine; relaunching while it's already running just reopens the tab. The
app runs the engine *from this repo*, so `git pull` updates it with no rebuild —
rebuild only if you move the repo folder or change the launcher itself. Engine output
logs to `~/Library/Logs/TecopaPrintworks.log`.

**First launch:** because the project lives under `~/Documents`, macOS shows a
one-time *"Tecopa Printworks would like to access files in your Documents folder"* prompt —
click **Allow** (the engine can't read the code, `.venv`, or map data without it). The
grant persists across rebuilds. Note that the rebrand to Tecopa Printworks changed the
app's bundle id, and macOS treats a new bundle id as a new app — the first launch after
the rename shows the Documents permission prompt once more. If you miss the prompt, the app shows a "needs
permission" alert; grant access under System Settings → Privacy & Security → Files and
Folders (or Full Disk Access) and relaunch.

Verify end-to-end with `scripts/macos/smoke_test.sh` (needs port 8848 free; the first
run also raises the one-time Documents prompt and an Automation prompt on quit — allow
both once).

## Layout

- `app/geo.py` — every coordinate conversion (overview px ↔ CRS meters ↔ windows)
- `app/ingest.py` — GPX → reproject → simplify → clean projected polylines
- `app/density.py` — visitation-weighted hotspots (count distinct tracks, not points)
- `app/spec.py` — the `CompositionSpec` contract + zoom-cap validation
- `app/relief.py` — pure-numpy relief passes (hillshade, hypsometric, texture, valley, grain)
- `app/render.py` — read DEM window, paint relief + tracks + markers in physical units
- `app/provenance.py` — the self-describing-poster manifest (embed / extract / sanitize)
- `app/wallpaper.py` — device presets + `spec_for_preset` (a screen is a sheet with a known ppi)
- `app/main.py` — the endpoints over the engine (upload, proof, final, reprint, region plan/build)
- `app/regionbuild.py` — GPX-first region creation: bbox/UTM/US-coverage planning + the `region_prep` subprocess orchestration behind `POST /api/regions/build`
- `app/plates.py` — stdlib plate installer/verifier (`python -m app.plates install|verify`)
- `region_prep.py` — offline: fetch 3DEP DEM, build COG + overview + region.json. Runnable from the terminal, and spawned in `.venv-prep` by the in-app build (see GPX-first below)
- `scripts/build_labels.py` — offline: fetch GNIS terrain names → `regions/<id>/labels.json`
- `scripts/pack_region.py` — offline: pack a built region into a deterministic `.trailplate.zip`

## GPX-first: the region is an outcome, not a first step

You drop GPX/KML/KMZ tracks first; the region is decided from them. If a built plate
covers the tracks, the upload auto-matches it (a "Matched · <region>" chip). If none
does — the common case for fresh client tracks — a **build card** appears:
`POST /api/regions/plan` derives a padded bbox and UTM zone from the raw track extent,
runs `region_prep.plan_build` (pure logic — no fetch stack) for an honest cost estimate
(resolution, grid, download size), and prefills a region name from the GPX `<name>`.
Accepting it calls `POST /api/regions/build`, which spawns `region_prep.py` in
`.venv-prep` on a dedicated single-slot job queue, streams its progress, builds GNIS
labels, and hot-reloads the region registry — then your tracks re-upload against the new
plate ("Built · <region>"). Tracks outside USGS 3DEP coverage (US-only) and
corridor-scale areas are refused honestly in-app; `app/regionbuild.py` holds the
planning helpers and the subprocess orchestration.

## Named geography (GNIS labels)

The `Place names` toggle draws named geography on the sheet: terrain features (ranges,
summits, passes, valleys, desert flats) from `regions/<id>/labels.json` — built offline
by `scripts/build_labels.py` from the USGS GNIS Landforms service — plus the water names
already carried in `hydro.json`. `render._draw_labels` places them with priority +
greedy collision avoidance (range → summit → lake → pass → valley → river), a knockout
paper halo for legibility, and a per-sheet density cap. Ranges/deserts read as wide
tracked caps; everything else is a haloed point label. All sizes are physical, so the
proof and final place the same names (invariant 1). Rebuild after adding a region:
`python scripts/build_labels.py <id>`.

## Self-describing posters ("the file is the artwork")

Every PNG final embeds a provenance manifest in one compressed `zTXt` chunk (see
`app/provenance.py`): the full `CompositionSpec`, the sha256 of each source GPX, the
engine name, and the manifest schema version. (No engine *version* rides the file —
byte-identical reprints across upgrades rest entirely on the additive-defaults
discipline: every new spec/animation key is omitted at its pre-feature default, for
encoders as much as the painter.) That makes the file **stateless-reprintable** —
`POST /api/reprint` re-renders any Tecopa Printworks PNG at print resolution from the file
alone (no session, no DB), and `POST /api/reprint/inspect` reads its provenance
without rendering. Same spec → pixel-identical reprint (invariants 1 + 3).

- **Privacy:** the manifest carries the exact track coordinates. The proof step's
  *Reprintable file* toggle (form field `embed_spec`, default on) turns it off to
  produce a share copy with no embedded spec. PDF finals never carry the manifest
  (Pillow's PDF writer has no metadata seam) — self-describing posters are PNG-only.
- **Security:** a reprint spec is untrusted input. `provenance.sanitize_photos` keeps
  a hotspot photo only if its real path stays inside the uploads dir (else drops it),
  and `spec.validate` re-enforces aspect / the 120 MP ceiling / the zoom cap before any
  pixels are made — a crafted PNG can neither read server files nor request a gigapixel.
- **Forever-contract:** `tests/fixtures/manifest_v1.json` freezes the v1 schema; a
  poster a user printed today must still reprint after future upgrades.

## Reprint forever, honestly

"Reprint it in 2035" is a mechanism, not a slogan. The chain, link by link:

1. **The file names its terrain.** The manifest's `region_pack` block records the
   plate's identity by content hash — which assets, which bytes — so a rebuilt plate
   can never silently repaint an old poster differently.
2. **Plates are artifacts, not a laptop's state.** `scripts/pack_region.py` packs a
   built region into a deterministic `<id>-<hash>.trailplate.zip` (pack twice →
   byte-identical), and `python -m app.plates install` fetches, hash-verifies every
   asset, and atomically places it under `regions/`; `python -m app.plates verify`
   checks a poster PNG against the installed plate.
3. **The right to run is granted, not assumed.** The engine is AGPL-3.0-or-later; the
   manifest schema is documented in `docs/MANIFEST.md` under CC0-1.0, so anyone may
   implement a reader or renderer without touching AGPL code.
4. **The claim is tested, not asserted.** The orphan drill
   (`tests/test_orphan_drill.py`) packs a plate, installs it into a *fresh, empty*
   regions root, and reprints a golden poster **byte-identically** — and it runs in CI
   on every push to `main` and every pull request (against a synthetic-DEM plate
   packed at test time). No machinery gates a tag on it yet, so the release ritual
   below runs the drill by hand, against the real plates, before anything ships.

Release ritual, in two lines: pack the real-DEM plates (`scripts/pack_region.py`),
publish the zips as release assets and commit `plates/index.json`; then run the orphan
drill against a fresh clone before announcing anything.

**Fonts:** the cartouche tries Georgia from the host system but the repo/package never
bundles `Georgia.ttf` (proprietary face); `TECOPA_FONT` is the seam for a licensed
face, and a packaged build ships a redistributable SIL-OFL serif as its default.

## Wallpapers ("a screen is a sheet with a known ppi")

The Frame step's `Output: Print | Wallpaper` control renders the same composition as a
pixel-native screen deliverable. A wallpaper is a print whose sheet size is derived
from the device (`print_w_in = px / ppi`) and whose **final dpi is the device's ppi**
(`spec.final_dpi()`), so `pixel_size()` returns the device's exact native pixels
(3840×2160, 1179×2556, …) and every engine invariant — physical units, the zoom cap,
determinism, provenance/reprint — carries over unchanged. A 2.6 pt track is literally
2.6 pt on the client's glass.

- Wallpapers render **clean**: no keyline, compass, or cartouche (`spec.keyline` off,
  empty title). Place names / contours / biome still apply; phone and tablet presets
  keep auto-placed labels out of the lock-screen clock band (`spec.top_clear_frac`).
- **PNG-only** — the sRGB profile and the reprint manifest embed as usual; PDF is
  refused with an honest 422 (it's the print-shop path and can't carry the manifest).
- The device table lives in `app/wallpaper.py`, served by `GET /api/wallpapers/presets`
  — the wizard never hardcodes device sizes. A device the table doesn't carry renders
  through the **Custom** option (`wallpaper_preset=custom` + exact `custom_px_w` /
  `custom_px_h` / `custom_ppi`), so the exact-native-pixels promise doesn't decay
  with the device cycle.
- **Social share canvases** ride the same machinery as `device_class: "social"`
  presets — Reel/Story 9:16 (1080×1920), feed 4:5 and 1:1 — so stills *and* films can
  target the frames platforms actually display, at a deliberate effective ppi
  (`SOCIAL_PPI`) that sets stroke weight for feed viewing. `bottom_clear_frac` (the
  clock band's bottom twin) keeps auto labels out of the home-indicator / caption zone.
- **Bundle:** once a proof is accepted, `POST /api/wallpapers/submit` re-targets the
  composition at each requested device (center-preserving crop re-fit per aspect via
  `geo.refit_crop_aspect`) and renders them all into one zip through the job queue.
  A device the region can't satisfy is skipped and reported, never silently dropped.
- `tests/fixtures/manifest_wallpaper_v1.json` freezes the wallpaper manifest contract,
  as `manifest_v1.json` does for prints.

## Journey Light ("lit by the same sun that lit your hike")

Turn a recorded track's timestamps into the poster's light. In **journey** mode the real
solar position — computed (NOAA/Meeus, `app/solar.py`, no new dependency) from the GPX
times and the journey's location — drives the terrain's ray-marched cast shadows and a
warm/cool golden-hour grade; the archival NW form-shading stays for legibility. The
default moment is *summit light* (the sun as it stood at your high point); a time-of-day
scrubber overrides it. The resolved sun rides the spec (never the timestamps), so reprint
and continue reproduce the light byte-for-byte. Using the whole GPX also unlocks **named
waypoint pins**, a DEM-sampled **elevation profile**, and **elevation/grade track
coloring** (all reprint-safe). And the film learns a new motion: `light_motion` on
`/api/timelapse/submit` renders a **Journey Light film** — a WebP/MP4 share twin where the
line grows *time-true* (the pen breathing with the real hike) while the sun travels with
it. Every knob defaults to the archival look, so existing posters render byte-identically.

## Invariants

1. One spec, painted at many sizes — never compute the picture twice.
2. Physical units (points / inches), never pixels, for anything visual.
3. Determinism — fixed seed on the spec; same spec → same image.
4. One projection throughout — DEM, overview, tracks, crop all in the region CRS.
5. Registration is correctness — prove the coordinate chain before tuning aesthetics.
6. The zoom cap — never request finer ground detail than the data holds.

## Tests

```
pytest -q
```

The real 3DEP DEMs are gitignored, so `tests/conftest.py` hydrates a tiny synthetic DEM
per region on first run — the endpoint / render / registration suites run on a fresh
clone and in CI (GitHub Actions, `.github/workflows/ci.yml`) rather than skipping. A
machine with real DEMs runs them against real terrain instead. `/readyz` reports whether
every region has a present DEM whose bounds match its `region.json`.

## License

- **Code:** GNU AGPL-3.0-or-later (see `LICENSE`) — anyone may run, study, fix, and
  re-host the engine, which is what makes "your file reprints itself" a promise the
  artifact can keep rather than a slogan.
- **Region plates + manifest schema:** CC0-1.0 public-domain dedication — the packs are
  derived from U.S. federal public-domain data (USGS 3DEP / NHD / NLCD 2021 / GNIS).
- **Name & branding:** "Tecopa Printworks" is covered by neither grant.

Rationale and the full decision record: `docs/superpowers/plans/2026-07-12-strategy-and-license.md`.
