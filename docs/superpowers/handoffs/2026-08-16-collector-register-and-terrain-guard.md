# Handoff — 2026-08-16: the Collector register, and the terrain guard

_Read `git log` before trusting any dated handoff, this one included. State as of commit `2b34d26`, pushed to `main`. 29 commits today._

## Start here

Two things shipped and one gate is now closed against you:

1. **The landing page speaks to a named customer.** `docs/superpowers/specs/2026-08-16-target-customer-profile-design.md` is canon for every customer-facing surface. Read it before writing a single word of page copy, a social caption, or an order-email reply.
2. **The 1:1 detail crop is chosen by ink content**, not by centre. See below for why that mattered.
3. **`marketing/build_deploy.py` will refuse to run.** That is the terrain guard, not a bug. See "The one thing blocking a deploy".

## The one thing blocking a deploy

`build_deploy.py` now refuses any region whose `assets/index.json` entry carries no `terrain` record. Today's index predates the record, so **all five plates refuse**:

```
error: UNVERIFIED terrain — assets/index.json carries no terrain record for these
       regions, so what their images were rendered from is unknown:
  elko_bonneville
  lassen_ca
  ...
```

The correct fix is a farm re-render, which stamps `synthetic: false` for every plate and silences the guard permanently. It is an hours-long run:

```bash
./.venv/bin/python scripts/render_asset_farm.py --regions elko_bonneville lassen_ca rifle_aspen susanville_reno tushar_beaver_ut
```

`--allow-unverified-terrain` will publish anyway and warns loudly. Use it only if you need a copy-only fix live before the re-render. **Do not weaken the guard to get past it.**

## Why the guard exists

`tests/conftest.py` hydrates a synthetic stand-in DEM for any plate missing one: a 240x300 `sin x cos` surface with a Gaussian bump, tagged `synthetic=1`. It renders *cleanly*. Correct hillshade, palette, place labels, route ink. The poster looks like a map while its landforms are invented, and the page footer promises every image is the engine's own render.

The record is stamped **at the moment the farm opens a DEM**, never read from disk at deploy time. That asymmetry is the whole design: a machine can render from a stand-in and later obtain the real file, at which point the file on disk reports "real" while the posters are still synthetic. The repo already has a documented bug of exactly this shape (CLAUDE.md, "The lassen_ca DEM goes orphan on a pull"). If you find yourself about to simplify this into a deploy-time `rasterio.open`, don't; the docstrings on `_terrain_record` and `load_index` cross-reference each other to say so.

Three answers, not two:

| Situation | Record | Effect |
|---|---|---|
| No DEM consulted (`--only detail/model/mockups/coin`) | `None` | prior record preserved by `_merge_index` |
| DEM present but unreadable | `{"synthetic": None, ...}` | overwrites prior, lands in the unverified refusal |
| DEM opened | `{"synthetic": bool, "sha256": ..., "bytes": ...}` | the real record |

`synthetic` must be a real bool. Anything else (`{}`, missing key, `null`, `0`, `"false"`) means the file was hand-edited or corrupted and routes to the *unverified* refusal. `--allow-synthetic` does not open that door, and `--allow-unverified-terrain` does not wave through a known-synthetic plate. Both are pinned.

`sha256` and `bytes` are recorded but **nothing checks them yet**. They are there so a future audit can say which DEM painted a given asset set.

## The detail-crop regression, and the lesson under it

`_detail` took a centre crop, justified by a docstring reading "the synth tracks converge there, so it lands on ink and labels". That was true of the old synthetic demo tracks, which radiated from a base camp at the plate centre. **The OSM demo-track feature shipped the same morning deliberately spread journeys across the plate**, which silently made the centre the emptiest part of every poster. The page's proof-of-craft image was showing bare terrain while the new copy pointed straight at labels and route ink.

No test could see it. The suite was green. It was caught by rendering the artifact and looking at it.

The crop is now chosen by scanning for `render.TRACK_INK` at full resolution (a hairline route blends into terrain if you downsample first), summing into 32 px cells, and picking the best window with an integral image; it falls back to centre when a poster carries no ink. `INK_TOL = 24` was chosen by measurement, not feel: at 60 the scan prefers a bare sunlit slope.

**If you add a marketing asset, add an eyeball step for it.** That is now twice in two days that the worst defect of a session was invisible to a green suite and visible to a human glance.

## Where the copy rules live

- **Canon:** `docs/superpowers/specs/2026-08-16-target-customer-profile-design.md`. The customer, his four doubts, the seven register rules, the say-instead table, and a structural filter of what he does not care about.
- **The plan that executed it:** `docs/superpowers/plans/2026-08-16-collector-register-copy-rework.md`, carrying the final copy verbatim plus dated notes on five claims that were corrected mid-flight.
- **Enforced by:** `tests/test_marketing_page.py`. `BUILDER_REGISTER` bans the builder's vocabulary; `test_the_customers_doubts_are_answered` pins four customer anchors.

Two traps that already bit, both worth knowing before you edit page copy:

1. **Line wraps inside a pinned anchor are load-bearing.** The tests assert literal substrings against the raw file, so wrapping between `until` and `you say yes` makes that anchor unsatisfiable. Keep any pinned phrase on one line.
2. **`grep -c "2.6"` lies.** The dot is a wildcard and matches `236px` in the CSS. Use `grep -cF`.

## Open threads

Tracked in the Notion Threads database; summarized here so a cold read does not need it.

| Thread | Shape |
|---|---|
| Re-render five plates for terrain records | Blocks deploys. Hours-long. The only true blocker. |
| Print price: $80 profile sense vs $149 live | Dom's call. Copy is written so the number is swappable; no price appears outside the pricing band. |
| Four `sources.json` DEM hashes cannot be restored | Only `lassen_ca` matches (`20cec75c…`, re-confirmed by today's terrain stamp). **No `sources.json` was touched.** Re-stamp or leave as drift evidence. |
| Corridor-plate trip lengths read as road trips | Taste call, tunable via `TRIP_SPAN_FRAC` / `TRIP_SPAN_MAX_M`. |
| Three plates render 7 of 8 journeys | Disconnected OSM pockets. Retry-with-next-candidate is the fix if wanted. |

Cosmetic, not tracked: the new lassen detail crop clips the left edge of the "Ridenoure Reservoir" marker chip. The label text is fully readable. Any 1:1 crop clips something at its border, so this was left rather than tuning a constant to one poster's framing.

## Known-good state

- `tests/test_marketing_page.py`, `test_terrain_provenance.py`, `test_asset_farm_detail.py`, `test_asset_farm_frame.py`: 49 passed.
- Full suite: the documented seven Georgia-vs-DejaVu font failures, unchanged. Compare the failure *set*, not the totals.
- All five plates carry real terrain (CLAUDE.md corrected today; it had claimed three were synthetic stand-ins).
- https://tecopa.plateworks.org serves the new copy: zero `2.6`, zero `AGPL`, both proof anchors, the fixed detail crop.
