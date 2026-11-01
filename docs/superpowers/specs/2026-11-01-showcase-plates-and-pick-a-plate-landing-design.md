# Showcase plates and the Pick-a-plate landing page: design

**Date:** 2026-11-01
**Status:** Approved by Dom, 2026-11-01. Brainstormed with Dom in a Claude Code session on 2026-11-01. Mockups in `.superpowers/brainstorm/14286-1793548420/content/` (gitignored, on Dom's Mac).
**Phasing (Dom, 2026-11-01):** generator overhauls are under way in another session. No plate is built and no image is rendered until that work lands. This phase plans the page's layout and content: this spec, the copy, and the story config as a plan. Section 12 splits the work into the two phases.
**Supersedes:** section 2.1 of `2026-09-24-ghost-landing-page-design.md`, the list of the landing page's sections. Sections 3 to 5 of that spec (the template, the relief viewer, the relief exporter) stand.
**Amends:** `2026-08-15-real-network-demo-tracks-design.md`, section 3 (journey composition). The trail-first rules and the pinned destinations in part 2 below are added to it.
**Governed by:** `2026-08-16-target-customer-profile-design.md` for every sentence a customer reads. `00-09 System/00 Resources/voice-principles.md` for the copy. Invariant 11 (marketing honesty) for every image and claim.

**Repos touched:**

| Repo | What changes |
|---|---|
| tecopa-plateworks | Five new plates. Trail-first demo journeys with pinned destinations. A story config for the farm. New farm tiers (story crops, Journey Light pair). The exporter. The live honesty tests. The docs this spec names in part 6. |
| plateworks-site | The Tecopa landing page: the plate chooser, five stories, the phone layout, the shared tail. A new script module and its tests. The new images. |
| plateworks-os | Business Plan v2, section 6 (Marketing) and the change log. The session log entry. |

## 1. Intent

The landing page at www.plateworks.org/tecopa/ shows finished posters well. It shows almost nothing of what the generator does to make them. Journey Light, the worn paths, the water, the land-cover coloring, the haze on far ridges and the real editions are all invisible on the page. The customer sees a nice map and has no reason to believe a person spent a year on how it is drawn.

Dom's answer to "what do you point at first" fixes the order of the story. First the shading. Then the coloring between desert, forest and water. Then how the track rides the trails and the mountains.

The demo trips on the page are the second problem. They run down section-line roads in straight lines with right-angle turns. On the Tecopa plate, 37 percent of 100 m steps run dead straight. On Lassen County, 23 percent. The routing is the cause, not the map data. Those plates have few mapped trails, so the router drives to every destination. A hike should read as a hike and a slow drive as a slow drive.

## 2. Goals, non-goals, anti-goals

**Goals**

1. A visitor sees the generator's craft, in Dom's order: shading, coloring and water, the track on the terrain.
2. Every demo track looks like a real recording of a hike or a slow drive. Switchbacks, bends that follow a canyon, no section-line squares.
3. Five new plates, each chosen so its ground shows one part of the generator at its best.
4. The page works on a phone as well as on a desk.
5. Every image stays an engine render of real country, and every claim keeps a live test.

**Non-goals**

- No change to prices, the order page, the request form or the privacy page, unless the page loads a new host.
- No new generator feature. The page shows what exists. The customer look changes (decision 12), and that is a default, not a feature.
- No change to the studio.
- No change to the six plates already built. They stay on the page as coins.

**Anti-goals** (the page fails if any of these happens)

- A spec sheet. Numbers, units or engineering words on the page. The profile's register rule: quality is shown and vouched, never measured.
- A claim without a render behind it, or a render of synthetic terrain.
- A chooser that hides plates off screen on a phone, or a horizontal swipe that fights the page scroll.
- A page that needs JavaScript to show its content. The honesty tests read the HTML.

## 3. Decisions made with Dom (2026-11-01)

| # | Decision | Dom's words or reason |
|---|---|---|
| 1 | The page is rebuilt around a plate chooser. Each plate opens its own story. | "I like pick a plate, but maybe each of the 5 options, due to their terrain differences, can highlight different, unique features." |
| 2 | Five showcase plates: Canyonlands and Moab, Lake Tahoe and Desolation, Eastern Sierra, Ruby Mountains, Zion. | "I like the five options you chose, go for all of them." |
| 3 | The page goes wherever the trails are good. The brand's one ground (Great Basin, Sierra, deserts) does not limit the showcase plates. | Dom approved Canyonlands and Zion with the rest. |
| 4 | Demo trips are routed over real trails and roads. They are not anyone's real trips. | "We don't have to be literal here, we just want to see beautiful maps with beautiful-looking tracks." |
| 5 | The story order inside a plate follows what Dom points at: shading, then coloring and water, then the track on the terrain. | Dom, on what he shows someone first. |
| 6 | On a phone: one row of five coins, the open plate's name under it, the row sticky under the site header while reading. | Dom asked for the phone solution and accepted it. |
| 7 | Without JavaScript the five stories stack in order and the coins are jump links. | Keeps every claim in the HTML for the honesty tests. Dom accepted it with decision 6. |
| 8 | The pinned photos in the Tahoe and Zion stories are the farm's demo photo for now. That photo is a painted gradient, not a photograph. Dom supplies real photographs before the page ships. | "Use the farm's demo photos." Then, told it is a gradient: "Do the placeholder gradient photo for now until I find something." |
| 9 | The heading "Every one is real country and real trips" becomes "real country and real trails." | Decision 4 makes "real trips" false. |
| 10 | The six plates already built keep their coins on the page, in a row above the shared tail. | Test `test_every_built_plate_is_on_the_page` requires it. |
| 11 | Layout and content first. Plates, journeys and renders wait for the generator overhauls running in another session. | "Some generator overhauls are happening in another session, so we should just be planning out the landing page layout and content before generating the visuals." |
| 12 | Every customer poster gets biome coloring, geography names, the dry-lake stipple and the elevation profile. `ORDER_LOOK` grows to say so, and the page shows the default. | "Every customer profile gets all that stuff yes." |
| 13 | The copy never uses the shape "I X by Y" ("I color the land by what grows there"). | "Use better structures for wording than 'I X by Y'." |

## 4. The stories

Each plate pairs what its ground does best with the part of the generator that draws it best. The pairing is the story. Three sections per story, each one crop and one or two sentences. Dom approved every pairing in this table.

| Plate | Story | Section 1 | Section 2 | Section 3 |
|---|---|---|---|---|
| Canyonlands and Moab | Cliffs and canyons | Every wall throws its shadow. Cast shadows and sky occlusion. The relief coin to turn. | The river in the canyon. The Colorado and the Green at the Confluence. | A slow drive. The White Rim Road at 1:1, bending with each side canyon. |
| Lake Tahoe and Desolation | Water | The lake shades deeper away from shore. | Every creek finds its way down. Desolation's lakes and their tapered outlets. | Your summits, marked. A mark on each peak done, a photo pinned beside one. |
| Eastern Sierra | Desert floor to alpine | Sage, pinyon, forest, granite. Land-cover coloring. | The climb at the foot of the sheet. The elevation profile strip. | A season draws itself. The film. |
| Ruby Mountains | A range alone in the basin | Far ridges fade. Soft light and haze. | A dry lake prints as a dry lake. The playa stipple on Franklin Lake. | The road you drive every time. Worn paths on Lamoille Canyon Road. |
| Zion | Lit by your own day | Journey Light, before and after. | The switchbacks at 1:1. Walter's Wiggles below Angels Landing. | This year's trips, then next year's. Real Editions 1, 2, 3. |

Features the page shows for the first time: Journey Light, worn paths, lake depth, tapered rivers, the dry-lake stipple, haze and soft light, land-cover coloring, the elevation profile, real editions, the film on a new plate.

Features left off the page on purpose: panel sets (priced, never pictured, and a wall mockup of a three-panel set would be the farm's `mockups` tier, which is out of scope here), wallpapers, the chronological track weave, contours as a named feature, photo frame styles, and track color by height. The trail ink stays gold on every showcase poster, because the page's lede promises trips traced in gold, and a coloured trail would contradict it (my call). Any of them can join a story later as a fourth section.

## 5. Constraints every part obeys

- **Register.** The Home-Ground Collector profile governs every sentence. Second person, plain verbs, the pursuit named, the maker present. No pt, dpi, hash, deterministic, archival, manifest or file-format talk. `BUILDER_REGISTER` in `tests/test_marketing_page.py` enforces it.
- **Voice.** No em dashes. Contractions where speech has them. Plain headings that name the section. Sentence case. The full name Tecopa Plateworks. Eyebrows and section labels may be uppercase and letter-spaced, per the typography canon.
- **Honesty.** Every image is an engine render of real terrain. The terrain guard in `marketing/build_deploy.py` stays as it is. Every claim on the page has a pin in `tests/test_marketing_page.py`, run with `-m live` after publish. A caption describes the render in front of the visitor. A claim describes the product. The two never blur. Example: the Zion Journey Light pair is lit by a sun the builder chose, so its caption says what the light is, and the product claim ("lit by the sun of the day you were there") stands on its own sentence and its own pin.
- **Plates are free.** The word "buy" never appears within three sentences of "plate." OSM geometry stays in the gitignored `cache/networks/`. Plates stay CC0 and carry no OSM data. The page keeps its OSM and 3DEP credit line.
- **Two venvs.** `region_prep.py` and `bake_playa.py` run in `.venv-prep`. Everything else runs in `.venv`.
- **Plate size.** The farm frames a poster at 300 dpi with one native pixel per printed pixel. A 17×22 at 1× on a 10 m plate needs 51 × 66 km of ground, either way up. Every showcase plate is at least 60 km on its short side.
- **Colors and motion.** The page accent is Amethyst, as the 2026-09-24 spec says. Trail gold appears only inside the posters. `prefers-reduced-motion: reduce` stops every motion. A viewer out of view stops drawing.
- **plateworks-site rules.** Addresses never change, and `npm run check` proves it. The components keep the theme's markup. Nothing in the site sends email or charges anyone. Dom merges every pull request, and a merge to plateworks-site is a deploy.
- **Builder.** STATE.md (2026-10-19) names Muse Code as the agent for Plateworks code, with Dom merging. Dom decides which agent builds this spec. The spec is written for either.

## 6. Part 1: the five showcase plates (tecopa-plateworks)

Build each plate by the runbook "Build a new plate" in `docs/changing-things.md`. The bounds below are starting points. The builder adjusts each one after the first `overview.png`, so the story's places sit well inside the frame. The id and the name are fixed here, because the page, the tests and the story config use them.

| id | Name | Starting bbox, lon/lat (W S E N) | About | Must hold |
|---|---|---|---|---|
| `canyonlands_ut` | Canyonlands and Moab | -110.25 37.95 -109.35 38.75 | 79 × 89 km | Island in the Sky, the Needles, the Confluence, the White Rim Road, Moab |
| `tahoe_ca` | Lake Tahoe and Desolation | -120.35 38.70 -119.70 39.35 | 56 × 72 km | The whole lake, Desolation Wilderness, Freel Peak, Mount Tallac, Mount Rose, Pyramid Peak |
| `eastern_sierra_ca` | Eastern Sierra | -118.75 36.45 -118.05 37.40 | 62 × 105 km | Mount Whitney and the Whitney Portal, Lone Pine, Independence, Big Pine and the Palisades, Bishop |
| `ruby_mountains_nv` | Ruby Mountains | -115.75 40.05 -115.05 40.85 | 59 × 89 km | Lamoille Canyon, the Ruby Crest, Ruby Dome, Franklin Lake (dry), Ruby Lake |
| `zion_ut` | Zion | -113.30 37.00 -112.70 37.60 | 53 × 67 km | Zion Canyon, Angels Landing, Observation Point, the Narrows, Kolob Terrace |

Steps per plate, in this order:

1. `.venv-prep/bin/python region_prep.py --id <id> --name "<name>" --bbox <w> <s> <e> <n> --epsg <local UTM>`. Use the UTM zone the neighbouring plates use. If `plan_build` steps the Eastern Sierra plate from 10 m to 30 m, trim its bbox until 10 m holds. Detail is the point of this plate.
2. `.venv/bin/python scripts/build_labels.py <id>`, then `.venv-prep/bin/python scripts/bake_playa.py <id>`. The Ruby Mountains story needs Franklin Lake in `playa.json`. Check that it is there before rendering.
3. Commit the plate files the runbook lists. `dem.tif` stays local.
4. `.venv/bin/python scripts/fetch_track_network.py <id>`. One plate per run, with the script's own backoff. The cache is the snapshot of record.
5. `.venv/bin/python scripts/verify_regions.py`, then judge the plate by eye on the real DEM.

The two tests that bind plates to the page, `test_every_built_plate_is_on_the_page` and `test_no_ghost_plates_on_the_page`, turn red the moment a plate exists without a coin on the live page. Build the plates on a branch and merge them with the page, or accept red live tests until the page ships. The live tests are not in the default run, so CI stays green either way.

## 7. Part 2: trail-first demo journeys (tecopa-plateworks, `scripts/track_network.py`)

Three changes to journey composition. Each is opt-in by plate through the story config in part 3, so the six existing plates render exactly as they do today unless their config asks otherwise.

**Pinned destinations.** A plate's story config may name its destinations. Each name is looked up in `labels.json` (summits and gaps) or `hydro.json` (lakes), snapped to the network as today, and used in place of the seeded farthest-point selection. A name that does not resolve fails the run with the name in the message. It never falls back to a random pick, because the story's captions name these places. Unnamed slots, if any, are filled by the existing selection.

**Trail-first outings.** For a plate that asks for it, the outing leg's road cost rises so the router leaves the road at the trailhead and stays on trail or 4WD ways to the destination. The current weights are `trail 0.6, 4wd 0.7, road 1.5`. The builder tunes the road cost on the real plates and records the value. A trip shape of `drive` is added beside `out_and_back`, `loop` and `4wd`, for the Canyonlands White Rim Road and the Lamoille Canyon Road. A `drive` prefers 4WD and road ways and may be pinned to a named road by its OSM name in the story config.

**Shared approaches.** Worn paths need several trips on one road. Pinned destinations inside one canyon (Lamoille Lake, Island Lake, Liberty Pass) share the only road in, so the worn-width pass gets its repeats from the ground itself. No forcing mechanism is added. The 2026-08-15 amendment that removed trailhead reuse stands.

Everything else stands: densify spacing in printed pixels, the 3 m jitter, the point budget, the season buckets for dates, determinism from cache plus seed.

**Shared approaches** need one more thing from the fetch. `fetch_track_network.py` keeps only `class` and `coords` per way today. It gains the way's OSM `name`, so a `drive` can be pinned to "White Rim Road" or "Lamoille Canyon Road". This change lands before the five networks are fetched, because the cache is the snapshot of record and is not refetched.

**Acceptance.** The straightness measure: take each routed path before densify and jitter, resample it at 100 m along its length, and count the heading changes between consecutive samples that are under 3 degrees. That count over all changes is the plate's straight share. The baseline in section 1 (37 percent Tecopa, 23 percent Lassen) was read from the densified and jittered output, sampled every seventh point, which the 3 m jitter blurs. It understates the problem. Phase B re-baselines the six plates with this method first, then tunes until each showcase plate is under 10 percent. The builder records both sets of numbers in `docs/decisions.md`.

## 8. Part 3: the farm and the exporter (tecopa-plateworks)

**The story config.** A new file, `marketing/stories.toml`, one table per showcase plate. It holds: the story title and its one-line eyebrow, the pinned destinations, the trip shapes and weights of part 2, the plate's look (the spec fields the poster renders with, section 14), and for each of the three sections: the section heading, the render variant it crops from, the crop window centre (CRS metres) and size (printed inches). The farm reads it. The exporter reads it. The honesty tests read it to know which images must be on the page. The six existing plates have no table and render as before.

**The look.** The farm's `_base_spec` renders with contours on and every other feature at the engine default. Biome coloring, geography names, soft light, haze, water depth, dry lakes and the profile strip are all off in today's renders. A customer's order renders with `ORDER_LOOK` in `app/orderspec.py` (soft light 0.35, haze 0.15, water depth 0.5, smart labels, the weave) and nothing else. Decision 12 settles it: `ORDER_LOOK` gains `biome=True`, `labels=True`, `dry_lakes=True` and `profile=True`, with the profile height at its default, and the farm's `_base_spec` renders every plate with `ORDER_LOOK` instead of bare defaults. The studio's new-poster defaults in `app/static/store.js` follow, so a poster opened in the studio matches an order. The rule that holds from here: a showcase poster renders with the same look a customer's poster gets. A plate's config may tune that look the way Dom would tune a customer's poster on that ground, for example more haze on a basin plate so far ridges fade, and the config records the values. The six existing plates re-render with the new look in Phase B, so the whole page shows one look. The `ORDER_LOOK` change touches `app/`, where the other session's overhaul is working, so it lands with or after that overhaul, by agreement between the two sessions.

**New tiers in `render_asset_farm.py`.**

| Tier | What it renders | Replaces or adds |
|---|---|---|
| `stories` | For each section in the plate's config, a 1:1 crop of print pixels from the named variant, at the window the config gives. Named `story_<n>.png`. | Adds. The `detail` tier stays for plates with no config. |
| `journey` | The poster rendered twice with the same spec: `light_mode="archival"` and `light_mode="journey"` with a sun the config gives (`sun_azimuth_deg`, `sun_altitude_deg`, `golden_strength`). Named `poster.png` and `poster_journey.png`. The Zion section 1 crops the same window from both. | Adds. Zion only, by config. |
| `editions` | Unchanged. Editions 1, 2 and 3. Zion section 3 shows all three at wall size. | Exists. |
| `film` | Unchanged. The Eastern Sierra section 3 shows it. | Exists. |
| `coin`, `relief`, `poster` | Unchanged. Every showcase plate gets a coin, a poster relief pair and a wall image. | Exists. |

The `_frame` rule stands: the poster is framed at 300 dpi, one native pixel per printed pixel. Each story crop is cut from print pixels, never upscaled, so what the page shows is what prints.

**The exporter, `scripts/export_relief.py`.** Adds per showcase plate: `story-<n>.webp` for each section (1200 px long edge, quality 84, like `detail.webp`), `journey-before.webp` and `journey-after.webp` for Zion, `edition-1.webp`, `edition-2.webp`, `edition-3.webp` for Zion at wall size (840 px long edge), and `film.mp4` for the Eastern Sierra as today's Lassen film. The terrain guard runs first and is not changed. Deterministic, as today. `tests/test_export_relief.py` grows one test per new output.

**The demo photo.** `_demo_photo.png` is pinned by `_annotate` as today. The Tahoe story's section 3 window is centred on the summit that carries it. The Zion story's section 2 window shows the switchbacks, with a photo pinned at Angels Landing if the window holds it.

## 9. Part 4: the page (plateworks-site)

**Structure, in HTML order.** The page stays `src/content/pages/tecopa.html` on the `custom-tecopa` template. The template's hero (eyebrow, title, lede, the Build button, the contour shader, the poster stage) stays. The poster in the stage becomes the open plate's poster: each story carries its own `tecopa-hero-relief` figure, and the script moves the open story's figure into the stage, as `placeHeroRelief` moves the one figure today. The Lassen poster leaves the hero. Without the script, each story's poster figure stays at the top of its story, so the stage is empty and hides itself. Below the hero:

1. **The chooser.** Five coins in one row, each the plate's `<id>-coin.webp` as a plain image, each a link to its story's anchor (`#canyonlands`, `#tahoe`, `#sierra`, `#rubies`, `#zion`). Under the row, the open plate's name and its story eyebrow.
2. **Five stories**, in the order of the table in section 4, each in its own `<section id="...">`. A story holds its poster figure (moved into the hero when the script runs), its caption (the place and the trips, as today's hero caption), then its three sections. A section is one image card, a plain heading, one or two sentences, and an uppercase eyebrow naming the feature in customer words ("Shading", "Water", "Journey Light"). Zion's section 1 is a before-and-after pair. Zion's section 3 is three wall images in a row. The Eastern Sierra's section 3 is the film card, as today.
3. **More country.** The six existing plates as coins, in the `tecopa-coins` markup the page uses today, under the heading "More country". The visitor can turn them. This keeps every built plate on the page.
4. **The tail**, unchanged in content: How it works, the Start button, Add next year's trips, Prices, Questions. "Add next year's trips" swaps the doubled Susanville poster for Zion's three real editions.

The heading over the whole set of stories reads "Every one is real country and real trails, lit so the mountains stand up off the paper." Its pin in the live tests changes with it.

**The chooser's behaviour** (`theme/assets/js/tecopa/plates.js`, a new module loaded by `index.js`):

- Without the script: all five stories show, stacked, and the coins are anchor links. This is the HTML the honesty tests read.
- With the script: one story shows and four get the `hidden` attribute. A coin tap, a hash change or a link with a hash opens that story and scrolls to its top. No hash opens the default story.
- The default story is Lake Tahoe. (My call. It is the brand's own ground and the plate the named Tahoe prospect lives on. It is one attribute to change.)
- Images inside a hidden story carry `loading="lazy"`, so a hidden story downloads nothing until it opens.
- Relief viewers: the open story's poster viewer and the More country coins are live. A hidden story's viewer is not created until it opens, and it is released when the story hides. At most eight WebGL contexts exist at once, under the browser limit of sixteen.
- Keyboard: the coins are links, so Tab reaches them and Enter opens them. The open coin carries `aria-current="true"`.
- Analytics: each coin carries `data-evt="Plate Pick"`, in the pattern of the page's existing `data-evt` hooks.
- Reduced motion: the story swaps with no animation.

**At phone width** (the site's existing phone breakpoint):

- The coins are 44 px, in one row with the page gutters, so all five fit a 375 px screen.
- Only the open plate's name shows under the row. No labels under the coins.
- Once the visitor scrolls into a story, the row shrinks to 34 px coins and sticks under the site header. It stays until the More country row.
- Sections stack one per screen, as the page's cards do today.

**The before-and-after pair** (Zion, section 1): a comparison with a draggable divider, both images in the HTML, the divider at the middle to start. On a touch screen the divider follows the finger. Without the script, the two images sit side by side with "Before" and "After" captions. (My call.)

**Tests.** `plates.test.js` under `theme/assets/js/tecopa/__tests__/` covers: hash to story, default story, the hidden set, the sticky threshold math. `sections.test.js` learns the story wrapper. `npm test`, `npm run build`, `npm run check` pass before the pull request. After the merge deploys, `.venv/bin/python -m pytest -m live tests/test_marketing_page.py` in tecopa-plateworks passes.

**Images.** Every new image lands under `public/content/images/2026/11/` in plateworks-site, named `<id>-coin.webp`, `<id>-coin-h.png`, `<id>-poster.webp`, `<id>-poster-h.png`, `<id>-wall.webp`, `<id>-story-<n>.webp`, and for Zion `zion_ut-journey-before.webp`, `zion_ut-journey-after.webp`, `zion_ut-edition-<n>.webp`, and for the Eastern Sierra `eastern_sierra_ca-film.mp4` under `public/content/media/2026/11/` with a poster frame. No new host, so the privacy page does not change.

## 10. Part 5: the copy

The copy is written in this phase, before any render exists, as a companion document: `2026-11-01-pick-a-plate-landing-copy.md` beside this spec. It holds every sentence on the page in order: the chooser labels, each story's title, eyebrow, poster caption and three sections, the More country heading, and the changed heading over the stories. The tail's copy is quoted from the live page unchanged. Dom reads and edits that document. When the renders exist, the builder checks each sentence against its crop and changes only what the picture contradicts. The table in section 4 holds each section's heading and its idea.

Rules for the new sentences, beyond section 5:

- A section's heading names the thing plainly. "The lake shades deeper away from shore." Not a twist, not a fragment pair.
- One or two sentences under each heading. The crop does the arguing.
- A number appears only when a customer would count it, such as a sheet size or a price. "Twenty-one switchbacks" stays only if the builder counts twenty-one in the render.
- Place names first. Every caption names its place.
- The product claim and the render caption are separate sentences (section 5, Honesty).
- No sentence of the shape "I X by Y" (decision 13). Lead with what is on the paper. "Pinyon country prints one colour, the forest another, the bare granite a third." The maker's first person stays for vouching and for the service ("I send you a proof before anything prints").
- The pinned photo is a placeholder until Dom supplies photographs (decision 8). The copy for those two sections is written for a real photograph. The page does not ship with the gradient in those slots: step 10 of section 12 checks it.

New pins in `tests/test_marketing_page.py`: the five story anchors, the five story titles, "real trails", each section heading, the Journey Light product claim, and the five new `<id>-coin` images. The retired-claims list gains "real trips".

## 11. Part 6: documents that change

| Repo | Document | Change |
|---|---|---|
| tecopa-plateworks | `CLAUDE.md` | The row for the Tecopa pages points here first. The row for the demo journeys adds this spec. |
| tecopa-plateworks | `docs/changing-things.md` | "Add a region to the farm" gains the story config step and the new tiers. "Edit landing or privacy copy" names the stories and the new pins. |
| tecopa-plateworks | `docs/marketing.md` | An amendment dated with this spec: the page is five stories, one per showcase plate. |
| tecopa-plateworks | `docs/decisions.md` | Rows for: the five plates, trail-first routing and the measured straightness, the story config, Tahoe as the default story, the Journey Light sun chosen for Zion. |
| tecopa-plateworks | `2026-09-24-ghost-landing-page-design.md` | A status line: section 2.1 superseded by this spec. |
| tecopa-plateworks | `2026-08-15-real-network-demo-tracks-design.md` | A status line pointing at part 2 here. |
| tecopa-plateworks | `marketing/DEPLOY.md`, `marketing/README.md` | The story config and the new tiers. |
| tecopa-plateworks | `app/orderspec.py`, `app/static/store.js`, their tests, `docs/decisions.md` | `ORDER_LOOK` and the studio defaults gain biome, labels, dry lakes and the profile (decision 12). |
| plateworks-os | Business Plan v2, section 4 (The offer) | What a Tecopa poster carries by default: the coloring, the names, the dry lakes, the profile strip. |
| plateworks-site | `README.md` or the docs page that describes the Tecopa template | The chooser, the stories, the phone layout. |
| plateworks-os | Business Plan v2, section 6 and the change log | The landing page is five stories. The marketing claim list, if the plan holds one. |
| plateworks-session-log | `SESSION_LOG.md` | This session's entry, and one per build session. |

Every pull request ends with `Docs: <path>` per the documentation standard.

## 12. Order of work

**Phase A: layout and content, now.** Nothing in this phase renders an image or builds a plate.

1. **This spec**, approved by Dom.
2. **The copy document** (part 5). Every sentence on the page, for Dom's read.
3. **The story config as a plan.** `marketing/stories.toml` with each plate's title, eyebrow, pinned destinations by name, trip shapes, and each section's crop described by place ("the Confluence overlook, looking into the inner gorge") instead of metres. The metres are filled in Phase B from the renders.
4. **The page on a branch.** The chooser module and its tests, the story markup, the phone layout, the comparison pair and the More country row (part 4), built in plateworks-site against the copy document, with the five new plates' image slots empty. The branch is not merged. It is reviewed in a local build only. Today's six coins and today's tail stay in it unchanged.

**Phase B: plates and renders, after the generator overhauls land.** It starts when Dom says the other session's work is on `main` and the engine renders as he wants it.

5. **The look.** `ORDER_LOOK`, the studio defaults and the farm's `_base_spec` take the new look (part 3, The look). Agreed with the other session, since it touches `app/`.
6. **Plates.** The fetch script keeps way names (part 2). Then build the five plates (part 1), fetch the five networks, commit the plate files.
7. **Journeys.** Pinned destinations, trail-first weights, the `drive` shape (part 2). Tests first. Re-baseline straightness on the six plates, then measure the five.
8. **Farm and exporter.** The `stories` and `journey` tiers, the exporter outputs, their tests (part 3). Render all eleven plates with the new look. Judge every crop by eye and move windows in the config until each section shows its feature. Fill the metres into the story config.
9. **Images and copy check.** Images into the site branch, the six existing plates' images replaced too. Each sentence read against its crop (part 5).
10. **Pins and the photo gate.** The live tests gain their new pins and lose "real trips" (part 5). Dom's photographs replace the gradient in the Tahoe and Zion sections, or those sections lose the photo and its sentence. The page does not ship with the gradient.
11. **Ship.** `npm test`, `npm run build`, `npm run check`. Pull request. Dom merges, which deploys. Run the live tests against www.plateworks.org/tecopa/.
12. **Docs.** Part 6, in the same pull requests as the work they describe.

Steps 3 and 5 to 8 are tecopa-plateworks pull requests. Steps 4 and 9 to 11 are one plateworks-site pull request. If the generator overhauls change a knob this spec names (`light_mode`, the sun fields, `golden_strength`, the relief passes, the look fields), the story config and part 3 follow the new names, and this spec gets an amendment line.

**Rollback.** The page is one content file, one script module and one stylesheet. Reverting the plateworks-site pull request restores today's page. The plates and the farm changes can stay. The live tests then go red on the five plates without coins, so revert the plate commits too, or hide the plates from `regions/` until the page returns.

## 13. Left to the builder

- Final bounds and UTM zone for each plate, after the overview render.
- The outing road cost, the `drive` shape's weights, and the straightness numbers.
- Each section's crop window, chosen by eye and recorded in the story config.
- The sun for Zion's Journey Light pair: a low sun from the west or southwest, about an hour before sunset on an autumn day, recorded in the config and in `decisions.md`.
- Which three editions subset Zion's trips, so the lineage reads as years.
- The comparison divider's implementation and the sticky row's thresholds.
- The sentences of the copy, within section 10.
- The story config's file format, if TOML does not suit the farm's tooling. JSON is fine.
- How the page branch shows an empty image slot during Phase A: a neutral placeholder block in the page's grounds, never a render of another plate under a new plate's name.
- Franklin Lake's name. The playa pass draws the stipple only, and `build_labels.py` keeps GNIS ranges, summits, gaps, basins, flats and valleys, not lakes, while the hydro names leave out dry lakes. So the dry lake prints without its name unless `build_labels.py` admits a GNIS lake name that falls inside a playa polygon. That is a plate-prep change in `scripts/`, not an engine change. The builder may make it in Phase B. Until then the Ruby Mountains section 2 does not promise the name.

## 14. The builder check (2026-11-01)

A reviewer read the first draft as a builder would and asked five questions. Three were settled as the writer's calls: the hero stage shows the open plate's poster (section 9), the straightness measure is defined on the raw routed path (section 7), and Franklin Lake prints without its name for now (section 13). Two went to Dom and became decisions 12 and 13, with the photo gate in decision 8. The reviewer also found that the network cache drops way names, which section 7 now fixes before the fetches.

## 15. Out of scope

- Prices, the order page, the request form, the privacy page.
- Panel sets, wallpapers and the farm's social mockups on the page.
- The studio, the engine, any new relief pass or spec knob.
- Social posts and the launch sequence in `docs/marketing.md`.
- The six existing plates' demo journeys. They render as today.
