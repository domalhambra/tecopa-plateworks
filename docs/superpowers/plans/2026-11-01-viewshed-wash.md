# The Viewshed Wash Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An option, off by default, that quiets the ground a poster's real marks cannot see, at any map size, in the studio and in an order that asks for it.

**Architecture:** Three stages, each mergeable alone. Stage 1 teaches the engine which hotspots are real marks. Stage 2 adds a pure line-of-sight module, a coarse seen-ground mask computed in `render` from the plate, and a `finish`-stage relief pass that reads it. Stage 3 carries waypoints into orders behind an `order.toml` key.

**Tech Stack:** Python 3.14, NumPy, SciPy, rasterio, FastAPI. Browser ES modules in the studio, with no JS test runner.

**Spec:** `docs/superpowers/specs/2026-11-01-viewshed-wash-design.md`. Its decision numbers are cited below.

## Global Constraints

- Default off: `viewshed` defaults to 0.0, and at 0.0 the pass never runs and no pixel moves.
- A new spec field reaches every manifest, because `serialize.spec_to_json` emits every field. So "unchanged" means unchanged pixels, and an equal spec hash for equal specs within one build. A hash from an older build differs, as with any new field (invariant 7).
- Size in ground metres, never pixels (invariant 2). The mask's grid is a pure function of the spec and plate, so proof and final agree (invariants 1 and 3).
- `_relief_extras(spec)` and the `shaded_relief` call stay as they are when the option is off.
- A relief pass never reads plate data (rule 4 of `docs/relief-passes.md`). `render` reads the plate.
- No mark is ever dropped silently.
- Any untrusted-manifest change goes through `provenance.bound_geometry` (invariant 8).
- `.venv` only; the region-prep stack stays out (invariant 13).
- Each pull request ends with its `Docs:` line. Nothing here changes a price or a promise until the landing page offers the wash, so each says why Business Plan v2 does not change.

## Review Focus

- **The same file uploaded twice:** each waypoint stays one mark. Pinned in Task 1.
- **Adding a track to a session:** no waypoint moves, and its label never jumps to a density spot. Pinned in Task 1.
- **A file with more than `MAX_WAYPOINTS` waypoints:** the reply says how many were left out. Pinned in Task 1.
- **A sightline over NaN ground (ocean, Canada, a plate hole):** the render does not fail, and NaN neither blocks nor counts as seen. Pinned in Task 3.
- **A crafted file declaring 1,000 marks on one spot, or all off the plate:** the work stays inside its budget, and the wash paints or skips without failing. Pinned in Task 4.

---

## Stage 1: Real marks

### Task 1: Which hotspots are marks, and keeping them

**Files:**
- Create: `app/marks.py`
- Modify: `app/ingest.py` (`_waypoint_hotspot`, `MAX_WAYPOINTS`, `load_waypoints`), `app/main.py` (`_merge_waypoints`, `_carry_annotations`, the upload reply)
- Test: `tests/test_marks.py`, `tests/test_ingest.py`

**Interfaces:**
- Produces: `is_mark(hs: dict) -> bool`, true for `mark: true`, a truthy `photo`, or a non-empty `label` (decision 16).
- Produces: `observers(hotspots: list) -> list[tuple[float, float]]`, the finite `(x, y)` of each mark, in order, with duplicates kept.
- Produces: `load_waypoints` still returns a list. New `waypoints_over_cap(data, region, filename) -> int`, or an equivalent that lets the upload report the count left out. The builder picks the shape.

- [ ] **Step 1: Write the failing tests**

`test_a_waypoint_is_a_mark`, `test_an_unnamed_density_spot_is_not`, `test_naming_a_density_spot_makes_it_a_mark`, `test_an_old_manifests_named_spot_counts`.

`test_a_waypoint_near_a_density_spot_replaces_it`: density at (0, 0), waypoint at (300, 0). Result has one spot, the waypoint, with `mark` true.

`test_two_waypoints_300_m_apart_both_stay`.

`test_the_same_waypoint_twice_is_one_mark`: two waypoints within 1 m. One stays.

`test_a_density_spot_carrying_a_photo_is_not_replaced`: a waypoint within 400 m of a spot with a photo. Both stay.

`test_adding_a_track_does_not_move_a_waypoint`: `_carry_annotations` with an old `mark: true` spot within `ANNOTATION_CARRY_M` of a new density spot. The old spot stays at its own `x, y`, and the density spot takes no label.

`test_over_the_waypoint_cap_is_counted`: a GPX with 1,005 waypoints. 1,000 load, and the count left out is 5.

- [ ] **Step 2: Run them and watch them fail**

Run: `.venv/bin/python -m pytest tests/test_marks.py tests/test_ingest.py -q`
Expected: FAIL, `app.marks` not found.

- [ ] **Step 3: Implement**

Set `mark: true` in `_waypoint_hotspot`. Raise `MAX_WAYPOINTS` to 1000. In `_merge_waypoints`, drop a density spot within `WAYPOINT_DEDUP_M` of a waypoint unless `is_mark` holds for it, and collapse waypoints within 1 m. In `_carry_annotations`, append an old `mark: true` spot unchanged. Add the left-out count to the upload reply as `waypoints_left_out`, and show it through the existing upload toast in the studio.

- [ ] **Step 4: Run the fast tier, compare by failure set, and commit**

Run: `.venv/bin/python -m pytest -n auto -m "not slow" -q`
Expected: no new failures. An existing test that pinned the old 400 m drop changes to the new rule, and that change is listed in the commit.

```bash
git add app/marks.py app/ingest.py app/main.py app/static tests
git commit -m "Keep every real mark: a waypoint is never dropped for a density spot"
```

### Task 2: Raise the mark cap

**Files:**
- Modify: `app/provenance.py` (`MAX_MANIFEST_HOTSPOTS`)
- Test: `tests/test_editions.py`

- [ ] **Step 1: Write the failing test**

`test_a_manifest_of_1000_hotspots_is_accepted`: `bound_geometry` passes 1,000 and raises `SpecError` at 1,001. The existing cap test keeps using the constant.

- [ ] **Step 2: Watch it fail, set `MAX_MANIFEST_HOTSPOTS = 1000`, and run**

Run: `.venv/bin/python -m pytest tests/test_editions.py tests/test_provenance.py -q`
Expected: PASS.

- [ ] **Step 3: Measure the drawing, then commit**

Render a Rifle–Aspen proof with 1,000 marks, wash off, labels on, and print the time beside a run with 7 marks. Record it in this plan's Build record. If it adds over 30 s, stop and report to Dom before raising the cap further: label placement is the suspect, and that fix is not in this plan.

```bash
git add app/provenance.py tests/test_editions.py docs/superpowers/plans/2026-11-01-viewshed-wash.md
git commit -m "Raise the mark cap to 1,000: 64 would stop a real collector"
```

## Stage 2: The wash

### Task 3: The line-of-sight module

**Files:**
- Create: `app/viewshed.py`
- Test: `tests/test_viewshed.py`

**Interfaces:**
- Produces: `EYE_M = 1.7`, `EARTH_R_M = 6_371_000.0`, `REFRACTION = 0.87`, `GRID_BUDGET_CELLS = 4_000_000`, `SAMPLE_BUDGET = <the builder's measured value>`.
- Produces: `grid_res_m(width_m: float, height_m: float, native_m: float) -> float`: the plate's area over `GRID_BUDGET_CELLS`, as a cell size, and never below `native_m`.
- Produces: `seen_mask(dem: np.ndarray, res_m: float, cells: list[tuple[float, float]]) -> np.ndarray`: bool, the union over observers at float `(col, row)`. NaN ground neither blocks nor counts as seen.

- [ ] **Step 1: Write the failing tests**

`test_a_ridge_blocks_the_view`: flat ground, a 200 m ridge, an observer on one side. Ground behind the ridge is False, and the ridge face is True.

`test_a_flat_plain_is_a_round_5_km`: flat grid at 30 m. The seen area's radius is between 4 and 6.5 km in the four cardinal and the four diagonal directions, within 10% of each other. This also pins the bilinear rule of decision 6.

`test_a_high_summit_sees_past_100_km`: a 4,300 m cone on a flat 500 km grid at 500 m. Some ground beyond 100 km is True.

`test_a_ray_stops_when_the_curve_hides_the_highest_ground`: instrument or assert through a sample count on a flat plate: samples stay under 5% of a ray to the plate's edge.

`test_nan_ground_neither_blocks_nor_counts`, `test_a_mark_in_a_hole_uses_the_nearest_finite_ground`, `test_the_result_is_deterministic`.

`test_the_budget_holds_at_1000_marks`: 1,000 observers on a 2,000 × 2,000 grid finish under 45 s, and marked slow if over 5 s. `test_more_marks_never_lose_ground`: the mask with one more mark is a superset of the mask without it, at 10 and at 500 marks.

- [ ] **Step 2: Run them and watch them fail**

Run: `.venv/bin/python -m pytest tests/test_viewshed.py -q`
Expected: FAIL, module not found.

- [ ] **Step 3: Implement `seen_mask` and `grid_res_m`**

A radial sweep: running maximum of `(z - drop(d) - z0) / d`, with `drop(d) = REFRACTION * d² / (2 * EARTH_R_M)`, sampled with bilinear interpolation. Sample spacing grows with distance. A ray ends when `plate_max - drop(d)` cannot beat the running maximum. Spread `SAMPLE_BUDGET` across marks, so more marks means fewer rays per mark and never a dropped mark. That rule is what can break the superset test, so union each mark's rays with a minimum ray count high enough to hold it.

- [ ] **Step 4: Run them, and commit**

Run: `.venv/bin/python -m pytest tests/test_viewshed.py -q`
Expected: PASS.

```bash
git add app/viewshed.py tests/test_viewshed.py
git commit -m "Add line of sight over a plate, with the curve of the earth and no fixed range"
```

### Task 4: The spec field, the mask and the pass

**Files:**
- Modify: `app/spec.py` (`viewshed: float = 0.0`, `STYLE_BOUNDS`), `app/render.py` (`BASE_KEY_MASK_ALWAYS` handling in `base_cache_key`, the `shaded_relief` call site, new `_seen_field`), `app/looks.py` (the pass), `docs/relief-passes.md`, `docs/architecture.md`
- Test: `tests/test_viewshed_render.py`, `tests/test_base_cache.py`, `tests/test_render_memory.py`

**Interfaces:**
- Consumes: `marks.observers`, `viewshed.seen_mask`, `viewshed.grid_res_m`.
- Produces: `render._seen_field(spec, region_dir, cfg, window_bounds) -> SeenField | None`, `None` when `spec.viewshed <= 0` or there are no marks. `SeenField` holds the coarse float32 mask, already feathered, its transform and the window's bounds. An in-process LRU keyed on `_plate_fingerprint`, the observers and the grid holds masks, so a toggle does no sweep.
- Produces: `frame.extras["viewshed"]` (the strength) and `frame.extras["seen"]` (`SeenField`), the latter added only at the call site when the field is not `None`.

- [ ] **Step 1: Write the failing tests**

`test_off_is_a_strict_no_op`: the same spec at 0.0, with and without the pass registered, gives identical bytes, as `tests/test_looks.py` does.

`test_no_marks_paints_as_off`: `viewshed=1.0` with only unnamed density spots gives the same pixels as 0.0.

`test_a_ridge_off_the_sheet_still_blocks`: a synthetic plate and a crop that excludes the ridge. The ground behind it is quieted.

`test_a_mark_off_the_sheet_still_washes`, `test_a_mark_off_the_plate_is_ignored_and_does_not_fail`.

`test_proof_and_final_agree_on_seen_ground`: the mask is the same object for both dpis, and the proof-versus-final MAD is within the bound of `test_proof_relief_is_a_faithful_scale_of_final`.

`test_unseen_ground_falls_at_most_15_percent`: at 1.0, on a mid-grey sheet. `test_water_keeps_its_colour`: a hydro polygon on unseen ground has the same RGB on and off. `test_a_seen_edge_feathers_over_about_100_m`.

`test_a_crafted_file_stays_in_budget`: 1,000 marks on one spot paint within the budget test's time.

In `tests/test_base_cache.py`: `test_moving_a_mark_misses_when_the_wash_is_on`, `test_changing_a_label_hits_when_the_wash_is_on`, `test_moving_a_mark_hits_when_the_wash_is_off`, `test_toggling_back_does_no_new_sweep`.

- [ ] **Step 2: Run them and watch them fail**

Run: `.venv/bin/python -m pytest tests/test_viewshed_render.py tests/test_base_cache.py -q`
Expected: the new tests FAIL.

- [ ] **Step 3: Implement**

`STYLE_BOUNDS["viewshed"] = (0.0, 1.0)`. In `base_cache_key`, when `spec.viewshed > 0`, add the observers' coordinates to the payload after the mask pops `hotspots`. `_seen_field` reads the plate at `grid_res_m` with `Resampling.average`. Decision 7 sets the look: unseen ground loses saturation and falls in value by up to 15% at 1.0, on a feather of about 100 ground metres. Register the pass at `finish`, gated on the field. Sample the coarse mask to the sheet in `relief._bands`, per `docs/relief-passes.md`, Memory.

- [ ] **Step 4: Update the memory table if it moved**

Run: `.venv/bin/python -m tests.test_render_memory`
Then paste the new row in `docs/relief-passes.md` in this commit, with the reason.

- [ ] **Step 5: Run the fast tier, and commit**

Run: `.venv/bin/python -m pytest -n auto -m "not slow" -q`
Expected: no new failures.

```bash
git add app/spec.py app/render.py app/looks.py docs/relief-passes.md docs/architecture.md tests
git commit -m "Quiet the ground a poster's marks cannot see, as an option that is off by default"
```

### Task 5: The studio toggle

**Files:**
- Modify: `app/main.py` (the proof route's `Form` and spec dict), `app/static/api.js`, `app/static/controls.js`, `app/static/compose.js`, `app/static/presets.js`, `app/static/store.js`

- [ ] **Step 1: Write the failing test**

`test_a_proof_takes_the_viewshed_form_field` in the panel API tests: a POST with `viewshed=0.6` reaches the spec, and an omitted field gives 0.0. `tests/test_static_registry.py` holds the control's range equal to `STYLE_BOUNDS`, if it already covers controls.

- [ ] **Step 2: Implement the route, then the controls**

`store.js` default 0, so a new poster starts off. Unlike `softLight`, this default is off for new posters too. Two `CONTROLS` entries in the Terrain panel: an on/off toggle, and a strength slider at 0.6 shown when it is on. Follow "Add a spec knob or studio control" in `docs/changing-things.md`. Help text, in the profile's register: "Quiets the ground you couldn't see from your marks. Calculated from the land alone, with no trees."

- [ ] **Step 3: Check it**

Run `node --check` on each changed module, and match every `$('id')` to the HTML. Then drive the browser: load Rifle–Aspen with waypoints, turn it on, turn it off, and turn it on again. Expected: the last flip returns without a fresh relief pass.

- [ ] **Step 4: Commit**

```bash
git add app/main.py app/static tests
git commit -m "Add the viewshed toggle to the studio, off by default"
```

## Stage 3: Orders

### Task 6: Waypoints in an order that asks for the wash

**Files:**
- Modify: `app/order.py` (`Order.viewshed`, `parse_viewshed`), `app/orderprep.py` (Prepare reads waypoints into state), `app/orderspec.py` (`default_spec`, `order_spec`), `app/orderpreview.py` (`render_maps`), `app/orderemail.py` or the preview template, `docs/changing-things.md` (Run an order)
- Test: `tests/test_order.py`, `tests/test_orderspec.py`, `tests/test_orderprep.py`, `tests/test_orderpreview_render.py`

**Interfaces:**
- Consumes: `ingest.load_waypoints`, `marks.is_mark`.
- Produces: `Order.viewshed: float`, parsed from `order.toml`'s `viewshed`, either `true` (0.6) or a number from 0 to 1. Absent gives 0.0.
- Produces: `state["waypoints"]`, a list of hotspot dicts in the plate's CRS.
- Produces: `orderspec.waypoint_hotspots(order, state) -> list`, empty when `order.viewshed` is 0.

- [ ] **Step 1: Write the failing tests**

`test_viewshed_key_parses`, including a refusal of `"yes"` with the key named.

`test_an_order_without_the_key_is_unchanged`: `default_spec` and `order_spec` give the same `hotspots` and the same pixels as an order folder with no waypoints, with its GPX holding waypoints.

`test_an_order_with_the_key_carries_its_waypoints`: hotspots hold the waypoints ahead of the photos, and `viewshed` is set. `test_the_approval_covers_the_waypoints`: changing a waypoint in state changes `spec_hash`.

`test_prepare_stops_over_1000_marks`: Prepare raises and names the count, and writes no proof. `test_a_saved_studio_spec_keeps_its_waypoints`: RB1's replace in `order_spec` keeps plain hotspots as it does today.

`test_preview_shows_both_with_the_key`: `render_maps` writes `<key>.png` and `<key>-wash.png`, and the entry records both. `test_preview_shows_one_without_the_key`.

- [ ] **Step 2: Run them and watch them fail**

Run: `.venv/bin/python -m pytest tests/test_order.py tests/test_orderspec.py tests/test_orderprep.py tests/test_orderpreview_render.py -q`
Expected: the new tests FAIL.

- [ ] **Step 3: Implement**

Read waypoints in the same Prepare step that reads tracks, only when `order.viewshed > 0`. `render_maps` makes the second image with waypoints and `viewshed` set, on the preview plate. The preview email and page show the two side by side when both exist. Update "Run an order" with the key, and with how Dom sets it from a customer's reply.

- [ ] **Step 4: Run the fast tier, and commit**

Run: `.venv/bin/python -m pytest -n auto -m "not slow" -q`
Expected: no new failures.

```bash
git add app docs/changing-things.md tests
git commit -m "Carry waypoints into an order that asks for the wash, and preview both"
```

### Task 7: Measure, and let Dom judge

**Files:**
- Modify: this plan (Build record), `docs/decisions.md`

- [ ] **Step 1: Time it**

Time a proof on Rifle–Aspen and on `elko_bonneville`, with the wash off and on, at 64 and at 1,000 marks. Expected: under 30 s added at 64 and under 60 s at 1,000, with Elko about equal to Rifle–Aspen. If a target is missed, report the numbers. Do not lower the mark count (the design, "Many marks").

- [ ] **Step 2: Render real proofs for Dom**

Rifle–Aspen with summit marks, and one plate with marks low in valleys, each with and without the wash. Send the pairs. These are for judging and are not landing page images.

- [ ] **Step 3: Record it, run the full suite, and open the pull request**

Run: `.venv/bin/python -m pytest -n auto -q`
Expected: no failures.

Record the strength Dom settles on in `docs/decisions.md`.

## Build record

2026-11-01, Task 2 (the mark cap): `MAX_MANIFEST_HOTSPOTS` is 1,000. `bound_geometry` passes 1,000 hotspots and refuses 1,001 (`test_a_manifest_of_1000_hotspots_is_accepted`).

- Record size: 1,000 realistic waypoint hotspots (label, icon, `mark: true`) add 93,843 bytes to the manifest (2,077 B with none, 95,920 B with 1,000). That is about 94 KB of the 900,000 B record budget, as decision 14 says. The record builds, fits and reads back.
- Proof time, Rifle-Aspen (`rifle_aspen`), 9 x 12 in at the proof's 96 dpi, labels on, wash off, marks scattered with a fixed seed inside the plate, one warm-up render first: 7 marks 0.43 s and 0.45 s; 1,000 marks 1.14 s and 1.09 s. The 1,000 marks add about 0.7 s, far under the 30 s limit. At 300 dpi (final): 7 marks 3.7 s, 1,000 marks 4.3 s.
- Drawing at that count: 1,000 marks over one 9 x 12 sheet draw every marker and label, and the labels pile onto each other. Nothing is dropped, and nothing separates them. The speed target holds; whether the sheet reads at that count is a design question, not a time one.
- The script is not in the repo (session scratchpad, `measure_marks.py`).
