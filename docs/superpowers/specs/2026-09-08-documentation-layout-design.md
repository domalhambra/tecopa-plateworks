# Documentation layout

**Status:** Accepted 2026-09-08. Implemented, pending commit.
**Scope:** How this repo is documented, per the workspace's
`00_Resources/documentation-standard.md`.
**Tier:** Medium. The repo is a data pipeline (region bake, ingest, compose,
rasterize, manifest) with 24 modules under `app/`, 16 scripts under `scripts/` plus the
macOS launcher's build, icon and smoke scripts, and a 60-file pytest suite (59 before
this rollout added `tests/test_docs.py`), so it needs an architecture doc and a task doc. It keeps the handoffs,
assessments, and quality folders it already carried under `docs/superpowers/`. Not
Large: there is no `PROJECT_CHARTER.md` or `DESIGN.md`, charters are Dom's to write,
and the only deploy is a manual runbook (`marketing/DEPLOY.md`), not a release process.

## What was wrong

- `CLAUDE.md` was a 27 KB operator manual, about 6,722 tokens against a budget of
  2,000: the naming table with its history, the versioned-drift essay, venv
  forensics, a 4 KB Known local failures section with a sha256 drift table, the macOS
  app, the region gotchas, the map of the repo. The check reported the budget, four
  missing routes, and eight dead paths on this Mac, where the gitignored runtime folders
  exist: the GitHub repo in owner/name form, `bin/python` from a split backtick span,
  four bare folder names and `quality/golden` in the map row, and `plates/` in the
  drift section.
- `README.md` was a 22 KB feature tour: setup, the macOS app, layout, GPX-first, GNIS
  labels, self-describing posters, reprint, fonts, wallpapers, Journey Light, the Looks
  knobs, water, hero plates, then the invariants a second time. It named a plate
  release ritual and a `plates` index that never ran (no plates folder has ever
  existed: commit f518be8 and the 2026-07-12 implementation handoff say so). Its Setup
  omitted the two extras CI installs. It still called the front end a thin browser aim
  view, replaced by the single-window studio on 2026-07-21 (commit 4e3a22f), and said no
  engine version rides the file two paragraphs before saying every manifest carries
  `engine_version`. Its Tests section said `pytest -q` with no tier.
- No `docs/README.md`, `AGENTS.md`, `docs/architecture.md`, `docs/changing-things.md`,
  or `docs/decisions.md`. Forty-five Markdown files sat under `docs/` (one untracked)
  with nothing saying which handoff was current. `HANDOFF.md` reads like a pointer to
  the newest and is the 2026-06-30 original with a banner to the 2026-07-03 one.
- No check wired.
- `docs/relief-passes.md` describes the forever-contract as binding in its body,
  corrected only by a blockquote partway in, at the end of "The three moving parts"
  (line 68 of 161). A reader who scans the first screen does not see it. The index row
  and the relief section of the task doc name where it sits and say it governs.
- The Mac's gitignored Netlify state still names the `Badwater Trails` folder as the
  publish path, from before the 2026-09-02 folder rename (commit d5a6d89). The deploy
  passes `--dir`, so it is harmless. The deploy section says so.

## The layout

| File | Role |
|---|---|
| `README.md` | What the system is, run it, prove a change, ship it, where to go next. |
| `CLAUDE.md` | A router under 2,000 tokens: identity, the "read this before changing that" table, fifteen invariants with reasons, working here, session logging inlined with the Repo relation. |
| `AGENTS.md` | Points any other agent at the guide, with the dev, test, and build commands and the two rules an agent breaks most easily. |
| `docs/README.md` | Every document with a "read when": working docs, reference, specs, plans, handoffs, assessments, quality, the runbook outside the folder, canon outside the repo. |
| `docs/architecture.md` | The shape, the module map (file, owns, tested by), runtime behavior, environment, delivery, the harness, cross-repo dependencies. |
| `docs/changing-things.md` | Fourteen task sections, from setting up a machine to recording a decision. |
| `docs/decisions.md` | Dated log from the specs, the plans, the handoffs, and the commit history, with a Rejected and deferred table. |
| `docs/MANIFEST.md`, `docs/relief-passes.md`, `docs/scope.md`, `docs/marketing.md` | Kept in place as reference, path-checked, indexed. |
| `docs/superpowers/` | The seven specs already here, plus this file. Plans, handoffs, assessments, and quality docs stay and are indexed as history. |
| `scripts/docs_check.py` | The check, vendored byte for byte from the workspace copy. The pair still needs its row in the workspace's `00_Resources/VENDORED.md`, which this rollout may not edit. |
| `tests/test_docs.py` | Runs the check with the suite. |

## What differs from the earlier rollouts

- The check is vendored, not ported: this is a Python repo. `tests/test_docs.py` is
  collected by the fast tier without a CI change, because `pytest.ini` sets
  `testpaths = tests` and `tests/conftest.py` does not classify it slow.
- Known-absent entries: the gitignored runtime folders `cache/`, `blobs/`, `assets/`,
  and `.venv/` (`dist/` is skipped by default), plus the exact path
  `docs/superpowers/assessments/2026-09-02-metal-render-viability.md`. That file
  exists on the Mac, is untracked, and waits on Dom's review. The index carries its row
  with that note, so a clone without it stays green. The five entries replace the
  check's default set: `SESSION_LOG.md` is tracked here, so excusing it would only hide
  a real deletion later.
- No file moved. `docs/MANIFEST.md`, `docs/marketing.md`, `docs/relief-passes.md`, and
  `docs/scope.md` stay at the top level. `docs/trails for claude design/` holds no
  Markdown.
- No spec copied in. All seven specs already lived here, and Badwater OS holds none for
  this repo.
- The seven-test Mac-only failure list moved from the guide to the Run the tests section
  of the task doc. It is a dated measurement, so the router keeps a pointer and not the
  list.
- A charter and a `DESIGN.md` are deferred to Dom, recorded in the Rejected and deferred
  table of `docs/decisions.md`. Charters are hand-written, never generated.
- No CI or gitignore change.
- Four Notion threads the audit touched, none closed here. The base-layer cache Phase 2
  thread's premise is contradicted by commit 1a4ea88: the cut point already moved
  before labels. The auto-docs switch-off (commit a3d4ba9) is documented as current
  state, and keep or revert stays open. The Python mismatch (the Mac venv on 3.14,
  `.python-version` on 3.11) is stated in Set up a machine as a recorded thread, not a
  verdict. The terrain-record thread ("re-render all five plates") was checked and left
  alone: `assets/index.json` on this Mac carries a non-synthetic terrain record for all
  five plates, but that file is gitignored, so the evidence is machine-local and proves
  nothing about another machine.

## Done means

- `.venv/bin/python -m pytest -n auto -m "not slow" -q` passes, `tests/test_docs.py`
  included, apart from the one documented font failure on this Mac.
- Every claim in the new docs is checked against the code, the specs, and the git log by
  a second pass before commit.
- Nothing under Badwater OS was edited.
