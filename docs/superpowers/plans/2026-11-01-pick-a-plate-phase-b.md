# Pick-a-plate landing, Phase B: plates, journeys, renders and ship, implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every poster the full customer look, build the five showcase plates with trail-first demo trips, render every image the stories need, and ship the page.

**Architecture:** `marketing/stories.toml` drives everything. A small loader (`scripts/story_config.py`) gives the farm, the router and the exporter one view of it. A plate with no table keeps today's journeys. The page branch from Phase A receives the images in place of its `data-slot` blocks.

**Tech Stack:** Python 3.14, pytest, the render engine, Overpass cache, WebP via Pillow (tecopa-plateworks). Astro, Vitest (plateworks-site).

**Spec:** `docs/superpowers/specs/2026-11-01-showcase-plates-and-pick-a-plate-landing-design.md`, parts 1 to 5 and section 12, steps 5 to 12. Copy: `2026-11-01-pick-a-plate-landing-copy.md`. Phase A plan: `2026-11-01-pick-a-plate-phase-a.md`.

## Global Constraints

- Invariant 5: `app/geo.py` is the only coordinate source. Invariant 11: never weaken the terrain guard in `marketing/build_deploy.py`. Invariant 12: never re-stamp `sources.json`. Invariant 13: `region_prep.py` and `bake_playa.py` run in `.venv-prep`, everything else in `.venv`.
- Story crops are cut from print pixels, never upscaled.
- The trail ink stays gold. Track color by height stays off. No showcase plate overrides it.
- A plate with no table in `stories.toml` routes exactly as it does today. Its look changes (Task 1), its journeys do not.
- A merge to plateworks-site is a deploy, and Dom merges it. The page does not ship with the gradient in the Tahoe or Zion sections.
- Plates stay CC0 and carry no OSM data. Network caches stay in the gitignored `cache/networks/`.
- Every pull request passes `python3 scripts/docs_check.py --impact origin/main` and ends with a `Docs:` line. Plan rule from Phase A: run a test command and read its result before each commit, and never chain a commit after a test run.
- Before any `git pull`, check `git branch --show-current`. Run nothing in the main checkout: other sessions use it.

**Worktree setup.** Branch `pick-a-plate-phase-b`, worktree `.claude/worktrees/pick-a-plate-phase-b`. `dem.tif`, `cache/` and `assets/` are gitignored, so link them from the main checkout: `ln -s <main>/cache cache`, `ln -s <main>/assets assets`, and for each of the six plates `ln -s <main>/regions/<id>/dem.tif regions/<id>/dem.tif` (with any other gitignored files `verify_regions.py` asks for). Use `<main>/.venv/bin/python` and `<main>/.venv-prep/bin/python`. New `dem.tif` files stay real files in the worktree until Task 12 moves them to the main checkout.

## Review Focus

- A pinned name that does not resolve must stop the run with the name in the message. `_demo_journeys` catches `ValueError` and `KeyError` and falls back to synthetic tracks, so a plain `ValueError` would ship a showcase poster with invented trips. Pinned in Task 4.
- A `drive` pinned to a road on a cache that has no way names (all six old caches) must fail the same way, never route somewhere else. Pinned in Task 4.
- `ORDER_LOOK` with `labels=True` collides with the explicit `labels=` argument in `orderspec.default_spec` (a `TypeError` on every order), and a plate with no `labels.json`, `landcover.tif` or `playa.json` must still render. Pinned in Task 1.
- A crop window partly off the sheet must shift inside it and keep its size, and a window bigger than the sheet must refuse, so no crop is ever upscaled or quietly smaller. Pinned in Task 6.
- The gradient reaching the live page under a photo caption. Pinned in Task 6 (`demo_photo_plates`) and enforced in Task 11.

---

### Task 1: The customer look

**Files:**
- Modify: `app/orderspec.py:43`, `default_spec` (line about 264)
- Modify: `app/static/store.js:58-59,81` and the `dryLakes` default beside `waterDepth`
- Modify: `scripts/render_asset_farm.py` (`_base_spec`)
- Modify: `tests/test_orderspec.py`, `docs/decisions.md`
- Test: `tests/test_asset_farm_look.py` (new)

**Interfaces:**
- Produces: `ORDER_LOOK` with `soft_light=0.35, haze_strength=0.15, water_depth=0.5, label_place="smart", track_weave=True, biome=True, labels=True, dry_lakes=True, profile=True`. `_base_spec(region, tracks, spots, edition=1, look=None) -> CompositionSpec`, whose look is `{**ORDER_LOOK, **(look or {})}`.

- [ ] **Step 1: Write the failing tests.**

```python
def test_order_look_is_the_full_customer_look():
    for k in ("biome", "labels", "dry_lakes", "profile"):
        assert orderspec.ORDER_LOOK[k] is True

def test_default_spec_has_no_labels_without_labels_json(order):  # exists: must still pass
    ...

def test_farm_renders_the_order_look(region):
    spec = _base_spec(region, [], [])
    for k, v in ORDER_LOOK.items():
        assert getattr(spec, k) == v

def test_a_plate_look_overrides_one_field_only(region):
    spec = _base_spec(region, [], [], look={"haze_strength": 0.4})
    assert spec.haze_strength == 0.4 and spec.soft_light == ORDER_LOOK["soft_light"]

def test_full_look_renders_on_a_plate_with_no_landcover_labels_or_playa(tmp_region):
    render.rasterize(_base_spec(tmp_region, [], []), dpi=40, region_dir=tmp_region.dir, watermark=False, cfg=tmp_region.cfg)
```

Use `synthetic_region("<id>")` for the regions, per the test runbook.

- [ ] **Step 2: Run them.** Run `.venv/bin/python -m pytest tests/test_orderspec.py tests/test_asset_farm_look.py -q`. Expected: the new tests FAIL.

- [ ] **Step 3: Implement.** In `default_spec`, write `**{**ORDER_LOOK, "labels": os.path.isfile(...)}`, so the file check still wins. Check `orderpreview.py` for the same collision (it uses `PREVIEW_LOOK = ORDER_LOOK`). In `store.js`, set `biome: true`, `labels: true`, `dryLakes: true`, `profile: true`, and rewrite the comment that says dry lakes stay off.

- [ ] **Step 4: Run the fast suite.** Run `.venv/bin/python -m pytest -n auto -m "not slow" -q`, and compare the failure set with `main`. Expected: only tests that pin the old look fail. Update each to the new look, and say so in the commit.

- [ ] **Step 5: Drive the studio.** Open a new poster in the studio. Expected: the toggles show the new defaults, and the proof renders with the coloring, names, stipple and strip.

- [ ] **Step 6: Commit, with the decisions row and a pull request.** A customer sees this change, so the same day open a plateworks-os pull request for Business Plan v2 section 4, listing what a poster carries by default. Message: `Every poster gets the coloring, the names, the dry lakes and the profile strip`.

### Task 2: Way names and the five plates

**Files:**
- Modify: `scripts/fetch_track_network.py` (`collect_ways`, `project_ways`), `scripts/track_network.py` (`build_graph` keeps the name on each edge)
- Create: `regions/<id>/` for the five plates, the files the runbook lists
- Modify: `tests/` for the fetch script, `tests/test_track_network.py`

**Interfaces:**
- Produces: a way is `{"class": str, "coords": list, "name": str}`, with `name` left out when the way has none. `g.edges[i]["name"]` is `None` for a nameless or old-cache way.

- [ ] **Step 1: Write the failing tests.** `test_collect_ways_keeps_the_osm_name`; `test_a_way_with_no_name_has_no_name_key`; `test_build_graph_carries_the_name_and_reads_an_old_cache`.
- [ ] **Step 2: Run them.** Expected: FAIL. **Step 3: Implement.** `collect_ways` holds a 4-tuple. **Step 4: Run them.** Expected: PASS. Commit: `Keep way names in the network cache, before the five networks are fetched`.
- [ ] **Step 5: Build each plate by spec part 1, one at a time,** in the order `tahoe_ca`, `zion_ut`, `canyonlands_ut`, `ruby_mountains_nv`, `eastern_sierra_ca`. Use the id, name and starting bbox from the spec's table, and the UTM zone of the neighbouring plates. If `plan_build` steps the Eastern Sierra from 10 m to 30 m, trim its bbox until 10 m holds.
- [ ] **Step 6: Check each plate.** Run `scripts/stripe_check.py <id>`. Expected: a score under the line of 12. Above it, stop: row 133 still holds that question, and it is Dom's. Run `.venv/bin/python scripts/verify_regions.py`. Read `overview.png`, and move the bbox until the spec's "Must hold" places sit well inside. Confirm `playa.json` holds Franklin Lake on `ruby_mountains_nv`.
- [ ] **Step 7: Fetch each network** with `scripts/fetch_track_network.py <id>`, one run per plate. Check each cache holds the named roads and paths: `White Rim Road`, `Lamoille Canyon Road`, `Walter's Wiggles` if mapped. Correct the names in `stories.toml` to what OSM says. Correct the destinations too: "Island in the Sky", "The Needles" and "The Confluence" may not be in `labels.json`, so replace each with the nearest named summit, gap or lake that is.
- [ ] **Step 8: Commit each plate's files** on the branch. `dem.tif` stays uncommitted.

### Task 3: The straightness measure

**Files:**
- Modify: `scripts/track_network.py`
- Create: `scripts/track_straightness.py` (prints one row per plate)
- Test: `tests/test_track_network.py`

**Interfaces:**
- Produces: `straight_share(path: np.ndarray, step_m=100.0, tol_deg=3.0) -> float`, and `network_tracks(region, ways, seed=7, n_trips=None, story=None, raw_out=None)`, where a list passed as `raw_out` receives each trip's raw routed path before densify and jitter.

- [ ] **Step 1: Write the failing tests.** A straight line gives `1.0`. A sine wave of 200 m wavelength gives under `0.1`. A path shorter than three samples gives `0.0`. `raw_out` receives one path per track, and passing it changes no track's coordinates.
- [ ] **Step 2: Run them.** Expected: FAIL. **Step 3: Implement.** Resample along length, then count heading changes under `tol_deg` over all changes. **Step 4: Run them.** Expected: PASS.
- [ ] **Step 5: Baseline the six plates.** Run `.venv/bin/python scripts/track_straightness.py`. Record the numbers in `docs/decisions.md`, stating that they replace the 37 and 23 percent in spec section 1. Commit.

### Task 4: Pinned destinations, trail-first outings, the `drive` shape

**Files:**
- Create: `scripts/story_config.py`
- Modify: `scripts/track_network.py`, `scripts/render_asset_farm.py` (`_demo_journeys` passes the story)
- Modify: `marketing/stories.toml` (`status = "ready"`, `road_cost` per plate), `tests/test_stories_config.py`
- Test: `tests/test_track_network.py`

**Interfaces:**
- Produces in `story_config.py`: `load_stories(path=STORIES) -> dict[str, dict]`, and `story_for(region_id) -> dict | None`.
- Produces in `track_network.py`: `class PinError(RuntimeError)`, deliberately outside what `_demo_journeys` catches. `pinned_destinations(pool, names) -> list[dict]`. `drive_path(g, road: str) -> list`. `outing_weights(story) -> dict`, which is `WEIGHTS["outing"]` with `road` replaced by `story["road_cost"]`.

- [ ] **Step 1: Write the failing tests** on the existing fixture network.

```python
def test_a_pinned_name_is_used_in_place_of_the_selection(): ...
def test_a_pinned_name_that_does_not_resolve_names_itself():
    with pytest.raises(PinError, match="Nowhere Peak"): ...
def test_farm_does_not_fall_back_to_synthetic_on_a_pin_error(): ...  # _demo_journeys raises
def test_a_higher_road_cost_keeps_an_outing_on_the_trail(): ...
def test_a_drive_follows_its_named_road(): ...
def test_a_drive_on_a_cache_with_no_names_raises_pin_error(): ...
def test_a_drive_makes_a_track_and_a_spot_named_for_its_road(): ...
def test_a_plate_with_no_story_composes_byte_identical_trips(): ...  # story=None vs before: fixed digest
def test_unnamed_slots_fill_from_the_seeded_selection(): ...
def test_a_story_cycles_its_trip_shapes(): ...
```

- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.** With a story, destinations are pinned first, in config order, then the pool fills to `trip_count`. Shapes cycle through `story["trips"]`. A `drive` adds `kind="drive"` (dates in the same bucket as a summit), `track_id="drive:<road>"`, and a spot at the road's far end. `drive_path` costs named edges at 0.1 and others by `WEIGHTS["4wd_day"]`, and routes between the two named vertices farthest apart. With `story=None`, no new RNG draw and no changed weight, or the six plates' trips move.
- [ ] **Step 4: Run them, then the fast suite.** Expected: PASS, same failure set. Commit.
- [ ] **Step 5: Tune.** Set `road_cost` for each of the five, starting at 3.0. Run `scripts/track_straightness.py`. Expected: each showcase plate under 10 percent. Record the values and the numbers in `docs/decisions.md`. Commit.

### Task 5: Pinned photos

**Files:**
- Modify: `scripts/render_asset_farm.py` (`_annotate`, `_demo_journeys`, `_edition_spots`), `marketing/stories.toml`
- Test: `tests/test_asset_farm_look.py`

**Interfaces:**
- Produces: `_annotate(spots, out_dir, story=None)`. Config keys `photo_at` (a spot label) and `photo_file` (a path under gitignored `marketing/photos/`). Tahoe sets `photo_at = "Mount Tallac"`, Zion sets `photo_at = "Angels Landing"`, and the other three set neither.

- [ ] **Step 1: Write the failing tests.** `no story pins spots[0] as today`; `a story with photo_at pins that spot only`; `a story with no photo_at pins nothing`; `a photo_at matching no spot raises PinError`; `photo_file wins over the gradient`.
- [ ] **Step 2: Run them.** Expected: FAIL. **Step 3: Implement.** Editions keep the rule, through the same `story`. **Step 4: Run them.** Expected: PASS. Commit.

### Task 6: The `stories` and `journey` tiers, and the exporter

**Files:**
- Modify: `scripts/render_asset_farm.py`, `scripts/export_relief.py`, `scripts/story_config.py`, `marketing/DEPLOY.md`, `marketing/README.md`
- Test: `tests/test_asset_farm_stories.py` (new), `tests/test_export_relief.py`

**Interfaces:**
- Consumes: `story_for` (Task 4), `_base_spec(..., look=)` (Task 1).
- Produces:
  - `crop_window(center_m, size_in, crop, image_size, dpi) -> (x0, y0, x1, y1)`, using `app/geo.py` for the ground to pixel step
  - `_journey(region, tracks, spots, out_dir, dpi, story) -> [path]`, writing `poster_journey.png`
  - `_stories(out_dir, region, story, dpi) -> [path]`, writing `story_<n>.png`, and for a `poster_journey` section both `story_<n>.png` and `story_<n>_before.png`
  - `story_images(src_dir, story) -> dict[str, bytes]`, writing `story-<n>.webp`, `journey-before.webp`, `journey-after.webp`, `edition-<n>.webp` and copying `film.mp4`
  - `demo_photo_plates() -> list[str]`, the plate ids with `photo_at` and no `photo_file`
- Config: a section gives `crop_center_m = [x, y]` and `crop_in = [w, h]`, or `crop_anchor = "foot"` for the elevation strip. `film` and `editions` sections have no crop.

- [ ] **Step 1: Write the failing tests.**

```python
def test_crop_window_keeps_print_pixels(): ...       # size_in * dpi exactly
def test_crop_window_shifts_inside_the_sheet_and_keeps_its_size(): ...
def test_crop_window_bigger_than_the_sheet_refuses(): ...
def test_foot_anchor_takes_the_bottom_of_the_sheet(): ...
def test_journey_pair_differs_only_in_light(): ...   # same spec but light fields
def test_a_section_with_no_window_fails_with_its_heading(): ...
def test_a_plate_with_no_story_writes_no_story_files(): ...
def test_demo_photo_plates_names_tahoe_and_zion_until_a_photo_is_set(): ...
```

In `test_export_relief.py`, add one test per new output, plus: `the terrain guard refuses before any story file is written`; `outputs are byte-identical across two runs`. Sizes: `story-<n>.webp` 1200 px long edge at quality 84. `edition-<n>.webp` 840 px. `journey-*.webp` 1200 px.

- [ ] **Step 2: Run them.** Expected: FAIL. **Step 3: Implement.** Add both tiers to `DEFAULT_TIERS` and `--only`. `stories` is in `RESTAGE_TIERS`, and `journey` is not, since it renders. **Step 4: Run them.** Expected: PASS. Commit, with the docs.

### Task 7: Render, choose the windows, fill the config

**Files:**
- Modify: `marketing/stories.toml` (windows, looks, Zion's sun)

- [ ] **Step 1: Render the five.** Run `.venv/bin/python scripts/render_asset_farm.py --regions <five ids>`, in the background.
- [ ] **Step 2: Choose every window by eye.** Read each poster's region at full pixels. Set `crop_center_m` and `crop_in` until each section shows its feature. Set each plate's `look` only where the ground asks for it (more haze on the Rubies), and Zion's sun: low, from the west or southwest, about an hour before sunset on an autumn day. Record the sun in `docs/decisions.md`.
- [ ] **Step 3: Choose Zion's three editions** so the lineage reads as years. Re-render `stories`, `journey` and `editions`.
- [ ] **Step 4: Re-render the six** with `--only poster detail coin relief editions`. This answers row 133's first question.
- [ ] **Step 5: Read each sentence against its crop,** starting with every `(check against the crop)` mark and the Walter's Wiggles heading. Change only what the picture contradicts, in the copy document and in `stories.toml`.
- [ ] **Step 6: Show Dom.** Publish a private contact sheet of every crop with its sentence. This is the checkpoint before anything goes to the site. Wait for his read.
- [ ] **Step 7: Commit, and open the tecopa-plateworks pull request.** Dom merges it just before the site's pull request.

### Task 8: Images into the page

**Files, on plateworks-site branch `tecopa-pick-a-plate`:**
- Create: `public/content/images/2026/11/<id>-*`, `public/content/media/2026/11/eastern_sierra_ca-film.mp4` and its poster frame
- Modify: `public/content/images/2026/09/<six ids>-*`, `src/content/pages/tecopa.html`, `test/tecopa-page.test.js`

- [ ] **Step 1: Write the failing tests.** `no data-slot is left on the page`; `every story image has a width, a height, an alt and loading="lazy"`; `every image and film path resolves in public/`; `every alt matches the copy document`; `add-next-years-trips shows Zion's three editions and not Susanville`; `the chooser coins are plain images, with no relief attributes`.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Replace each slot** from the copy document and the exported files. Keep the markup of the existing relief and image cards: poster `data-relief-surface`, `data-relief-height`, `data-relief-aspect`, with a plain `<img>` inside. Fill the `{days and miles}` captions from the render.
- [ ] **Step 4: Run them.** Then run `npm test && npm run build && npm run check -- --images`. Expected: every step exits 0.
- [ ] **Step 5: Drive the page** at 375 and 1280 px, using a temporary `site-preview` entry in the workspace's `.claude/launch.json`, restored afterwards. Check: the poster relief draws and turns after each coin; `document.querySelectorAll('canvas.tecopa-relief__canvas').length` never exceeds eight, including on Canyonlands; a hidden story's images load nothing in the network log; the divider moves by a real drag; the film plays on Sierra only when in view. Ask Dom to try the divider with a finger on his phone against the deploy preview, since the pane sends only mouse clicks.
- [ ] **Step 6: Commit.**

### Task 9: The live pins

**Files:**
- Modify: `tests/test_marketing_page.py`, `docs/changing-things.md`, `docs/marketing.md`, `CLAUDE.md`, both superseded specs' status lines

- [ ] **Step 1: Add the pins from spec section 10:** the five story anchors, the five titles, "real trails", each section heading, the Journey Light claim, the five new `<id>-coin` images, `"real trips"` in a new retired list. Each is a `live` test, so it stays out of the default run.
- [ ] **Step 2: Run them against a local build.** The tests read `SITE`, so point it at the preview for this one run through a local edit, and restore it. Expected: PASS.
- [ ] **Step 3: Docs, per spec part 6.** Commit.

### Task 10: The photo gate

- [ ] **Step 1: Run `demo_photo_plates()`.** Expected before Dom's photographs: `['tahoe_ca', 'zion_ut']`.
- [ ] **Step 2: Ask Dom.** This is his to supply. With a photograph: set `photo_file`, re-render those two plates, and re-export. Without one: remove `photo_at`, and remove the photo sentence from Tahoe section 3 and Zion section 2 in the copy and on the page.
- [ ] **Step 3: Run it again.** Expected: `[]`. The page does not ship until it is.

The six existing plates' posters carry the same gradient today, through `spots[0]`, on the live page. Spec decision 8 covers only the two sections. Bring this to Dom at Step 2 as his call. To remove it, `_annotate` stops pinning for a network plate with no story, and the six re-render.

### Task 11: Ship

- [ ] **Step 1: Confirm the gate.** `demo_photo_plates()` is `[]`. `npm test`, `npm run build`, `npm run check -- --images` all exit 0.
- [ ] **Step 2: Open the plateworks-site pull request.** Dom merges tecopa-plateworks first, then this one, which deploys.
- [ ] **Step 3: Run the live tests.** Run `.venv/bin/python -m pytest -m live tests/test_marketing_page.py`. Expected: all PASS against www.plateworks.org/tecopa/. A red test goes to Dom with its output.

### Task 12: Close out

- [ ] **Step 1: Move the five `dem.tif` files** into the main checkout's plates, without changing the branch that checkout is on. Run `verify_regions.py` there.
- [ ] **Step 2: Business Plan v2 section 6 and its change log,** in a plateworks-os pull request: the landing page is five stories.
- [ ] **Step 3: Session log.** Close rows 138 and 133's first question. Remove both worktrees.
