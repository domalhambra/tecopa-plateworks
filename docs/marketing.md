# TrailPrint marketing plan — one story, told three times

TrailPrint's feature list reads as thirteen things: GPX import, relief posters,
contours, biome tint, place names, markers, icons, pinned photos, wallpapers, device
bundles, time-lapse films, reprinting, editions. Nobody buys thirteen things. The fix
is to never market features side by side, but as **one story told at three depths** —
and the scope doc (`docs/scope.md`) already wrote the story. This plan is its
outward-facing twin.

> **Your years outdoors, as one artifact that keeps growing.**

Everything the app does is a *consequence* of that sentence: the poster is how the
artifact looks, the film is the artifact in motion, the wallpaper is the artifact on
your phone, editions are how it grows, reprint-forever is why it's safe to invest in.

## The message ladder

**5 seconds (hero line):**
"Drop in your GPX files. Get a museum-quality relief poster of everywhere you've been
— that you can add to every year, forever."

**30 seconds (the pillars, in customer language):**

1. **One picture, every format.** The same composition renders as an archival print,
   an exact-pixel phone/desktop wallpaper, and a time-lapse film of your trails
   appearing in order — the film's last frame *is* your poster.
2. **The file is the whole record.** Every poster carries its own recipe, your route
   data, and even your pinned photos inside the PNG. No account. No cloud. No
   database to lose.
3. **It grows with you.** Next year, drop last year's poster back in with your new
   tracks. It becomes *Edition 2* — same frame, more ink, its lineage printed in the
   corner.

**2 minutes:** the demo script (below).

## Feature translation table

Never say the left column in public. Always say the right column.

| Engineering truth | Customer-facing line |
|---|---|
| Provenance manifest in a zTXt chunk | "The poster is the save file." |
| Deterministic render, spec-driven | "The proof you approve is *pixel-for-pixel* the print you receive." |
| `/api/reprint`, frozen-fixture forever-contract | "Lose everything but the file? Reprint it in 2035. We promise." |
| Living editions + lineage | "Year two doesn't need a new poster. It needs Edition 2." |
| Embedded photos in the manifest | "Pin a photo to the summit. It travels *inside* the file." |
| Wallpaper ppi math | "A wallpaper cut to your exact screen — your 2.6 pt trail is 2.6 pt on glass." |
| APNG time-lapse, journeys in day order | "Watch your year draw itself." |
| GNIS labels, hydro, biome tint | "Real place names, real rivers, real land — from USGS data." |
| Zoom cap, off-DEM refusal | "We never invent terrain. If the data isn't sharp enough, we tell you." |
| `embed_spec=false` share copy | "One toggle strips your exact routes for a share-safe copy." |
| Curated regions (4 today) | "Handcrafted plates" — scarcity as craft, not limitation. |

The last row matters: four regions (Lassen County CA, Susanville–Reno, Elko–Bonneville,
Rifle–Aspen) is not a weakness to hide. Market them like vintages or map plates —
"now serving: the Lassen plate" — and make each new region a launch event.

## Audiences, in priority order

1. **Ultra & trail runners.** They already fetishize the artifact — buckles, bibs,
   split prints. Pitch: "your training block + race day, one poster." The **film** is
   the killer asset here; a season of long runs drawing itself over shaded relief is
   exactly what this crowd reposts.
2. **The yearly ritualists** — hikers, peak-baggers, hunters, ski tourers who think in
   seasons. They are the *editions* audience: "January 1st tradition: drop last year's
   poster in, add the new year."
3. **Gift buyers** — the spouse who exports a year of GPX. They need the simplest
   funnel: three steps, one price, an honest proof preview. Editions become the
   *repeat gift*: same poster, next edition, every anniversary.
4. **Data-sovereignty nerds** (the Show HN audience) — local app, no account,
   self-describing files, frozen schema contracts. Fewer posters, best word-of-mouth.
   Pitch pillar 2 hard.

## The demo IS the marketing

TrailPrint manufactures its own marketing assets — don't design promo graphics,
render them. The 90-second hero sequence (also the landing-page scroll story):

1. *(0–10s)* A folder of GPX files drags onto the window; trails snap onto shaded
   relief. — "Ten years of GPX. One map."
2. *(10–25s)* Frame step: crop tightens, title set, place names on, a photo pins to a
   summit marker. — "Frame it like a print shop would."
3. *(25–40s)* The time-lapse plays: bare terrain, journeys ink themselves in day
   order, ending on the finished poster. — "Watch the year draw itself."
4. *(40–55s)* The same composition as a phone lock screen (labels dodging the clock)
   and a 4K desktop. — "One picture, every screen."
5. *(55–75s)* **The magic trick.** A finished PNG drags back into the app. The whole
   session resurrects — tracks, style, crop, photo. New GPX drops in; the cartouche
   ticks to *Edition 2*. — "Next year, the poster is the save file."
6. *(75–90s)* The print on a wall. — "Your years outdoors, as one artifact that keeps
   growing."

Beat 5 is the differentiator. Every competitor sells a *snapshot*; TrailPrint sells a
*continuing thing*. Lead every long-form asset toward that beat.

## Landing page blueprint

1. **Hero:** looping time-lapse film (it's an APNG — it *is* a web asset), the
   5-second line, one CTA ("Make yours").
2. **Three steps strip:** *Drop your tracks → Frame your poster → Print, wallpaper,
   or film* (matches the real wizard).
3. **Three pillars,** one screen each, alternating image/text — every image rendered
   by the app itself.
4. **The magic trick section:** Edition 1 beside Edition 3 of the same poster,
   lineage cartouche zoomed. Headline: "The poster is the save file."
5. **Trust block:** "The proof is the print" (determinism) · "Reprint forever"
   (frozen contract) · "Private by default" (local, share-copy toggle, no account).
6. **Region gallery:** the four plates with real sample posters, plus "Request the
   next region" email capture — the cheapest demand signal for where to build plate
   #5.
7. **FAQ that converts honesty into trust:** *Why only these regions?* (we refuse to
   print terrain we don't have real elevation data for) · *What if you disappear?*
   (your file reprints itself) · *Strava?* (export GPX; direct import if people ask).

## Channels & launch sequence

- **Phase 0 — asset farm (1–2 weeks).** Render 10–15 flagship pieces across the four
  plates: 3 posters with photos/markers, 2 films, 2 phone wallpapers, 1 three-edition
  lineage set. These feed everything below.
- **Phase 1 — the nerd launch.** Show HN / lobste.rs, pitching pillar 2 ("posters
  that carry their own recipe and reprint themselves forever"). Validates the
  architecture story and stress-tests the message. Pair with a technical blog post —
  "We embed the whole poster recipe in a PNG chunk" — which doubles as durable SEO.
- **Phase 2 — the trail launch.** r/ultrarunning, r/trailrunning, r/Strava, r/hiking
  plus regional groups for the four plates (Lassen/Reno and Roaring Fork communities
  are small and dense). Asset: the film, posted natively — "my year, drawing itself."
  Offer a founding-user run of each plate.
- **Phase 3 — the ritual engine.** Editions write the calendar: year-end ("turn 2026
  into Edition 1"), race seasons, region drops. The repeat purchase isn't "buy another
  product" — it's "your poster is due for its next edition," and it requires no data
  retention because *their file* holds everything.
- **Ongoing:** every customer film shared on social is a looping ad. Consider a
  subtle opt-in cartouche mark on share copies.

## Naming kit (customer-facing)

- The still: **the Print**. The screen deliverable: **Wallpapers**. The APNG: **the
  Year-Film** (or "the Film").
- `POST /api/continue`: **"Continue a poster"** in UI copy; **Living Editions** as
  the brand concept.
- The reprint promise: **"Reprint Forever."**
- The share toggle: **"Share copy (routes removed)."**
- Regions: **plates** ("the Lassen plate") — evokes printmaking, matches the craft.

## What success looks like, in order

1. A stranger repeats the one-liner back after the hero section (test on 5 people
   before anything else).
2. Film completion rate on the landing page — do people watch to the Edition-2 beat?
3. Region-request emails — the expansion roadmap, crowdsourced.
4. **Edition-2 rate a year out** — the single number that proves the chronicle
   thesis. One customer returning a poster for Edition 2 is the testimonial that
   anchors all future copy.

**Do first:** render the Phase-0 asset farm and cut the 90-second sequence. Every
downstream decision gets easier once the film exists — and the app already knows how
to make it.
