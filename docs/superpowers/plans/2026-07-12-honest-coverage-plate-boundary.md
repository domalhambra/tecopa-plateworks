# TrailPrint — Honest Coverage & the Plate Boundary (design + implementation plan)

_2026-07-12 · Status: **proposed** (not yet built). Part copy, part UX. Sibling to
`2026-07-12-keep-the-png-onboarding.md` (both are "the messaging promises more than the
artifact delivers"). Does **not** touch the geo coverage rock — it makes the *existing*
four-plate scope honest._

---

## Context — the hero line implies a coverage the app doesn't have, and the chronicle
framing makes it worse every year

The marketing hero (`docs/marketing.md`): *"Get a museum-quality relief poster of
**everywhere you've been**."* The reality: everywhere you've been **that falls inside one
of four western-US plates** (Lassen CA, Susanville–Reno, Elko–Bonneville, Rifle–Aspen).
Anything outside returns a hard 422, and points outside the region CRS are, per the red-team,
**silently dropped** to `(inf, inf)` in ingest.

The chronicle framing — TrailPrint's whole thesis — makes this *sharper over time*, not
softer. The more years a user adds (the entire point of Living Editions), the more likely
their life has spilled past the plate: a move, a trip, a race in another state. The product
that markets "your years outdoors, as one artifact that keeps growing" will, for its most
engaged users, increasingly meet next year's GPX with a 422 or a silent drop. The failure
is concentrated exactly on the customers the editions strategy is designed to retain.

## Two problems, one theme: own the boundary instead of hiding it

### Problem 1 — the copy over-claims

"Everywhere you've been" is a promise the 422 will contradict. The marketing plan *already
has the honest frame and doesn't apply it to the hero*: it says to sell regions as **plates**
/ "vintages" ("now serving: the Lassen plate") and treats scarcity as craft. The fix is to
carry that framing up into the hero and the FAQ:

- Hero owns the plate: *"your Lassen years, as one poster"* — not implied global coverage.
- The FAQ answer *"Why only these regions?"* (already drafted: *"we refuse to print terrain
  we don't have real elevation data for"*) becomes a **strength** the hero sets up rather
  than a caveat buried at the bottom. This is the same honesty the engine already practices
  with the zoom cap ("we never invent terrain").

### Problem 2 — the out-of-plate experience is a raw refusal or a silent loss

When a user uploads GPX that partly or wholly leaves the plate, two things can happen today
and neither is good: a whole-crop overhang trips the off-DEM guard's 422 (correct, but
terse), or individual out-of-CRS points vanish silently (a data-integrity failure — the
poster is quietly wrong). Neither tells the user the *truth*: **"some of your journey is
outside this plate."**

The fix is a coverage-aware upload response — the temporal-honesty sibling of the off-DEM
guard:

- On upload, compute the fraction of track points (and of distinct journeys) that fall
  **outside** the plate's true DEM bounds. Surface it: *"3 of your 14 journeys extend beyond
  the Lassen plate and won't appear on this poster."* — named, counted, never silent.
- Point-level out-of-CRS drops must become **visible**, not `(inf, inf)` swallowed — this is
  also on the red-team's list; this plan is the product surface for it.
- Where a neighboring plate would cover the overflow, *say so*: *"the rest falls in the
  Susanville–Reno plate."* — which quietly becomes the best possible **region-request /
  cross-sell** signal (the marketing plan already wants "Request the next region" capture;
  this generates it from real user data at the exact moment of need).

## Concrete work

- **Copy:** rewrite the hero + FAQ to own the plate (marketing/landing.html + the copy in
  `docs/marketing.md`). No engine change.
- **Coverage report on upload:** a small function over the already-parsed tracks vs the
  plate's true DEM bounds (the same bounds the off-DEM guard already derives), returned in
  the upload response and shown in the wizard. Reuses existing geometry.
- **Make point drops loud:** replace the silent `(inf, inf)` drop in ingest with a counted,
  surfaced "N points outside coverage" — a data-integrity fix with a product face.
- **Neighbor hint + request capture:** when overflow intersects another built plate or a
  requestable area, offer it; wire to the region-request email capture the marketing plan
  specifies.

## Invariants / risks

- **This is the off-DEM guard, told forward to the user.** Invariant 5 already refuses to
  paint invented terrain; this plan makes the *reason* legible instead of a bare 422. No new
  rendering behavior — only honest reporting of a boundary the engine already enforces.
- **No coverage is added.** Explicitly not the global-geo rock; four plates stays four
  plates. The change is that the boundary is *narrated*, not hidden.

## Out of scope

Global / on-demand coverage (the red-team's geo rock, its own multi-XL build). Auto-stitching
a journey across two plates into one poster — a real future feature, but it needs a shared
projection and is out of scope for making today's boundary honest.
