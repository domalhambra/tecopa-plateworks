# The viewshed wash — Design

**Date:** 2026-11-01
**Status:** Draft for Dom's read, after a builder check. Two questions are open. Nothing is built.
**Prototype:** the private page "Tecopa Feature Prototypes". It computed real viewsheds from six named summits on the Rifle–Aspen plate, outside the engine.
**Relates to:** `2026-08-16-target-customer-profile-design.md`, `2026-11-01-showcase-plates-and-pick-a-plate-landing-design.md` (Phase B renders the page's images, so this lands before it or waits for a later render), `../../relief-passes.md`.

## Intent

A poster shows where someone walked. It does not show what they know. The wash shows the ground in line of sight from each of a customer's marks, so the map fills in as marks are added. No track-poster product draws this, to our knowledge, and it draws the Collector's own claim: knowing their ground. It leads with the marks, not the trail ink, as the profile asks.

Dom asked for features that take the poster further and show well on the landing page. Dom asked to see this one, and the prototype is what Dom saw. The wash was recommended first of three, because it costs the least and serves the profile most.

## Goals

- An option, off by default, that washes the sheet by what the marks can see. A person can view the same sheet with it and without it, and choose either.
- A sheet painted at any size shows the same seen ground (invariant 1).
- It scales to any map: one county, or Oregon to Colorado. The work per sheet stays about the same, and it does not grow with the ground covered.
- Adding marks in the next edition visibly grows the seen ground. That is the page's picture.
- True to the plate: every seen cell comes from a line-of-sight calculation on the plate's own DEM.

## Non-goals

- A percentage or tally of ground seen. A number invites a claim the bare-ground calculation cannot back.
- A viewshed from every point along a track. Only marks count in this version. A track has thousands of points, and the profile says the marks are what people point at.
- A wash that grows frame by frame in the film. Marks carry no date. The film shows the finished wash from its first frame.
- Trees, buildings or haze.

## Anti-goals

The build fails, even if it runs, if any of these are true:

- A sheet with the option off changes by one byte.
- The wash claims more than it knows. Customer copy says "line of sight over bare ground", never "what you saw".
- A proof and its final disagree about which ground is seen.
- Moving a mark leaves the old wash on the sheet.
- A mark is dropped silently, for any reason.
- It reads as a mask laid over the map. In the prototype the seen edge was hard and graphic. The terrain must stay the subject.

## Decisions

Each is Claude's call unless it says Dom's. Dom can overrule any of them on reading.

| # | Decision | Why |
|---|---|---|
| 1 | Dom: it is an option, off by default, and a person sees both versions. The spec field is `viewshed`, a float from 0.0 to 1.0, default 0.0, in `STYLE_BOUNDS`. The studio shows an on/off toggle, with one `CONTROLS` entry, and a strength behind it. Toggling is immediate after the first paint, because the seen-ground mask and both paints are cached. | The relief seam's rule: a field, a reader, a pass and a control. A person judges this by flipping it. |
| 2 | OPEN for Dom, see Open questions: which hotspots are observers. Whichever count, a hotspot off the sheet but on the plate still counts, and one off the plate is reported, as hotspots already are. | `density.hotspots` makes spots at the centres of busy 1 km cells, and nobody stood there on purpose. |
| 3 | The eye stands 1.7 m above the ground at the mark. The mark's own location is used as given. | The prototype snapped to the nearest high cell because its marks were named summits, and a customer's mark is where they stood. |
| 4 | The calculation reads the plate's DEM, out past the sheet edge to the plate's bounds, on a fixed ground grid. It belongs in `render`, and the result reaches the pass through `frame.extras`. | A ridge just off the sheet blocks the view, so the frame alone would overstate what is seen. Rule 4 of the seam says region data is `render`'s business and a pass stays pure. A fixed ground grid keeps proof and final identical (invariant 1), the way `_shadow_res_m` does for the cast shadow. |
| 5 | The grid scales with the plate; decision 13 sets the rule. Rifle–Aspen comes out near 30 m. | The prototype ran on 30 m and read well. The wash's edge is a feathered band, not a line a print shows at 1:1. |
| 6 | Rays sample the DEM with bilinear interpolation. | The prototype's first version truncated to cells and drew false edges due east through each pin. A test holds this. |
| 7 | The look: seen ground stays as the terrain already is. Unseen ground loses saturation and falls in value by up to 15% at knob 1.0. The edge feathers over about 100 ground metres. | The prototype tinted seen ground warm, and that read as a mask and fought the hypsometric colour. Quieting the unseen ground keeps the terrain as the subject. Dom judges the final strength on a real proof. |
| 8 | The pass runs at the `finish` stage, before the tonal curve. | The latest stage that lets the curve and grain sit over it evenly. |
| 9 | `hotspots` leaves the terrain cache's mask when `viewshed` > 0. Below that it stays masked. Only the observers' coordinates enter the key: a change to a mark's label, icon or photo must still hit the cache. | `BASE_KEY_MASK_ALWAYS` lists `hotspots` as inert. With the wash on, it no longer is, and moving a mark would show a stale wash. With it off, the terrain cache's hit rate stays as it is. |
| 10 | `ORDER_LOOK` does not gain the knob, so a customer's poster has no wash unless they choose it. If orders get the wash (Open question 2), the preview shows that poster with and without it. | Dom: off by default, and a person sees both. |
| 11 | Editions carry the knob on the spec as any other. Marks added in the next edition widen the wash. No new manifest field. | The edition promise needs nothing more. An old manifest reads as 0 through `spec_from_json`. |
| 12 | Sight distance has no fixed limit. A ray runs until it leaves the plate, or until the curve of the earth (with normal refraction, the standard 0.87 factor on the drop) hides even the plate's highest ground. So distance comes from the terrain: about 5 km from a flat playa, and about 250 km from a summit 4,300 m above the ground around it. | Dom: it must scale, so a fixed cut-off is wrong. The curve is what makes a flat plate round and true, and it also ends each ray early. |
| 13 | The grid has a fixed cell budget for any plate, about 4 million cells, and it is never finer than the plate's own cell. Ray samples get further apart with distance. Oregon to Colorado therefore costs about what a county costs, on a coarser grid. | Dom: a large map is not the same rendering as a small one. A wide sheet shows the wash as a soft band, so it needs no more cells than that. |
| 14 | `MAX_MANIFEST_HOTSPOTS` rises from 64 to 1,000, in this build. The wash's total ray work has a fixed budget however many marks a file declares, so a crafted file cannot hold the machine longer by declaring more. | 64 dates from the first editions work (commit 1571987), and it would stop a real collector. 1,000 marks are about 94 KB of the record's 900 KB budget, before photos. It is the cap that protects `bound_geometry`, so it moves with a test and a budget (invariant 8). |
| 15 | Water keeps its colour. The wash quiets terrain only, and lakes and rivers paint over it unchanged. | They paint after the `finish` stage, so this needs no extra work, and blue water stays legible. |

## What it must do at the edges

- **No marks, knob above 0:** the sheet paints as if the knob were 0.
- **A mark in a NaN hole or over a lake:** it still calculates from its point, using the nearest finite ground. It never fails the render.
- **A panel set:** painted once across the whole sheet, so seams need nothing special.
- **Many marks:** a sheet with 1,000 marks must add under 60 seconds to a proof on Dom's Mac, and 64 marks under 30. Marks on the sheet's own label and marker drawing must hold up at that count too, which is not measured yet. If a target cannot be met, report the measurement to Dom. Do not lower the mark count or drop a mark.
- **Any size of map:** measure on `elko_bonneville` (483 × 331 km). The time must be about the same as on Rifle–Aspen.
- **Plate mismatch on reprint:** the seen ground moves with the plate. The existing 422 covers it.

## Constraints

- The four rules of a relief pass in `../../relief-passes.md`: ground metres, deterministic, strict no-op at the default, never reads plate data from the pass.
- Memory: a pass that holds one more full-sheet plane updates the table in `../../relief-passes.md` and `tests/test_render_memory.py` in the same commit. Hold the mask on the coarse grid and upsample in bands.
- Invariants 1, 2, 3, 7 and 11 of `CLAUDE.md`.
- A customer sentence goes through the profile. A claim on the page gets its test in `tests/test_marketing_page.py`.

## How we know it works

- At knob 0, byte-identity against a build without the pass.
- A proof-versus-final check on the seen mask.
- A synthetic ridge between two points blocks the view. Moving the ridge off the sheet still blocks it.
- A flat plain shows a round viewshed of about 5 km, set by the curve of the earth, with no false edge along the axes.
- A high summit on a wide synthetic plate sees past 100 km.
- A manifest declaring 1,000 marks reprints, and one declaring 1,001 answers 422.
- Flipping the toggle back to a state already painted does no new relief work.
- Moving a mark changes the sheet, and changing only its label hits the cache.
- Dom reads a real proof on Rifle–Aspen, and on one plate where marks sit low in valleys.

## Left to the builder

- The sweep's exact algorithm and ray count, within the time limit.
- How the plate grid is read and how the mask upsamples.
- The control's label and help text in the studio, within the profile's register.
- The name of the module. `app/looks.py` is the pattern to follow.

## Open questions for Dom

1. **Which hotspots count as marks?** A hotspot today is a density spot, a GPX waypoint or a photo spot. The recommendation is waypoints and photo spots only. Density spots move when a track is added, which can shrink the wash, and nobody stood there on purpose. This needs a provenance flag on each hotspot and a rule for old manifests. `_merge_waypoints` also drops a waypoint within 400 m of an existing spot, so it must stop dropping real marks.
2. **Do orders get the wash?** An order's hotspots come from photos only, so a customer's GPX waypoints never reach the spec. The page cannot show a thing a customer cannot buy, and orders are how customers buy. The recommendation is to carry waypoints into orders in this build. It is new work in the order pipeline.

## Not decided here

- Whether the landing page shows the wash, and with what words. That is Pick-a-plate's Phase B.
