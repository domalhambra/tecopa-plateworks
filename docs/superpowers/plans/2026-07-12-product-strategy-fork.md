# TrailPrint — Product Strategy Fork (decision doc)

_2026-07-12 · Status: **needs a decision from Dom** (not an implementation plan — it
resolves a conflict the codebase can't resolve for itself). Blocks the distribution
choices in `2026-07-12-reprint-forever-continuity.md`._

---

## Context — three strategy documents describe three different products

The repo has three planning documents that each assume a different answer to "who buys
this and how," and none references the others' assumption:

| Document | Implied product | Load-bearing assumption |
|---|---|---|
| `docs/scope.md` (Jul 8) | A **local, single-machine artifact tool** | *"There is no account, no database, no cloud"* is the **product's identity**, stated as a permanent line-in-the-sand ("Still out of scope: cloud sync and accounts"). |
| `assessments/2026-07-01-…-roadmap.md` | A **hosted, multi-tenant, paid web app (v2)** | Auth is "the hinge"; the whole v2 build is the **direct negation** of the scope doc's identity. |
| `docs/marketing.md` | A **consumer gift/ritual product at "one price"** | Targets gift buyers and yearly ritualists — people who will **never run `python -m venv`** — buying something that today **has no way to take money**. |

These are not three phases of one plan; they are three incompatible products. The symptom
is concrete and shippable-facing: the landing page's primary CTA, **"Make yours,"** links
to `#how` (`marketing/landing.html:188`) — an anchor to an explainer section. There is
**no answer in the entire funnel to "a stranger wants one."** The marketing plan sells a
purchase the architecture has no endpoint for, guarded by a scope doc that forbids building
one.

## The unscoped fourth option — and why it's probably the real answer

The red-team roadmap priced exactly one path out of "local tool": the **hosted multi-tenant
v2** (auth + Postgres + Redis + S3 + global geo + Stripe + fulfillment — an XL-on-XL build
whose two hardest rocks, global geo licensing and physical fulfillment, are still open
questions). But there is a fourth option nobody scoped, and it is the one *consistent with
the stated identity*:

**Ship the local app as an actual packaged app, and sell plates and prints — not renders.**

- A signed desktop app (the wizard already presents as a native macOS shell — see PR #15),
  region **plates** downloaded on demand (the pack format from the continuity plan), the
  render engine running **on the buyer's machine**. No auth, no tenancy, no server render
  fleet — the scope doc's identity preserved, not negated.
- Revenue is **plates and prints**, not compute. You sell the Lassen plate (a craft
  "vintage," exactly the marketing framing), and/or a print-lab fulfillment of the PNG the
  user already rendered locally. The unwatermarked-final problem the red-team worried about
  (a hosted user extracting a free 300-dpi PNG) **doesn't exist** when the compute is theirs
  — you're not gating a render, you're selling a plate and a paper print.

This option also **resolves the licensing constraint** the continuity plan surfaces: to
make "your file reprints itself" true you must publish the engine (companion plan). You
*cannot* build a moat out of hosted proprietary renders if the reprinter has to be public —
but you *can* sell plates, prints, and convenience around a public engine. The forever-
promise and the business model only reconcile on this branch.

## The three forks, priced

- **Fork A — Local-forever, packaged, sell plates/prints.** *Consistent with scope.md.*
  Build: app packaging/signing + plate distribution + a print-lab handoff + a store for
  plates. No auth, no render fleet, no global geo required to launch. Revenue per plate/print.
  Risk: desktop distribution friction; smaller TAM than web; print margins.
- **Fork B — Hosted multi-tenant (the red-team's v2).** *Negates scope.md; the roadmap
  already details it.* Build: everything in roadmap §3 (XL·XL). Two open rocks (global geo
  licensing, physical-vs-digital fulfillment) gate it. Revenue per render/subscription.
  Risk: the promise ("your file reprints itself") competes with your own hosting.
- **Fork C — Hybrid: local free tool + hosted print/plate storefront.** The engine is the
  free, public, local artifact tool (the Show HN story); the **only** hosted surface is a
  thin storefront that takes an already-rendered PNG (or a plate selection) and sells a
  physical print or a premium plate. Auth scoped to *orders*, not to renders. Smaller than B,
  monetizes better than pure A.

**Recommendation: Fork A or C, not B.** Both keep the identity the scope doc spent a whole
document defending, both are consistent with publishing the engine (which the forever-
promise requires), and both sidestep the two unresolved v2 rocks. B is a different company.

## What a decision unblocks

- **The continuity plan's distribution step** (who hosts plates; do users self-serve them).
- **The CTA.** "Make yours" becomes "Download the app" (A), or "Order a print" (C) — a real
  destination, not `#how`.
- **The licensing plan's engine-license choice** (a permissive license fits A/C; B might
  want a source-available/commercial split).
- **Every "should we build auth/payments/fulfillment" question** in the roadmap, which is
  currently un-answerable because the target product is undefined.

## The decision, stated plainly

**Question for Dom:** Is TrailPrint (A) a packaged local app that sells plates and prints,
(B) a hosted multi-tenant web app, or (C) a free local engine with a hosted print/plate
storefront? Everything downstream — the license, the plate distribution, the CTA, whether
auth is ever built — waits on this one answer, and the three current strategy docs each
silently assume a different one.

## Out of scope (here)

Implementation of whichever fork wins — this doc only forces the choice and prices it. The
roadmap already details Fork B; Fork A/C would each need their own build plan once chosen.
