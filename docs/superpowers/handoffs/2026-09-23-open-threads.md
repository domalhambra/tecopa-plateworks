# Handoff: Tecopa's open threads, 2026-09-23

Every Tecopa thread still open in `plateworks-session-log` on 2026-09-23.
Ten threads. Each section below carries the thread's exact title, so you can
find it in `threads.md` and close it there.

Written at `da77791` on `main`, working tree clean. Each "State" line was
checked against the repo on 2026-09-23, not copied from the thread.

Two Tecopa threads closed on 2026-09-23 and need no work:

- The bleed-band test thread duplicates the eight-test thread in section 3.
- The FastAPI auto-docs stay off. Dom kept commit `a3d4ba9`.

## Why this order

The goal is a working path from a customer's GPX file to a paid print. The
customer path is the mailto order link on the landing page, then a render in
the studio on the Mac. Two things block it: an undecided price, and deploys
that refuse until five plates re-render. Everything else waits behind those
two.

The re-render reads the demo tracks: `scripts/render_asset_farm.py` line 275
calls `network_tracks()`. Settle the two demo-track threads before the
re-render, or you render twice.

## Before you start

- Read `../../../CLAUDE.md`, then `../../changing-things.md` § Run the tests.
- Use the venv. Bare `pytest` fails with `No module named 'rasterio'`.
  Fast tier: `.venv/bin/python -m pytest -n auto -m "not slow" -q`.
  Full suite: `.venv/bin/python -m pytest -n auto -q`.
- Compare the failure set, not the totals.
- Items marked **Dom** need his judgment or his files. Ask him.

## Order

1. **Dom**: the print price.
2. The two demo-track threads, then the plate re-render.
3. The eight Mac-only test failures: confirm, then answer one question.
4. **Dom**: the ink budget, with a real multi-year GPX set.
5. Hygiene: pycache, the CI Python version, the Metal record.
6. **Dom**: the cache validation by eye.

## 1. Decide the print price: the profile says $80, the page says $149

State: `marketing/landing.html` line 488 sells The Print at $149. Dom's own
sense for the target customer is $80 at 18×24. The tension is recorded in
`../specs/2026-08-16-target-customer-profile-design.md`, Consequences §4.

Task: ask Dom to choose one: cut the price, sell a larger sheet at $149, or
hold at $149 and test. Then change the pricing band only. No other copy
names a price.

Done when: the pricing band shows Dom's number and the deploy in section 2
carries it.

## 2. Demo tracks, then the re-render

### Three plates render 7 journeys where 8 were intended (disconnected OSM pockets)

State: unchanged. `network_tracks()` is at `scripts/track_network.py` line
446.

Recommendation: when a destination is unreachable, retry with the next
candidate from the pool. Keep the honest log line when the pool runs out.
Add a test with a disconnected network.

Done when: `susanville_reno`, `rifle_aspen` and `tushar_beaver_ut` each
compose eight journeys.

### Trip lengths on corridor plates read as road trips, not day hikes (taste call)

State: shipped as-is on 2026-08-16 with Dom's approval. The knobs are
`TRIP_SPAN_FRAC` and `TRIP_SPAN_MAX_M` in `scripts/track_network.py` lines
70 and 72.

Task: ask Dom one question: keep the lengths, or bias corridor plates toward
fewer, longer journeys. If he keeps them, close the thread as accepted. Ask
before the re-render.

### Re-render all five plates to stamp terrain records (deploys refuse until then)

Task: run the farm. It takes hours, so run it in the background.

```
./.venv/bin/python scripts/render_asset_farm.py --regions elko_bonneville lassen_ca rifle_aspen susanville_reno tushar_beaver_ut
```

Then run `marketing/build_deploy.py` with no `--allow-unverified-terrain`.
Look at the rendered plates before you deploy.

Done when: the deploy runs clean with no override.

## 3. Tecopa Plateworks: eight render tests fail in the full suite

State: these eight are the documented Mac-only set in
`../../changing-things.md` § Run the tests. Seven are font-metric tests whose
thresholds match DejaVu while the Mac has Georgia. One is
`test_mp4_twin_is_tagged_bt709`: the bundled ffmpeg writes no `colr` box on
macOS. CI is green.

Task:

1. Run the full suite. Confirm the failure set is the documented eight and
   nothing else.
2. Answer one question for Dom: which fonts do customer renders on the Mac
   use? The studio runs on the Mac, so every customer poster renders there.
   If label placement drifts between proof and print on the Mac, it affects
   customer prints, not only the tests.
3. If the Mac renders with the shipped fonts and the drift is inside the
   print tolerance, close the thread as documented behavior. If not, report
   the gap to Dom and leave the thread open.

## 4. Ink budget still unmeasured against a genuine multi-year GPX set

State: the ceiling is about 66 long journeys, measured with one real track
repeated. A real customer with ten years of tracks is the case this
protects.

Task: ask Dom for a real multi-year set with many outings of mixed length.
`onx-markups-07192026.gpx` does not help: it is a planned route with no
`<trk>`. Render at 18×24, 200 dpi, weave on. Then grep the log for
`event=basecache.refuse`. Record the measured slope in `../../decisions.md`.

Done when: the budget is measured against real variety, or raised or lowered
to match it.

## 5. Hygiene

### Tecopa: pycache predates the folder rename, so tracebacks name Badwater Trails

Task: delete the `__pycache__` folders outside `.venv`. They are gitignored
caches and regenerate on the next run.

```
find . -name __pycache__ -not -path './.venv/*' -prune -exec rm -rf {} +
```

Done when: a failing test's traceback names `Tecopa Plateworks`.

### Tecopa: CI runs Python 3.11 (.python-version) while the Mac venv is 3.14

State: `.python-version` still says `3.11`.

Recommendation: bump it to `3.14`, so CI tests the interpreter that renders
customer posters. First check that every pin in `requirements-lock.txt` has
a 3.14 wheel for `ubuntu-latest`. If one does not, keep 3.11 and record it
as the deliberate CI floor in `../../decisions.md`.

Done when: CI is green on 3.14, or the floor is recorded.

### Tecopa: Metal render viability assessment written, uncommitted pending review

State: partly stale. The assessment was committed on 2026-09-08 in
`d49fb82`. `../../decisions.md` line 232 still calls it uncommitted.

Task: ask Dom to accept the verdict "not now". Then fix the wording on line
232. The assessment's CPU-side idea, a 256-entry lookup table in
`_biome_layers` (`app/render.py` line 290), saves about 1 s per refine. It is
optional. Do it only if Dom wants it.

## 6. Validate the base AND route-ink caches on real terrain (Mac-only)

Two halves:

- You can run this one: `pytest -m serial` against the real plates. The
  orphan drill has not run on real terrain since `fb634b2`.
- **Dom**: in the studio, on a real plate at 18×24, drag a terrain knob and a
  furniture knob (title, compass, marker size). He judges by eye whether the
  proof still predicts the print.

After a real session, grep the log for `event=basecache.refuse`.

## Closing threads

For each thread you finish, in `plateworks-session-log/threads.md`:

1. Set `**Status:** Closed`.
2. Add `**Closed:**` with the date, and `**Closed in:**` linking your session
   entry.
3. Write the `**Resolution:**` from what you verified: the commit, the
   command and its output.
4. Run `python3 check.py` in that repo. It must report 0 findings.

Log the session as `../../../CLAUDE.md` says.
