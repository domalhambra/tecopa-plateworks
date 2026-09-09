# Tecopa Plateworks

A local app that turns GPX, KML, and KMZ tracks into a shaded-relief poster of your journeys inside one curated plate. The poster performs as a print, a wallpaper, a film, or a social canvas. No account, no database, no cloud: the file is the archive. One FastAPI process serves the studio and the render engine.

This file is a router: the rules that must not break, and the one document to read for each change. Everything else lives in `docs/`, indexed at `docs/README.md`.

## Read this before changing that

Unnamed sections below are in `docs/changing-things.md`.

| Changing | Read first |
|---|---|
| Anything, for the first time | `README.md`, then `docs/architecture.md` |
| A venv, Python, a new machine | Set up a machine |
| The tests, a Mac-only failure | Run the tests |
| A pull touching `regions/`, a 503 naming drift | Repair an orphaned DEM |
| A plate, `region_prep.py`, labels, playa | `docs/superpowers/specs/2026-07-19-gpx-first-region-creation-design.md`, then Build a new plate |
| A relief technique | `docs/relief-passes.md` (its corrections blockquote governs), then Add a relief technique |
| What the product is for, what stays out | `docs/scope.md` |
| A spec field, `STYLE_BOUNDS`, `app/static/controls.js` | Add a spec knob or studio control |
| The manifest, a verb that reads a file | `docs/MANIFEST.md`, then Change the manifest or add a file-consuming verb |
| `engine_version`, `spec_from_json`, a reprint promise | `docs/superpowers/specs/2026-07-27-retire-the-forever-contract-design.md` |
| A font or type role | Bind fonts per role, then `00_Resources/typography-standards.md` |
| Anything under `app/static/` | Work on the studio front end |
| The farm, the landing page, Netlify | `marketing/DEPLOY.md`, then Add a region to the farm and deploy the landing page |
| A sentence a customer reads | `docs/superpowers/specs/2026-08-16-target-customer-profile-design.md`, then Edit landing or privacy copy, then `docs/marketing.md` |
| The demo journeys | `docs/superpowers/specs/2026-08-15-real-network-demo-tracks-design.md` |
| The macOS launcher | `docs/superpowers/specs/2026-07-18-macos-launcher-app-design.md`, then Rebuild the macOS launcher |
| Blender | Render a hero plate |
| A past decision | `docs/decisions.md` |
| Machine state, a trap a session hit | `docs/superpowers/handoffs/2026-08-16-collector-register-and-terrain-guard.md`, then `git log` |
| How this repo is documented | `docs/superpowers/specs/2026-09-08-documentation-layout-design.md` |

## Invariants

1. **One spec, painted at many sizes.** Compose decides the picture once in ground coordinates; rasterize paints it at any size. Region data stays in the region dir, never on the spec.
2. **Physical units, never pixels.** A pixel-sized element looks bold in the proof and vanishes in the final.
3. **Determinism within a build.** Same spec, seed, and build give identical bytes, so the proof predicts the print.
4. **One projection, the region CRS metres.** Tracks are reprojected on arrival.
5. **`app/geo.py` is the only coordinate source.** Prove the chain before tuning looks.
6. **The zoom cap at the final dpi.** A 422 on a large print of a small plate is correct.
7. **The forever-contract is retired.** `engine_version` records cross-build drift. No new revs, and never reintroduce omit-at-default. `serialize.spec_from_json` stays read-tolerant. A plate mismatch refuses with 422 unless `allow_plate_mismatch=true`. A relief pass is a no-op at its pre-feature default.
8. **`provenance.spec_from_manifest` is the one untrusted-manifest door.** Every verb that turns an uploaded file into a spec goes through it. `/api/reprint/inspect` is the exception: it builds no spec.
9. **Names that must not move.** The zTXt keyword `trailprint` is frozen forever: changing it orphans every printed poster. `ENGINE` is stamped, never read back; readers also accept `LEGACY_ENGINES`. `ENGINE_URL` is the repo's real name, since GitHub frees old names. `TECOPA_*` and the bundle id are name-neutral.
10. **Never commit a font.** The repo is public and MB Type is licensed. `.gitignore` blocks font files (commit 39ad08c).
11. **Marketing honesty.** Every marketing image is an engine render of real country: `marketing/build_deploy.py` refuses a region with no real terrain record in `assets/index.json`. Never weaken it. Every claim has a test. Plates are free.
12. **Never re-stamp `sources.json`** to silence the drift gate. The mismatch is the only record that a plate was swapped.
13. **Two venvs.** Never install the region-prep stack into `.venv`: it pulled numpy, scipy and rasterio past their pins for six weeks. `region_prep.py` runs in `.venv-prep`.
14. **Words.** Tecopa Plateworks in full, never bare Plateworks. Plate, proof, edition, share copy, save file.
15. **License.** Code AGPL-3.0-or-later, plates and the manifest schema CC0-1.0, the name under neither. An outside contribution needs a DCO sign-off or a CLA.

## Working here

- `.venv/bin/python -m pytest -n auto -m "not slow" -q` before any claim of done, the full suite before a push to `main`. Compare the failure set, not the totals.
- `ready: True` does not mean real terrain: `tests/conftest.py` hydrates a synthetic DEM. After a pull touching `regions/`, run `.venv/bin/python scripts/verify_regions.py`.
- No JS test runner. `node --check` each module, match every `$('id')` to the HTML, drive the browser.
- Only the landing page deploys, by hand. FastAPI auto-docs are off (commit a3d4ba9).
- TDD, and granular present-tense commits that say why. Cloud sessions squash-merge from `claude/**`; the Mac commits to `main` only when green.
- `tests/test_docs.py` holds this file under 2,000 tokens.

## Session logging

Log sessions to the Notion **Session Log** database. Inlined because a cloud container clones only this repo.

- Parent: `{"type": "data_source_id", "data_source_id": "60f3ea17-4424-4815-8a4b-6a4d4de61c4f"}`
- `Session Title` (title) and `date:Date:start` (ISO date)
- `Repo`: relation. **This repo is** `["https://app.notion.com/p/3a44f171f472818782c1c9dbb2b6547a"]`.
- `Activity`: build | fix | research | write | ops | plan
- `Status`: Complete | In Progress | Blocked
- `Shipped`: checkbox (`"__YES__"`) for deploys and launches
- `Tags`: a JSON array **encoded as a string**, a constrained multi-select. Use `Tecopa Plateworks`. An invented value fails the whole write.
- `Quarter` computes itself from Date. Never set it by hand.

Body sections: What We Did / Open Threads / Next Steps / Notes.

Open a **Threads** record for work left unfinished and a **Decisions** record for any durable choice, both related to the session page. A Notion decision also gets a row in `docs/decisions.md`.

- **Threads**: data source `a6971fe4-6e13-4699-a0c3-3f23d5d8b552`. `Thread` (title), `Status` (Open | Closed | Dropped), `date:Opened:start`, `Opened in`. Closing one also needs `date:Closed:start`, `Closed in`, and `Resolution`. Close the threads this session resolved.
- **Decisions**: data source `d6449689-97bd-4b10-9dc7-5d7a3d6b64f5`. `Decision` (title), `Status` (Proposed | Accepted | Superseded), `date:Date:start`, `Context`, `Consequences`, `Made in`. Never delete one. Supersede it and link `Supersedes` / `Superseded by`.

**If Notion is unreachable**, append the entry to `SESSION_LOG.md` here (newest first, append-only) and say so in the closing summary. Confirm the write returned a page ID before reporting the log as done.
