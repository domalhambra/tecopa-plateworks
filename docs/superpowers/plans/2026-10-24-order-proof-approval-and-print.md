# Order Proof, Approval and Print Output Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An order goes from Prepare to a proof the client approves, then to print files Dom sends to the PRO-1100: the paper table, the proof and soft proof, the studio's Open / Save / Approve for an order, and `order finish` writing the TIFFs and `PRINT.txt`.

**Architecture:** One function turns an order folder into its `CompositionSpec` (`app/orderspec.py`), so Prepare's proof, the studio and Finish all paint the same spec. The studio saves the spec it proofed into `state.json` (`manual.spec`); Approve records a hash of that spec; Finish refuses unless the hash still matches. Print files are the final render, cut into panels for a set, rotated to feed the 17 in roll, written as uncompressed 8-bit sRGB TIFFs.

**Tech Stack:** Python 3 / FastAPI / Pillow 12.3 (ImageCms for the soft proof, TIFF writer), vanilla JS studio, Swift `tecopa` tool.

**Spec:** `docs/superpowers/specs/2026-09-24-order-pipeline-design.md` (sections 1, 2, 4, 6, Errors), with `docs/superpowers/specs/2026-10-11-print-sizes-panel-sets-and-size-preview-design.md` §6 (Finish for a set) and `docs/superpowers/specs/2026-10-12-tecopa-client-intake-and-payment-design.md` (the client approves the proof; nothing prints before).

**Plan B:** photos on the map (sub-project 3) is its own plan, written after this one is reviewed. It adds photo spots to the spec this plan saves, approves and prints, and adds "every photo placed" to Finish's refusals.

## Planning decisions (Dom, 2026-10-24, and found while planning)

| # | Decision |
|---|---|
| P1 | Paper: Red River Premium Matte 230 on the 17 in roll, the Lab's standard stock. Profile `RR Premium Matte Canon Pro-1100.icc` (installed in `/Library/ColorSync/Profiles/`). This supersedes PT-101 in spec §4 and §6. The test sheet confirms it and picks the intent. |
| P2 | Approval is a studio button. The studio opens an order, Dom saves the proofed spec to the order, and Approve records the approval and the spec's hash. |
| P3 | Prepare writes the client's proof: a screen JPG and a one-page PDF marked PROOF, from the same spec Finish prints. Save to order in the studio writes them again. |
| P4 | The TIFF is 8-bit. The renderer leaves float32 at `relief.py:1045-1047` (truncating to uint8), every later stage is 8-bit, and Pillow has no 16-bit RGB mode. Spec §6 asked the plan to check first: 16-bit is not available without rewriting the compositor. |
| P5 | The TIFF is the print at exactly its size. No white border: the poster is designed to its sheet (keyline inside the trim). Whether the roll print needs a border is settled by the first test print, not here. |
| P6 | Feed: the 17 in side goes across the roll. 17×22 portrait and 17×11 landscape print as they are; 11×17 portrait and 22×17 landscape rotate 90° counter-clockwise. A set's panels follow the same rule. |
| P7 | The test sheet is an order: Dom's own tracks through Prepare, Approve and Finish, printed once per intent. No code beyond this plan (YAGNI). |
| P8 | New order modules never import `app.main`: importing it starts queues, caches and region discovery. `app.main` imports them. The sRGB profile moves to `app/icc.py` for that reason. |
| P9 | `FINAL_FORMATS` stays `png` and `pdf`. Spec §6 said it gains `tif`; only Finish writes a print TIFF, from the approved spec, so the studio's finals do not need one. |

## Global Constraints

- Run `.venv/bin/python -m pytest -n auto -m "not slow" -q` before any claim of done; the full suite before a push to `main`. Compare the failure set, not the totals.
- 300 ppi for every print (`FINAL_DPI`, `app/spec.py:35`). `MAX_OUTPUT_PIXELS` (120 MP) and `MAX_UPSAMPLE` (2.0) hold.
- Physical units, never pixels (invariant 2). Determinism within a build (invariant 3): same spec, same bytes.
- Customer data never in the repo (`app/order.py`, `refuse_inside_repo`). Nothing writes to `in/`.
- Words: "Tecopa Plateworks" in full, never bare "Plateworks"; plate, proof, edition.
- Never commit a font. No new dependency.
- Studio rules (`docs/changing-things.md` › Work on the studio front end): `node --check` each module, every `$('id')` in `index.html`, `tests/test_static_registry.py` passes, no outside host, drive the real studio in a browser.
- A sentence a client reads follows `docs/superpowers/specs/2026-08-16-target-customer-profile-design.md`; Dom reviews that copy before it ships.
- `tests/test_docs.py` holds `CLAUDE.md` under 2,000 tokens.

## Review Focus

1. **A set's panels**: each panel TIFF is exactly 17×22 in at 300 ppi after its rotation, named `-<k>of<n>` in hang order, with gap strips never printed. Test in Task 8.
2. **A change after approval**: Save after Approve, a rebuilt plate, or a hand-edited `state.json` must make Finish refuse. Tests in Tasks 6, 7 and 8.
3. **The profile is missing** (CI, a new Mac): Prepare still writes the proof, skips the soft proof, and says why in the report. Test in Task 4.
4. **The plate moved under a saved spec** (Prepare rebuilt it): the studio and Finish paint the current plate, never the old plate id. Test in Task 3.
5. **A title that slugs to nothing** (only punctuation or emoji): file names fall back to `poster`. Test in Task 3.

---

### Task 1: The paper table

**Files:**
- Create: `config/papers.toml`, `app/papers.py`
- Test: `tests/test_papers.py`

**Interfaces:**
- Produces: `Paper` (frozen dataclass: `key: str, name: str, roll_in: float, profile: str, intent: str, preset: str, enabled: bool`), `PaperError(ValueError)`, `load_papers(path=PAPERS_PATH) -> list[Paper]`, `enabled_paper(path=PAPERS_PATH) -> Paper`, `feed_rotation(w_in: float, h_in: float, roll_in: float) -> int` (0 or 90), `INTENTS = ("perceptual", "relative")`.

`config/papers.toml` holds one row today:

```toml
[[paper]]
key = "rr-pm230-roll17"
name = "Red River Premium Matte 230"
roll_in = 17
profile = "RR Premium Matte Canon Pro-1100.icc"
intent = "perceptual"        # until the test sheet decides (P7)
preset = "Tecopa · RR Premium Matte 17 in roll"   # Dom names it in Print & Layout
enabled = true
```

Read it strictly, like `config/sizes.toml` is read: UTF-8, only these fields, all required, `intent` in `INTENTS`, `roll_in` > 0.

- [ ] **Step 1: Write the failing tests**

```python
def test_the_shipped_table_has_one_enabled_paper():
    p = papers.enabled_paper()
    assert p.name == "Red River Premium Matte 230"
    assert p.roll_in == 17 and p.intent in papers.INTENTS

def test_feed_puts_the_17_in_side_across_the_roll():
    assert papers.feed_rotation(17, 22, 17) == 0
    assert papers.feed_rotation(22, 17, 17) == 90
    assert papers.feed_rotation(11, 17, 17) == 90
    assert papers.feed_rotation(17, 11, 17) == 0

def test_a_piece_no_side_of_which_fits_the_roll_is_refused():
    with pytest.raises(papers.PaperError, match="17 in roll"):
        papers.feed_rotation(18, 24, 17)

def test_a_bad_table_is_refused(tmp_path):
    # unknown field, intent outside INTENTS, zero or two enabled rows: each raises PaperError
    ...
```

The last test writes three bad tables to `tmp_path` and asserts `PaperError` for each, one `pytest.raises` per table.

- [ ] **Step 2: Run them and see them fail** — `.venv/bin/python -m pytest tests/test_papers.py -q`: FAIL, no module `app.papers`.
- [ ] **Step 3: Implement `app/papers.py` and `config/papers.toml`** as above. `PAPERS_PATH` is `config/papers.toml` beside the repo root (resolve it as `app/order.py` resolves the repo root). `feed_rotation` compares with a 1e-6 tolerance.
- [ ] **Step 4: Run them and see them pass.**
- [ ] **Step 5: Commit** — `git commit -m "The paper table: one 17 in roll of RR Premium Matte 230, and which way a piece feeds"`

### Task 2: The sRGB profile and the soft proof

**Files:**
- Create: `app/icc.py`
- Modify: `app/main.py:127-142` (use `icc.srgb_profile()`; keep the name `SRGB_PROFILE`)
- Test: `tests/test_softproof.py`; `tests/test_srgb_profile.py` must pass unchanged

**Interfaces:**
- Produces: `srgb_profile() -> bytes` (moved as is, fixed creation date included), `PROFILE_DIRS = ("/Library/ColorSync/Profiles", "~/Library/ColorSync/Profiles")`, `find_profile(name: str, dirs=PROFILE_DIRS) -> str | None`, `soft_proof(img: Image.Image, paper_profile: str, intent: str) -> Image.Image`.

`soft_proof` builds `ImageCms.buildProofTransform(sRGB, sRGB, paper_profile, "RGB", "RGB", renderingIntent=<intent>, proofRenderingIntent=<intent>, flags=ImageCms.Flags.SOFTPROOFING)` and applies it. `intent` maps `"perceptual"` to `Intent.PERCEPTUAL` and `"relative"` to `Intent.RELATIVE_COLORIMETRIC`.

- [ ] **Step 1: Write the failing tests**

```python
def test_main_still_embeds_the_same_profile_bytes():
    from app import icc, main
    assert main.SRGB_PROFILE == icc.srgb_profile()

def test_a_missing_profile_is_none(tmp_path):
    assert icc.find_profile("Nope.icc", dirs=(str(tmp_path),)) is None

def test_soft_proof_runs_and_keeps_the_size(tmp_path):
    paper = tmp_path / "paper.icc"
    paper.write_bytes(icc.srgb_profile())          # sRGB stands in for a paper in CI
    img = Image.new("RGB", (40, 30), (200, 120, 60))
    out = icc.soft_proof(img, str(paper), "perceptual")
    assert out.size == (40, 30) and out.mode == "RGB"
```

- [ ] **Step 2: Run them and see them fail** (no module `app.icc`).
- [ ] **Step 3: Move `_srgb_profile` into `app/icc.py` as `srgb_profile`, add `find_profile` and `soft_proof`; `app/main.py` sets `SRGB_PROFILE = icc.srgb_profile()` inside its existing `try`.**
- [ ] **Step 4: Run `tests/test_softproof.py tests/test_srgb_profile.py tests/test_main.py -q`: PASS.**
- [ ] **Step 5: Commit** — `"The sRGB profile moves to app/icc.py, beside a soft proof through a paper's profile"`

### Task 3: One spec for an order

**Files:**
- Create: `app/orderspec.py`
- Modify: `app/orderpreview.py` (import `ORDER_LOOK` instead of defining `PREVIEW_LOOK`; keep `PREVIEW_LOOK = ORDER_LOOK` as an alias so its tests hold)
- Test: `tests/test_orderspec.py`

**Interfaces:**
- Consumes: `app.order` (`Order`, `read_state`, `OrderError`), `orderpreview.load_tracks_m`, `serialize.spec_to_json` / `spec_from_json`, `regionbuild.slugify`.
- Produces: `ORDER_LOOK` (the dict now in `orderpreview.PREVIEW_LOOK`), `plate_dir(state: dict) -> str`, `default_spec(order: Order, state: dict) -> CompositionSpec`, `order_spec(order: Order, state: dict) -> CompositionSpec`, `spec_hash(spec: CompositionSpec) -> str`, `file_stem(title: str) -> str`.

- `plate_dir` is `os.path.join(state["plate"]["root"], state["plate"]["id"])`; raises `OrderError("Run Prepare first: work/state.json has no plate.")` when missing or when `region.json` is not there.
- `default_spec` builds the spec exactly as `orderpreview.render_maps` does (crop = `state["frame"]`, print size = `state["print_in"]`, `panels`/`gap` from state, tracks from `load_tracks_m(order.payloads(), state["epsg"])`, `hotspots=[]`, `seed=7`, `title_text=order.title`, `labels` = `labels.json` exists, `**ORDER_LOOK`), from the plate's `region.json`.
- `order_spec` returns `spec_from_json(state["manual"]["spec"])` when present, else `default_spec`. Either way it rebinds `region_id`, `crs` and `native_resolution_m` to the current plate's `region.json` (Review Focus 4).
- `spec_hash` is the sha256 hex of `json.dumps(spec_to_json(spec), sort_keys=True, separators=(",", ":"))`.
- `file_stem` is `slugify(title)`, or `"poster"` when that is empty (Review Focus 5).

- [ ] **Step 1: Write the failing tests** — on an order folder in `tmp_path` whose plate is `synthetic_region("lassen_ca")` (`tests/conftest.py:133`), with a hand-written `state.json` holding `frame`, `print_in`, `epsg`, `panels`, `gap`, `plate`:

```python
def test_default_spec_frames_as_prepare_did(order):
    s = orderspec.order_spec(order, read_state(order))
    assert s.crop == tuple(read_state(order)["frame"]) and s.title_text == order.title

def test_a_saved_spec_wins_but_follows_the_current_plate(order):
    st = read_state(order); saved = spec_to_json(orderspec.default_spec(order, st))
    saved["region_id"] = "old_plate"; saved["title_text"] = "Edited"
    set_manual(order, "spec", saved)
    s = orderspec.order_spec(order, read_state(order))
    assert s.title_text == "Edited" and s.region_id == st["plate"]["id"]

def test_the_hash_follows_the_spec(order):
    a = orderspec.default_spec(order, read_state(order))
    assert orderspec.spec_hash(a) == orderspec.spec_hash(a)
    assert orderspec.spec_hash(a) != orderspec.spec_hash(dataclasses.replace(a, title_text="x"))

def test_a_title_with_no_letters_names_files_poster():
    assert orderspec.file_stem("★ !!") == "poster"

def test_no_plate_says_run_prepare(tmp_path): ...   # OrderError, match="Run Prepare"
```

- [ ] **Step 2: Run and see them fail.**
- [ ] **Step 3: Implement `app/orderspec.py`; point `orderpreview` at `ORDER_LOOK`.**
- [ ] **Step 4: Run `tests/test_orderspec.py tests/test_orderpreview.py tests/test_orderpreview_render.py -q`: PASS.**
- [ ] **Step 5: Commit** — `"One spec for an order, shared by the proof, the studio and Finish"`

### Task 4: The proof files

**Files:**
- Create: `app/orderproof.py`, `app/proofpdf.py`
- Test: `tests/test_orderproof.py`

**Interfaces:**
- Consumes: `orderspec.order_spec / plate_dir / file_stem`, `papers.enabled_paper`, `icc.find_profile / soft_proof`, `render.rasterize`, `panel_geo.paint_gaps`.
- Produces: `PROOF_DPI = 96.0`, `write_proofs(order: Order, spec: CompositionSpec, plate: str, dpi: float = PROOF_DPI, paper=None, profile_dirs=icc.PROFILE_DIRS) -> dict`, and `proofpdf.write(path: str, image: Image.Image, title: str, lines: list[str]) -> None`.

`write_proofs` renders once (`watermark=True`, `watermark_text="PROOF"`, then `paint_gaps` for a set) and writes:

| File | What |
|---|---|
| `work/proof.png` | the proof, sRGB profile embedded |
| `work/softproof.png` | the proof through the paper's profile and intent; skipped when `find_profile` gives `None` |
| `out/proof/<stem>-proof.jpg` | the client's proof, quality 90, sRGB profile |
| `out/proof/<stem>-proof.pdf` | one page: the title, the map fitted, and the client lines |

It returns `{"files": [...], "soft_proof": "<profile>, <intent>" | None, "soft_proof_why": "<profile> is not installed" | None, "hash": spec_hash(spec)}`.

The client lines (Dom reviews this copy, Global Constraints):
1. `Proof of your Tecopa Plateworks map, <size name>.`
2. `Reply to approve it, or ask for your one round of changes. Nothing prints before you approve.`

`proofpdf.write` follows `app/previewpdf.py`: Letter, `PAGE_DPI = 300`, landscape when the map is wider than tall, temp file and `os.replace`, Pillow `save("PDF", resolution=..., quality=85, subsampling=0, title=...)`.

- [ ] **Step 1: Write the failing tests** — the Task 3 order fixture, `dpi=12`:

```python
def test_proofs_are_written_and_marked(order):
    st = read_state(order); spec = orderspec.order_spec(order, st)
    r = orderproof.write_proofs(order, spec, orderspec.plate_dir(st), dpi=12, profile_dirs=(str(paper_dir),))
    stem = orderspec.file_stem(order.title)
    for f in ("work/proof.png", "work/softproof.png", f"out/proof/{stem}-proof.jpg", f"out/proof/{stem}-proof.pdf"):
        assert os.path.isfile(os.path.join(order.dir, f))
    assert r["hash"] == orderspec.spec_hash(spec)

def test_no_profile_skips_the_soft_proof_and_says_why(order, tmp_path):
    r = orderproof.write_proofs(..., profile_dirs=(str(tmp_path),))
    assert r["soft_proof"] is None and "not installed" in r["soft_proof_why"]
    assert not os.path.exists(os.path.join(order.dir, "work/softproof.png"))

def test_a_set_proof_shows_the_gaps_in_wall_tone(set_order): ...   # a gap pixel equals panels.WALL_TONE
def test_the_pdf_is_one_page(order): ...                          # Image.open(pdf).n_frames == 1
```

`paper_dir` holds a copy of `icc.srgb_profile()` named as `papers.enabled_paper().profile`.

- [ ] **Step 2: Run and see them fail.**
- [ ] **Step 3: Implement `app/orderproof.py` and `app/proofpdf.py`.**
- [ ] **Step 4: Run and see them pass.**
- [ ] **Step 5: Commit** — `"Prepare's proof files: the proof, the soft proof on the roll's paper, and the client's JPG and PDF"`

### Task 5: Prepare writes the proof

**Files:**
- Modify: `app/orderprep.py` (`prepare` at :238, `write_report` at :520)
- Test: `tests/test_orderprep.py`

**Interfaces:**
- Consumes: `orderproof.write_proofs`, `orderspec.order_spec / plate_dir`.
- Produces: `prepare(order_dir, tools, log=print, proofs=None) -> dict`. `proofs` defaults to a function that calls `write_proofs(order, order_spec(order, state), plate_dir(state))`; tests pass a fake. State gains `proof` (the dict `write_proofs` returns) and, on a plate rebuild, `approval: None`.

Rules:
- The proof runs after the plate on both paths: a fresh build and the early "plate is current" return (:269-272).
- A `SpecError` or `OSError` from the proof does not stop Prepare. The plate stays; the first warning is `PROOF NOT RENDERED: <reason>`, and `proof` is `None`.
- Whenever Prepare builds or rebuilds the plate, it writes `approval = None` (Review Focus 2). A current plate keeps the approval.
- The report gains, after Upsampling: `Proof: out/proof/<stem>-proof.jpg and .pdf` and `Soft proof: <profile>, <intent>` or `Soft proof: skipped, <why>`.
- The widened-frame warning names the smaller size (spec §3 and §4; the runbook says this waits for the paper table). `smaller_size(order: Order, track_bounds_m, layer_m: float) -> str | None` in `app/orderprep.py` walks the menu below the ordered size (`three`, `two`, `17x22`, `11x17`, from `app.order.SIZE_KEYS`) and returns the first whose nestled frame holds at `layer_m` within `MAX_UPSAMPLE` (`orderplate.nestled_frame`, `needed_resolution`). The sentence `A smaller print would keep them nestled.` (:317) becomes `11 × 17 in would keep them nestled.` with that size's name from `config/sizes.toml`, or stays as it is when `smaller_size` gives `None`.

- [ ] **Step 1: Write the failing tests** with the existing `tools` fixture and a fake `proofs`:

```python
def test_prepare_writes_the_proof_on_a_fresh_plate_and_a_current_one(tools, tmp_path): ...
    # two prepare() calls; the fake records two calls; state["proof"] is the fake's return
def test_a_proof_failure_keeps_the_plate_and_leads_the_warnings(tools, tmp_path): ...
    # fake raises SpecError("off the DEM"); state["warnings"][0] starts "PROOF NOT RENDERED"
def test_a_rebuilt_plate_clears_the_approval(tools, tmp_path): ...
    # write_state(order, {"approval": {...}}); change a track; prepare(); approval is None
def test_the_report_names_the_proof_and_the_soft_proof(tools, tmp_path): ...
def test_a_widened_17x22_names_11x17_when_it_holds():
    # long thin tracks, layer_m forcing a widening at 17x22: smaller_size(...) == "11x17"
def test_no_smaller_size_keeps_the_old_sentence():
    # ordered 11x17: smaller_size(...) is None
```

- [ ] **Step 2: Run and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run `tests/test_orderprep.py -q`: PASS.**
- [ ] **Step 5: Commit** — `"Prepare writes the proof, and a rebuilt plate clears an approval"`

### Task 6: The order routes

**Files:**
- Create: `app/orderstudio.py`
- Modify: `app/main.py` (extract the session-and-prefill part of `continue_poster`, :2081-end of its prefill, into `_open_spec_session(spec, region, *, sources=(), edition=1, lineage=(), extra=None) -> dict`; `continue_poster` calls it unchanged; add four routes above the static mounts at :2182)
- Test: `tests/test_order_routes.py`; `tests/test_main.py` continue tests pass unchanged

**Interfaces:**
- Consumes: `orderspec`, `orderproof.write_proofs`, `order.load / read_state / write_state / set_manual / orders_root`, `regions.Region(rid, root)`.
- Produces in `app/orderstudio.py`: `list_orders(root=None) -> list[dict]` (each `{folder, name, order_number, title, prepared: bool, approved: bool}`, newest folder first), `save_spec(order, spec) -> dict` (writes `manual.spec`, clears `approval` when the hash changes, rewrites the proof files, returns the new state), `approve(order, spec) -> dict` (refuses with `OrderError("Save to order first: the studio's proof differs from the saved one.")` unless `spec_hash(spec)` equals the saved spec's hash; writes `approval = {"at": <UTC ISO>, "hash": <hash>}`), `approval_ok(order, state) -> bool`.
- Produces in `app/main.py`:

| Route | Body | Answer |
|---|---|---|
| `GET /api/orders` | — | `list_orders()` |
| `POST /api/order/open` | `folder` (form) | 404 when the folder is not under `orders_root()`; 409 `Run Prepare first` with no plate. Registers `REGIONS[plate_id] = Region(plate_id, plate_root)` on every call, creates the session from `order_spec` through `_open_spec_session(..., extra={"order_dir": folder})`, and answers its response plus `order: {folder, title, approved}`. |
| `POST /api/order/save` | `session_id` | 409 `Render a proof first` when the session has no spec; 409 when the session has no `order_dir`. Else `save_spec` and `{saved: true, approved: false, proof: [...]}`. |
| `POST /api/order/approve` | `session_id` | 409 with `approve`'s message when it refuses; else `{approved: true, at}`. |

- [ ] **Step 1: Write the failing tests** with `TestClient(app)`, `TECOPA_ORDERS_DIR` at `tmp_path`, and the Task 3 order whose plate is a synthetic region:

```python
def test_open_save_approve_round_trip(client, order): ...
    # open -> proof (POST /api/proof with the returned proof_form) -> save -> approve -> state approval hash == saved hash
def test_open_refuses_a_folder_outside_the_orders_root(client, tmp_path): ...   # 404
def test_save_before_a_proof_is_409(client, order): ...
def test_approve_after_an_unsaved_change_is_409(client, order): ...
    # open, proof, save, change the title, proof again, approve -> 409 "Save to order first"
def test_saving_a_changed_spec_clears_the_approval(client, order): ...
def test_continue_still_answers_its_shape(client): ...   # the extracted helper changes nothing
```

- [ ] **Step 2: Run and see them fail.**
- [ ] **Step 3: Implement the extraction first and run `tests/test_main.py -q` (PASS), then the routes.**
- [ ] **Step 4: Run `tests/test_order_routes.py tests/test_main.py -q`: PASS.**
- [ ] **Step 5: Commit** — `"The studio can open an order, save its proofed spec, and record the approval"`

### Task 7: The studio's Order panel

**Files:**
- Create: `app/static/order.js`
- Modify: `app/static/index.html` (an Order panel), `app/static/api.js` (`listOrders`, `openOrder(folder)`, `saveOrder(sessionId)`, `approveOrder(sessionId)`), `app/static/compose.js` (export the prefill path `continueFromPoster` uses at :302 so `order.js` lands an opened order the same way)
- Test: `tests/test_static_registry.py` (unchanged rules must pass); browser drive

**Interfaces:**
- Consumes: the Task 6 routes.
- Produces: element ids `orderSelect`, `orderOpen`, `orderSave`, `orderApprove`, `orderStatus`.

Behaviour: the panel lists orders from `GET /api/orders` (title and number; "approved" after an approved one). Open lands the order like a continued poster. Save to order is enabled after a proof; Approve after a save; any later proof that changes the spec turns the status to "Changed since approval: save again" and disables Approve until saved. `orderStatus` names the proof files after a save.

- [ ] **Step 1: Add the ids to `index.html` and run `.venv/bin/python -m pytest tests/test_static_registry.py -q`** — expect PASS (ids unique) before any JS.
- [ ] **Step 2: Implement `order.js` and the `api.js` functions; `node --check` each changed module.**
- [ ] **Step 3: Match every `$('id')` in `order.js` to `index.html`.**
- [ ] **Step 4: Drive the studio**: start the engine, open a fixture order under a temporary `TECOPA_ORDERS_DIR`, proof, Save, Approve, change the title, proof, see Approve disabled and the status line. Take a screenshot of each state.
- [ ] **Step 5: Commit** — `"The studio's Order panel: open an order, save it, approve it"`

### Task 8: Finish writes the print files

**Files:**
- Create: `app/orderfinish.py`
- Modify: `scripts/order.py` (a `finish` subcommand, errors as `finish stopped: …`)
- Test: `tests/test_orderfinish.py`

**Interfaces:**
- Consumes: `orderspec`, `orderstudio.approval_ok`, `papers.enabled_paper / feed_rotation`, `icc.srgb_profile`, `render.rasterize`, `panel_geo.cut`, `provenance.build_final_spec / build_manifest / region_pack_block / manifest_pnginfo`.
- Produces: `finish(order_dir: str, log=print, dpi: float | None = None) -> dict` (returns `{"files": [...], "print_note": path}`; `dpi=None` means `spec.final_dpi()`; tests pass a small dpi), `print_note(order, spec, paper, pieces, approval) -> str`.

Steps inside `finish`, in order:
1. Load the order and state. Refuse (`OrderError`) with: `Approve the proof in the studio first.` when there is no approval; `The order changed after approval: approve it again.` when `approval_ok` is false.
2. `spec = order_spec(...)`; embed photos as `main._embed_photos` does (`box_px = max(24, round(spec.photo_box_in * dpi))`, `provenance.build_final_spec(spec, box_px)`).
3. Render once with `watermark=False`. Cut a set with `panel_geo.cut` (gap strips are never printed); a single sheet is one piece.
4. For each piece, rotate by `feed_rotation(w_in, h_in, paper.roll_in)` (`Image.rotate(90, expand=True)`, counter-clockwise) and save `out/print/<stem>-<size>.tif`, or `<stem>-<size>-<k>of<n>.tif` for a set, with `compression=None`, `dpi=(dpi, dpi)`, `icc_profile=srgb_profile()`.
5. Write `work/record.png`: the unrotated render with the manifest (`build_manifest(spec, region_pack=region_pack_block(plate, labels=spec.labels, biome=spec.biome, dry_lakes=spec.dry_lakes))`, as `app/main.py:1281` builds it; `manifest_pnginfo`), the sRGB profile and the dpi (spec Amendments: the record lives in `work/`).
6. Write `out/print/PRINT.txt` from `print_note`.

`PRINT.txt` lines, in order:

```
Tecopa Plateworks print note
Order: <order_number or folder name> · <title>
Paper: Red River Premium Matte 230, 17 in roll
Profile: RR Premium Matte Canon Pro-1100.icc
Intent: perceptual
Preset: <preset>
Print at 100 %, centred, from Canon Professional Print & Layout.
Approved: <approval at>, hash <first 12 characters>

File: <name>.tif
  Size: 17 × 22 in, 5100 × 6600 px at 300 ppi
  Feed: as it is, the 17 in side across the roll
      | rotated 90° counter-clockwise, the 17 in side across the roll; the map's top is on the left
  Panel: <k> of <n>                      (a set only)

Hang: panels 1 to <n>, left to right, with a <gap> in gap   (a set only)
```

- [ ] **Step 1: Write the failing tests** — the Task 3 order, `dpi=10`, approval written through `orderstudio`:

```python
def test_finish_refuses_without_approval(order): ...            # match "Approve the proof"
def test_finish_refuses_a_change_after_approval(order): ...     # save a new title after approve -> match "changed after approval"
def test_finish_refuses_a_hand_edited_state(order): ...         # edit manual.spec in state.json directly -> refused
def test_a_single_sheet_tiff_is_the_print_at_its_size(order):
    r = orderfinish.finish(order.dir, dpi=10)
    with Image.open(r["files"][0]) as im:
        assert im.size == (170, 110)        # 11x17 portrait at 10 dpi, rotated 90° to feed (P6)
        assert im.info["icc_profile"] == icc.srgb_profile()
        assert round(im.info["dpi"][0]) == 10 and im.info.get("compression") == "raw"
def test_a_three_panel_set_writes_three_rotated_panels_in_hang_order(set_order): ...
    # names end -1of3.tif .. -3of3.tif; each panel is 17x22 in at 10 dpi after rotation (Review Focus 1)
def test_the_print_note_lists_paper_profile_intent_and_each_file(order): ...
def test_the_record_png_carries_the_manifest(order): ...        # zTXt "trailprint" present
def test_the_cli_finish_stops_with_the_reason(order, capsys): ...   # exit 1, stderr "finish stopped:"
```

- [ ] **Step 2: Run and see them fail.**
- [ ] **Step 3: Implement `app/orderfinish.py` and the CLI subcommand.**
- [ ] **Step 4: Run `tests/test_orderfinish.py -q`: PASS. Then one real Finish on the Mac at 300 ppi for an 11×17 order: the TIFF reads 3300 × 5100 (before rotation) in Preview's inspector, with the sRGB profile.**
- [ ] **Step 5: Commit** — `"order finish: the approved spec as print TIFFs for the 17 in roll, and the print note"`

### Task 9: `tecopa order finish`

**Files:**
- Modify: `tools/tecopa/Sources/TecopaKit/Orders.swift` (a `finishEntry`, a tracked run like `prepareEntry`: `ScriptRunner.start("scripts/order.py", ["finish", folder], command: "order_finish")`, `readOnly: false`), `tools/tecopa/Sources/tecopa/Commands.swift` (a `Finish` subcommand of `OrderCommand`), `tools/tecopa/Tests/TecopaKitTests/MCPServerTests.swift` (add `order_finish` to `writes`; the count goes from 35 to 36)
- Test: `swift test --package-path tools/tecopa` (Mac only)

- [ ] **Step 1: Update `MCPServerTests.swift` (writes set, count 36); run `swift test`: FAIL.**
- [ ] **Step 2: Add the entry and the subcommand; keep logic out of the tool.**
- [ ] **Step 3: Run `swift test --package-path tools/tecopa`: PASS.**
- [ ] **Step 4: Commit** — `"tecopa order finish runs Finish as a tracked run"`

### Task 10: The docs and the test sheet

**Files:**
- Modify: `docs/changing-things.md` (Run an order: steps for the proof, the studio's Order panel, sending the proof, Approve, Finish, printing; a new subsection "The test sheet"), `docs/decisions.md` (a section `2026-10-24 (order proof, approval and print)` with P1–P8), `docs/superpowers/specs/2026-09-24-order-pipeline-design.md` (dated amendment blockquotes in §2, §4 and §6: the paper, 8-bit, the studio approval, the proof files; do not rewrite the body), `docs/architecture.md` (the new modules), `CLAUDE.md` (the router row for an order names `app/orderfinish.py` and `config/papers.toml`; stay under 2,000 tokens), `README.md` if it lists the order commands
- Test: `tests/test_docs.py`; `.venv/bin/python scripts/docs_check.py .`

The test sheet subsection says: make an order folder of Dom's own tracks; Prepare, Save, Approve, Finish; print the TIFF twice from Print & Layout, once per intent, on the roll; set `intent` in `config/papers.toml` to the winner and add a row to `docs/decisions.md`. The first print also settles P5 (a border or none).

- [ ] **Step 1: Write the docs.**
- [ ] **Step 2: Run `tests/test_docs.py` and `scripts/docs_check.py`: PASS, 0 findings.**
- [ ] **Step 3: Run the full suite: `.venv/bin/python -m pytest -n auto -q`; compare the failure set with `main`.**
- [ ] **Step 4: Commit** — `"Docs: the proof, the studio approval, Finish and the test sheet"`

## Not in this plan

- Photos on the map (Plan B, sub-project 3), and Finish's refusal for an unplaced photo.
- The customer package (sub-project 5): the full JPG, the share stills, the film, the zip, the iCloud copy, the set's hanging guide.
- A white border (P5) and a second paper. Both wait for the test print.
