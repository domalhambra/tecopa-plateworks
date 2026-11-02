# The viewshed wash — Design

**Date:** 2026-11-01
**Status:** Approved by Dom, 2026-11-01. Built on branch `claude/viewshed-wash-design`; awaits Dom's read of a real proof.
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
| 2 | Dom: only real marks are observers: GPX or KML waypoints, photo spots, and any spot a person named or gave a photo. Machine-made density spots are not. A real mark off the sheet but on the plate still counts, and one off the plate is reported, as hotspots already are. | Density spots sit at the centres of busy 1 km cells, nobody stood there on purpose, and adding a track can move them. |
| 3 | The eye stands 1.7 m above the ground at the mark. The mark's own location is used as given. | The prototype snapped to the nearest high cell because its marks were named summits, and a customer's mark is where they stood. |
| 4 | The calculation reads the plate's DEM, out past the sheet edge to the plate's bounds, on a fixed ground grid. It belongs in `render`, and the result reaches the pass through `frame.extras`. | A ridge just off the sheet blocks the view, so the frame alone would overstate what is seen. Rule 4 of the seam says region data is `render`'s business and a pass stays pure. A fixed ground grid keeps proof and final identical (invariant 1), the way `_shadow_res_m` does for the cast shadow. |
| 5 | The grid scales with the plate; decision 13 sets the rule. Rifle–Aspen comes out near 30 m. | The prototype ran on 30 m and read well. The wash's edge is a feathered band, not a line a print shows at 1:1. |
| 6 | Rays sample the DEM with bilinear interpolation. | The prototype's first version truncated to cells and drew false edges due east through each pin. A test holds this. |
| 7 | The look: seen ground stays as the terrain already is. Unseen ground loses saturation and falls in value by up to 15% at knob 1.0. The edge feathers over the larger of 100 ground metres and 3 grid cells. The build picked the numbers the spec left open: unseen ground loses 50% of its saturation, and its value falls 12.8% at the `finish` stage, which the tonal curve after it steepens to at most 15% on the print. Both wait for Dom's read of a real proof. | The prototype tinted seen ground warm, and that read as a mask and fought the hypsometric colour. Quieting the unseen ground keeps the terrain as the subject. Dom judges the final strength on a real proof. |
| 8 | The pass runs at the `finish` stage, before the tonal curve. | The latest stage that lets the curve and grain sit over it evenly. |
| 9 | `hotspots` leaves the terrain cache's mask when `viewshed` > 0. Below that it stays masked. Only the observers' coordinates enter the key: a change to a mark's label, icon or photo must still hit the cache. | `BASE_KEY_MASK_ALWAYS` lists `hotspots` as inert. With the wash on, it no longer is, and moving a mark would show a stale wash. With it off, the terrain cache's hit rate stays as it is. |
| 10 | `ORDER_LOOK` does not gain the knob, so a customer's poster has no wash unless they choose it. Decisions 18 to 20 say how an order asks for it. | Dom: off by default, and a person sees both. |
| 11 | Editions carry the knob on the spec as any other. Marks added in the next edition widen the wash. No new manifest field. | The edition promise needs nothing more. An old manifest reads as 0 through `spec_from_json`. |
| 12 | Sight distance has no fixed limit. A ray runs until it leaves the plate, or until the curve of the earth (with normal refraction, the standard 0.87 factor on the drop) hides even the plate's highest ground. So distance comes from the terrain: about 5 km from a flat playa, and about 250 km from a summit 4,300 m above the ground around it. | Dom: it must scale, so a fixed cut-off is wrong. The curve is what makes a flat plate round and true, and it also ends each ray early. |
| 13 | The grid has a fixed cell budget for any plate, about 4 million cells, and it is never finer than the plate's own cell. Ray samples get further apart with distance. Oregon to Colorado therefore costs about what a county costs, on a coarser grid. | Dom: a large map is not the same rendering as a small one. A wide sheet shows the wash as a soft band, so it needs no more cells than that. |
| 14 | `MAX_MANIFEST_HOTSPOTS` rises from 64 to 1,000, in this build. The wash's total ray work has a fixed budget however many marks a file declares, so a crafted file cannot hold the machine longer by declaring more. | 64 dates from the first editions work (commit 1571987), and it would stop a real collector. 1,000 marks are about 94 KB of the record's 900 KB budget, before photos. It is the cap that protects `bound_geometry`, so it moves with a test and a budget (invariant 8). Photo-bearing hotspots keep a cap of 64 in a manifest (`MAX_MANIFEST_PHOTOS`), because each photo costs real drawing work that the wash's budget does not cover. |
| 15 | Water keeps its colour. The wash quiets terrain only, and lakes and rivers paint over it. Rivers are unchanged. A lake is 235/255 opaque, so the ground under it still shows a little, and a lake can move up to 3 levels per channel under the wash. | They paint after the `finish` stage, so this needs no extra work, and blue water stays legible. A lake mask the size of the sheet would cost more than the 3 levels show. |
| 16 | A hotspot gains an optional `mark: true`, set by `ingest._waypoint_hotspot`. A hotspot is a mark if it has that key, a photo or a non-empty label. An old manifest needs no migration: its named spots and photo spots count, and its unnamed density spots do not. | One rule covers new and old files, and read-tolerance keeps old files opening. |
| 17 | `_merge_waypoints` keeps every waypoint. A waypoint within 400 m of a density spot replaces that spot. Two waypoints close together both stay. | The old rule dropped a real mark in favour of a machine-made one. Two finds 300 m apart are two marks to a shed hunter. |
| 18 | Dom: orders get the wash. Prepare reads waypoints from the order's files with `ingest.load_waypoints`, in the same step that reads the tracks, and keeps them in the order's state, as photos are kept. `order new` reads no file, so it reads no waypoint. | The page cannot show a thing a customer cannot buy. |
| 19 | An order's waypoints reach its spec, and draw as pins, only when that order asks for the wash, through a new `viewshed` key in `order.toml`. Without the key the order prints exactly as it does today. Dom sets the key from the customer's reply; no intake form changes in this build. After a studio save, the saved spec decides what prints, and Prepare warns when the key disagrees. | Off by default. A customer's phone may hold hundreds of waypoints they never meant to print. Turning those on for every order would change a poster nobody asked to change. |
| 20 | With the key set, the size preview shows the poster with and without the wash, and the approval hash covers the waypoints. An order over 1,000 real marks stops at Prepare and names the count, and Dom asks the customer for a trimmed file. `order new` never replaces or removes a file, so the old file leaves the count only when Dom deletes it from `in/` by hand. | Dom: a person sees both. A customer approves what prints. No mark is dropped silently. |

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
- A density spot never widens the wash, and naming it makes it a mark.
- A waypoint within 400 m of a density spot survives, and an old manifest's named spots still count.
- An order without the `viewshed` key has an unchanged spec hash and prints the same bytes.
- An order with the key shows its waypoints as pins, and its preview shows both versions.
- Flipping the toggle back to a state already painted does no new relief work.
- Moving a mark changes the sheet, and changing only its label hits the cache.
- Dom reads a real proof on Rifle–Aspen, and on one plate where marks sit low in valleys.

## Left to the builder

- The sweep's exact algorithm and ray count, within the time limit.
- How the plate grid is read and how the mask upsamples.
- The control's label and help text in the studio, within the profile's register.
- The name of the module. `app/looks.py` is the pattern to follow.

## Not decided here

- Whether the landing page shows the wash, and with what words. That is Pick-a-plate's Phase B.

## What the build changed

Written after the build, 2026-11-01, from the ruling lines of the build ledger. The sections above are the design as Dom approved it, except decisions 7, 15, 18 and 20, which carry the amendment in their rows. Each entry below says what the build did and why. The strength of the wash is still open: Dom judges it on a real proof.

| Ruling | What the build did |
|---|---|
| Waypoints off the plate | A waypoint off the plate stays, and the upload reply counts it apart from the waypoints over a file's cap. The spec binds: no mark is dropped silently. The first reading of the plan, that `load_waypoints` dropped them, was wrong. |
| Pixels, not bytes | The anti-goal "changes by one byte" reads as pixels. A new field always reaches `spec_to_json` (invariant 7), so a new manifest differs in bytes. |
| Carrying waypoints into an edition | A carry also drops a recomputed density spot within 400 m of a kept waypoint, so the density peak a pin replaced does not return beside it on every added track. |
| Photo hotspots in a manifest | A manifest keeps a cap of 64 photo-bearing hotspots (`MAX_MANIFEST_PHOTOS`), beside the cap of 1,000 hotspots. `bound_geometry` runs before `drop_unembedded_photos`. Each photo costs drawing work that the wash's budget does not cover. |
| One fixed fan, no per-mark share | Every mark runs the same fan of 1,024 rays, so more marks can only add ground. `SAMPLE_BUDGET` is a sizing ceiling for 1,000 marks that a test holds. It is not a share of each mark. One mark is no finer than a thousand. |
| The first sweep, replaced | The first sweep over-claimed seen ground by 47 to 73%, against the anti-goals. The replacement lays rings one cell apart with no pyramid, paints a tile only when all four neighbours are seen, and stamps boundary samples at cell size. It leaves +10 to +22% at the edge, at twice the sweep time. |
| The slowest case | A bowl where every mark sees everything takes 47.23 s at 1,000 marks, 2 s past the 45 s outer limit set for the build. Real plates take 13 to 21 s. The case stands. |
| The feather | The feather is the larger of 100 m and 3 grid cells. Two cells showed stair steps on Elko's enhanced ratio map at the tightest crop. Elko's edge is 600 m wide against 400 m. |
| Lakes | Lakes can move up to 3 levels per channel under the wash (decision 15). |
| The approval hash | `spec_hash` keeps the new field, so an order approved before this build asks to be approved again, with a clear message. Invariant 7 forbids omitting it at the default. No approved order stood in `~/Tecopa Orders` at the time. |
| The look's two numbers | Unseen ground loses 50% of its saturation and falls 12.8% in value at `finish` (decision 7). Decision 7 names no saturation number. |
| Marks without a bound in the studio | A proof with the wash on and more than 1,000 marks answers 422, naming both numbers, because sessions add marks upload by upload past the per-file cap. A final needs no second check, since it renders only a stamped proof's spec. No mark is dropped. |
| Two store fields | The studio keeps `viewshedOn` and `viewshed`, since `toggleMap` tests equality with an on value, which a slider's value cannot hold. The spec keeps one field. |
| A look that omits the knob | A look or preset that omits the knob leaves it as the person set it, as soft light and haze do. Archival pins it off. A look can never turn the wash on, so default-off holds. |
| The saved spec decides | After a studio save, the saved spec decides what prints, and `order.toml`'s `viewshed` does not override it. Prepare warns when they disagree, and its report reads from the spec that prints. An override would void the customer's approval silently. |
| Prepare reads waypoints, not `order new` | `order new` opens no file, and Prepare is where tracks are first read (decision 18). The wash reaches every printed order. |
| One waypoint, once | The same waypoint in two files, within 1 m, counts once, in orders as in the studio. A false stop would have Dom asking a customer to cut real marks. |
| Over-cap messages | Both messages name steps that exist (final review). The studio says to start a new poster from fewer files, or turn the wash off, because it has no control that removes a mark. An order's message says that `order new` never replaces or removes a file, so a trimmed file leaves the old one in the count until Dom deletes it by hand. |
