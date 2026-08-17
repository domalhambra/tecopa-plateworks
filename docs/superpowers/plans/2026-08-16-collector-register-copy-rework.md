# Collector-Register Copy Rework Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewrite every customer-facing sentence on the landing page (and the canon that feeds it) into the Home-Ground Collector's register, per the approved profile spec.

**Architecture:** The spec is `docs/superpowers/specs/2026-08-16-target-customer-profile-design.md`; read it before any task. The rework is TDD for copy: a register-gate test bans the builder's vocabulary and pins the customer's anchors first (red), then eight page sections are rewritten block by block (green), then `docs/marketing.md` is reconciled so canon stops mandating what the page no longer says, then deploy and live verification. Prices stay exactly as they are: the $80-versus-$149 tension is recorded in the spec and decided by Dom outside this plan.

**Tech Stack:** Static HTML (`marketing/landing.html`), pytest pins (`tests/test_marketing_page.py`), the `build_deploy.py` staging script, Netlify CLI.

**Register rules (from the spec, condensed for the implementer):** second person and plain verbs (upload, see, print, hang); name the pursuit, never "adventures"; the maker is present ("I frame it", "my eye on the sheet") because the press is literally one person; quality is shown and vouched, never measured (no pt, dpi, ppi, hash, deterministic, byte-identical); press lexicon is seasoning, never load-bearing; no em dashes in any rewritten prose (voice-principles.md bans them; use colons, commas, periods); no privacy reassurance anywhere (it answers a question nobody asked). Copy blocks below are final wording. Do not improvise substitutes; if a block cannot be applied verbatim (drifted context), stop and surface it.

---

### Task 1: The register gate (failing tests first)

**Files:**
- Modify: `tests/test_marketing_page.py` (append after `test_osm_attribution_is_present`)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_marketing_page.py`:

```python
# the profile spec (docs/superpowers/specs/2026-08-16-target-customer-profile-design.md)
# struck the builder's register from customer surfaces: measurements as selling
# points, file-format talk, licence names, and privacy reassurance that answers
# a question nobody asked. The page speaks to the Home-Ground Collector.
BUILDER_REGISTER = [
    "2.6",                      # the pt-width lines, both variants
    "pixel-for-pixel",
    "hash-addressed",
    "a known ppi",
    "physical units",
    "deterministic",
    "byte-identical",
    "CC0",
    "AGPL",
    "Private by default",
    "keep my tracks",
    "disappears",               # the "What if Tecopa Plateworks disappears?" FAQ
]


def test_the_page_speaks_to_the_collector_not_the_builder():
    for phrase in BUILDER_REGISTER:
        assert phrase not in PAGE, f"builder register on a customer surface: {phrase!r}"


def test_the_customers_doubts_are_answered():
    # the four doubts from the profile spec, pinned by their load-bearing phrases
    assert "until you say yes" in PAGE          # doubt 4: you see it before it prints
    assert "export GPX in bulk" in PAGE         # doubt 2: getting tracks out is easy
    assert "the person who makes your poster" in PAGE   # the one plain order-door line
    assert "Tell me where you've been" in PAGE  # the request door, maker-present
```

- [ ] **Step 2: Run to verify both fail**

```bash
./.venv/bin/python -m pytest tests/test_marketing_page.py -q
```

Expected: 2 failed (`test_the_page_speaks_to_the_collector_not_the_builder` on `"2.6"`, `test_the_customers_doubts_are_answered` on `"until you say yes"`), 6 passed.

- [ ] **Step 3: Commit the red gate**

```bash
git add tests/test_marketing_page.py
git commit -m "tests: gate the landing page on the Collector's register, red first"
```

---

### Task 2: Head metadata and hero

**Files:**
- Modify: `marketing/landing.html:6-14` (title, description, og:title, og:description) and `:240-251` (hero)

- [ ] **Step 1: Replace the four head strings**

| Line | New value |
|---|---|
| `<title>` (:6) | `Tecopa Plateworks — everywhere you've gone, on one poster` |
| `meta description` (:8) | `Email your GPX tracks and get back a shaded-relief poster of everywhere you've gone. You see the exact poster before it prints.` (127 chars: the first draft ran 207 and search snippets truncate near 160, which cut off the proof answer) |
| `og:title` (:13) | `Everywhere you've gone, on one poster` |
| `og:description` (:14) | `Years of tracks sit on your phone, never once seen as a whole. Tecopa Plateworks prints them as one shaded-relief poster of your ground.` |

(The title tag keeps its existing em dash: it is the brand separator, not prose.)

- [ ] **Step 2: Replace the hero copy (`:240-251`)**

H1 (keep the `gild` span):

```html
<h1>Everywhere you've gone, <span class="gild">on one poster</span>.</h1>
```

Lede:

```html
<p class="lede">Ten years of Lassen weekends. One map. The tracks are already on
  your phone: onX, Gaia, the watch. You've just never seen them all in one place.
  Tecopa Plateworks sets your years onto a shaded-relief poster of your ground:
  real terrain, real place names, your photos pinned to the spots they came from.
  You see the exact poster before anything prints.</p>
```

Caption under the CTAs:

```html
<p class="caption" style="margin-top:22px">No account · no app to learn · yours forever.</p>
```

Eyebrow (`GPX in · archival print out`), both CTAs, and the film figure stay as they are.

- [ ] **Step 3: Commit**

```bash
git add marketing/landing.html
git commit -m "marketing: hero sells the seeing, not the artifact"
```

---

### Task 3: The pillars band (retire "One score, three performances")

**Files:**
- Modify: `marketing/landing.html:262-293`

- [ ] **Step 1: Replace the band head**

```html
<p class="eyebrow">What you get</p>
<h2>The poster is the point. The rest comes with it.</h2>
<p class="lede">One map, decided once. It prints as the poster, cuts itself to your
  phone as a wallpaper, and plays as a short film of your year drawing itself.
  Same picture, three forms.</p>
```

(The first draft ended "three forms, one price." It is true of the $79 Poster and
reads as misleading three sections above four price tiers, so the price claim
stays where the prices are.)

- [ ] **Step 2: Replace the three pillar cards**

```html
<div class="pillar">
  <div class="n">01 · THE MAP</div>
  <h3>Composed like a fine map</h3>
  <p>Shaded relief from real USGS terrain, water in its true course, place names
    set in the map's own type, your photos pinned to the spots they came from.
    Framed and finished the way a print shop would, because that's what this is.</p>
</div>
<div class="pillar">
  <div class="n">02 · IT COMES WITH</div>
  <h3>The screens and the film</h3>
  <p>The same map, cut to your phone's exact screen as a wallpaper, and played as
    a film: your trips appear in the order you took them, and the last frame is
    the poster.</p>
</div>
<div class="pillar">
  <div class="n">03 · NEXT YEAR</div>
  <h3>The map fills in</h3>
  <p>Next year, send this year's poster back with the new tracks. Same frame,
    more ink, Edition 2 printed in the corner.</p>
</div>
```

- [ ] **Step 3: Commit**

```bash
git add marketing/landing.html
git commit -m "marketing: pillars go poster-first, in plain words"
```

---

### Task 4: The ritual band

**Files:**
- Modify: `marketing/landing.html:300-303` (lede) and `:313-318` (trip-note)

- [ ] **Step 1: Replace the lede** (eyebrow and the H2 "Same frame. More ink. Every year." stay: they already pass the tailgate test)

```html
<p class="lede">Next year, drop the new tracks onto this year's poster. The crop
  holds, the type holds, the palette holds. Only the ink accumulates, and the
  edition number ticks over in the corner like a printmaker's plate. Nothing
  else on the wall can do this.</p>
```

- [ ] **Step 2: Replace the trip-note text** (keep the `SAME FRAME →` span)

```html
<span>Everything the next edition needs travels with the poster file itself.
  Keep the file with the print; next year, send it back with the new tracks
  and the map picks up where it left off.</span>
```

- [ ] **Step 3: Commit**

```bash
git add marketing/landing.html
git commit -m "marketing: the ritual keeps its headline, loses the machinery"
```

---

### Task 5: The wallpaper and detail bands (both 2.6 pt sites)

**Files:**
- Modify: `marketing/landing.html:326-333` (wallpaper) and `:346-356` (detail)

- [ ] **Step 1: Replace the wallpaper band copy**

```html
<p class="eyebrow">It comes with the screens</p>
<h2>From the wall to the lock screen.</h2>
<p class="lede">Pick your phone and the wallpaper is cut to its exact screen,
  drawn at the same weight as your print. Labels even dodge the lock-screen clock.</p>
```

(The first draft said "matching your print line for line." Line *weights* do hold
across devices, but `geo.refit_crop_aspect` changes the ground extent when the
aspect ratio differs, so a reader taking "line for line" to mean the same
composition would be misled on an ultrawide.)

And the three `fmt-list` items:

```html
<li><span class="tag">Print</span><div><b>Archival poster</b><p>The 18×24 sheet, framed and finished, printed as sharp as the terrain data honestly allows.</p></div></li>
<li><span class="tag">Wallpaper</span><div><b>Every device preset</b><p>Phone, tablet, laptop, desktop, ultrawide. Labels dodge the lock-screen clock.</p></div></li>
<li><span class="tag">Film</span><div><b>The year in motion</b><p>Your trips draw themselves in day order over terrain that holds still.</p></div></li>
```

- [ ] **Step 2: Replace the detail band lede and caption** (eyebrow "Look closer" and H2 "The thought is in the details." stay)

```html
<p class="lede">Look close: the labels sit clear of the ink, the rivers run their
  true courses, the type holds up at arm's length. This is the part I obsess
  over, and it's the part you'll see every day from the couch.</p>
```

```html
<figcaption class="plate">Actual print pixels: a 1:1 crop of the sheet, unscaled</figcaption>
```

- [ ] **Step 3: Run the gate; the banned-vocabulary test should now pass**

```bash
./.venv/bin/python -m pytest tests/test_marketing_page.py::test_the_page_speaks_to_the_collector_not_the_builder -q
```

Expected: still FAILS, with exactly one failure naming `'pixel-for-pixel'` (the test stops at the first failing assert, and after this task that is the first survivor in list order). The failure message changing from `'2.6'` to `'pixel-for-pixel'` is the checkpoint: both 2.6 sites are dead.

- [ ] **Step 4: Commit**

```bash
git add marketing/landing.html
git commit -m "marketing: retire 2.6 pt from copy; the customer never asked"
```

---

### Task 6: The plates band and the request door

**Files:**
- Modify: `marketing/landing.html:366-368` (lede) and `:431-432` (request card text)

- [ ] **Step 1: Replace the band lede**

```html
<p class="lede">Each region is a hand-built plate: real USGS elevation, real
  place names, tuned until the relief reads right. I never invent ground: if the
  data isn't sharp enough for the size you want, I say so before you pay.</p>
```

- [ ] **Step 2: Replace the request-card text** (the form itself is untouched; its pins are load-bearing)

```html
<div class="coord">Tell me where you've been. The most-asked ground gets cut
  next, and a commission jumps the queue.</div>
```

- [ ] **Step 3: Commit**

```bash
git add marketing/landing.html
git commit -m "marketing: the plates band drops the hash talk, gains the maker"
```

---

### Task 7: The two doors and pricing

**Files:**
- Modify: `marketing/landing.html:448-475` (doors) and `:483-495` (pricing)

- [ ] **Step 1: Replace the doors band head**

```html
<p class="eyebrow">Two ways in</p>
<h2>A press you can email, or a studio you can run.</h2>
<p class="lede">Tecopa Plateworks is one person and a local app. Pick the door
  that fits how much you want to touch the machinery.</p>
```

- [ ] **Step 2: Replace door one** (h3 and CTA stay)

```html
<p>Email me your year: a bulk GPX export from Gaia, Strava, onX, or your watch.
  I frame it, send you the exact poster to look over, and nothing prints until
  you say yes. Paper arrives; the file comes with it.</p>
<p class="fine">You're emailing your tracks to the person who makes your poster.
  That's the whole machine.</p>
```

- [ ] **Step 3: Replace door two** (h3 stays; per spec Consequences §6 the door stays, demoted and re-registered; the GitHub href is pinned by `test_the_studio_door_exists`)

```html
<p>The app is free if you'd rather do it yourself. It's the same studio I use,
  open source, running on your own machine. Make the poster, order paper with
  the finished file, or print it anywhere you like.</p>
<p class="fine">Free, forever. The plates are free too: the studio pulls the
  same terrain the press uses.</p>
<div class="cta"><a class="btn btn-ghost" data-evt="Studio Click" href="https://github.com/domalhambra/tecopa-plateworks">Run the studio · GitHub</a></div>
```

- [ ] **Step 4: Replace the pricing band head and caption** (the four price cards keep their numbers; reword only as below)

```html
<p class="eyebrow">Founding prices</p>
<h2>Honest numbers to start.</h2>
<p class="lede">Revisited after the first run of orders. Every price includes the
  proof: you see the exact poster and say yes before anything prints or ships.</p>
```

Price-card paragraphs (headings and dollar figures unchanged):

```html
<div><h3><span class="dot"></span>The Poster — $79</h3><p>The digital final: the print-resolution file, wallpapers cut to your screens, and the film. One map, every form.</p></div>
<div><h3><span class="dot"></span>The Print — $149</h3><p>The 18×24 archival print, digital Poster included. The difference buys the physical craft: museum-grade matte stock, my eye on the sheet before it ships, and the shipping itself. Smaller sheets on request.</p></div>
<div><h3><span class="dot"></span>Edition N+1 — $49 / $99</h3><p>Next year, send this year's poster back with the new tracks. The digital edition is $49; the reprinted 18×24 is $99. The ritual costs less than the first year, on purpose.</p></div>
<div><h3><span class="dot"></span>Commission a plate — $299</h3><p>Your ground isn't covered yet? The fee buys the making: the curation, the terrain work, checking it against real ground. Your first 18×24 print is included, and the finished plate publishes free with your name in its record. <a data-evt="Commission Click" href="mailto:domalhambra@hey.com?subject=Tecopa%20Plateworks%20plate%20commission">Start a commission →</a></p></div>
```

(The price-card `<h3>` em dashes are label separators like the title tag, not prose; they stay.)

Caption below the cards:

```html
<p class="caption" style="margin-top:28px">Plates are free. Always. The ground
  your poster stands on is never for sale; that's what makes a reprint years
  from now a promise I can keep. Commission pricing is a founding rate and will
  rise as the plate library grows.</p>
```

- [ ] **Step 5: Commit**

```bash
git add marketing/landing.html
git commit -m "marketing: two doors and prices in the maker's voice"
```

---

### Task 8: Trust block, FAQ, footer

**Files:**
- Modify: `marketing/landing.html:501-506` (trust), `:513-519` (FAQ), `:527` (footer license line)

- [ ] **Step 1: Replace the trust block** (eyebrow included; the three items become the doubts the spec says to answer)

```html
<p class="eyebrow" style="margin-bottom:36px">The part you'd ask about</p>
<div class="trust">
  <div><h3><span class="dot"></span>You see it before it prints</h3><p>The proof I email you is the exact poster. Look it over, ask for changes, and nothing prints or ships until you say yes.</p></div>
  <div><h3><span class="dot"></span>Your tracks are easy to get out</h3><p>Gaia, onX, Strava, and most watches export GPX in bulk. If yours hides the button, I'll point you at it.</p></div>
  <div><h3><span class="dot"></span>It reprints, years from now</h3><p>Keep the file with the print. Send it back in five years for a fresh sheet or the next edition. If the terrain data changed underneath, I'll tell you what moved before printing.</p></div>
</div>
```

- [ ] **Step 2: Replace the FAQ** (five details become four; the struck questions per the spec are "What if Tecopa Plateworks disappears?", "Do you keep my tracks?", and the time-lapse mechanics; "Why only a few regions?" folds into the coverage question)

```html
<details open><summary>How do I get my tracks out of onX or Gaia?</summary><p>Every tracking app has an export: Gaia, onX, and Strava all export GPX in bulk, and most watches will hand over a folder of it. Send me whatever comes out, and re-export everything each year; duplicates and wrong formats are my problem, not yours.</p></details>
<details><summary>Will it look this good on my wall?</summary><p>The crops on this page are unscaled print pixels from the same engine that makes your sheet. And you don't take it on faith: you see your exact poster before it prints.</p></details>
<details><summary>What happens after I email my tracks?</summary><p>I set your years onto the plate, frame the map, and email you the proof: your exact poster, ready to look over. You ask for changes, I make them, you say yes, and the sheet ships with the file alongside.</p></details>
<details><summary>My ground isn't one of the five plates. Now what?</summary><p>Ask for it. The request list decides what gets cut next, and a commission jumps the queue. Each plate is built on real elevation data and checked against real ground, which is why there are five and not five hundred.</p></details>
```

- [ ] **Step 3: Replace the footer license line** (href unchanged; it is pinned)

```html
<div><a data-evt="Studio Click" href="https://github.com/domalhambra/tecopa-plateworks" style="text-decoration:none">Open source</a></div>
```

The engine-render honesty line and the OSM attribution line stay exactly as they are (both pinned).

- [ ] **Step 4: Run the whole pin suite; everything should now pass**

```bash
./.venv/bin/python -m pytest tests/test_marketing_page.py -q
```

Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add marketing/landing.html
git commit -m "marketing: trust and FAQ answer the customer's doubts, not ours"
```

---

### Task 9: Reconcile `docs/marketing.md` with the profile

**Files:**
- Modify: `docs/marketing.md`

The spec's Consequences §2, verbatim intent: an amendment that leaves the page-prescribing passages standing makes marketing.md require and forbid the same material at once. Four edits, each an in-place dated amendment (the doc already carries dated corrections; follow that style):

- [ ] **Step 1: Point the doc at the profile.** Under the opening block (after line 8), insert:

```markdown
> **Amendment 2026-08-16:** the audience and register for every customer-facing
> surface are now canon in
> `docs/superpowers/specs/2026-08-16-target-customer-profile-design.md` (the
> Home-Ground Collector). Where this plan and that profile disagree about what
> the page says, the profile wins. The audiences list below survives as a
> channel map around that one customer, not as co-equal personas.
```

- [ ] **Step 2: Re-translate the feature table's right column** (left column unchanged, except the last row's plate count: "(4 today)" becomes "(5 today)", a deliberate drive-by correction against the five `region.json` files on disk). Replace the table rows with:

```markdown
| Engineering truth | Customer-facing line |
|---|---|
| Provenance manifest in a zTXt chunk | "Keep the file with the print; next year is easy." |
| Deterministic render, spec-driven | "You see the exact poster before it prints." |
| `/api/reprint` — the file carries its whole recipe | "Send it back years from now; it reprints." |
| Living editions + lineage | "Same frame, more ink, Edition 2 in the corner." |
| Embedded photos in the manifest | "Your photos, pinned to the spots they came from." |
| Wallpaper ppi math | "The wallpaper is drawn at the same weight as your print." |
| APNG time-lapse, journeys in day order | "Watch your year draw itself." |
| GNIS labels, hydro, biome tint | "Real terrain, real place names, real rivers." |
| Zoom cap, off-DEM refusal | "I never invent ground. If the data isn't sharp enough, I say so." |
| `embed_spec=false` share copy | "One toggle makes a copy safe to post." (social captions only; never page copy) |
| Curated regions (5 today) | "Handcrafted plates" — scarcity as craft, not limitation. |
```

- [ ] **Step 3: Amend the two page-prescribing sections.** Append after §Landing page blueprint's list:

```markdown
> **Amendment 2026-08-16:** items 5 and 7 are superseded by the profile spec.
> The trust block answers the Collector's four doubts (looks good, easy,
> worth it, shows up right), never "Private by default"; the FAQ asks his
> questions, never "What if you disappear?" or "Do you keep my tracks?". The
> file-as-record and privacy stories live in the nerd channels only.
```

And in §The funnel, honestly, replace the sentence "Requires trusting a person with your tracks; the page says so plainly and states the retention promise (used once, deleted after the edition ships). **That promise is operational — honor it or remove it.**" with:

```markdown
Requires trusting a person with your tracks, and the page carries exactly one
plain line about it at the order door ("you're emailing your tracks to the
person who makes your poster"), per the profile spec: privacy reassurance
answers a question the print-shop customer never asked. (The stated retention
promise was removed from copy 2026-08-15 rather than adopted operationally.)
```

- [ ] **Step 4: Extend §Hierarchy correction (2026-08-13).** Append to that section:

```markdown
**Second half (2026-08-16):** craft copy is written from the customer's chair,
not the builder's. "Design and craft first" produced sentences like "a 2.6 pt
trail is 2.6 pt on glass": craft measured instead of craft shown. The
translation table above is re-baselined against the Home-Ground Collector, and
the register rules live in the profile spec.
```

- [ ] **Step 5: Sweep the rest of the doc** for any remaining passage that prescribes struck page material (grep for `Private by default`, `retention`, `disappear`, `2.6` in `docs/marketing.md`); reconcile any hit with a dated amendment in the same style. Two expected hits need no action: the Step 4 amendment quotes the struck 2.6 line as history, and the ritual-engine channel sentence ("it requires no data retention because *their file* holds everything") describes the business mechanism, never page copy. The naming-kit and success-metric sections stay untouched.

- [ ] **Step 6: Commit**

```bash
git add docs/marketing.md
git commit -m "marketing: canon stops mandating what the page no longer says"
```

---

### Task 10: Verify, eyeball, deploy, verify live

**Files:**
- No source changes. Uses `marketing/build_deploy.py`, Netlify site `1902a58d-74a9-4def-8b4e-d93793f81ac4`.

- [ ] **Step 1: Full marketing suite green**

```bash
./.venv/bin/python -m pytest tests/test_marketing_page.py -q
```

Expected: 8 passed.

- [ ] **Step 2: The eyeball gate.** Serve the repo root (`python3 -m http.server 8777`) and open `http://127.0.0.1:8777/marketing/landing.html` in a real browser. Check: every section renders with no layout break from changed copy lengths; no em dash survives in rewritten prose; then the tailgate read: read the page top to bottom in the shed hunter's voice and flag any sentence he would squint at. This gate is load-bearing; the last session's three worst defects were invisible to a green suite.

- [ ] **Step 3: Confirm with Dom, then deploy**

Production deploy is outward-facing: confirm before running.

```bash
python3 marketing/build_deploy.py
netlify deploy --prod --dir dist/landing --site 1902a58d-74a9-4def-8b4e-d93793f81ac4
```

- [ ] **Step 4: Verify live**

```bash
curl -s https://tecopa.plateworks.org/ | grep -cF "2.6"         # expect 0 (-F: the dot is a wildcard without it, and matches 236px in the CSS)
curl -s https://tecopa.plateworks.org/ | grep -c "until you say yes"   # expect >= 2
curl -s https://tecopa.plateworks.org/ | grep -c "region-request"      # expect >= 2 (form intact)
curl -s https://tecopa.plateworks.org/ | grep -c "OpenStreetMap contributors"  # expect 1
```

Also confirm in a browser that the Netlify form still submits (detection strips `data-netlify`; the `form-name` hidden input is what must survive).

- [ ] **Step 5: Final commit if anything moved, and push**

```bash
git push
```
