# Per-Role Font Seam Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the sheet set each typographic role in its own face — point labels, area labels, hydrography, cartouche — instead of stamping one face through `_font(size)`, so the slate in `00_Resources/typography-standards.md` can actually ship.

**Architecture:** One registry. `_font(size)` grows a `role` argument backed by a `TYPE_ROLES` table; every text call site names its role. Which *files* fill those roles stays operator-side (env vars), because MB Type is licensed and this repo is public. The role table — assignments, point sizes, tracking, casing — simply changes when it changes.

**Tech Stack:** Python 3.14, Pillow (`ImageFont.truetype`), pytest. No new dependencies.

> **Revised 2026-07-27**, after the decision in
> `docs/superpowers/specs/2026-07-27-retire-the-forever-contract-design.md`. The first
> version of this plan carried a `type_rev`, cache-key masking for it, and endpoint plus
> client plumbing — three tasks and most of its difficulty — solely to keep old posters
> re-rendering byte-identically. That promise is being retired, so the role table changes
> in place and those tasks are gone. What remains is the seam itself.

*Line numbers below were checked against `main` on 2026-07-27. Re-grep before trusting any of them.*

---

## Background the implementer needs

Read these before starting:

- `CLAUDE.md` → *Invariants*. Physical units, determinism, one projection, registration,
  the zoom cap. All still non-negotiable. (Its *forever-contract* section is being
  rewritten under the spec above — do not add a revision for this work.)
- `00_Resources/typography-standards.md` (workspace, not this repo) → the decision matrix
  and *Open questions* 1, 2 and 4. This work settles 1 and 2 on a real proof; 4 asked for a
  `type_rev` and is answered by the retirement decision instead.
- `app/render.py:1116-1147` — the font cache and `_load_font`, the code being changed.
- `app/render.py:99-108` — `GEO_KINDS`, the per-kind size/caps/rank table this plan extends.

### Four constraints that shape the design

**1. Faces cannot be committed.** MB Type is licensed per-user; the repo is AGPL-3.0 and public, and `README.md:172` already records that the engine bundles no proprietary face. So the seam selects a *role*, and the operator binds roles to files. The committed default must stay the freely-redistributable chain (`Georgia` → DejaVu). This is **enforced, not remembered**: commit `39ad08c` added `*.otf` / `*.ttf` / `*.woff` / `*.woff2` to `.gitignore` because MB Type licence paragraph 7 names "a source repository" explicitly. Do not weaken those patterns to make a test convenient.

**2. Font identity lives outside the manifest, and that is now fine.** `TECOPA_FONT` changes the picture today and rides in no manifest. Under the retired contract this was a hole to defend against; it is now simply how it works. Recording the bound faces in the manifest as a *note* is deferred (see the spec's "Not decided here") — do not build it as part of this work.

**3. Advocate is a caps/small-caps face, not a text face.** Its lowercase positions draw small caps and it exposes no `smcp`. So under the slate, area labels must be passed **mixed case** so the lowercase renders as small caps — the opposite of today's `name.upper()` at `render.py:2007`. A face swap alone gets this wrong; the casing rule belongs in the role table.

**4. This host is font-poor, and CI is font-poor differently.** Verified 2026-07-27: `DejaVuSans.ttf` and `DejaVuSerif.ttf` are **not installed on this Mac** — only `Georgia.ttf` resolves. CI's Ubuntu is the mirror image (DejaVu, no Georgia); that asymmetry is the documented cause of the six known MAD failures in `CLAUDE.md`. Two consequences the tests must respect:
- **Never assert on `FreeTypeFont.path`.** The last-resort `ImageFont.load_default(size)` returns a font whose `.path` is a `_io.BytesIO`, so a `"Sans" in font.path` check raises `TypeError` rather than failing cleanly. `tests/test_hot_paths.py:228` already dodges this by asserting object **identity**. Do the same.
- **No cross-host byte-identity golden.** A committed golden PNG of a real render would need both this Mac's Georgia *and* its real `lassen_ca` DEM; CI has neither (`tests/conftest.py` hydrates a synthetic DEM). Prove no-op claims structurally instead.

---

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `app/render.py` | the role registry, `_font(size, role)`, every text call site, `GEO_KINDS` | modify |
| `scripts/render_mockups.py` | its independent caption font chain | modify |
| `tests/test_type_roles.py` | the seam: role routing, env binding | create |
| `tests/test_labels.py` | the slate's casing and tracking assertions | modify |
| `README.md`, `CLAUDE.md` | the operator-facing contract | modify |

No new modules, no spec field, no client changes. The registry is ~30 lines and belongs next to the font cache it keys.

**Test-helper note.** `tests/conftest.py` defines **no fixtures** — it hydrates synthetic DEMs at import time. Snippets below build their own specs via the local `_spec(**kw)` helper in `tests/test_labels.py`.

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
      and pass `role` at each site above. **Two consumers touch the tuple:**
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

### Task 4: Change the table to the slate

No rev, no gate. The table changes and new renders use it — including re-renders of older
posters, which is now an accepted consequence
(`specs/2026-07-27-retire-the-forever-contract-design.md`).

**Files:**
- Modify: `app/render.py` (`GEO_KINDS`, `_draw_labels`)
- Test: `tests/test_labels.py`

Three changes ride together, and none of them is "swap the face":

- **Area labels move to mixed case** (Advocate draws small caps from lowercase). Note this
  also silences tracking at `render.py:2008` — `tracking = ... if caps else 0` — so `caps`
  currently means two things. **Split it into `caps` and `tracked`** rather than letting
  the casing change quietly drop `GEO_TRACKING_EM`.
- **Point sizes must be re-derived, not carried across.** Hermes Maia's x-height is 0.538
  against Georgia's 0.481 — the same nominal size sets ~12% larger. Normalise on x-height
  for anything 8–13 pt.
- **The cartouche picks between Century Supra A 700 and Hermes Maia 600** (open question 2).
  The head-to-head rendered on 2026-07-27 favours Century Supra: at 7.6 pt over relief with
  a 1.1 pt halo, Hermes Maia is clearly the better *label* face, but the cartouche is
  display type on paper where the atlas lineage reads. Confirm on a proof before writing it.

- [ ] **Step 1: Write the failing tests**

```python
def test_area_labels_are_mixed_case(): ...        # small caps under Advocate, not ALL CAPS
def test_area_labels_keep_their_tracking(): ...   # the caps/tracked split
def test_point_and_area_labels_are_still_dpi_stable(): ...   # MAD < 3.0, 96 vs 300 dpi
```

- [ ] **Step 2: Run and watch them fail.**

- [ ] **Step 3: Implement** the widened table and the `caps` / `tracked` split.

- [ ] **Step 4: Run the full suite.**

Run: `./.venv/bin/python -m pytest -q`
Expected: the six known Georgia-font failures named in `CLAUDE.md`
(`test_bleed.py::test_full_bleed_render_keeps_furniture_off_the_bleed_band`, two in
`test_labels.py`, two in `test_oblique.py`,
`test_smart_labels_and_weave.py::test_smart_labels_are_dpi_stable`) — **match the names,
not just the count.** Those six are MAD-threshold failures tuned to DejaVu metrics; binding
roles will move their numbers. If one crosses back under 3.0, that is not a bug — record it.

- [ ] **Step 5: Look at a real poster.** A green suite does not prove the sheet reads.

```bash
TECOPA_FONT_POINT="…/Hermes Maia 6/Hermes Maia 6 Regular.otf" \
TECOPA_FONT_AREA="…/Advocate/Advocate 34 Narr Reg.otf" \
TECOPA_FONT_WATER="…/Valkyrie A/Valkyrie A Italic.otf" \
TECOPA_FONT_TITLE="…/Century Supra A/Century Supra A Bold.otf" \
./.venv/bin/python scripts/render_poster.py --region lassen_ca
```

Judge it on the real `lassen_ca` plate only — the other four have synthetic DEMs
(`CLAUDE.md`), and a synthetic plate cannot show whether a label survives real terrain.
Check the two range labels specifically: they exercise the curved-label path fixed in
`0b6b217`, and Advocate's condensed widths are exactly what that path was starved of.

- [ ] **Step 6: Commit**

```bash
git commit -am "Set each role in the face the medium actually wants"
```

---

### Task 5: The marketing captions, and the docs

**Files:**
- Modify: `scripts/render_mockups.py:330-346` (`_caption_font`)
- Modify: `README.md:172`, `CLAUDE.md`
- Modify (workspace, outside this repo): `00_Resources/typography-standards.md`

- [ ] **Step 1: Route the mockup captions through the seam.** `_caption_font` is an
      independent chain that reads `TECOPA_FONT` but knows nothing about roles, so after
      Task 4 the marketing captions diverge from the sheet they advertise. `CLAUDE.md`
      requires every marketing image to be engine-rendered; make it call
      `render._font(size, "body")` (or `"title"` — decide and say why in the commit).

- [ ] **Step 2: Write the env-var table** into `README.md` — the five `TECOPA_FONT_<ROLE>`
      names, the fallback order, and the honest sentence:

> The engine ships no licensed face. Roles are names; you bind them to files you have a
> licence for. A poster rendered on a host with different bindings will look different —
> the bindings are operator state, not part of the file.

- [ ] **Step 3: Add a Type row to `CLAUDE.md`,** next to the Naming table: what a role is,
      that faces are operator-side, and the one-line version of constraint 1.

- [ ] **Step 4: Close the workspace open questions** in
      `00_Resources/typography-standards.md` — fill the *Per-property implementation* row
      for Tecopa Plateworks, and answer open questions 1 and 2 with what the proof settled.
      Question 4 asked for a `type_rev`; record that it was answered by retiring the
      forever-contract instead, and point at the spec.

- [ ] **Step 5: Commit**

```bash
git commit -am "Document the type roles and what binds them"
```

---

## Out of scope, deliberately

- **Studio UI for binding faces to roles.** Faces are operator-side; a picker implies the
  app ships faces. Env vars until there is a reason.
- **Recording the bound faces in the manifest.** Deferred by the retirement spec — with the
  promise gone it would be a note, not a guarantee. Revisit after this lands.
- **Web / OG / native-app typography.** Those columns are already shipped or already
  specified.
- **Re-tuning the six known-failing MAD thresholds.** They are tuned to DejaVu metrics on
  CI and fail locally against Georgia. Binding roles will move them again. Separate
  cleanup, and it wants `TECOPA_FONT` pinned in CI first so the thresholds mean one thing.
