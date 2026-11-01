# DEM Stripe Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Plate elevation files carry no resampling stripes: new plates come out clean, and the six curated plates are rebuilt only after Dom approves the result.

**Architecture:** `region_prep.build_dem_cog` reads the static 3DEP layers natively instead of through `py3dep.get_dem`, and every warp onto the plate grid uses Lanczos. A detector script gives one repeatable stripe score. A rebuild script writes a candidate DEM on a plate's committed grid to a folder outside `regions/`, so Dom can compare before anything is swapped.

**Tech Stack:** Python 3.14, rasterio/GDAL, NumPy, SciPy, pytest. Builds run in `.venv-prep`.

**Spec:** No separate spec. The diagnosis below is the argument for this plan.

## Diagnosis (2026-11-01)

`py3dep.get_dem` calls `dem.rio.reproject(5070)` on the static layers with no resampling argument, so it uses nearest-neighbour. The build then warps that grid to UTM with bilinear. Both steps resample onto a rotated or differently spaced grid, and low-order resampling leaves periodic diagonal stripes.

Scores from the detector in Task 1. 12 or more counts as striped.

| Data | Score |
|---|---|
| Rifle–Aspen, native 3DEP 1/3 arc-second | 4.8 |
| Rifle–Aspen, `py3dep` output | 23–24 |
| Rifle–Aspen, native resampled to `py3dep`'s grid with nearest-neighbour | 25.5, same periods and angle as `py3dep` |
| Rifle–Aspen, today's chain, fresh fetch | 30 |
| Rifle–Aspen, native to UTM, bilinear | 37.5 |
| Rifle–Aspen, native to UTM, cubic | 16.9 |
| Rifle–Aspen, native to UTM, Lanczos | 6.0–6.4 |
| Elko, plate as built, worst window | 40.5 |
| Elko, native 1 arc-second | 4.1 |
| Elko, native to 30 m UTM, bilinear | 27.5 |
| Elko, native to 30 m UTM, Lanczos | 3.9 |
| 5 m dynamic grid, `py3dep` output | 7.1 |
| 5 m dynamic grid, warped bilinear to UTM | 57.4 |

Striped windows out of 36 on each plate: `lassen_ca` 31, `tecopa_ca` 30, `susanville_reno` 29, `rifle_aspen` 25, `tushar_beaver_ut` 25, `elko_bonneville` 11.

Lanczos through the dynamic path has not been measured. Task 3 measures it.

## Global Constraints

- Invariant 13: the region-prep stack runs in `.venv-prep` only. Never install it into `.venv`.
- Invariant 12: never re-stamp `sources.json`, and never re-run `write_sources_manifest` on a curated plate. A rebuilt DEM shows as DRIFT, and that record stays.
- Invariant 7: a rebuilt plate has a new `pack_version`. Reprinting an older poster answers 422 unless `allow_plate_mismatch=true`. Do not weaken this check.
- Invariant 11: never weaken the terrain guard. Published images must be re-rendered by the engine from real terrain.
- `region.json`, `hydro.json`, `labels.json`, `landcover.tif` and `playa.json` do not change. Only `dem.tif` changes.
- Dom's typed yes is required before Task 5 and before Task 6. A merge to plateworks-site is a deploy, so group it.
- TDD and present-tense commits. Run `.venv/bin/python -m pytest -n auto -m "not slow" -q` before any claim of done, and the full suite before a push to `main`.

## Review Focus

- **A hole, lake or border in the source:** nodata stays NaN, and Lanczos makes no spike beside it. Pinned in Task 2.
- **The seam between longitude slices:** a two-slice build matches a one-slice build. Pinned in Task 2.
- **A dropped connection during a native read:** it retries like `fetch_dem`, and a lasting error stops at once. Pinned in Task 2.
- **A summit above `elevation_max` after the rebuild:** Lanczos can overshoot a little, and `region.json` does not change. Rendering must not fail or show a band. Pinned in Task 4.
- **Reprinting an older poster after the swap:** the reply is the existing 422 naming the terrain change, and the override works. Checked on a real poster in Task 5.

---

### Task 1: The stripe detector

**Files:**
- Create: `scripts/stripe_check.py`
- Test: `tests/test_stripe_check.py`
- Modify: `docs/README.md` (list this plan)

**Interfaces:**
- Produces: `STRIPE_RED_SCORE = 12.0`, and `peaks(a: np.ndarray, dx: float, dy: float, n: int = 3) -> list[dict]`, where each dict has `score`, `period_m` and `angle_deg`, strongest first.
- Produces: the command `scripts/stripe_check.py <dem.tif> [xmin ymin xmax ymax]`, exit 1 when red.
- Produces: `scan(path: str, grid: int = 6, size: int = 400) -> dict` with `red`, `valid`, `median` and `worst`. It skips a window more than 1% NaN.

- [ ] **Step 1: Write the failing tests**

`test_natural_terrain_stays_green`: seeded sum of Gaussian-filtered noise at sigma 2, 5, 12 and 30, 600 × 600, 10 m cells. Assert `peaks(a, 10, 10)[0]["score"] < STRIPE_RED_SCORE`.

`test_stripes_go_red_with_their_period_and_angle`: the same field plus `0.5 * sin(2π(0.7x + 0.7y) * 10 / 40)`. Assert score at or above `STRIPE_RED_SCORE`, `period_m` within 2 of 40.4, and `angle_deg` within 2 of 45.

`test_a_mostly_nan_window_is_skipped`: `scan` on a tmp GeoTIFF that is all NaN returns `valid == 0`.

- [ ] **Step 2: Run them and watch them fail**

Run: `.venv/bin/python -m pytest tests/test_stripe_check.py -q`
Expected: FAIL, module not found.

- [ ] **Step 3: Implement `scripts/stripe_check.py`**

Method: fill NaN with the mean, subtract `gaussian_filter(a, 12)`, apply a Hann window, take the FFT magnitude, and divide by `median_filter(size=25, mode="nearest")`. Ignore periods over 300 m and keep one half-plane. Take the highest ratio, blank 13 × 13 cells around it, and repeat for `n` peaks.

- [ ] **Step 4: Run the tests and the real file**

Run: `.venv/bin/python -m pytest tests/test_stripe_check.py -q`
Expected: PASS.

Run: `.venv/bin/python scripts/stripe_check.py regions/rifle_aspen/dem.tif 340000 4330000 346000 4335000`
Expected: `RED`, top score about 31, exit 1.

- [ ] **Step 5: Add this plan to `docs/README.md`, then commit**

```bash
git add scripts/stripe_check.py tests/test_stripe_check.py docs/README.md docs/superpowers/plans/2026-11-01-dem-lanczos-resampling.md
git commit -m "Add a stripe detector for plate elevation files"
```

### Task 2: Read static layers natively and warp with Lanczos

**Files:**
- Modify: `region_prep.py` (`STATIC_LAYER_URLS`, `build_dem_cog`, `write_sources_manifest`, the header comment of `fetch_dem`, the Albers comment in `overview_png`)
- Test: `tests/test_region_prep.py`

**Interfaces:**
- Consumes: `stripe_check.peaks` and `STRIPE_RED_SCORE` from Task 1, in tests only.
- Produces: `DEM_WARP_RESAMPLING = Resampling.lanczos`.
- Produces: `read_static_native(bbox_4326, resolution_m, open_static=None) -> tuple[np.ndarray, Affine, CRS]`, a float32 array with nodata as NaN.
- Produces: `STATIC_LAYER_URLS` gains `60: .../2/TIFF/USGS_Seamless_DEM_2.vrt`. `fill_layer_m` stays 10 or 30.

- [ ] **Step 1: Write the failing tests**

Fixture `native_src`: a local GeoTIFF in EPSG:4269 with cells of 1/3 arc-second, seeded fractal terrain with relief like the mountains (a few hundred metres) and short-wave detail down to the cell size, passed through `open_static`. Use a bbox about 0.06° square.

`test_the_static_chain_control_goes_red`: warp the fixture to EPSG:5070 with nearest-neighbour, then to UTM with bilinear, using rasterio directly. Assert score at or above `STRIPE_RED_SCORE`. This proves the fixture can catch the bug. If it stays green, add short-wave detail to the fixture. Do not lower the threshold.

`test_build_dem_cog_static_grid_has_no_stripes`: `plan_build(bbox, GRID_CRS, 10)`, build with `open_static=native_src`, and assert the output's interior scores below `STRIPE_RED_SCORE`.

`test_build_dem_cog_static_never_calls_py3dep`: monkeypatch `fetch_dem` to raise, and the build still succeeds.

`test_two_slices_match_one_slice`: build the fixture with `plan["n_slices"]` 1 and 2. Assert the largest absolute difference is at most 0.05 m.

`test_native_read_keeps_nodata_as_nan_without_a_spike`: put a block of -999999 in the fixture. Assert those cells are NaN in the output, and that finite output cells stay within 5 m of the fixture's finite range.

`test_native_read_retries_a_dropped_connection` and `test_native_read_raises_a_lasting_error_at_once`: use `open_static` that raises `TimeoutError` once, and one that raises a RasterioIOError with "No such file or directory". Reuse the `waits` fixture.

`test_sources_manifest_names_the_native_read`: a static build's `via` is `rasterio, USGS_Seamless_DEM_13.vrt` and a dynamic build's stays `py3dep.get_dem`.

Change `test_static_layer_urls_are_the_ones_py3dep_reads` to include the 60 m URL. Change `test_build_dem_cog_leaves_a_static_grid_alone` to use a fixture with a hole and to monkeypatch `fill_dem_holes` to raise. It must still assert `fill is None` and that the hole stays NaN.

- [ ] **Step 2: Run them and watch them fail**

Run: `.venv/bin/python -m pytest tests/test_region_prep.py -q -k "static or slices or native"`
Expected: the control passes, and the new build tests FAIL.

- [ ] **Step 3: Implement `read_static_native`**

Open through `open_static or _open_static_layer` with `STATIC_LAYER_URLS[int(round(resolution_m))]`. Transform the bbox to the layer's CRS. Read a window padded by 4 source cells each side so the Lanczos kernel is never cut at a slice edge. Set values below `FILL_FLOOR_M` and the layer's nodata to NaN. Wrap the read in `with_retries(..., "3DEP")`.

- [ ] **Step 4: Change `build_dem_cog`**

When `_is_static(res)`, use `read_static_native`. Otherwise keep `fetch_dem`. Use `DEM_WARP_RESAMPLING` for the static warp. The dynamic warp changes in Task 3.

- [ ] **Step 5: Run the fast tier**

Run: `.venv/bin/python -m pytest -n auto -m "not slow" -q`
Expected: no new failures, compared by failure set.

- [ ] **Step 6: Commit**

```bash
git add region_prep.py tests/test_region_prep.py
git commit -m "Read static 3DEP natively and warp with Lanczos, so plates carry no stripes"
```

### Task 3: Lanczos on the dynamic path

**Files:**
- Modify: `region_prep.py` (`build_dem_cog`)
- Test: `tests/test_region_prep.py`
- Create: `scripts/stripe_probe_dynamic.py` (a real-data check, run by hand)

**Interfaces:**
- Consumes: `DEM_WARP_RESAMPLING` from Task 2.

- [ ] **Step 1: Write the failing test**

`test_build_dem_cog_warps_every_path_with_the_same_resampling`: spy on `region_prep`'s `reproject` during a dynamic build with `_FakeDA`. Assert the first call's `resampling` is `DEM_WARP_RESAMPLING`.

- [ ] **Step 2: Run it and watch it fail, then use `DEM_WARP_RESAMPLING` on the dynamic warp**

Run: `.venv/bin/python -m pytest tests/test_region_prep.py -q -k "same_resampling or fills_a_dynamic"`
Expected after the change: PASS. The hole-fill test still fills its hole.

- [ ] **Step 3: Measure on real data**

`scripts/stripe_probe_dynamic.py` fetches bbox `-106.8634 39.0953 -106.7693 39.1598` at 5 m through `fetch_dem`, warps it to EPSG:32613 at 5 m with `DEM_WARP_RESAMPLING`, and prints the `stripe_check.peaks` result.

Run: `.venv-prep/bin/python scripts/stripe_probe_dynamic.py`
Expected: top score below 12, where today's bilinear warp scores 57.4.

**If it stays at 12 or above:** stop and report it to Dom. The likely next step is to ask the service for a grid that is not close to the plate's cell, and that is a separate decision. Do not tune around it here.

- [ ] **Step 4: Commit**

```bash
git add region_prep.py tests/test_region_prep.py scripts/stripe_probe_dynamic.py
git commit -m "Warp dynamic grids with Lanczos: the bilinear warp was adding stripes"
```

### Task 4: Build a candidate DEM and compare it

**Files:**
- Create: `scripts/dem_candidate.py`
- Test: `tests/test_dem_candidate.py`
- Modify: `docs/changing-things.md` (Repair an orphaned DEM: name this script), `docs/decisions.md` (a 2026-11-01 section)

**Interfaces:**
- Consumes: `region_prep.plan_build`, `region_prep.build_dem_cog`, `stripe_check.scan`.
- Produces: `committed_plan(region_dir: str) -> tuple[bbox, crs, plan]`. It takes `fetch_bbox_4326` from `sources.json` and the grid from `region.json`, because a plate's committed grid may not match what `plan_build` gives today (`susanville_reno` is tagged as regridded).
- Produces: `compare(old_path: str, new_path: str, cfg: dict) -> dict` with `old_scan`, `new_scan`, `rms_m`, `mean_m`, `new_min`, `new_max`, `over_max_share`.
- Produces: the command `scripts/dem_candidate.py <id> --out <dir>`. It refuses an `--out` inside `regions/`.

- [ ] **Step 1: Write the failing tests**

`test_committed_plan_uses_the_grid_in_region_json`: a tmp plate whose `region.json` bounds differ from `plan_build`'s. Assert the plan's `grid` and `transform` match `region.json`, and that the geometry check would pass.

`test_candidate_refuses_to_write_into_regions`: assert exit non-zero and no file written.

`test_compare_reports_overshoot_above_elevation_max`: two tmp rasters, one with a cell above `cfg["elevation_max"]`. Assert `over_max_share > 0`.

`test_a_summit_above_elevation_max_renders`: use a synthetic plate whose DEM holds cells 2 m above `elevation_max`, render a proof, and assert it succeeds and that those cells' relief matches their neighbours within normal variation.

- [ ] **Step 2: Run them, watch them fail, implement `scripts/dem_candidate.py`, and run them again**

Run: `.venv/bin/python -m pytest tests/test_dem_candidate.py -q`
Expected after the code: PASS.

- [ ] **Step 3: Build Rifle–Aspen outside `regions/`**

Run: `.venv-prep/bin/python scripts/dem_candidate.py rifle_aspen --out cache/dem_candidates`

Expected on the candidate: at most 2 of 36 windows red, a median score below 8, `rms_m` under about 2, `mean_m` near 0, and `over_max_share` under 0.001.

- [ ] **Step 4: Make the comparison for Dom**

Render one 1:1 crop from the current plate and one from the candidate, with the same spec, at Capitol Peak and at the eastern test window. Show Dom the pairs.

- [ ] **Step 5: Record and commit**

Add the diagnosis table's conclusion to `docs/decisions.md`, and run `python3 scripts/docs_check.py --impact origin/main`.

```bash
git add scripts/dem_candidate.py tests/test_dem_candidate.py docs/changing-things.md docs/decisions.md
git commit -m "Build a candidate DEM on a plate's committed grid, outside regions/"
```

**Stop here. Tasks 5 and 6 wait for Dom's typed yes.**

### Task 5: Swap the six plates

**Files:**
- Modify: `.gitignore` (add `backups/`)
- Modify: `docs/changing-things.md` ("Four of the five plates carry this known drift" becomes all six, with the reason), `docs/decisions.md`
- Replace, untracked: `regions/<id>/dem.tif`
- Create, untracked: `backups/dem-before-lanczos-2026-11/<id>/dem.tif`

- [ ] **Step 1: Check what is in flight**

Run: `ls "$HOME/Tecopa Orders"`
Expected: no live order that depends on a curated plate. An order's own plate lives in its order folder and does not change. Stop and ask Dom about anything else.

- [ ] **Step 2: Check disk space and back up**

The six DEMs total about 1.5 GB, and the backup needs that much free. Copy each `dem.tif` to the backup folder and compare sha256. These backups are how an old poster gets an exact reprint.

- [ ] **Step 3: Build the remaining five candidates**

Run `scripts/dem_candidate.py` for `lassen_ca`, `susanville_reno`, `tushar_beaver_ut`, `tecopa_ca` and `elko_bonneville`. Hold each to the Task 4 limits. `elko_bonneville` runs for much longer and is 30 m, so measure it on its own grid.

- [ ] **Step 4: Swap one plate and verify it**

Move the candidate into place with a same-filesystem rename, starting with `rifle_aspen`.

Run: `.venv/bin/python scripts/verify_regions.py`
Expected: geometry `ok` and sha256 DRIFT for that plate. Do not re-stamp.

Render one proof. The base cache misses by itself, because `_plate_fingerprint` reads the file's mtime and size.

- [ ] **Step 5: Confirm the reprint reply on a real poster**

POST the old `assets/rifle_aspen/poster.png` to `/api/reprint`. Expected: 422 naming the terrain change. With `allow_plate_mismatch=true`, expected: a render.

- [ ] **Step 6: Swap the other five, run the full suite, and commit**

Run: `.venv/bin/python -m pytest -n auto -q`
Expected: no new failures, compared by failure set.

```bash
git add .gitignore docs/changing-things.md docs/decisions.md
git commit -m "Record the Lanczos rebuild of the six plates"
```

### Task 6: Re-render and republish the images

**Files:**
- Regenerate, untracked: `assets/<id>/*`, `assets/index.json`
- Modify in plateworks-site: the relief images and the film on the Tecopa pages

- [ ] **Step 1: Re-render**

Run: `.venv/bin/python scripts/render_asset_farm.py --regions elko_bonneville lassen_ca rifle_aspen susanville_reno tushar_beaver_ut`

Then run `scripts/export_relief.py` with the same ids. The terrain guard must pass without any change to it. `tecopa_ca` joins only if it is already in the farm's list.

- [ ] **Step 2: Compare, then show Dom**

Run the detector on `assets/rifle_aspen/poster.png`'s luminance at the Capitol crop, and show Dom the new close-ups beside the old ones.

- [ ] **Step 3: Publish on Dom's word**

Group the images into one plateworks-site merge, since a merge is a deploy. Follow "Add a region to the farm and publish its relief images" in `docs/changing-things.md`.

Run: `.venv/bin/python -m pytest -m live tests/test_marketing_page.py`
Expected: all pass.

## Out of scope

- Plates printed before this change. They stay as printed.
- Hole filling in `_read_static`. It keeps its own average or bilinear read, and it touches only hole cells on a dynamic grid. Its stripes are not measured.
- Rock drawing, the viewshed wash and snow.
