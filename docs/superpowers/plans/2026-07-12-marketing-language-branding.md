# TrailPrint — Marketing, Language & Branding (the playbook)

_2026-07-12 · Status: **actionable playbook.** Companion to `docs/marketing.md` (the
story and its three depths) and `2026-07-12-strategy-and-license.md` (the decisions).
The business model it operationalizes: **the concierge press** — the customer sends GPX,
TrailPrint returns the poster, digital or printed; plates are free forever; revenue is
posters, prints, editions, and plate commissions._

---

## The brand in one idea

TrailPrint is not an app company; it is a **press**. A printmaker's shop for a life
outdoors: plates, proofs, editions, reprints — vocabulary the engine already enforces in
code. Every decision below derives from one rule: **say it like a printmaker, prove it
like an engineer.**

## Step 1 — Clear the name (this week, before any spend)

1. Search "TrailPrint": USPTO TESS, the .com/.co domains, both app stores, Instagram /
   Reddit handles, plain Google for anyone selling under the name.
2. Gate: clean → register the domain and handles the same day. Encumbered → shortlist
   alternates privately (same press-vocabulary energy), re-run the search, commit once.
3. Output: a one-paragraph go/no-go note appended to the strategy doc (Decision 2
   flagged this; this step closes it). Nothing else in this playbook spends money
   before this gate.

## Step 2 — The identity comes from the engine (one weekend)

The design system already exists — it's the poster. Codify, don't invent:

1. **Palette:** route-ink gold `rgb(214,158,58)`, paper cream, terrain olive, relief
   charcoal — pull the exact values from `render.py` / `app/static/tokens.css` (the
   landing page already does this).
2. **Type:** the cartouche face is the brand face. Georgia→DejaVu today via
   `TRAILPRINT_FONT`; when the packaged build's SIL-OFL serif is chosen, it becomes the
   official brand face everywhere at once.
3. **Wordmark:** TRAILPRINT set exactly like a cartouche title — tracked caps, gold on
   cream or charcoal. No abstract logo; the cartouche style *is* the mark.
4. **The recurring motif:** the edition line — `EDITION 3 · 2024–2026` — on email
   signatures, social cards, packaging. It says "the artifact grows" in six characters.
5. **The honesty rule:** every marketing image is rendered by the engine
   (`scripts/render_asset_farm.py`) — never a mockup. If the product can't render it,
   the ad can't show it.

## Step 3 — The language system (write once, reuse forever)

### The lexicon

| Say | Never say |
|---|---|
| plate | region, dataset, coverage area |
| the Print · Wallpapers · the Year-Film | export, output, formats |
| proof | preview |
| edition · "Continue a poster" | update, re-order |
| Reprint Forever | backup, cloud sync |
| share copy (routes removed) | privacy mode |
| the save file (the PNG) | your data |
| commission a plate | request coverage |

Plus the standing rule from `docs/marketing.md`: plates are **free, always** — the word
"buy" never appears within three sentences of "plate."

### The voice, three rules

1. **Physical and specific.** Inches, points, miles, hashes. "A 2.6 pt trail is 2.6 pt
   on glass" beats any adjective.
2. **Printmaker, not platform.** No "users, accounts, cloud, seats, AI-powered." The
   customer is "you"; the product is "the press," "your poster," "your file."
3. **Claims are test-backed.** If CI doesn't prove it, the copy can't say it. The
   claims register below is the whitelist; anything stronger needs a new test first.

### The claims register (copy-paste sentences, each with its receipt)

- "The proof you approve is pixel-for-pixel the print you receive." — determinism suite.
- "Your poster names the exact terrain it was painted from." — `region_pack`,
  `docs/MANIFEST.md`.
- "Lose everything but the file? It reprints — byte-identically — on a fresh machine.
  We test that on every change." — the orphan drill (`tests/test_orphan_drill.py`).
- "No account. No cloud. The PNG is the save file." — the architecture; the save-file
  note in the wizard.
- "We never invent terrain — if the data isn't sharp enough, we say so." — zoom cap +
  off-DEM guard.
- "The engine is AGPL; the file format is public domain. You are never locked in, even
  to us." — `LICENSE`, `docs/MANIFEST.md` (CC0).

## Step 4 — Price architecture (decide the numbers in one sitting)

| Product | What it is | Pricing homework |
|---|---|---|
| **The Poster** | digital final: print-res PNG + wallpapers + the Year-Film — one composition, every performance | comp Mapiful/Grafomap digital tiers; render cost is negligible, so price the craft, not the compute |
| **The Print** | lab-fulfilled paper, shipped; 18×24 flagship | lab cost × 2.5–3 |
| **Edition N+1** | continue last year's poster | ~60% of the first poster — loyalty by design; "your poster is due" |
| **Plate commission** | the making of an uncovered region: bbox curation, DEM/hydro/labels bakes, look validation on real terrain, priority, first print included | price the labor honestly (hours × rate + first print); the plate publishes free; commissioner credited |
| **Plates** | the terrain packs | **$0 forever** — the trust layer; say so on the pricing page |

Steps: (1) pull the comps, (2) set the four numbers, (3) publish them on the landing
page. A concierge with public prices reads as craft; hidden prices read as agency.

## Step 5 — The concierge funnel (build the templates this week)

Per customer, in order:

1. **Intake** (reply template to the CTA email): which plate; how to export GPX from
   Strava / Gaia / onX / Avenza (link the in-app help page); what happens next; the
   price list.
2. **Fit check:** tracks vs the plate — the upload response counts `dropped_points`
   and `journeys_outside_plate`; quote those honestly before the proof.
3. **Proof:** render, send the watermarked proof, one revision loop included.
4. **Payment:** invoice / Stripe payment link on proof approval.
5. **Delivery:** the PNG (+ wallpapers/film if bought) with the save-file paragraph
   verbatim in the email — keep this file; next January it becomes the next edition.
   The print ships from the lab.
6. **The calendar hook:** with consent, one January reminder — "drop last year's PNG
   back in." No data retained; their file is the database.

Deliverables to write once: the intake template, the delivery template, the
proof-approval one-liner. (The GPX-export help page already exists in the app.)

## Step 6 — Launch sequence (four phases, each with a done-test)

**Phase 0 — the asset farm (weeks 1–2).**
- [ ] Rebuild real DEMs for all four plates; run `render_asset_farm.py` for the full
      spread (posters, wallpapers, films + MP4 twins, edition triptychs).
- [ ] Pick three heroes: a poster with photo + markers; a three-edition triptych; a
      Year-Film (MP4 for social, APNG for the page).
- [ ] Landing page live on the cleared domain; CTA = the concierge mailto; prices
      published (Step 4).
- **Done-test:** five strangers see the hero; at least three repeat the one-liner back
  unprompted.

**Phase 1 — the nerd launch (week 3).**
- [ ] Technical blog post: "The poster is the save file" — the zTXt manifest, plate
      hashes, the orphan drill; ends on the AGPL/CC0 stance. Durable SEO.
- [ ] Show HN with the post; work the thread for a day — answer with receipts (tests,
      line numbers), never marketing.
- **Done-test:** plate-request or commission emails > 0; the architecture story
  survives HN scrutiny without correction.

**Phase 2 — the trail launch (weeks 4–6).**
- [ ] Post the Year-Film natively (MP4 twin) to r/ultrarunning, r/trailrunning,
      r/Strava, plus the four plates' local communities.
- [ ] Founding run per plate: the first N prints at a founding price, buyers named in
      a plate-page credits list.
- [ ] One physical outpost per plate area (running or gear shop): a framed sample and
      cards.
- **Done-test:** the first stranger's poster — not a friend's, not HN's — paid and
  shipped.

**Phase 3 — the ritual engine (ongoing).**
- [ ] January "Edition season" campaign; race-season blocks for the ultra crowd.
- [ ] Every commissioned plate ships with a drop announcement — the commissioner's
      story is the launch content.
- [ ] Year-end gallery of the year's editions (with consent) — the gallery is the
      testimonial wall.
- **Done-test:** the Edition-2 rate. One real customer returning a poster for its next
  edition anchors all future copy.

## Step 7 — Measurement (five numbers, nothing else)

1. One-liner playback rate (the Phase-0 gate).
2. Film completion to the Edition beat on the landing page.
3. Plate requests + **commission inquiries** (demand with a credit card).
4. Proof→purchase conversion (concierge funnel health).
5. **Edition-2 rate a year out** — the thesis metric.

## Out of scope (until the Edition-2 rate exists)

Paid ads; a posting-schedule social grind; influencer seeding; packaged-app / app-store
marketing (waits on the Fork-A packaging work); any claim not in the register.
