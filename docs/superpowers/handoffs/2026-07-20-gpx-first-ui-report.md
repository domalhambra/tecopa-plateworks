# Handoff: re-port the GPX-first UI (and the Tecopa rename) onto the Studio architecture

**Date:** 2026-07-20
**Status:** Backend shipped on `main` (#38). Front-end deferred — this document is the brief for it.

---

## 1. Why this handoff exists

Two branches (`macos-launcher-app`, `gpx-first-flow`) built a full feature — backend *and* UI —
against the pre-Studio front end (a linear 4-step wizard in a single `app.js` + `state.js`).
While they were in flight, **#34 "Studio GUI redesign"** and **#35 "Studio polish"** merged and
replaced that wizard with a section-based studio split across ~15 ES modules.

The two architectures conflict structurally, not textually. Rather than force a merge that would
have discarded the redesign or produced broken JS, we split the work:

- **#38 (merged)** — all backend: the macOS launcher, the Tecopa Printworks rename in Python, and
  the complete GPX-first region-creation API. `app/static/` was left **byte-identical to `main`**.
- **#36 / #37 (closed, branches retained)** — reference for the UI that still needs porting.

So today: **the engine can plan and build a region from dropped tracks, but nothing in the UI
calls it.** The endpoints are reachable only via `curl`.

---

## 2. What is already on `main` (the contract to build against)

All of this is shipped, tested, and verified against live USGS servers — do not rebuild it.

### Endpoints (`app/main.py`)

| Endpoint | Behavior |
|---|---|
| `POST /api/regions/plan` | multipart `files=` (same File[] a failed upload had). Returns `{us_covered, bbox, epsg, name_prefill, id, prep_ready, resolution_m, grid, grid_mpx, est_dem_mb, n_slices, over_budget}`. Pure logic — never fetches or writes. |
| `POST /api/regions/build` | JSON `{id, name, bbox, epsg}`. Re-validates id shape, US coverage, collision, epsg range, and over-budget **server-side** (the client's plan response is untrusted). Returns `{job}`. |
| `GET /api/regions/build/{jid}` | `{state: queued\|running\|done\|error, progress, error, result: {region, labels_note}}` |

Runs on a **dedicated single-slot queue** (`BUILD_QUEUE`), so a multi-minute build never blocks
poster renders. On success it hot-reloads the region registry in place — no restart needed.

### Supporting modules

- `app/regionbuild.py` — `derive_bbox` (track bounds + 20% pad, 3 km floor), `utm_epsg`,
  `bbox_covered` (US 3DEP envelope), `slugify`/`unique_id`, and `run_build` (spawns
  `region_prep.py` in `.venv-prep`, streams stdout to job progress, sweeps a partial
  `regions/<id>/` on failure, treats a GNIS-labels failure as non-fatal).
- `ingest.lonlat_extent` — raw lon/lat bounds + name prefill across GPX/KML/KMZ, **including
  `<rte>` routes**, with no region required.
- `app/jobs.py` — `progress` field + `set_progress` (updates under the queue lock).

### Tests (all passing)

`tests/test_regionbuild.py` (planning helpers, route-only GPX) and
`tests/test_region_endpoints.py` (plan/build against **stub prep scripts** — progress streaming,
failure sweep, labels-nonfatal, hot-reload, plus over-budget / bad-epsg / oversize / collision
rejections). No network needed. Full suite on `main`: **629 passed, 8 skipped** (skips are
optional-dependency gates).

### Environment

`.venv-prep` is installed locally (gitignored). `PREP_PYTHON` defaults to `.venv-prep/bin/python`,
overridable via `TECOPA_PREP_PYTHON`. Without it, `plan` returns `prep_ready: false` and the UI is
expected to show setup instructions instead of a Build button.

---

## 3. The new architecture (what you're building into)

**No linear wizard.** `state.step`/`state.steps` are gone. The studio is a **section machine**
driven by a left rail:

```
library · compose · style · layers · light · social · films · exports
```

`app.js` is now a ~286-line router: `SURFACE`/`PANEL`/`TITLE` maps decide which surface and
inspector panel show per section, and `ready(section)` gates access (options need tracks;
social/films need a stamped proof).

| File | Responsibility |
|---|---|
| `app.js` | Router (`setSection`), shell sync, theme, palette, **drag-anywhere drop router**, `startOver`, `loadRegions` |
| `store.js` | `state` (was `state.js`) + `setField()` — the single choke point where the stale-proof guard lives. **Use `setField` for user edits**, not direct assignment. |
| `library.js` | The Library home: `buildRegionGallery()`, poster inspect/continue/reprint |
| `compose.js` | Map workspace: `doUpload()`, `selectRegion()`, `continueFromPoster()`, framing |
| `ui.js` | `$`, `toast(msg, kind)`, `announce`, `escapeHtml`, `saveBlob`, `withTransition` |
| `api.js` | Fetch wrappers; throws `ApiError` carrying `.status` and `.message` |
| `controls.js` / `inspector.js` / `presets.js` | Declarative control registry → inspector panels |
| CSS | `tokens.css` → `base.css` → `shell.css` → `panels.css` (`style.css` is legacy-ish) |

### Key integration points (verified line numbers on `5083073`)

1. **`compose.js:212`** — `catch (e) { toast('Upload failed: ' + e.message, 'error'); }`
   This single line is where the **no-region 422 branch** hooks in. The old code detected
   `e.status === 422 && /any available region/.test(e.message)`. `ApiError` still carries both
   fields, so that check ports as-is.

2. **`app.js:221-230`** — the drag-anywhere router **already routes GPX-first**:
   ```js
   if (/\.png$/i.test(f.name)) { setSection('library'); library.openPoster(f); }
   else if (/\.(gpx|kml|kmz)$/i.test(f.name)) { setSection('compose'); compose.doUpload([f]); }
   ```
   Dropping a track file anywhere already jumps to Compose and uploads. **A meaningful part of
   "drop-first" already exists** — don't rebuild it, build on it.

3. **`library.js:37-51`** — `buildRegionGallery()` renders selectable region cards that call
   `compose.selectRegion(id)` and jump to Compose. This is the region-first affordance the
   original design wanted to demote.

4. **`index.html:75-79`** — the Library home still leads region-first:
   *"Turn your tracks into a poster / Choose a region and drop your GPX…"* with a **Regions**
   gallery as the first thing on the page.

5. **`api.js`** — the `planRegion` / `buildRegion` / `buildStatus` wrappers were reverted out.
   They must be re-added (they're small; see `git show origin/gpx-first-flow:app/static/api.js`).

---

## 4. What needs porting

### A. Tecopa Printworks rename (front-end only — backend is done)

Small and mechanical, but **must be done as one atomic set** — a partial rename caused a real bug
during integration (`index.html` used `localStorage.getItem('tecopa')` while `store.js` still had
`LS_KEY = 'trailprint'`, silently orphaning saved prefs).

- `index.html:6` `<title>`, `:10` inline `localStorage` key, `:26` brand markup
  (`TrailPrint <b>Studio</b>` → `Tecopa <b>Printworks</b>`)
- `store.js:84` `LS_KEY` — **must match the inline key in `index.html`**
- `help.html` — several prose mentions
- `api.js`, `style.css`, `library.js`, `app/mockups.py` — prose/comment mentions
- Decide: is the product still "Studio"? The rail/section UI is literally a studio, so
  "Tecopa Printworks" alone may read better than "Tecopa Printworks Studio".

**Migration question:** changing `LS_KEY` orphans existing saved prefs (theme, region, print size).
Either accept the reset or read the old key once and migrate.

### B. GPX-first flow

The original design assumed removing a linear Region step. **That step no longer exists**, so the
design needs revisiting rather than transcribing. What carries over vs. what's open:

**Carries over unchanged (validated by real use):**
- The creation-card content model: honest US-only state, honest `.venv-prep`-missing state
  (show setup command, no Build button), cost estimate, editable name prefilled from GPX `<name>`.
- Streamed build progress → on `done`, re-upload the kept `File[]` so the tracks land on the new
  plate.
- A **Matched vs Built** distinction in the region label.
- Always leave a visible exit (the old build card dead-ended when both non-build states hid the
  only button — see §6).

**Needs a fresh decision (bring to brainstorm):**
1. **Where does the creation card live?** The upload fails in Compose, but the Library home owns
   region choice. Card in Compose (where the failure happened) or Library (where regions live)?
2. **Does the Library home stop leading with the region gallery?** The GPX-first thesis says the
   region is an *outcome*. Options: lead with a dropzone and demote the gallery to "Built plates";
   or keep the gallery but reframe the copy. This is the core UX call.
3. **Is a modal plates dialog still needed?** The Library section already *is* a browsable gallery
   surface — the old `<dialog>` may be redundant now.
4. **Does the build get an Exports-style job card?** There's now a real jobs surface
   (`jobs.js`, Exports section) that didn't exist in the old wizard. A region build is a
   long-running job — it may belong there rather than in a bespoke card.

---

## 5. Reference material

- **Design spec:** `docs/superpowers/specs/2026-07-19-gpx-first-region-creation-design.md`
  (decisions + rationale; the backend half is shipped, the UI half is the part to re-think)
- **Old implementation:** `git show origin/gpx-first-flow:app/static/app.js` — the
  `enterCreationFlow` / `startBuild` / `showBuildError` functions are sound logic; only their
  DOM/section assumptions are stale. Same branch has the card markup in `index.html` and the
  `.build-card` / `.plates-dialog` CSS.
- **Plan (backend already executed):** `docs/superpowers/plans/2026-07-20-gpx-first-region-creation.md`

---

## 6. Hard-won lessons (do not re-learn these)

From the adversarial reviews and live browser verification of the original implementation —
**nine confirmed bugs**, several of which will recur if the port is naive:

1. **Refresh the client region cache after a build.** A session-built plate never entered
   `state.regions`, so `activeRegion()` returned `null` and every Frame-step guard
   (refit-on-size-change, zoom-floor warning, feasibility gate) silently no-op'd for exactly the
   new region. Fix: `state.regions = await api.getRegions()` before re-uploading.
2. **The creation card must always have an exit.** Both honest non-build states hid the only
   button *and* Start Over was still hidden (it's only revealed on upload success), leaving a
   dead-end recoverable only by reload. Reveal the exit when entering the card.
3. **Clear the stale region label.** Entering the creation flow (or Start Over) left the previously
   matched region name in the toolbar. In the new architecture `refreshShell()` reads
   `state.regionName`, so clear the state, not just the DOM.
4. **Don't put full-width buttons inside `.map-pane`.** It's a centered flex row with an absolutely
   positioned dropzone overlay; in-flow children render as slivers peeking around the 20px inset.
   Put secondary actions outside it.
5. **Partial renames break things.** See the `LS_KEY` bug in §4A.
6. **Choose test coordinates carefully.** `elko_bonneville` is a corridor-scale plate covering much
   of NV/UT — "obviously out-of-plate" western coordinates often match it. Virginia (~-79.5, 37.8)
   is reliably outside every current plate; the Alps for the non-US path.

---

## 7. Verification approach that worked

There is no JS test runner, so:

- **`node --check`** on every edited module (copy to `.mjs` first) catches syntax errors cheaply.
- **Cross-reference every `$('id')` against `index.html`** after DOM surgery — dangling ids were a
  recurring near-miss.
- **Drive the real UI in a browser.** Click coordinates are unreliable in the headless preview
  (0×0 viewport), but `javascript_tool` works well: dispatch a synthetic `DragEvent` with a
  `DataTransfer` carrying a constructed `File` to exercise the true drop → upload → 422 → card
  path. This is how all four card states were verified.
- **The real build takes ~17s** for a small area (~0.4 Mpx). Verified end to end against live
  USGS 3DEP/NHD: DEM, hydro, landcover, GNIS labels, sha256 provenance, then a rendered proof.

**Note:** the engine's zoom cap will correctly 422 a large print of a small region
(`"1.0 m/px requested, data floor is 10 m/px"`). That is the invariant working, not a bug — use a
small print size when smoke-testing a freshly built small plate.

---

## 8. Suggested first steps

1. Read this document and the design spec's §"Flow design".
2. Open the app on `main` and click through the studio — the sections, the rail gating, the Library
   home — so the target architecture is concrete rather than described.
3. Brainstorm the four open questions in §4B. The backend contract is fixed, so this is purely a
   UX/placement design conversation.
4. Then plan and implement. Consider doing the rename as its own small, atomic PR first — it's
   independent, low-risk, and removes noise from the feature diff.
