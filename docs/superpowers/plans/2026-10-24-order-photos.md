# Order Photos Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A customer's photos land on their map: each photo finds its spot from its GPS or its time on the track, sits in open ground with a leader line to its spot (or in a gallery band when open ground runs out), and Dom places, moves, crops, captions or drops any photo in the studio before he approves.

**Architecture:** A photo is a marker with a photo: the existing hotspot model (`spec.hotspots`, `render._draw_photos`, the manifest's embedded photos) gains a box offset, a crop focus and a spot source. Prepare reads the photos in `in/`, finds spots, writes upright JPEGs to `work/photos/`, and lays the boxes out with a pure geometry module (`app/photolayout.py`) fed by what the renderer already knows is occupied. `orderspec.default_spec` turns the placed photos into hotspots, so Plan A's save, approve and Finish carry them unchanged.

**Tech Stack:** Python 3, Pillow 12.3 (ExifTags, ImageOps.exif_transpose), pillow-heif (new, spec §5), numpy, the vanilla JS studio.

**Spec:** `docs/superpowers/specs/2026-09-24-order-pipeline-design.md` §5 (Photos), §2 (Prepare keeps manual changes), Errors, Testing. **Depends on:** `docs/superpowers/plans/2026-10-24-order-proof-approval-and-print.md` (Plan A), built first on the same branch: `app/orderspec.py`, `app/orderstudio.py`, the Order panel, `app/orderfinish.py`.

## Planning decisions (for Dom's review before the build)

| # | Decision |
|---|---|
| B1 | A photo extends the marker model, not a new record. The spec asked the plan to choose. A hotspot already carries `photo`, `label` and an embedded JPEG through the manifest door, and the renderer, the set clamping and the studio rows already handle it. A hotspot gains three optional keys: `box` (`{"dx_in", "dy_in"}`, the box centre's offset from its spot, in inches), `crop` (`{"cx", "cy"}`, the centre-crop focus, 0 to 1) and `source` (`"gps"`, `"time"` or `"manual"`). |
| B2 | The gallery band runs across the top or the bottom of the map, Dom's choice per order (Dom, 2026-10-24). A spec field `photo_band_side` (`"top"`, the default, or `"bottom"`) picks it, and the furniture stack (title, compass, credit) takes the other end: lower left with a top band, upper left with a bottom band. Prepare grows the frame toward the band's side by the band's height, so the tracks keep their nestled share. The spec's "a strip below" becomes one of the two choices. |
| B3 | Dom drags a box on the rendered proof (Dom leaned to drag; settled 2026-10-24). The proof image is the sheet at the proof's dpi, so a drag in proof pixels divided by that dpi is an offset in inches. Each photo box is outlined over the proof; a drop sends its new `box` offset and the proof renders again. A tray photo is placed by a click on the proof, which becomes a ground spot through the spec's crop. A drop onto a route, furniture or another box is kept and warned (Dom sometimes wants it there). Crop focus stays two sliders. `canvas.js`'s plate overview is not used for this. |
| B4 | Time matching uses the track's surviving points (`Track.coords_t`, unix seconds UTC, simplified) and interpolates between the two points around the photo's time. A photo more than 10 minutes (`PHOTO_TIME_TOLERANCE_S = 600`) from any track time gets no time spot. Spec §5: only when the photo stores `OffsetTimeOriginal`. |
| B5 | The default caption is the nearest `labels.json` feature (the plate's GNIS names) within 2,000 m of the spot, measured to its nearest vertex; else empty. `hydro.json` names are not used. |
| B6 | The box's long edge scales with the sheet from spec §5's 2.25 in on 12×18: `photo_box_in = round(2.25 * sqrt(area / 216), 2)`, where `area` is the sheet's area in square inches, or one panel's for a set (2.09 in on 11×17, 2.96 in on 17×22). |
| B7 | Limits: open ground takes at most 8 photos (`OPEN_MAX = 8`) and the band 12 (`BAND_MAX = 12`), spec §5's starting values. More than 8 placed photos uses the band. More than 12 is a Prepare warning, and Finish refuses until 12 or fewer remain. |
| B8 | pillow-heif enters `requirements.txt` and `requirements-lock.txt` (spec §5: "HEIC needs pillow-heif in `.venv`"). It is the one new dependency. |
| B9 | GPS goes from lon/lat to the plate's CRS through `app/geo.py` `lonlat_to_crs` (invariant 5: the only coordinate source). |

## Global Constraints

- Plan A's Global Constraints hold, except "No new dependency": pillow-heif is allowed (B8).
- Physical units, never pixels (invariant 2): box offsets, box size and band height are inches; the layout works at a working dpi and stores inches.
- `provenance.spec_from_manifest` is the one untrusted-manifest door (invariant 8): the new hotspot keys are bounded there (finite numbers, `dx_in`/`dy_in` within the sheet, `cx`/`cy` in 0..1, `source` in its three values); anything else is dropped.
- A new spec field follows `docs/changing-things.md` › Add a spec knob or studio control, and the manifest change follows › Change the manifest or add a file-consuming verb, with `docs/MANIFEST.md`.
- Determinism (invariant 3): the layout is deterministic for the same inputs (no random order; ties broken by photo file name).
- Nothing writes to `in/`. Photos are customer data: they stay in the order folder.

## Review Focus

1. **A phone photo saved sideways** (EXIF orientation 6 or 8): the box shows it upright, and its pixel size for the too-small check is the upright one. Test in Task 1.
2. **A photo time without an offset**: no time spot, even when the naive time happens to match the track. Test in Task 2.
3. **A spot behind a gap strip of a window set**: warned like a route end (Plan A's report wording), and its box never lands across a seam. Test in Task 6.
4. **Prepare run again after studio edits**: placed, moved, cropped, captioned and dropped photos all survive; a new photo added to `in/` joins the tray without moving the others. Test in Task 7.
5. **A crafted manifest** with a huge `dx_in` or a NaN `cx`: dropped at the door, never a 500. Test in Task 4.

---

### Task 1: Read a photo

**Files:**
- Modify: `requirements.txt`, `requirements-lock.txt` (pillow-heif, pinned to the newest release that supports Pillow 12.3)
- Create: `app/photos.py`
- Test: `tests/test_photos.py` (fixtures made in the test with Pillow: a JPEG with GPS, with `DateTimeOriginal` and `OffsetTimeOriginal`, with orientation 6, and with no EXIF)

**Interfaces:**
- Produces: `PHOTO_EXTS` (moved from `app/ordernew.py:48`; `ordernew` imports it), `PhotoMeta` (frozen dataclass: `name: str, lonlat: tuple | None, taken_utc: float | None, size_px: tuple`), `read_meta(path: str) -> PhotoMeta`, `write_work_jpeg(src: str, dst: str, max_px: int = 4000) -> tuple` (upright via `ImageOps.exif_transpose`, RGB, quality 92, returns the written size).

`taken_utc` is set only when both `DateTimeOriginal` and `OffsetTimeOriginal` are present (spec §5); it is unix seconds UTC. `size_px` is the upright size.

- [ ] **Step 1: Write the failing tests** — `test_gps_becomes_lon_lat`, `test_time_needs_its_offset` (offset absent → `taken_utc is None`), `test_sideways_photo_reports_its_upright_size`, `test_heic_is_read` (skip when pillow-heif cannot write a fixture), `test_work_jpeg_is_upright_and_capped`.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement; register the HEIC opener once in `app/photos.py` (`pillow_heif.register_heif_opener()`).**
- [ ] **Step 4: Run them and see them pass.**
- [ ] **Step 5: Commit** — `"Read a photo's place, time and upright size, HEIC included"`

### Task 2: Find a photo's spot

**Files:**
- Create: `app/photospot.py`
- Test: `tests/test_photospot.py`

**Interfaces:**
- Consumes: `photos.PhotoMeta`, `ingest.Track` (`coords`, `coords_t`), `geo.RegionGeo` and `geo.lonlat_to_crs`.
- Produces: `PHOTO_TIME_TOLERANCE_S = 600`, `Spot` (frozen: `x: float, y: float, source: str`), `spot_for(meta: PhotoMeta, tracks: list, region: RegionGeo) -> Spot | None`, `in_frame(spot: Spot, frame: tuple) -> bool`.

Order (spec §5): GPS first; else time on the track (B4); else `None` (the tray).

- [ ] **Step 1: Write the failing tests** — `test_gps_wins_over_time`, `test_time_interpolates_between_track_points` (a photo halfway in time between two points lands halfway between them), `test_a_time_outside_the_tolerance_has_no_spot`, `test_a_naive_time_never_matches` (Review Focus 2), `test_a_track_with_no_times_gives_no_time_spot`.
- [ ] **Step 2: Run and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run and see them pass.**
- [ ] **Step 5: Commit** — `"A photo's spot from its GPS, then its time on the track"`

### Task 3: The default caption

**Files:**
- Create: `app/photocaption.py`
- Test: `tests/test_photocaption.py`

**Interfaces:**
- Produces: `CAPTION_RADIUS_M = 2000.0`, `nearest_name(x: float, y: float, labels: dict, radius_m: float = CAPTION_RADIUS_M) -> str`, where `labels` is the parsed `labels.json` (`{"crs", "features": [{"name", "kind", "rank", "coords": [[x, y], ...]}]}`).

- [ ] **Step 1: Write the failing tests** — `test_the_nearest_vertex_wins`, `test_nothing_within_2_km_is_empty`, `test_a_tie_takes_the_higher_rank` (rank as `render._label_candidates` orders it: read it and match).
- [ ] **Steps 2–4:** fail, implement, pass.
- [ ] **Step 5: Commit** — `"A photo's default caption is the nearest named place within 2 km"`

### Task 4: The spec carries a photo's box, crop and source

**Files:**
- Modify: `app/spec.py` (a field `photo_layout: str = "open"`, values `("open", "band")`, and a field `photo_band_side: str = "top"`, values `("top", "bottom")`, both checked in `validate`; the hotspot keys of B1 documented at :133), `app/serialize.py` (round-trip), `app/provenance.py` (bound the new keys at the manifest door, per Global Constraints), `docs/MANIFEST.md`
- Test: `tests/test_photo_spec.py`; the existing `tests/test_provenance.py`, `tests/test_main.py` and `tests/test_editions.py` pass unchanged

**Interfaces:**
- Produces: `PHOTO_LAYOUTS = ("open", "band")`; hotspot keys `box`, `crop`, `source`; `provenance` keeps them only when well-formed.

- [ ] **Step 1: Write the failing tests** — `test_photo_layout_round_trips`, `test_validate_refuses_an_unknown_layout`, `test_box_and_crop_survive_a_manifest_round_trip`, `test_a_crafted_box_or_crop_is_dropped_at_the_door` (huge `dx_in`, NaN `cx`, `source="evil"`: each dropped, no exception; Review Focus 5).
- [ ] **Steps 2–4:** fail, implement, pass. Follow › Add a spec knob for the cache-key rule: `photo_layout` changes the overlay, not the base layer.
- [ ] **Step 5: Commit** — `"A photo marker carries its box offset, crop focus and spot source, bounded at the manifest door"`

### Task 5: The renderer draws boxes where they are told, and the band

**Files:**
- Modify: `app/render.py` (`_draw_photos` at :1424; a band painter beside it; `_paint_overlays` at :3060), and expose `occupancy(spec, region_dir, dpi, cfg=None) -> Occupancy` for Task 6
- Test: `tests/test_markers.py` (new cases), `tests/test_photo_band.py`

**Interfaces:**
- Consumes: hotspot `box`, `crop`; `spec.photo_layout`; `spec.photo_box_in`.
- Produces: `Occupancy` (frozen: `size_px: tuple, route: np.ndarray` (bool, True where a route is, grown by `PHOTO_ROUTE_CLEARANCE_IN = 0.15`), `rects: list` (the `_label_keepout` rects plus the title block), `dpi: float`), `BAND_PAD_IN = 0.25`, `band_height_in(spec) -> float` (box + 2 × pad + caption line).

Rules:
- `open`: a hotspot with `box` draws its box centred at spot + (`dx_in`, `dy_in`) × dpi; without `box`, today's placement stands (old posters reprint unchanged, invariant 7). The leader is one straight line from the spot to the box edge. `crop` moves the centre-crop window; absent, centre.
- `band`: boxes in one row across the map inside the trim, at the top or the bottom (`spec.photo_band_side`), left to right in hotspot order, each with its number; the spot gets a numbered mark instead of a leader. A set's band runs across the whole hung width, and no box crosses a seam band (`panels.seam_bands_px`).
- With `photo_band_side = "bottom"` and a band, the furniture stack moves to the upper left: `_furniture_stack_rects`, `_furniture_stack_top` and the clear bands in `_label_keepout` follow it, so labels and the layout avoid its new place. With `"top"`, or with no band, the furniture stays where it is today, and every existing render's pixels hold.
- Without photos, nothing changes: the existing render tests' hashes hold.

- [ ] **Step 1: Write the failing tests** — `test_a_box_offset_moves_the_box` (pixel of the frame colour at the expected offset), `test_old_hotspots_without_box_render_as_before` (compare to a render on `main`'s code path: same pixels), `test_crop_focus_moves_the_window`, `test_band_draws_numbered_boxes_across_the_top`, `test_a_bottom_band_moves_the_furniture_to_the_upper_left` (the title block's rect sits in the top third; the band in the bottom strip), `test_band_avoids_seams_on_a_set`, `test_occupancy_marks_routes_and_furniture`.
- [ ] **Steps 2–4:** fail, implement, pass. Run `tests/test_markers.py tests/test_panel_furniture.py tests/test_output_fitness.py -q` too.
- [ ] **Step 5: Commit** — `"Photo boxes where the layout puts them, and the gallery band across the top"`

### Task 6: Lay the photos out in open ground

**Files:**
- Create: `app/photolayout.py`
- Test: `tests/test_photolayout.py`

**Interfaces:**
- Consumes: `render.Occupancy` (Task 5), spots in sheet inches.
- Produces: `OPEN_MAX = 8`, `BAND_MAX = 12`, `RING_DIRECTIONS = 8`, `RING_STEPS_IN = (0.6, 1.0, 1.5)` (box-edge distance from the spot, in inches), `layout(spots_in: list, box_in: float, occ: Occupancy, fixed: dict | None = None) -> dict` returning `{"layout": "open" | "band", "boxes": {i: (dx_in, dy_in)}, "unplaced": [i, ...]}`.

Algorithm (pure geometry, deterministic):
1. More than `OPEN_MAX` spots → band.
2. Photos in a fixed order: `fixed` boxes first (Dom's moves, kept as they are), then the rest by spot y, then x, then index.
3. For each photo, candidates are the 8 directions × 3 steps. A candidate is valid when the box is inside the trim, outside every `occ.rects` rect, outside `occ.route` (any True pixel under the box), outside every placed box (with `BAND_PAD_IN` between), its leader crosses no placed leader, and it does not straddle a seam band.
4. Take the valid candidate with the shortest leader; ties go to the earlier direction (N, NE, E, SE, S, SW, W, NW).
5. Any photo with no valid candidate → band for the whole poster (spec §5: the two never mix).

- [ ] **Step 1: Write the failing tests** on a hand-built `Occupancy` (numpy masks, no render): `test_one_photo_takes_the_shortest_clear_leader`, `test_boxes_never_overlap_routes_or_furniture`, `test_leaders_never_cross`, `test_a_fixed_box_is_kept`, `test_nine_photos_use_the_band`, `test_a_blocked_photo_sends_all_to_the_band`, `test_no_box_straddles_a_seam` (Review Focus 3), `test_same_inputs_same_layout`.
- [ ] **Steps 2–4:** fail, implement, pass.
- [ ] **Step 5: Commit** — `"Photos find open ground with leaders that never cross, or all go to the band"`

### Task 7: Prepare places the photos

**Files:**
- Modify: `app/orderprep.py` (a photo step after the plate, before the proof), `app/orderspec.py` (`default_spec` builds hotspots, `photo_layout` and `photo_box_in` from state), `app/order.py` (`Order.photo_files()` beside `track_files()`)
- Test: `tests/test_orderprep_photos.py`, `tests/test_orderspec.py` (new cases)

**Interfaces:**
- Consumes: Tasks 1–6.
- Produces: state key `photos`, a list in file-name order of `{"file", "work", "spot": {"x", "y"} | None, "source", "caption", "box": {"dx_in", "dy_in"} | None, "crop": {"cx", "cy"}, "dropped": false, "warnings": []}`; state key `photo_layout`; `manual.photos` (a dict keyed by file name, written only by the studio, Task 8) wins field by field over Prepare's values.

Rules:
- `box_in` follows B6. Spots outside the frame are kept and warned: `<file>: its spot is outside the frame. Widen the frame or drop it.` (spec §5).
- A photo smaller than its box at 300 ppi (upright long side < `box_in × 300`) is warned: `<file>: <w>×<h> px is small for a <box_in> in box at 300 ppi.`
- A spot behind a gap strip of a window set is warned as `Photo <file> is behind gap <n>` (Plan A's wording for route ends; Review Focus 3).
- More than `BAND_MAX` placed photos: warning `<n> photos: the band holds 12. Drop some in the studio.`
- The report gains `Photos: <placed> placed (<gps> by GPS, <time> by time, <manual> by hand), <tray> in the tray, <dropped> dropped; layout <open|band>`.
- `default_spec`: one hotspot per placed, not dropped photo: `{"x", "y", "weight": 1, "label": caption, "photo": <absolute path of work/photos/<n>.jpg>, "box", "crop", "source"}`; `photo_layout` and `photo_box_in` from state. The photo path is always in the order folder, never under the engine's `uploads/` (which is swept after 24 h and sits in the repo): Plan A's Finish refuses when a photo on the approved spec can no longer be read (`PHOTOS_GONE`), and `provenance.build_final_spec` must read these absolute paths (check `provenance.load_photo`; extend it to accept a path inside `orders_root()` if it only accepts the uploads dir).
- The band needs ground above the nestled frame, and the layout is known only once the plate exists. So an order with photos plans its plate around the frame grown by `band_height_in` (in ground units at the print's scale) at both the top and the bottom, whichever layout and side win: the open layout uses the nestled frame, and the band uses the frame grown toward its side only (B2). `order.toml` takes `band_side = "top" | "bottom"` (default `"top"`), and the studio can change it. State records the frame in use and `band_frame: true | false`. An order with no photos plans its plate exactly as before.
- Prepare run again keeps every `manual.photos` field and adds new photos in `in/` to the tray or their found spots without moving fixed boxes (Review Focus 4).

- [ ] **Step 1: Write the failing tests** with the Plan A `tools` stub and a fake `proofs`: `test_photos_get_spots_captions_and_boxes`, `test_a_photo_with_no_spot_goes_to_the_tray`, `test_small_and_outside_photos_are_warned`, `test_prepare_again_keeps_the_studio_edits_and_adds_new_photos`, `test_default_spec_turns_placed_photos_into_hotspots`, `test_a_band_grows_the_frame_upward`.
- [ ] **Steps 2–4:** fail, implement, pass. Run `tests/test_orderprep.py tests/test_orderspec.py -q` too.
- [ ] **Step 5: Commit** — `"Prepare finds each photo's spot, captions it and lays the boxes out"`

### Task 8: The studio's photo controls

**Files:**
- Modify: `app/orderstudio.py` (photo edits), `app/main.py` (one route), `app/static/order.js`, `app/static/index.html`, `app/static/api.js`
- Test: `tests/test_order_routes.py` (new cases); `tests/test_static_registry.py`; browser drive

**Interfaces:**
- Consumes: Plan A's Order panel and session `order_dir`; state `photos`.
- Produces: `orderstudio.edit_photo(order, file: str, change: dict) -> dict` (writes `manual.photos[file]`; `change` holds any of `spot` (`{"x","y"}`), `box` (`{"dx_in","dy_in"}`, from a drag), `crop`, `caption`, `dropped`; re-runs `photolayout.layout` for the photos without a fixed box; refreshes the session's hotspots from `order_spec`; answers each photo's box rect in proof pixels plus a `warnings` list when a dropped box overlaps a route, furniture or another box, using `render.occupancy`), `proof_px_to_ground(spec, dpi, px, py) -> (x, y)` and `ground_to_proof_px(spec, dpi, x, y) -> (px, py)` in `app/orderstudio.py` (through the spec's crop and print size; invariant 5: built on `app/geo.py`'s crop window functions), and `POST /api/order/photo` (`session_id`, `file`, the change as JSON) answering the new photo list. The front end draws each box as an outline over the proof image and makes it draggable; on drop it sends `box` in inches (pixels ÷ the proof's dpi). Placing a tray photo: the panel's "Place" button arms the next click on the proof, whose pixel becomes the spot through `proof_px_to_ground`.
- A `band_side` change (`top` / `bottom`) goes through the same route with `file` empty; it writes `manual.band_side`, which Prepare and `default_spec` read before `order.toml`'s.
- Element ids: `orderPhotos` (the list), `orderBandSide` (Top / Bottom, shown only when the layout is the band), `orderBoxes` (the outline layer over the proof image), and per row `data-file` on buttons Place, Drop / Restore, a caption field, and crop sliders `cx` / `cy`.

- [ ] **Step 1: Write the failing route tests** — `test_place_a_tray_photo_by_proof_pixel`, `test_drag_a_box_sets_its_offset_in_inches`, `test_a_drop_on_a_route_is_kept_and_warned`, `test_proof_px_and_ground_round_trip`, `test_drop_and_restore`, `test_edits_survive_prepare_again` (Prepare run after an edit), `test_an_edit_clears_the_approval`.
- [ ] **Steps 2–4:** fail, implement, pass. `node --check`, `$('id')` match, registry test.
- [ ] **Step 5: Drive the studio**: open an order with three photos (one with GPS, one with only a time, one with neither), place the tray photo by clicking the proof, drag one box (and once onto a route, to see the warning), crop one, drop and restore one, proof, save, approve. Screenshot each state.
- [ ] **Step 6: Commit** — `"The studio places, moves, crops, captions and drops an order's photos"`

### Task 9: Finish's photo refusals

**Files:**
- Modify: `app/orderfinish.py`
- Test: `tests/test_orderfinish.py` (new cases)

**Interfaces:**
- Consumes: state `photos`.
- Produces: two refusals before any render, in this order: `<n> photos have no spot: place or drop them in the studio.` (spec Errors) and `<n> photos: the band holds 12. Drop some in the studio.` (B7).

- [ ] **Step 1: Write the failing tests** — `test_finish_refuses_a_tray_photo`, `test_finish_refuses_more_than_12_photos`, `test_finish_embeds_placed_photos` (the record PNG's manifest holds each photo as an embedded JPEG).
- [ ] **Steps 2–4:** fail, implement, pass.
- [ ] **Step 5: Commit** — `"Finish refuses until every photo is placed or dropped"`

### Task 10: Docs and the acceptance run

**Files:**
- Modify: `docs/changing-things.md` (Run an order: photos), `docs/decisions.md` (a section with B1–B9 as Dom settled them), `docs/superpowers/specs/2026-09-24-order-pipeline-design.md` (a dated amendment blockquote in §5: B1, B2 and B3 as settled), `docs/architecture.md`, `docs/README.md` (index this plan), `CLAUDE.md` if the order row changes
- Test: `tests/test_docs.py`, `scripts/docs_check.py`, the full suite

- [ ] **Step 1: Write the docs.**
- [ ] **Step 2: Docs tests: PASS, 0 findings; full suite: compare the failure set with the branch before this plan.**
- [ ] **Step 3: Acceptance (Mac, spec Testing):** three real orders, a compact home ground, a long north–south trip and an east–west road trip, each with phone photos, one camera photo without GPS and one photo without a time zone. Record per order: spots found by GPS / time / by hand, the layout, and the warnings.
- [ ] **Step 4: Commit** — `"Docs: an order's photos, and the acceptance run"`

## Not in this plan

- The customer package (sub-project 5): the stills and film show the photos as the poster does.
- Photo limits beyond the starting values (B7), until testing says otherwise.
