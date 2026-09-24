# The Tecopa Landing Page on Ghost — Design

**Date:** 2026-09-24
**Status:** Draft for Dom's review (brainstorming session, 2026-09-24)
**Replaces:** `marketing/landing.html` and `marketing/privacy.html` on Netlify
**Follows:** `00-09 System/01 Docs/superpowers/specs/2026-09-14-undercurrent-ghost-pilot-design.md`
in plateworks-os (the pilot that Dom kept on 2026-09-23), and its parent brainstorm
`2026-09-14-ghost-consolidation-brainstorm.md`
**Sells:** the concierge service in `2026-09-24-order-pipeline-design.md`
**Prices:** `docs/decisions.md`, 2026-09-24

**Repos and systems touched:**

- tecopa-plateworks: this spec, a relief exporter, the asset farm, the honesty tests,
  `marketing/`, and the docs.
- `moment-theme` in `20-29 Properties/22 Plateworks Blog/` (local repo, no remote): a
  new page template, a relief viewer, and a contour shader.
- The Ghost site at `blog.plateworks.org`: theme upload, pages, images, a video, code
  injection, and `redirects.yaml`.
- Cloudflare zone `plateworks.org`: one redirect rule.
- plateworks-hd: `scripts/verify-redirects.ts` and a Tecopa URL list.
- plateworks-os: `properties.md`.

## Goal

Move tecopa.plateworks.org to a Ghost page at `blog.plateworks.org/tecopa/`. The page
sells the concierge service: the customer emails tracks and photos, and Dom makes,
prints and delivers the poster. The page uses its own template with a sense of
adventure: drifting contour lines, a wall of posters, and 3D relief previews that the
visitor can turn by hand. Dom edits the words and prices in Ghost Admin, with no code.

## Why

- The live page shows old prices and a $299 plate commission that no longer exists.
- The live page sells a program. The customer wants a poster of their own ground
  (the order pipeline spec, Why).
- On Netlify, every copy change is an HTML edit and a deploy by hand. Undercurrent
  moved to Ghost for this reason, and editing got easier.

## Decisions (from brainstorming)

| # | Decision |
|---|---|
| 1 | The page sells the concierge service. The copy is new. It does not move word for word. |
| 2 | A customer orders by email to `badwaterguidance@gmail.com`. Dom replies with a Stripe or PayPal payment link. The page takes no payment and has no form. |
| 3 | The region-request form is removed. Every track in the lower 48 gets its own plate. |
| 4 | The plate commission is removed. |
| 5 | The line "I look over every sheet before it ships" is removed. A print lab makes the 18×24. |
| 6 | The template is built first. The page launches on it. |
| 7 | Ghost runs one theme. Tecopa gets a page template inside Moment: `custom-tecopa.hbs`. |
| 8 | The 3D previews render in the browser from two images: a surface image and a height map. Ghost hosts both. The GLB files and `<model-viewer>` retire. |
| 9 | A preview has the shape of a coin or of a poster. The poster preview shows the customer's product in relief. |
| 10 | The theme work starts from the downloaded releases: Moment 2.1.3, Scope 1.0.3, Essence 1.1.0. |
| 11 | The media host `media.plateworks.org` is designed but not built. See §7. |

## 1. Pages and addresses

| Item | Value |
|---|---|
| Landing page | Ghost page, slug `tecopa`, template `custom-tecopa` |
| Privacy page | Ghost page, slug `tecopa-privacy-policy`, template `custom-product`, with a section titled "Support" at its foot |
| Old landing address | `tecopa.plateworks.org/*` 301s to `blog.plateworks.org/tecopa/` with the path kept, at the Cloudflare edge |
| Old privacy address | Ghost's `redirects.yaml` sends `/tecopa/privacy/` to `/tecopa-privacy-policy/` |
| Analytics | The Plausible script for the `tecopa.plateworks.org` site and the `evt()` helper go in the landing page's code injection. The `data-evt` attributes stay on the order buttons. |

The address bar shows the blog host. Dom accepted this for Undercurrent on 2026-09-14.

## 2. What the page says

The customer profile governs every sentence:
`2026-08-16-target-customer-profile-design.md`. The voice canon governs the rest:
`00-09 System/00 Resources/voice-principles.md`. No em dashes, contractions where speech
has them, concrete before abstract, and the full name Tecopa Plateworks. Claude drafts
the copy. Dom reads it before publish.

| # | Section | Content |
|---|---|---|
| 1 | Hero | The page title, "Everywhere you've gone, on one poster," over the contour shader. One poster preview in relief. The order button. |
| 2 | Poster wall | Engine renders of real ground, in a tilted wall that moves as the page scrolls |
| 3 | What you get | The printed poster first. Photos placed on the spots where they were taken. The full-size file and the share images come with it. |
| 4 | How it works | Three steps. Export your tracks. Email them with your photos. See the exact poster, say yes, then pay. |
| 5 | Ground I've made | The six coins, as examples of finished ground |
| 6 | The film | The 9:16 film, muted, on a loop |
| 7 | Prices | The table below |
| 8 | The map fills in | Edition N+1: next year's poster with the new tracks, for less |
| 9 | Do it yourself | One plain line to the free app on GitHub |
| 10 | Questions | Getting tracks out of onX or Gaia. Will it look good on the wall. What happens after you email. Where you can map: the lower 48. |
| 11 | Property links | Privacy, Support |

Prices, from `docs/decisions.md`:

| Product | Price |
|---|---|
| The Poster (digital only) | $39 |
| The Print, 13×19 | $79 |
| The Print, 18×24 | $89 |
| Edition N+1, digital | $25 |
| Edition N+1 reprint, 13×19 | $59 |
| Edition N+1 reprint, 18×24 | $69 |

The order button is a `mailto:` link with a subject line. It sits in an HTML card inside
`<!--email_off-->` markers, so Cloudflare does not rewrite it.

## 3. The template

`custom-tecopa.hbs` at the theme root. It renders inside Moment's `default.hbs`, so the
blog header and footer stay. Its styles are scoped to a body class the template sets, in
a new source file under `assets/css/templates/`. Its script is a new entry under
`assets/js/tecopa/`, loaded only by this template.

| Part | Borrowed from | How |
|---|---|---|
| Hero backdrop | Essence 1.1.0 shader framework, already vendored under `assets/js/product/vendor/essence/` | A new fragment shader draws contour lines that drift. It reuses the vendored render loop, context-loss handling and performance tier. |
| Poster wall | Moment 2.1.3 Tilt Flow home layout | The tilt and scroll motion restyles a Ghost gallery card on this template. The gallery card holds the images, so Dom edits the wall in Ghost Admin. |
| What you get, How it works | Scope 1.0.3 split features section | Each row is a Ghost page with the internal tag `#tecopa-row`. The row's feature image and excerpt fill the row. The template reads them with `{{#get "pages"}}`, oldest publish date first. |
| Prices, Questions | Ghost native cards | A Markdown card holds the price table. Toggle cards hold the questions. The template styles both. |
| Coins, poster preview | New, §4 | HTML cards with `data-relief` attributes. The template script turns each one into a viewer. |
| The film | Ghost video card | The template styles it for 9:16. |

Rules that carry over from the blog folder's `CLAUDE.md`:

- Colors come from `assets/css/vars.css` only. Its hexes follow
  `00-09 System/00 Resources/color-standards.md`. Run `node scripts/contrast-check.mjs`
  after any color change.
- Package with `npm run build && npx zippie moment.zip`. Do not run `npm run translate`
  or `npm run build:prod`.
- Upload through the Admin API so Ghost overwrites `moment-theme-v6`.
- Test every changed part before packaging.
- `npm run verify` passes: the build, gscan and the biome lint.

Motion rules for every moving part:

- `prefers-reduced-motion: reduce` stops all motion. The shader shows one still frame.
  The tilt wall lies flat. The viewers do not turn by themselves.
- Without WebGL, the shader area shows the section's background color. Each viewer shows
  its surface image as a plain `<img>`.
- A viewer that scrolls out of view stops drawing.

## 4. The relief viewer

A small WebGL renderer in the theme, `assets/js/tecopa/relief.js`. It draws a solid
with a relief top surface from two images.

Inputs, as attributes on the card's element:

| Attribute | Meaning |
|---|---|
| `data-relief-surface` | URL of the surface image (WebP) |
| `data-relief-height` | URL of the height map (8-bit grayscale PNG) |
| `data-relief-shape` | `disc` or `poster` |
| `data-relief-aspect` | Width over height, for `poster` only, for example `0.75` for 18×24 |
| `data-relief-alt` | Text for screen readers and for the `<img>` fallback |

Behavior:

- The top surface is a grid displaced by the height map. The sides and the base are
  flat. A disc matches today's GLB coin: 128 rim segments and a relief of 4 mm on a
  22 cm plate, scaled to the canvas.
- Drag turns the preview. It returns slowly to rest when released. When idle, it turns
  slowly.
- One light from above and to the left, so the relief reads as terrain.
- Keyboard: the canvas takes focus, and the arrow keys turn it.
- Size target: 20 KB minified or less. Measure it in the build.

The page loads at most seven viewers: six coins and one poster. Each viewer has its
own canvas and context, below the usual browser limit of 16. The plan measures memory on
a phone before it keeps this layout.

## 5. The relief exporter

A new script in this repo, `scripts/export_relief.py`, beside `scripts/render_model.py`.
It turns a finished render into the two images the viewer reads.

- Input: a render PNG from the asset farm. For a coin, the image that
  `render_asset_farm.py` passes to `build_plate_glb`. For a poster, `poster.png`.
- Height: `render_mockups._height_field`, the same luminance height field that
  `render_model.py` uses. The web preview and the GLB coin show the same relief.
- Output `surface.webp`: 1024 px on the long edge, WebP quality 85.
- Output `height.png`: 256 px on the long edge, 8-bit grayscale.
- A disc crops the centered square, as `render_model._centered_square` does. A poster
  keeps the full frame.
- Deterministic: same input PNG, same output bytes.
- `scripts/render_asset_farm.py` calls it for every region, beside the GLB.
- It refuses a region with no real terrain record in `assets/index.json`, the same gate
  as `marketing/build_deploy.py` (invariant 11).

Measured on `lassen_ca` on 2026-09-24: the GLB is 1.96 MB, and 1.68 MB of that is its
PNG texture. The same texture as WebP at quality 85 is 0.21 MB. The height map is an
estimate: about 15 KB. The six coins drop from 12.4 MB to about 1.4 MB, and the viewer
script drops from 0.98 MB to about 20 KB.

Dom uploads the images to Ghost by hand, or Claude uploads them through the Ghost MCP
`images_upload`. A re-render means a re-upload. The brainstorm of 2026-09-14 named
this cost and accepted it.

## 6. The privacy page

The privacy page is rewritten for what a Ghost page loads, in the same way as
Undercurrent's: Ghost's analytics, the theme's fonts, scripts from `cdn.jsdelivr.net`,
images and video from `storage.ghost.io`, and Plausible. Ghost hosts the page and
Fastly carries it. Its contact address is `badwaterguidance@gmail.com`, in an HTML card
inside `<!--email_off-->` markers. Its last section is titled "Support", so Ghost gives
it the `#support` anchor.

The profile struck privacy talk from customer surfaces. The privacy page stays because
the footer links to it and because it states what the page loads. The landing page says
nothing about privacy.

## 7. The media host, deferred

Dom's plan: the Netlify site becomes `media.plateworks.org` and serves rich media that
Ghost cannot hold. With the viewer in the theme and the images on Ghost, the Tecopa
page has no such file at launch, if Ghost accepts the film.

- The plan uploads `film.mp4` to a Ghost video card first.
- If Ghost refuses it, the media host is built for the film: the Netlify site takes the
  custom domain `media.plateworks.org` with one Cloudflare DNS record, and a `_headers`
  file allows `https://blog.plateworks.org` to load its files.
- If Ghost accepts it, the media host waits for the first file that Ghost refuses. The
  rich-media brainstorm for Undercurrent and Ignition may find one.

The Netlify site keeps its last landing deploy until the cutover in §9 is kept.

## 8. The honesty checks

Invariant 11 says every claim on the page has a test. Today the tests read
`marketing/landing.html`. That file retires.

- `tests/test_marketing_page.py` changes to fetch the published page at
  `https://blog.plateworks.org/tecopa/` and the privacy page. The tests carry the
  `live` marker and are left out of the default run.
- They pin: every price in the table in §2, the order address, the Do-it-yourself link
  to `https://github.com/domalhambra/tecopa-plateworks`, "OpenStreetMap contributors",
  the four customer doubts from the profile, and the absence of the retired claims and
  of the builder's register. The commission pin
  (`test_demand_signals_have_a_channel`) is deleted with the commission.
- The privacy checks change to what a Ghost page loads.
- Run them after every publish of either page:
  `.venv/bin/python -m pytest -m live tests/test_marketing_page.py`.
- `tests/test_export_relief.py` runs in the default suite. It checks the output sizes,
  the grayscale mode, determinism, the disc crop, and the terrain gate.

## 9. Order of work

1. **Exporter.** `export_relief.py` and its tests, then the asset farm call.
2. **Theme.** A branch in `moment-theme`: the template, the viewer, the shader, and the
   styles. Test every part in a local Ghost or on a draft page, then upload.
3. **Content.** The six row pages, the images, the film, and the landing and privacy
   pages as drafts. Dom reads them.
4. **Film check.** If Ghost refuses the film, build the media host (§7).
5. **Cutover.** Publish both pages. Add the Cloudflare rule and the `redirects.yaml`
   entry. Add the Tecopa pairs to `verify-redirects.ts` and run it. Run the live tests.
6. **Retire.** Tag `landing-final-2026-MM-DD` on the commit before removal. Remove
   `marketing/landing.html`, `marketing/privacy.html`, `marketing/vendor/`, and the
   landing parts of `marketing/build_deploy.py`.
7. **Docs.** `CLAUDE.md` (the rows for the farm, the landing page and Netlify, and
   invariant 11's wording), `docs/marketing.md` (the commission, the region request,
   the blueprint), `marketing/DEPLOY.md`, `marketing/README.md`, `docs/decisions.md`,
   and `properties.md` in plateworks-os.

**Rollback:** delete the Cloudflare rule. The Netlify site still holds the last landing
deploy, so tecopa.plateworks.org serves the old page again. Redeploy from the tag if the
Netlify site changed.

## Out of scope

- Rich media for the Undercurrent and Ignition pages. That is its own brainstorm.
- An order form, online payment, or a checkout on the page.
- Retiring the GLB coin from the asset farm. Social posts may still link to it.
- A custom domain for the Ghost page.

## Open, for the plan to settle

- Ghost's size limits for a theme upload and for a video upload. Check before step 2
  and step 4.
- Memory use of seven WebGL viewers on a phone.
- The order of the six coins, and which region's poster is the hero preview.
