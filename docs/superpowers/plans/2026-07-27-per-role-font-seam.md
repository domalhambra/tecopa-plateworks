# Per-Role Font Seam Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the sheet set each typographic role in its own face — point labels, area labels, hydrography, cartouche — instead of stamping one face through `_font(size)`, so the slate in `00_Resources/typography-standards.md` can actually ship.

**Architecture:** One registry, one rev. `_font(size)` grows a `role` argument backed by a `TYPE_ROLES` table; every text call site names its role. Which *files* fill those roles stays operator-side (env vars), because MB Type is licensed and this repo is AGPL and public. A new `type_rev` on `CompositionSpec` carries the *role table* — assignments, point sizes, tracking, casing — because that is what moves pixels on the existing chain and therefore cannot be additive. Rev 1 is exactly today's sheet.

**Tech Stack:** Python 3.14, Pillow (`ImageFont.truetype`), pytest. No new dependencies.

*Line numbers below were checked against `main` on 2026-07-27. Re-grep before trusting any of them.*

---

## Background the implementer needs

Read these before starting:

- `CLAUDE.md` → *The forever-contract* and *Invariants*. Non-negotiable.
- `docs/relief-passes.md` → *When a change is not additive*. `relief_rev` is the precedent this plan copies; `tests/test_relief_rev.py` is the test shape. **Follow it all the way through `app/main.py` and `app/static/` (Task 7) — a rev that stops at the spec is a rev the app can never reach.**
- `00_Resources/typography-standards.md` (workspace, not this repo) → the decision matrix and *Open questions* 1, 2 and 4. This plan closes 4 and gives 1 and 2 a surface to be settled on.
- `app/render.py:1116-1147` — the font cache and `_load_font`, the code being changed.
- `app/render.py:99-108` — `GEO_KINDS`, the per-kind size/caps/rank table this plan extends.

### Four constraints that shape the design

**1. Faces cannot be committed.** MB Type is licensed per-user; the repo is AGPL-3.0 and public, and `README.md:172` already records that the engine bundles no proprietary face. So the seam selects a *role*, and the operator binds roles to files. The committed default must stay the freely-redistributable chain (`Georgia` → DejaVu). This is **enforced, not remembered**: commit `39ad08c` added `*.otf` / `*.ttf` / `*.woff` / `*.woff2` to `.gitignore` because MB Type licence paragraph 7 names "a source repository" explicitly. Do not weaken those patterns to make a test convenient.

**2. Font identity is already outside the manifest.** `TECOPA_FONT` changes the picture today and rides in no manifest. A reprint on a different host with different fonts already produces different bytes. This plan does **not** close that hole and must not pretend to — `type_rev` pins the *layout decisions*, not the binaries. Say so in the docs (Task 8). Closing it properly would mean hashing the face into the manifest and refusing to reprint without it: a separate decision with real usability cost.

**3. Advocate is a caps/small-caps face, not a text face.** Its lowercase positions draw small caps and it exposes no `smcp`. So under the slate, area labels must be passed **mixed case** so the lowercase renders as small caps — the opposite of today's `name.upper()` at `render.py:2007`. A face swap alone gets this wrong; the casing rule belongs in the role table.

**4. This host is font-poor, and CI is font-poor differently.** Verified 2026-07-27: `DejaVuSans.ttf` and `DejaVuSerif.ttf` are **not installed on this Mac** — only `Georgia.ttf` resolves. CI's Ubuntu is the mirror image (DejaVu, no Georgia); that asymmetry is the documented cause of the six known MAD failures in `CLAUDE.md`. Two consequences the tests must respect:
- **Never assert on `FreeTypeFont.path`.** The last-resort `ImageFont.load_default(size)` returns a font whose `.path` is a `_io.BytesIO`, so a `"Sans" in font.path` check raises `TypeError` rather than failing cleanly. `tests/test_hot_paths.py:228` already dodges this by asserting object **identity**. Do the same.
- **No cross-host byte-identity golden.** A committed golden PNG of a real render would need both this Mac's Georgia *and* its real `lassen_ca` DEM; CI has neither (`tests/conftest.py` hydrates a synthetic DEM). Prove no-op claims structurally instead.

---

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `app/render.py` | the role registry, `_font(size, role)`, `_load_font`, every text call site, `GEO_KINDS` | modify |
| `app/spec.py` | `type_rev` field + `TYPE_REVS` validation | modify |
| `app/serialize.py` | omit `type_rev` at 1 (the additive contract) | modify |
| `app/main.py` | the `Form` default for new proofs; the continue-path restore | modify |
| `app/static/api.js`, `store.js`, `compose.js`, `controls.js` | the null-means-omit client plumbing | modify |
| `scripts/render_poster.py` | a `--type-rev` flag, so the visual gate can see rev 2 | modify |
| `scripts/render_mockups.py` | its independent caption font chain | modify |
| `tests/test_type_roles.py` | the seam: role routing, env binding, cache keying | create |
| `tests/test_type_rev.py` | the rev: rev 1 unchanged, rev 2 bounded, both DPI-stable | create |
| `tests/test_labels.py:196` | asserts against `GEO_KINDS` by name; follows the rename | modify |
| `tests/test_base_cache.py`, `tests/test_ink_cache.py` | prove the new spec field is masked correctly | modify |
| `README.md`, `CLAUDE.md`, `docs/MANIFEST.md` | the operator-facing contract | modify |

No new modules. The registry is ~30 lines and belongs next to the font cache it keys.

**Test-helper note.** `tests/conftest.py` defines **no fixtures** — it hydrates synthetic DEMs at import time. Every snippet below therefore builds its own spec via a local `_spec(**kw)` helper, the shape `tests/test_relief_rev.py` uses. `from dataclasses import replace` is needed wherever a snippet calls `replace`.

---

### Task 1: `_font` takes a role, and an unbound role changes nothing

The riskiest step is the one that changes nothing. Prove that first.

**Files:**
- Modify: `app/render.py:1116-1129` (`_font`), new registry above it
- Test: `tests/test_type_roles.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_type_roles.py
"""The per-role font seam: naming a role must not move a pixel until a role is bound."""
from app import render


def test_an_unbound_role_is_the_very_same_font_object(monkeypatch):
    # Identity, not .path: the last-resort load_default() has a BytesIO path, and this
    # host has only Georgia (see the plan's constraint 4).
    monkeypatch.delenv("TECOPA_FONT", raising=False)
    plain = render._font(24)
    for role in render.TYPE_ROLES:
        assert render._font(24, role) is plain, f"unbound role {role!r} must share the chain"


def test_an_unknown_role_is_refused():
    import pytest
    with pytest.raises(ValueError):
        render._font(24, "cartouche")      # not in TYPE_ROLES -- typo, not a feature
```

- [ ] **Step 2: Run it and watch it fail**

Run: `./.venv/bin/python -m pytest tests/test_type_roles.py -q`
Expected: FAIL — `AttributeError: module 'app.render' has no attribute 'TYPE_ROLES'`.

- [ ] **Step 3: Implement the registry**

In `app/render.py`, above the font cache (`~line 1101`):

```python
# ---- typographic roles -------------------------------------------------------------
# One face per role rather than one face for the sheet: a poster has no chrome, no prose
# and no code, so the web roles do not transfer (00_Resources/typography-standards.md).
# A role is a NAME, not a file -- the faces are licensed and this repo is public, so the
# operator binds them (TECOPA_FONT_<ROLE>) and the committed default is the free chain.
TYPE_ROLES = ("body", "point", "area", "water", "title")
```

Then `_font` and its helper:

```python
def _font(size, role="body"):
    """The face for `role` at `size` px, memoized per thread on (bound face, size).
    The env bindings are read on every call, so rebinding a role takes effect on the
    next one. Roles bound to the same face share one cache entry -- and therefore one
    FT_Face, which is why the cache is thread-local (see the note above)."""
    cache = getattr(_font_local, "fonts", None)
    if cache is None:
        cache = _font_local.fonts = {}
    key = (_role_face(role), size)
    font = cache.get(key)
    if font is None:
        if len(cache) >= _FONT_CACHE_MAX:
            cache.clear()
        font = cache[key] = _load_font(*key)
    return font

def _role_face(role):
    """The operator's binding for `role`: the role-specific env var, else the sheet-wide
    TECOPA_FONT, else "" -- the committed Georgia/DejaVu chain in `_load_font`."""
    if role not in TYPE_ROLES:
        raise ValueError(f"unknown type role {role!r}; expected one of {TYPE_ROLES}")
    return (os.environ.get(f"TECOPA_FONT_{role.upper()}")
            or os.environ.get("TECOPA_FONT") or "")
```

`_load_font` is unchanged.

- [ ] **Step 4: Run it and watch it pass**

Run: `./.venv/bin/python -m pytest tests/test_type_roles.py -q` → PASS.

- [ ] **Step 5: Prove the existing sheet still renders as it did**

The structural claim, not a golden PNG (constraint 4): the suite that covers the label
pass must be untouched by the seam.

Run: `./.venv/bin/python -m pytest tests/test_labels.py tests/test_smart_labels_and_weave.py tests/test_hot_paths.py -q`
Expected: only the known Georgia MAD failures named in `CLAUDE.md`. Any other failure
means the seam is not inert — fix it here, not later.

- [ ] **Step 6: Commit**

```bash
git add app/render.py tests/test_type_roles.py
git commit -m "Give the sheet a type-role seam that binds nothing yet"
```

---

### Task 2: Bind a role from the environment

**Files:**
- Modify: `app/render.py` (only if Task 1's key is wrong)
- Test: `tests/test_type_roles.py`

**Bind to faces that exist here.** DejaVu is absent on this Mac (constraint 4), so the
two bindings are `Georgia.ttf` and `""` (the default chain), distinguished by identity.

- [ ] **Step 1: Write the failing test**

```python
def test_a_bound_role_wins_over_the_sheet_wide_face(monkeypatch):
    monkeypatch.delenv("TECOPA_FONT", raising=False)
    monkeypatch.setenv("TECOPA_FONT_POINT", "Georgia.ttf")
    monkeypatch.setenv("TECOPA_FONT_AREA", "ThisFaceDoesNotExist.ttf")   # -> fallback chain
    assert render._font(24, "point") is not render._font(24, "area")


def test_rebinding_a_role_is_not_served_from_the_cache(monkeypatch):
    monkeypatch.setenv("TECOPA_FONT_POINT", "Georgia.ttf")
    first = render._font(24, "point")
    monkeypatch.setenv("TECOPA_FONT_POINT", "AlsoNotAFace.ttf")
    assert render._font(24, "point") is not first
```

- [ ] **Step 2: Run and watch them fail.** If they pass immediately, Task 1's key already
      delivered this behaviour — that is a legitimate outcome for a registry this small.
      Keep the tests (they pin the contract) and say so in the commit message; do **not**
      read a pass here as evidence something is wrong.

- [ ] **Step 3-4: Fix the key if needed; run to green.**

- [ ] **Step 5: Commit**

```bash
git commit -am "Let the operator bind one role without rebinding the sheet"
```

---

### Task 3: Every call site names its role

**Files:**
- Modify: `app/render.py:99-108` (`GEO_KINDS`), `:2006` (the unpack), `:2009` (geography
  labels), `:1217` (marker labels), `:1449-1452` (cartouche/stats/credit/scale bar),
  `:1663` and `:2282` (compass — **there are two**), `:2355` (elevation strip),
  `:2402` (PROOF watermark)
- Test: `tests/test_type_roles.py`

The mapping, from the decision matrix:

| Call site | Role | Why |
|---|---|---|
| `_draw_labels`, `kind in ("summit", "gap")` | `point` | peaks and passes are the point-feature register |
| `_draw_labels`, `kind in ("range", "flat", "basin", "valley")` | `area` | tracked caps / small caps |
| `_draw_labels`, `kind in ("lake", "river")` | `water` | italic hydrography |
| `_title_block_metrics` title (`:1449`) | `title` | the cartouche |
| stats, credit, scale bar (`:1450-1452`), marker labels (`:1217`), both compasses (`:1663`, `:2282`), elevation strip (`:2355`), PROOF watermark (`:2402`) | `body` | **deliberately unchanged.** Sheet furniture follows the sheet-wide face; splitting it further is a decision nobody has made yet. |

- [ ] **Step 1: Write the failing test** — assert the routing, not the pixels:

```python
def test_each_label_kind_asks_for_its_own_role(monkeypatch):
    from tests.test_labels import _spec, _labels_for
    asked = []
    real = render._font
    monkeypatch.setattr(render, "_font",
                        lambda size, role="body": (asked.append(role), real(size, role))[1])
    spec = _spec(labels=True)
    render.rasterize(spec, dpi=96, region_dir="regions/lassen_ca",
                     hydro={"lakes": [], "rivers": []}, labels=_labels_for(spec))
    assert {"point", "area", "title"} <= set(asked)
```

(`_spec(labels=True)` puts a `range` and a `summit` in crop and sets `title_text="-"`,
so all three roles are reachable. `water` is not — `_labels_for` passes no lakes.)

- [ ] **Step 2: Run and watch it fail** — `asked` holds only `"body"`.

- [ ] **Step 3: Add a fourth column to `GEO_KINDS`** — `(pt_size, caps, keep_rank, role)` —
      and pass `role` at each site above. **Two consumers break on the widened tuple:**
      - `render.py:2006` — `pt_size, caps, _ = GEO_KINDS[kind]` raises `ValueError: too
        many values to unpack`. Widen it.
      - `render.py:1707, 1731, 1744` (`_label_candidates`) index `[2]` for keep-rank —
        those survive a fourth column, but re-read them to confirm nothing else unpacks.

      Update the `GEO_KINDS` docstring above line 99.

- [ ] **Step 4: Run to green, then re-run Task 1's Step 5 suite.** Naming roles still
      binds nothing, so nothing may move.

- [ ] **Step 5: Commit**

```bash
git commit -am "Name the role at every place the sheet sets type"
```

---

### Task 4: `type_rev` on the spec, omitted at 1

Follows `relief_rev` exactly. Read `app/spec.py:99,111,240-241,275,337-342` and the
omit-at-default branches in `app/serialize.py` first.

**Files:**
- Modify: `app/spec.py`, `app/serialize.py`
- Test: `tests/test_type_rev.py` (create)

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_type_rev.py
"""type_rev: the role table is a revision, not a knob (docs/relief-passes.md)."""
import json, os
from dataclasses import replace

import pytest

from app import render, serialize
from app.spec import CompositionSpec, SpecError

REGION_DIR = "regions/lassen_ca"


def _spec(**kw):
    cfg = json.load(open(os.path.join(REGION_DIR, "region.json")))
    bx = cfg["bounds"]
    cx, cy = (bx[0] + bx[2]) / 2, (bx[1] + bx[3]) / 2
    half = 18000.0
    return CompositionSpec(region_id="lassen_ca", crs=cfg["crs"],
                           crop=(cx - half, cy - half * 4 / 3, cx + half, cy + half * 4 / 3),
                           print_w_in=9, print_h_in=12, native_resolution_m=10,
                           tracks=[], hotspots=[], seed=7, title_text="-", **kw)


def test_type_rev_is_omitted_from_a_default_manifest():
    assert "type_rev" not in serialize.spec_to_json(_spec())


def test_type_rev_rides_when_set():
    assert serialize.spec_to_json(_spec(type_rev=2))["type_rev"] == 2


def test_an_unknown_type_rev_is_refused():
    with pytest.raises(SpecError):
        _spec(type_rev=3).validate(300)
```

- [ ] **Step 2: Run and watch all three fail** — the first two on
      `TypeError: unexpected keyword argument 'type_rev'`, the third on no exception raised.

- [ ] **Step 3: Implement** — `TYPE_REVS = (1, 2)` and `type_rev: int = 1` in `app/spec.py`
      with the `isinstance(..., bool)` guard the other revs use; the omit-at-1 branch in
      `app/serialize.py` beside the `profile_rev` one.

- [ ] **Step 4: Run to green.**

- [ ] **Step 5: Verify the frozen fixtures and the dataclass enumerations**

Run: `./.venv/bin/python -m pytest tests/test_provenance.py tests/test_editions.py tests/test_base_cache.py tests/test_ink_cache.py -q`

Expected: `test_provenance` / `test_editions` PASS — a failure there means the omission is
wrong; fix it, never the fixture. The two cache suites **enumerate the dataclass**, so a
new field trips them the moment it lands. Task 5 fixes that; do not defer it past this
point or the failure resurfaces inside a later full-suite gate and gets misread.

- [ ] **Step 6: Commit**

```bash
git commit -am "Add type_rev: the role table is a revision, not a knob"
```

---

### Task 5: Mask `type_rev` out of both cache keys

Immediately after Task 4 — the enumeration tests are already red.

**Files:**
- Modify: `app/render.py` (`BASE_KEY_MASK_ALWAYS`, `INK_KEY_MASK_ALWAYS`)
- Modify: `tests/test_base_cache.py`, `tests/test_ink_cache.py`

**The call is already made: mask it in both,** beside `labels` and `label_place`. Type is
painted by `_apply_labels` and `_paint_overlays`, both of which run *outside* the cached
terrain and outside the cached route ink. Do not "let the test decide" — both suites go
green either way (masked: the layer genuinely doesn't move; unmasked: the payload
genuinely differs), so the masks are a judgement about what the layers read, not a
question the tests can answer.

- [ ] **Step 1: Write the failing test** (`tests/test_base_cache.py`, using its own
      `_live_spec()` / `_cfg()` / `_key()` helpers, not bare names):

```python
def test_type_rev_does_not_stale_the_cached_terrain():
    spec = _live_spec()
    assert _key(spec) == _key(replace(spec, type_rev=2)), \
        "type paints above the terrain; a rev must not refetch the DEM"
```

- [ ] **Step 2: Run and watch it fail** — the keys differ, because `serialize` deletes
      `type_rev` at 1 and keeps it at 2.
- [ ] **Step 3: Add `"type_rev"` to both `BASE_KEY_MASK_ALWAYS` and `INK_KEY_MASK_ALWAYS`,**
      with a one-line comment on the same reasoning as `labels` / `label_place`.
- [ ] **Step 4: Run to green,** both cache suites including the enumeration tests.
- [ ] **Step 5: Commit**

```bash
git commit -am "Mask type_rev out of the terrain and ink keys: type never touches either"
```

---

### Task 6: Rev 2 is the typography slate

**Files:**
- Modify: `app/render.py` (`GEO_KINDS` → `GEO_KINDS_REVS`), `_draw_labels`, `_label_candidates`
- Modify: `tests/test_labels.py:196` (asserts `f["kind"] in render.GEO_KINDS` by name)
- Test: `tests/test_type_rev.py`

Rev 2 changes more than which file loads:

- **Area labels move to mixed case** (Advocate draws small caps from lowercase). Note this
  also silences tracking at `render.py:2008` — `tracking = ... if caps else 0` — so
  `caps` currently means two things. **Split them in the role table** (`caps` and
  `tracked` as separate columns) rather than letting the casing change quietly drop
  `GEO_TRACKING_EM`.
- **Point sizes must be re-derived, not carried across.** Hermes Maia's x-height is 0.538
  against Georgia's 0.481 — the same nominal size sets ~12% larger. Normalise on x-height
  for anything 8–13 pt.
- **The cartouche picks between Century Supra A 700 and Hermes Maia 600** (open question 2).
  Settle it on a real proof before writing the table; the head-to-head that produced this
  plan favours Century Supra.
- **`_label_candidates` (`render.py:1691`) reads `GEO_KINDS` too** (1707, 1731, 1744) for
  keep-rank, and runs *before* the draw loop. If rev 2 retunes any rank, thread `spec`'s
  rev through there as well — it already receives `spec`.

- [ ] **Step 1: Write the failing tests** (the `tests/test_relief_rev.py` shape):

```python
def test_rev_1_is_the_table_we_shipped(): ...          # the rev-1 dict equals today's literal
def test_rev_2_is_bounded_against_rev_1(): ...         # same composition, not a redesign
def test_rev_2_is_a_faithful_proof_to_final_scale(): ...  # MAD < 3.0, 96 vs 300 dpi
def test_area_labels_are_mixed_case_under_rev_2(): ...    # small caps, not ALL CAPS
def test_area_labels_keep_their_tracking_under_rev_2(): ...  # the caps/tracked split
```

- [ ] **Step 2: Run and watch them fail.**

- [ ] **Step 3: Implement** — `GEO_KINDS_REVS = {1: {...today...}, 2: {...slate...}}` read
      through `spec.type_rev`. **Rev 1's dict must be the current literal moved, not
      retyped.** Keep a `GEO_KINDS = GEO_KINDS_REVS[1]` alias or update
      `tests/test_labels.py:196` — decide which, don't leave it broken.

- [ ] **Step 4: Run the full suite.**

Run: `./.venv/bin/python -m pytest -q`
Expected: 6 failed — **and the six are the known Georgia-font failures named in
`CLAUDE.md`** (`test_bleed.py::test_full_bleed_render_keeps_furniture_off_the_bleed_band`,
two in `test_labels.py`, two in `test_oblique.py`,
`test_smart_labels_and_weave.py::test_smart_labels_are_dpi_stable`). Match the names, not
just the count.

- [ ] **Step 5: Look at a real poster.** A green suite does not prove the sheet reads.
      `scripts/render_poster.py` has no rev flag, so **add `--type-rev` first** or this
      renders rev 1 with the new faces bound — the exact combination constraint 3 says
      gets the casing wrong.

```bash
TECOPA_FONT_POINT="…/Hermes Maia 6/Hermes Maia 6 Regular.otf" \
TECOPA_FONT_AREA="…/Advocate/Advocate 34 Narr Reg.otf" \
TECOPA_FONT_WATER="…/Valkyrie A/Valkyrie A Italic.otf" \
TECOPA_FONT_TITLE="…/Century Supra A/Century Supra A Bold.otf" \
./.venv/bin/python scripts/render_poster.py --region lassen_ca --type-rev 2
```

Judge it on the real `lassen_ca` plate only — the other four have synthetic DEMs
(`CLAUDE.md`), and a synthetic plate cannot show whether a label survives real terrain.

- [ ] **Step 6: Commit**

```bash
git commit -am "Rev 2: set each role in the face the medium actually wants"
```

---

### Task 7: Make the rev reachable from the app

Without this, rev 2 ships dead. `relief_rev` (v1.13) is the worked example — copy all four parts.

**Files:**
- Modify: `app/main.py:999-1021` (the `Form` default and the payload), `:1801-1807`
  (the continue-path restore)
- Modify: `app/static/api.js:115-119`, `store.js:71-73`, `compose.js:296`, `controls.js:131`

- [ ] **Step 1: Write the failing test** — a continued edition must re-typeset like its
      predecessor, which is the whole reason the rev exists:

```python
def test_a_continued_edition_keeps_its_predecessors_type_rev():
    # a rev-1 poster continued after rev 2 ships must still set type the rev-1 way
    ...  # mirror tests/test_editions.py::test_continue_ritual_round_trip
```

- [ ] **Step 2: Run and watch it fail.**

- [ ] **Step 3: Implement**
      - `app/main.py:1000` — `type_rev: int = Form(2)` beside `relief_rev`, so **new**
        proofs get the current table while old manifests (which omit the key) stay at 1.
      - `app/main.py:~1807` — `"typeRev": spec.type_rev` beside `"reliefRev"`.
      - `app/static/store.js` — `typeRev: null` (null = omit → server default).
      - `app/static/api.js` — `type_rev: style.typeRev != null ? style.typeRev : undefined`.
      - `app/static/compose.js:296` — `typeRev: s.typeRev ?? 1`.
      - `app/static/controls.js` — a `CONTROLS` entry only if the studio should expose it;
        `reliefRev` has one, so match whatever that does.

- [ ] **Step 4: Run to green**, then `node --check` each edited JS module (there is no JS
      test runner — `CLAUDE.md`), then drive the real UI: load a poster, continue it, and
      confirm the reprint sets type the old way.

- [ ] **Step 5: Commit**

```bash
git commit -am "Carry type_rev through the endpoint and the continue ritual"
```

---

### Task 8: The marketing captions, and the docs

**Files:**
- Modify: `scripts/render_mockups.py:330-346` (`_caption_font`)
- Modify: `README.md:172`, `CLAUDE.md`, `docs/MANIFEST.md`
- Modify (workspace, outside this repo): `00_Resources/typography-standards.md`

- [ ] **Step 1: Route the mockup captions through the seam.** `_caption_font` is an
      independent chain that reads `TECOPA_FONT` but knows nothing about roles, so after
      Task 6 the marketing captions diverge from the sheet they advertise. `CLAUDE.md`
      requires every marketing image to be engine-rendered; make it call
      `render._font(size, "body")` (or `"title"` — decide and say why in the commit).

- [ ] **Step 2: Write the env-var table** into `README.md` — the five `TECOPA_FONT_<ROLE>`
      names, the fallback order, and the sentence that matters:

> The engine ships no licensed face. Roles are names; you bind them to files you have a
> licence for. A poster reprinted on a host with different bindings will not be
> byte-identical — `type_rev` pins the layout decisions, not the binaries.

- [ ] **Step 3: Record the rev in `docs/MANIFEST.md`.** Note that the file currently
      documents **neither** `profile_rev` nor `relief_rev` (grep: zero hits), so there is
      no existing section to sit beside — this adds one, and the honest move is to
      document all three revs together, including that a reader must treat an absent
      `type_rev` as 1.

- [ ] **Step 4: Add a Type row to `CLAUDE.md`,** next to the Naming table: what a role is,
      that faces are operator-side, and the one-line version of constraint 2.

- [ ] **Step 5: Close the workspace open questions** in
      `00_Resources/typography-standards.md` — fill the *Per-property implementation* row
      for Tecopa Plateworks, and answer open questions 1, 2 and 4 with what the proof
      actually settled. Question 4 asked for exactly this rev.

- [ ] **Step 6: Commit**

```bash
git commit -am "Document the type roles, and what type_rev does not promise"
```

---

## Out of scope, deliberately

- **Studio UI for binding faces to roles.** Faces are operator-side; a picker implies the
  app ships faces. Env vars until there is a reason.
- **Hashing the face into the manifest.** It would make reprint identity real, and it
  would also make a poster unreprintable on a host without that exact file. Worth its own
  brainstorm; see constraint 2.
- **Web / OG / native-app typography.** Those columns are already shipped or already
  specified.
- **Re-tuning the six known-failing MAD thresholds.** They are tuned to DejaVu metrics on
  CI and fail locally against Georgia. Binding roles will move them again. Separate
  cleanup, and it wants `TECOPA_FONT` pinned in CI first so the thresholds mean one thing.
