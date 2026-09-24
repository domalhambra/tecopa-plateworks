# The Tecopa Landing Page on Ghost — Design

**Date:** 2026-09-24
**Status:** Approved by Dom for build, 2026-09-24, with the theme modules in §3.1.
**Replaces:** `marketing/landing.html` and `marketing/privacy.html` on Netlify
**Follows:** `00-09 System/01 Docs/superpowers/specs/2026-09-14-undercurrent-ghost-pilot-design.md`
in plateworks-os (the pilot that Dom kept on 2026-09-23), and its parent brainstorm
`2026-09-14-ghost-consolidation-brainstorm.md`
**Sells:** the concierge service in `2026-09-24-order-pipeline-design.md`
**Prices:** `docs/decisions.md`, 2026-09-24
**Prototype:** `../prototypes/2026-09-24-ghost-landing-preview.html`. Dom approved its
direction at version 4 of the preview artifact.

**Repos and systems touched:**

- tecopa-plateworks: this spec, a relief exporter, the asset farm, the honesty tests,
  `marketing/`, and the docs.
- `moment-theme` in `20-29 Properties/22 Plateworks Blog/` (local repo, no remote): a
  new page template, a relief viewer, and a contour shader.
- The Ghost site at `blog.plateworks.org`: theme upload, three pages, images, a video,
  code injection, and `redirects.yaml`.
- Cloudflare zone `plateworks.org`: one redirect rule.
- plateworks-hd: `scripts/verify-redirects.ts` and a Tecopa URL list.
- plateworks-os: `properties.md`.

## Goal

Move tecopa.plateworks.org to a Ghost page at `blog.plateworks.org/tecopa/`. The page
shows the posters and lets them sell themselves: drifting contour lines, a wall of
posters, close-ups of the ground, and 3D relief previews that the visitor turns by hand.
One button, "Build your poster," leads to a second page that explains how to order.
Dom edits the words, images and prices in Ghost Admin, with no code.

## Why

- The live page shows old prices and a $299 plate commission that no longer exists.
- The live page sells a program. The customer wants a poster of their own ground
  (the order pipeline spec, Why).
- On Netlify, every copy change is an HTML edit and a deploy by hand. Undercurrent
  moved to Ghost for this reason, and editing got easier.

## Decisions (from brainstorming and the previews)

| # | Decision |
|---|---|
| 1 | The page sells the concierge service. The copy is new. It does not move word for word. |
| 2 | The landing page leads with the beauty of the maps. It says nothing about files, formats, or share images. |
| 3 | Headings name the section plainly: "Prices," "How it works," "Up close." No comma-and-twist headings. This rule is now in `voice-principles.md`, Anti-patterns. |
| 4 | The call to action is "Build your poster." It opens a separate order page. |
| 5 | A customer orders by email to `badwaterguidance@gmail.com`. After the customer says yes to the proof, Dom sends a payment link by Stripe or PayPal. LegalZoom also offers payment links; Dom decides later whether to use it. No page takes payment, and no page has a form. |
| 6 | The region-request form is removed. Every track in the lower 48 gets its own plate. |
| 7 | The plate commission is removed. |
| 8 | The line "I look over every sheet before it ships" is removed. A print lab makes the 18×24. |
| 9 | The template is built first. The page launches on it. |
| 10 | Ghost runs one theme. Tecopa gets a page template inside Moment: `custom-tecopa.hbs`. |
| 11 | The 3D previews render in the browser from two images: a surface image and a height map. Ghost hosts both. The GLB files and `<model-viewer>` retire from the page. |
| 12 | A preview has the shape of a coin or of a poster. The hero shows a poster in relief. |
| 13 | The theme work starts from the downloaded releases in `~/Downloads`: Moment 2.1.3 and Essence 1.1.0. |
| 14 | The media host `media.plateworks.org` is designed but not built. See §7. |
| 15 | The page accent is canon Amethyst, Tecopa's assigned accent in `color-standards.md`. The trail gold appears only inside the posters. |
| 16 | The page uses the Priority Vision modules that suit it, listed in §3.1. The Undercurrent and Ignition pages share them: `00-09 System/01 Docs/superpowers/specs/2026-09-24-product-pages-v2-design.md` in plateworks-os. |

## 1. Pages and addresses

| Item | Value |
|---|---|
| Landing page | Ghost page, slug `tecopa`, template `custom-tecopa` |
| Order page | Ghost page, slug `tecopa-build`, title "Build your poster", template `custom-tecopa` |
| Privacy page | Ghost page, slug `tecopa-privacy-policy`, template `custom-product`, with a section titled "Support" at its foot |
| Old landing address | `tecopa.plateworks.org/*` 301s to `blog.plateworks.org/tecopa/` with the path kept, at the Cloudflare edge |
| Old privacy address | Ghost's `redirects.yaml` sends `/tecopa/privacy/` to `/tecopa-privacy-policy/` |
| Analytics | The Plausible script for the `tecopa.plateworks.org` site and the `evt()` helper go in the code injection of the landing and order pages. `data-evt` attributes: `Build Click` on every "Build your poster" link, `Order Email Click` on the email button. |

The address bar shows the blog host. Dom accepted this for Undercurrent on 2026-09-14.

## 2. What the pages say

The customer profile governs every sentence:
`2026-08-16-target-customer-profile-design.md`. The voice canon governs the rest:
`00-09 System/00 Resources/voice-principles.md`. No em dashes, contractions where speech
has them, concrete before abstract, plain headings, and the full name Tecopa
Plateworks. The prototype holds the draft copy. Dom reads the final copy before publish.

### 2.1 The landing page

| # | Heading | Content |
|---|---|---|
| 1 | A poster of everywhere you've been | The page title over the contour shader. One lede about the land. The "Build your poster" button. The Lassen County poster in relief, with a caption. |
| 2 | Posters I've made | A tilted wall of the finished posters, moving as the page scrolls |
| 3 | Up close | Three close-ups from the engine's detail crops: one wide, two side by side. The captions name places only. One caption says that photos hang beside the spots where they were taken. |
| 4 | See the relief | The six coins |
| 5 | Watch a poster come together | The poster film, muted, on a loop |
| 6 | How it works | Three short steps: send your trips, see your poster, say yes. Step one links to the order page. |
| 7 | Prices | Two short tables, "Your first poster" and "Next year", and a link to the order page |
| 8 | Add next year's trips | Edition N+1 in two sentences, beside one poster |
| 9 | Questions | Getting tracks out of onX or Gaia. Will it look this good on my wall. What happens after I email. Where can you map. Can I make my own (the GitHub link). |
| 10 | Property links | Privacy, Support |

Prices, from `docs/decisions.md`:

| Group | Product | Price |
|---|---|---|
| Your first poster | Print, 13×19 | $79 |
| Your first poster | Print, 18×24 | $89 |
| Your first poster | Digital poster | $39 |
| Next year | Print, 13×19 | $59 |
| Next year | Print, 18×24 | $69 |
| Next year | Digital poster | $25 |

The page does not claim that shipping is included. No decision says so.

### 2.2 The order page

Title "Build your poster". Six numbered steps, because ordering is a real sequence:

1. Gather your tracks: GPX, KML or KMZ, from onX, Gaia, Strava or a watch.
2. Pick your photos. Optional. Photos from a phone work best.
3. Choose a size: the "Your first poster" table.
4. Email me: a "Start the email" button, the address as selectable text with a copy
   button, and an outline to copy (size, title, notes).
5. See it, then say yes. Nothing prints until you do.
6. Pay, and it's on its way: a payment link by Stripe or PayPal.

The email button is a `mailto:` link with a subject and the outline as its body. The
button and the address sit in an HTML card inside `<!--email_off-->` markers, so
Cloudflare does not rewrite them. A `mailto:` link does nothing on some devices, so the
address is always visible as text.

## 3. The template

`custom-tecopa.hbs` at the theme root. It renders inside Moment's `default.hbs`, so the
blog header and footer stay. Its styles are scoped to a body class the template sets, in
a new source file under `assets/css/templates/`. Its script is a new entry under
`assets/js/tecopa/`, loaded only by this template. The prototype holds working versions
of the shader, the wall motion and the viewer. The plan ports them into the theme's
build.

| Part | Source | How Dom edits it |
|---|---|---|
| Hero backdrop | A new contour shader. It reuses the Essence 1.1.0 render loop, context-loss handling and performance tier, already vendored under `assets/js/product/vendor/essence/`. | Not editable. It has no content. |
| Hero poster | The relief viewer, §4 | An HTML card with `data-relief` attributes |
| Poster wall | Moment 2.1.3 Tilt Flow motion, applied to a Ghost gallery card on this template | Add or remove images in the gallery card |
| Up close | Ghost image cards: one wide, then a two-image gallery card | Swap the images and captions |
| Coins | The relief viewer, §4 | An HTML card with six `data-relief` elements |
| Film | Ghost video card, styled for the film's shape | Replace the video |
| How it works, Prices | A Ghost list and a Markdown card, styled by the template | Edit the text |
| Questions | Ghost toggle cards | Edit the text |
| Order page | The same template. Its steps are a numbered list. The email card is an HTML card. | Edit the text |

Rules that carry over from the blog folder's `CLAUDE.md`:

- Colors come from `assets/css/vars.css` only. Its hexes follow
  `00-09 System/00 Resources/color-standards.md`. Run `node scripts/contrast-check.mjs`
  after any color change.
- Package with `npm run build && npx zippie moment.zip`. Do not run `npm run translate`
  or `npm run build:prod`.
- Upload through the Admin API so Ghost overwrites `moment-theme-v6`.
- Test every changed part before packaging.
- `npm run verify` passes: the build, gscan and the biome lint.

**Colors.** The page accent is canon Amethyst, Tecopa's assigned accent
(`color-standards.md`, §Tecopa Plateworks: Amethyst). The button uses `--amethyst-fill`
and `--amethyst-on-fill`. The title italic, the step numbers, link underlines and the
focus ring use `--amethyst-ink`. The contour lines and the coin edges use section-ramp
stops, and the poster edge uses `--section-025`. The gold of the trails appears only
inside the posters. No new color enters canon.

Motion rules for every moving part:

- `prefers-reduced-motion: reduce` stops all motion. The shader shows one still frame.
  The wall lies still. The viewers do not move by themselves.
- Without WebGL, the shader area shows the section's background color. Each viewer shows
  its surface image as a plain `<img>`.
- A shader or a viewer that scrolls out of view stops drawing.

### 3.1 Theme modules

| Module | Source | On this page |
|---|---|---|
| Text mask | Essence 1.1.0 `assets/js/text-mask.js`, copied unchanged to `assets/js/product/vendor/essence/text-mask.js` | The hero title and lede rise line by line as the contour lines fade in |
| Scroll recipes | Moment `scroll-with-attributes.js`, already loaded | The wide close-up starts full width and settles into a framed print as it scrolls in |
| Clip reveal | Moment's reveal effects | The two side-by-side close-ups unroll from the top, like a poster opening |
| Parallax | Moment `parallax.js`, already loaded | The terrain drifts slightly inside each close-up frame |
| Cursor label | Moment `cursor.js`, already loaded | "Drag to turn" follows the pointer over the relief previews |
| Rolling-letter button | Moment `button-animation.js`, already loaded | "Build your poster" rolls its letters on hover |

Left out: horizontal scroll and Essence's navigation transition, which fight Moment's own
scroll and page transitions; scroll snap, which cuts off long sections; the testimonials
carousel, until there are customer quotes.

**Licensing.** Priority Vision's licence allows derivative works for Dom's own sites. The
Essence shader code derives from React Bits (MIT with the Commons Clause) and stays out of
public repos. This repo is public, so the theme code lives only in `moment-theme`. The
prototype here holds only code written for it.

## 4. The relief viewer

A small WebGL renderer in the theme, `assets/js/tecopa/relief.js`. It draws a solid with
a relief top surface from two images. The prototype's viewer is the reference.

Inputs, as attributes on the card's element:

| Attribute | Meaning |
|---|---|
| `data-relief-surface` | URL of the surface image (WebP) |
| `data-relief-height` | URL of the height map (8-bit grayscale PNG) |
| `data-relief-shape` | `disc` or `poster` |
| `data-relief-aspect` | Width over height, for `poster` only |
| `data-relief-alt` | Text for screen readers and for the `<img>` fallback |

Behavior, as built and checked in the prototype:

- The top surface is a grid displaced by the height map, after a light blur so the
  relief reads as land. The sides and the base are solid.
- At rest, a preview faces the viewer and sways slowly. A coin never turns its back.
- Drag turns the preview. After release it eases back to rest.
- One light from the upper left.
- Keyboard: the canvas takes focus, and the arrow keys turn it.
- WebGL 1 only, so older phones work. No library.

The page loads seven viewers: six coins and one poster. Each has its own canvas and
context, below the usual browser limit of 16. The plan measures memory on a phone
before it keeps this layout.

## 5. The relief exporter

A new script in this repo, `scripts/export_relief.py`, beside `scripts/render_model.py`.
It turns finished renders into the images the page uses.

| Output | Source | Size |
|---|---|---|
| `coin.webp` | The texture that `render_asset_farm.py` passes to `build_plate_glb` | 1024 px, WebP quality 82 |
| `coin-h.png` | The same texture through `render_mockups._height_field` | 256 px, 8-bit grayscale |
| `poster-relief.webp` | `poster.png` | 1400 px long edge, WebP quality 84 |
| `poster-relief-h.png` | `poster.png` through `_height_field` | 320 px long edge, 8-bit grayscale |
| `wall.webp` | `poster.png` | 840 px long edge, WebP quality 80 |
| `detail.webp` | `detail.png` | 1200 px long edge, WebP quality 84 |

- The height field is the one `render_model.py` uses, so the web preview and the GLB
  coin show the same relief.
- Deterministic: same inputs, same output bytes.
- `scripts/render_asset_farm.py` calls it for every region.
- It refuses a region with no real terrain record in `assets/index.json`, the same gate
  as `marketing/build_deploy.py` (invariant 11).

Measured on 2026-09-24 with the prototype's exporter: the coin surfaces are 154 to
268 KB and the height maps 44 to 56 KB. The six coins total 1.41 MB, against 12.4 MB of
GLB files. The prototype viewer and shader together are about 20 KB of unminified
script, against 0.98 MB for `<model-viewer>`.

Dom uploads the images to Ghost by hand, or Claude uploads them through the Ghost MCP
`images_upload`. A re-render means a re-upload. The 2026-09-14 brainstorm named this
cost and accepted it.

## 6. The privacy page

The privacy page is rewritten for what a Ghost page loads, in the same way as
Undercurrent's: Ghost's analytics, the theme's fonts, scripts from `cdn.jsdelivr.net`,
images and video from `storage.ghost.io`, and Plausible. Ghost hosts the page and
Fastly carries it. Its contact address is `badwaterguidance@gmail.com`, in an HTML card
inside `<!--email_off-->` markers. Its last section is titled "Support", so Ghost gives
it the `#support` anchor.

The profile struck privacy talk from customer surfaces. The privacy page stays because
the footer links to it and because it states what the pages load. The landing and
order pages say nothing about privacy.

## 7. The media host, deferred

Dom's plan: the Netlify site becomes `media.plateworks.org` and serves rich media that
Ghost cannot hold. With the viewer in the theme and the images on Ghost, the Tecopa
pages have no such file at launch, if Ghost accepts the film.

- The plan uploads the film to a Ghost video card first.
- If Ghost refuses it, the media host is built for the film: the Netlify site takes the
  custom domain `media.plateworks.org` with one Cloudflare DNS record, and a `_headers`
  file allows `https://blog.plateworks.org` to load its files.
- If Ghost accepts it, the media host waits for the first file that Ghost refuses. The
  rich-media brainstorm for Undercurrent and Ignition may find one.

The Netlify site keeps its last landing deploy until the cutover in §9 is kept.

## 8. The honesty checks

Invariant 11 says every claim on the page has a test. Today the tests read
`marketing/landing.html`. That file retires.

- `tests/test_marketing_page.py` changes to fetch the published landing, order and
  privacy pages from `blog.plateworks.org`. The tests carry the `live` marker and are
  left out of the default run.
- They pin: every price in §2.1 on the landing page, the three first-poster prices on
  the order page, the order address on the order page, a link from the landing page to
  the order page, the GitHub link, "OpenStreetMap contributors", and three customer
  doubts from the profile ("until you say yes", "export GPX in bulk", "the person who
  makes your poster"). They also check that the retired claims and the builder's
  register stay absent.
- Deleted with the things they pinned: the commission pin in
  `test_demand_signals_have_a_channel`, the region-request form pin, and the "Tell me
  where you've been" anchor.
- The privacy checks change to what a Ghost page loads.
- Run them after every publish of any of the three pages:
  `.venv/bin/python -m pytest -m live tests/test_marketing_page.py`.
- `tests/test_export_relief.py` runs in the default suite. It checks each output's size
  and mode, determinism, the disc crop, and the terrain gate.

## 9. Order of work

1. **Exporter.** `export_relief.py` and its tests, then the asset farm call.
2. **Theme.** A branch in `moment-theme`: the template, the viewer, the shader, and the
   styles, ported from the prototype. Test every part on a
   draft page, then upload.
3. **Content.** The images, the film, and the landing, order and privacy pages as
   drafts. Dom reads them.
4. **Film check.** If Ghost refuses the film, build the media host (§7).
5. **Cutover.** Publish the three pages. Add the Cloudflare rule and the
   `redirects.yaml` entry. Add the Tecopa pairs to `verify-redirects.ts` and run it. Run
   the live tests.
6. **Retire.** Tag `landing-final-2026-MM-DD` on the commit before removal. Remove
   `marketing/landing.html`, `marketing/privacy.html`, `marketing/vendor/`, and the
   landing parts of `marketing/build_deploy.py`.
7. **Docs.** `CLAUDE.md` (the rows for the farm, the landing page and Netlify, and
   invariant 11's wording), `docs/changing-things.md` (Edit landing or privacy copy),
   `docs/marketing.md` (the commission, the region request, the blueprint),
   `marketing/DEPLOY.md`, `marketing/README.md`, `docs/decisions.md`, and
   `properties.md` in plateworks-os.

**Rollback:** delete the Cloudflare rule. The Netlify site still holds the last landing
deploy, so tecopa.plateworks.org serves the old page again. Redeploy from the tag if the
Netlify site changed.

## Out of scope

- Rich media for the Undercurrent and Ignition pages. That is its own brainstorm.
- An order form, online payment, or a checkout on any page.
- The choice of LegalZoom as a payment option.
- Retiring the GLB coin from the asset farm. Social posts may still link to it.
- A custom domain for the Ghost pages.

## Open, for the plan to settle

- Ghost's size limits for a theme upload and for a video upload. Check before step 2
  and step 4.
- Memory use of seven WebGL viewers on a phone.
- The order of the six coins, and which region's poster is the hero. The prototype uses
  Lassen County.
