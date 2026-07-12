# TrailPrint — Strategy & Licensing (decision record)

_2026-07-12 · Status: **decided, pending PR merge** (merging the PR that carries this doc
and `LICENSE` is the act of adoption). Supersedes the six 2026-07-12 blind-spot plans:
this doc carries the decisions; `2026-07-12-honesty-continuity-implementation.md` carries
all the build work. Red-teamed before consolidation — the six documents' findings all
survived; their packaging didn't (four of six bundled cheap fixes with unpriced
infrastructure, and one growth feature was cut outright)._

---

## Context — three documents described three incompatible products

| Document | Implied product | Load-bearing assumption |
|---|---|---|
| `docs/scope.md` | Local, single-machine artifact tool | "No account, no database, no cloud" is the product's **identity** |
| `assessments/2026-07-01-…-roadmap.md` §3 | Hosted, multi-tenant, paid web app | Auth is "the hinge"; the v2 build **negates** the identity |
| `docs/marketing.md` | Consumer gift/ritual product, "one price" | Buyers who will never run `python -m venv`, purchasing through a funnel that has no endpoint (the landing CTA "Make yours" links to `#how`) |

Meanwhile the headline promise — *"Lose everything but the file? Reprint it in 2035. We
promise"* — was true on exactly one machine: reprint 422s wherever the region isn't built
(`app/main.py:927`), the DEMs are gitignored with no distribution channel, and the repo
had **no license**, so even with the code in hand nobody else could legally run the engine.
The strategy question and the licensing question are the same question: *the promise is
only as strong as a stranger's right and ability to run the reprinter.*

## Decision 1 — the product trunk: a published local engine; sell prints and convenience, not renders

TrailPrint stays what `docs/scope.md` says it is: **local-first, no accounts, no cloud,
the artifact is the archive.** The engine is **published** (Decision 2 makes that legally
real), region plates become downloadable artifacts, and the promise becomes mechanism
instead of slogan.

Revenue attaches to what is genuinely scarce, with clear eyes about what isn't:

- **Free by design, so never the SKU: the plates.** They are overwhelmingly U.S. federal
  public-domain facts (Decision 3) with little-to-no copyright under *Feist*, we dedicate
  them CC0 anyway (below) — and, decisively, the reprint-forever promise *requires* them
  to stay publicly downloadable: a paywalled plate would tax the product's own archival
  claim, and anyone could legally mirror it regardless. Plates are the **trust layer and
  the brand device** — provenance on every cartouche, scarcity-as-craft positioning, a
  release calendar, a demand-signal engine — never a line item. In the concierge model the
  customer never even touches one. The one plate-shaped thing that IS sold is the
  commission, below.
- **Durable revenue:** **physical prints** (fulfillment, color management, craft),
  **editions** (the yearly ritual — the retention engine), **plate commissions** (a
  one-time fee that buys the *making* of an uncovered region — bbox curation, the DEM /
  hydro / labels bakes, look validation on real terrain — plus priority and the first
  print; the finished plate still publishes free, with the commissioner credited — a
  `commissioned_by` line in `sources.json` → `PLATE.txt` is a small follow-up), and the
  **packaged app experience** (a signed, double-clickable build is worth money even over
  AGPL source — paying for the build is normal).
- **Retired as strategy:** the hosted-proprietary multi-tenant v2 of the 2026-07-01
  roadmap. A public AGPL engine plus the local-first identity forecloses "sell access to
  the renderer" as the business. Roadmap §3's infrastructure items survive only where they
  serve this trunk (e.g. an eventual thin storefront for print orders — auth scoped to
  *orders*, never to *renders*). Note AGPL does not forbid *us* hosting anything later;
  it forbids others taking the engine proprietary.

**The one residual open choice** — concierge-only vs. a thin hosted print storefront, and
when — is monetization flavor. It gates **no phase** of the implementation plan and can be
decided after the machinery ships. Until then the CTA tells the truth at each phase
(implementation plan, Phase 5): "Order a print" (concierge) now; "Get the app" when a
packaged build exists.

## Decision 2 — the license architecture

### Code: **GNU AGPL-3.0-or-later** (`LICENSE`, canonical text, in this PR)

Scored against the four things the license must do for *this* product:

| Criterion | MIT / Apache-2.0 | **AGPL-3.0-or-later** | BSL / source-available |
|---|---|---|---|
| Makes "your file reprints itself" true (strangers may run + port the engine forever) | ✅ | ✅ | ⚠️ restricted use undercuts the promise |
| Reads well to the Show HN / data-sovereignty audience (marketing's audience #4) | ✅ | ✅ (end-user app, not a library — the usual AGPL friction doesn't apply) | ❌ they will notice |
| Stops a print-my-map incumbent from absorbing the engine into a proprietary hosted product | ❌ explicitly allows it | ✅ they must publish their service source — they won't | ✅ |
| Preserves Dom's optionality (dual-license, commercial exceptions, app-store builds) | ✅ | ✅ **while sole copyright holder** — can grant himself or others any terms | ✅ |

AGPL is the only column with four checks. Two riders make the fourth check stay true:

- **Keep relicensing power:** as sole author Dom is unbound by his own license. The day an
  outside contribution is accepted, require a DCO sign-off or lightweight CLA, or that
  power erodes commit by commit.
- **"or-later," deliberately:** the promise's own scenario is *Dom disappears*. With no
  copyright holder left to relicense, `-only` would freeze the code into whatever
  incompatibilities 2040 brings; `-or-later` leaves the FSF's future-version escape hatch
  open to whoever finds the file. The archival product wants the archival variant.

*Adoption mechanics:* a license binds on distribution. Merging this PR adopts it as the
repo's terms; it takes full public effect when the repo is published (implementation plan,
Phase 3). Swapping the file before merge is free; after strangers have received the code,
that version's grant is irrevocable — which is precisely the feature.

### Plates + manifest schema: **CC0-1.0**

The region packs (`*.trailplate` — DEM, hydro, labels, landcover, `sources.json`) and the
documented manifest schema (`docs/MANIFEST.md`, Phase 0) are dedicated to the public
domain. Rationale: the packs are ~all PD federal data with thin-to-nil compilation rights
(claiming otherwise builds on sand), and the schema being CC0 means **anyone may write a
manifest reader/renderer without touching AGPL code** — the deepest layer of the
never-orphaned promise: even if the engine rots, the file format is free to reimplement.

### Name & branding: **reserved — and "TrailPrint" is a no-go (searched 2026-07-12)**

Neither grant covers the product name — fork the engine, yes; sell under our name, no.
The clearance search came back encumbered on every axis:

- **trailprint.com** — registered since 2017 to **"Trail Print,"** an active US
  mountain-biking apparel shop that even sells *microfiber trail maps*: a senior
  common-law user of the exact name, in the same outdoor market, with Facebook /
  Instagram presence (@trailprint answers 200).
- **TrailPrint3D** (trailprint3d.com + a popular free Blender add-on on MakerWorld /
  Printables) — converts **GPX files into 3D-printable terrain maps**. The same
  GPX-to-terrain-keepsake niche; confusion is guaranteed, in both directions.
- **trailprint.net** — registered 2026-04-27 (three months before this search),
  currently a blocked deployment: someone else is building on the name right now.
- USPTO surfaced no federal registration for the compound (best-effort — confirm at
  filing time), but a filing would face both the senior user and a crowded descriptive
  field ("trail print" floods Etsy as a generic phrase).

**Recommendation: rename to "Hillshade Press."** Clearance snapshot (2026-07-12):
hillshadepress.com **available**; no brand of that name found (nearest hits are
phonetically distant local printers — Hillside Press, Hill Print Solutions);
"hillshade" is the product's own core technique, and the compound keeps the entire
press lexicon — plates, proofs, editions — intact. Suggestive rather than descriptive
for a poster press: a materially stronger trademark position than TrailPrint ever had.

At adoption (on Dom's word): register the domain + handles the same day, run the USPTO
search on the compound at filing, then flip the marketing surfaces. Repo and internal
identifiers can lag — and the manifest's `ENGINE = "trailprint"` string is a **frozen
schema constant** (provenance vocabulary under the forever-contract, not branding) and
must never change regardless of the brand.

**Superseded by selection — the name is "Tecopa Plateworks" (2026-07-12).** Dom
declined Hillshade Press and steered rounds 3–4 (evocative, then Tecopa) — full
clearance record and the always-full-compound rule live in the playbook. Landing
surfaces flipped the same day; tecopaplateworks.com registration is Dom's same-day
action; internal identifiers sweep in a follow-up commit; `ENGINE` never changes.

## Decision 3 — the data resale verdict (asked directly: "can I sell this?")

**Yes, for all four current plates.** Verified across every `regions/*/sources.json` and
`scripts/build_labels.py` — every input is a U.S. federal government work:

| Layer | Source | License |
|---|---|---|
| Elevation / relief | USGS 3DEP 10 m / 30 m DEM | Public domain (17 U.S.C. § 105) |
| Water | USGS NHD waterbodies + flowlines | Public domain |
| Land cover (biome tint) | NLCD 2021 (USGS/MRLC) | Public domain |
| Place names | USGS GNIS Landforms | Public domain |

Public-domain data may be used for any purpose, **including commercial resale** — there is
no rights-holder to license from. The HyRiver fetch libraries' licenses govern their code,
not the data they fetch. *(Engineering conclusion, not legal advice; the facts are simple
enough that a one-time lawyer confirmation before commercial launch is cheap insurance.)*

Three caveats, each with a home in the implementation plan:

1. **Attribution** is a courtesy today and becomes *mandatory* the day any non-federal
   source enters — so the credit line renders from `sources.json` now (Phase 5), and the
   habit exists before it's law.
2. **The Georgia font** is the one proprietary-adjacent element (`render.py:335`). Posters
   *rendered with* it are fine (typeface designs aren't copyrightable in the U.S.; a raster
   isn't a derivative of the font software) — but **never ship `Georgia.ttf`** in a
   packaged build; pick a redistributable (SIL OFL) default face for distribution
   (Phase 5). `TRAILPRINT_FONT` already allows a licensed upgrade.
3. **Non-USGS sources are a hard gate.** Copernicus GLO-30 (attribution required), OSM
   water (ODbL share-alike — can obligate publishing derived data), HydroSHEDS (some
   versions non-commercial): none enters a plate without its license recorded in
   `sources.json` and cleared for resale first. Today's all-PD posture is an asset; losing
   it should be a decision, never an accident.

## What these decisions unblock

Every phase of `2026-07-12-honesty-continuity-implementation.md`: the LICENSE is Phase 0's
anchor; the CC0 schema doc is the third-party-reader escape hatch; the trunk decision kills
the "is this hosted?" ambiguity that made auth/payments/fulfillment unanswerable; and the
resale verdict clears the poster business itself. The monetization flavor is resolved as
a working model (2026-07-12, Dom): **concierge-first** — the customer sends GPX,
TrailPrint returns the poster, digital or printed; a thin storefront can follow volume.
The outward-facing playbook that operationalizes all of this — pricing, funnel, launch
sequence, language, branding — is `2026-07-12-marketing-language-branding.md`.
