# Tecopa Plateworks

A local app that turns GPX, KML, and KMZ tracks into a shaded-relief poster of where
you have been inside one curated plate, performed as a print, a wallpaper, a time-lapse
film, or a social canvas. An archival PNG final carries its own recipe in an embedded
manifest, so the file reprints and continues itself: no account, no database, no cloud.
A share copy (`embed_spec=false`) deliberately carries none.
One FastAPI process serves a single-window browser studio and the Python render engine.
The landing page at `tecopa.plateworks.org` is static and deployed by hand. Code is
AGPL-3.0-or-later (`LICENSE`), plates and the manifest schema are CC0-1.0, and the name
is covered by neither.

## Run it

```bash
python3.14 -m venv .venv
.venv/bin/pip install -r requirements-lock.txt
.venv/bin/pip install pandas geopandas
.venv/bin/pip install -r requirements-share.txt
.venv/bin/uvicorn app.main:app --reload        # the studio, http://127.0.0.1:8000
```

The three installs are CI's recipe (`.github/workflows/ci.yml`). The two extras sit
outside the lock on purpose, so the region-prep and MP4 tests run instead of skipping.
To build new plates from the studio, create a second venv once:
`python3 -m venv .venv-prep && .venv-prep/bin/pip install -r requirements-regionprep.txt`.
Never install that stack into `.venv`. `scripts/macos/build_app.sh --install` builds the
macOS launcher, which runs the engine from this repo's `.venv` on port 8848. The full
recipe, and what to do when a venv dies, is in `docs/changing-things.md`.

## Prove a change

```bash
.venv/bin/python -m pytest -n auto -m "not slow" -q   # the fast tier, CI's pull-request tier
.venv/bin/python -m pytest -n auto -q                 # the full suite, about three minutes. CI runs it on every push to main
.venv/bin/python -m pytest tests/test_docs.py -q      # the docs check alone
.venv/bin/python scripts/verify_regions.py            # every plate's hash and geometry state
```

`tests/test_docs.py` calls `docs_check.check_repo` from `scripts/docs_check.py` with the
three required docs, `docs/architecture.md`, `docs/changing-things.md` and
`docs/decisions.md`, and five known-absent entries: the gitignored `cache/`, `blobs/`,
`assets/` and `.venv/`, plus the uncommitted metal-render assessment.
Real DEMs are gitignored, so `tests/conftest.py` hydrates a synthetic one per plate and
a fresh clone runs the render suites. Some tests fail only on the Mac. Compare the
failure set in `docs/changing-things.md`, under Run the tests, not the totals. The
studio has no JS runner: `node --check` each module, then drive the browser.

## Ship it

Only the landing page ships, by hand, from a staged root. The engine runs locally and
the launcher is a personal build.

```bash
.venv/bin/python scripts/render_asset_farm.py --regions <ids>   # engine renders of real terrain
python3 marketing/build_deploy.py                               # the staged root. The terrain guard refuses a synthetic region
netlify deploy --prod --dir=<staged root> --site=1902a58d-74a9-4def-8b4e-d93793f81ac4
```

The runbook is `marketing/DEPLOY.md`. Every image on the page is an engine render, and
every claim on it has a test behind it (`tests/test_marketing_page.py`).

## Where to go next

| You want to | Read |
|---|---|
| Change anything, and know the rules first | `CLAUDE.md` |
| Learn which file owns what, and which test covers it | `docs/architecture.md` |
| Do a task: a machine, a plate, a relief pass, a knob, fonts, the front end, the deploy, the launcher | `docs/changing-things.md` |
| Know why something is the way it is | `docs/decisions.md` |
| Know what the product is for, and what stays out | `docs/scope.md` |
| Know what a poster file carries | `docs/MANIFEST.md` |
| Everything else: the specs, plans, handoffs, and assessments | `docs/README.md` |
