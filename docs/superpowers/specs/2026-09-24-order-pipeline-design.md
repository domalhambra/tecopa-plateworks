# Order Pipeline: from a Customer's Tracks to a Print and a Package — Design

**Date:** 2026-09-24
**Status:** Approved by Dom (brainstorming session, 2026-09-23 to 2026-09-24)
**Extends:** `2026-07-19-gpx-first-region-creation-design.md` (plate building, the build queue)
**Amends:** invariant 6 in `CLAUDE.md`, and pillar 2 of `docs/scope.md` (see Amendments)

## Goal

Tecopa Plateworks makes a consistently great map from any GPX track in the lower 48,
efficiently. One order is one folder in and one folder out. The studio is kept for
the one manual job left: placing photos and approving the proof.

## Why

The marketing sold the program. The customer does not care about the program. They
care about a great-looking poster of their own ground, with their photos on it, and
something to share. Tecopa Plateworks is a concierge service: the customer sends
tracks and photos, and Dom prints and delivers. This design works backward from that
poster to the program changes.

The printer is a Canon imagePROGRAF PRO-1100: 17" maximum width, sheets up to 17×22,
or a 17" roll. It prints from a TIFF. The customer gets a JPG and a share kit.

## Decisions (from brainstorming)

| # | Decision |
|---|---|
| 1 | Any GPX in the lower 48. The plate is built per order around the tracks. Alaska and Hawaii come later. |
| 2 | Framing is "nestled": the tracks span about 60% of the map, with ground around them. |
| 3 | The sheet is a standard frame size from a paper table, not a custom length. |
| 4 | Photos sit in open ground with leader lines to their spots. A gallery band is the fallback. |
| 5 | A photo's spot comes from its GPS, then from its time on the track, then from a drag in the studio. |
| 6 | Terrain uses the coarsest 3DEP layer that holds the print (10, 3 or 1 m). Upsampling is allowed up to 2×. |
| 7 | Deliverables: the print (TIFF), the full-resolution JPG, and a share kit (4:5 and 9:16 stills, 9:16 film). |
| 8 | Launch paper: Canon Photo Paper Pro Platinum PT-101 at 13×19 and 8.5×11. PT-101 17×22 and LU-101 4×6 are options. |
| 9 | 300 ppi for every print. |
| 10 | Approach A: an order pipeline driven by two commands, with the studio for review. Studio-first wizards and patching the curated-plate flow were rejected. |
| 11 | The share kit has no square still. The film uses light motion. |
| 12 | Delivery is an iCloud Drive link. A "no place names" option exists for share files and is off by default. |

## 1. The order folder

Customer data stays outside the repo. The repo is public.

```
~/Tecopa Orders/                     (TECOPA_ORDERS_DIR overrides)
  _cache/                            3DEP, NHD, NLCD tiles shared by all orders
  2026-10-001-smith/
    in/            GPX, KML, KMZ and photos, exactly as the customer sent them
    order.toml     title, subtitle, size, orientation, options, notes
    work/          plate, state.json, proofs, the record PNG
    out/print/     <title>-<size>.tif, PRINT.txt
    out/customer/  the JPG, the share kit, <title>.zip
```

- `order.toml` holds what Dom decides. `work/state.json` holds what Prepare and the
  studio decide: frame, paper row, orientation, photo spots, photo boxes, captions,
  and approval.
- Nothing writes to `in/`. The studio writes only to `work/`.

## 2. The three steps

1. **Prepare** — `scripts/order.py prepare <folder>`. Runs in `.venv`. Reads the
   tracks and photos. Reuses or builds a plate (section 3). Frames the tracks and
   picks the sheet (section 4). Finds photo spots and lays out photos (section 5).
   Renders the proof and the PT-101 soft proof. Ends with a report of what it could
   not do, for example "2 photos have no spot."
2. **Review** — the studio opens the order from `work/state.json`. Dom places
   unplaced photos, moves photo boxes, edits the title and captions, and adjusts the
   frame. Approve writes the approval and a hash of the state.
3. **Finish** — `scripts/order.py finish <folder>`. Refuses if the state changed
   after approval. Renders the TIFF (section 6) and the customer package (section 7).

Rules:

- Prepare runs again safely. It keeps every manual change in `state.json`: placed
  photos, moved boxes, edited captions, an adjusted frame.
- One order at a time. There is no queue.
- The curated plates stay. The marketing farm and the demos use them. An order
  reuses a curated plate when the frame fits inside it at the print's resolution.

## 3. The plate for each order

Prepare builds the plate through the existing path: `regionbuild.run_build` spawns
`region_prep.py` in `.venv-prep`, then `scripts/build_labels.py`. Sources do not
change: 3DEP, NHD, NLCD, GNIS.

**Frame first, plate second.**

1. Measure the bounding box of all tracks.
2. Grow it until the tracks span `NESTLE_FILL = 0.60` of the frame on the side they
   fill more. Tune the constant by eye on proofs.
3. Match the frame to the sheet's aspect ratio (section 4).
4. Build the plate 10% larger than the frame on each side. The margin gives room for
   oblique and for small frame changes in the studio.

For orders, this replaces the 20% padding with a 3 km floor in `derive_bbox`. The
in-app build flow keeps `derive_bbox`.

**Resolution follows the print.** Needed ground resolution = frame width ÷ (print
width × 300).

- The plate's grid follows the need. From 10 to 20 m and from 30 to 60 m it uses the
  static 10 or 30 m tiles, which are more reliable than the dynamic service, so the
  plate holds at most 4× the print's pixels. Other grids come from the 3DEP dynamic
  service: quarter metres below 10 m (a 1 or 3 m layer must fully cover the plate),
  and 5 m steps from 20 to 30 m and above 60 m. The static 60 m tiles cover Alaska
  only. `DEM_RES_CHOICES` does not change.
- Check 3DEP coverage for the layer before using it. The 3DEP service fills gaps with
  resampled coarser data and does not say so. A layer is used only if it covers
  everything the best layer covers, within 0.5%, so ocean and ground across a border
  count against no layer. A plate that is mostly outside US data is refused.
- If no layer is fine enough, allow upsampling up to 2×.
- Past 2×, widen the frame until 2× holds. The customer's size wins over the
  nestled fill. Warn when the fill drops below 40%, and name the smaller sheet that
  would keep the nestled look.

**Projection:** the UTM zone of the frame's centre. Frames wider than 600 km use
CONUS Albers (EPSG:5070).

**Build time:** unknown. The plan for sub-project 1 measures it on three real track
sets. The target is under 10 minutes.

## 4. The sheet and the paper table

`config/papers.toml` lists every sheet. Dom enables a row when the paper is in stock.

| Paper | Sheet | Print size | At launch |
|---|---|---|---|
| PT-101 Platinum | 13×19 | 12×18 (The Print) | on |
| PT-101 Platinum | 8.5×11 | 8×10 | on |
| PT-101 Platinum | 17×22 | 16×20 | option |
| LU-101 Luster | 4×6 | 4×6 | option |
| Roll, 17" | 17 × any | 12×36 panoramic | later |

Each row stores: paper name, sheet size, print size, ICC profile name, rendering
intent, margins, whether the image rotates to feed, and the Print & Layout preset name.

**Choosing the size:**

- The customer's order sets the size. Prepare picks portrait or landscape, whichever
  frames the tracks with less wasted ground.
- With no size set (a quote or a demo), Prepare scores every enabled row by how close
  it comes to `NESTLE_FILL` within the 2× upsampling limit. It recommends the best.
- When the best orientation still wastes much of the sheet, Prepare warns and names
  the row that fits better.
- Dom can override the size or orientation in `order.toml` or the studio. The frame
  then refits.

**Margins:** the print sits centred on the sheet with a white border, for example
0.5" on 13×19. No full bleed at launch.

## 5. Photos

**Formats:** JPEG, PNG, HEIC. HEIC needs `pillow-heif` in `.venv`.

**Finding the spot, in order:**

1. EXIF GPS.
2. Time on the track. Match `DateTimeOriginal` to the track time only when the photo
   stores `OffsetTimeOriginal`. GPX times are UTC. Without the offset, skip this step.
3. Neither: the photo goes to the studio's unplaced tray. Dom drags it to its spot.

A photo's spot makes a mark. The mark's default caption is the nearest GNIS name
within 2 km, and Dom can edit it (sample-kit finding #11). The existing `/api/photo`
attaches a photo to a marker index. Orders need a photo to own its spot. The plan for
sub-project 3 decides whether to extend the marker model or add a photo-spot record.

**Layout in open ground:**

- Open ground excludes tracks (with clearance), the title block, and major labels.
- Place each photo near its spot. Leader lines do not cross each other. They should
  not cross a track.
- Photo box size scales with the sheet, about 2.25" on 12×18. The frame styles stay:
  mat, keyline, borderless, polaroid.
- Photos are centre-cropped to the box. Dom can move a box or change its crop in the
  studio. Prepare keeps those changes.

**Gallery band fallback:** if any photo has no open slot, the whole poster uses the
band. The map shows numbered marks, and the photos run in a strip below. The two
layouts never mix. The photo limits are set after testing, starting at 8 in open
ground and 12 in the band.

**Checks:**

- A photo too small for its box at 300 ppi gets a warning.
- A spot outside the frame gets a warning. Dom widens the frame or drops the photo.

## 6. Print output

Finish writes `out/print/<title>-<size>.tif` and `out/print/PRINT.txt`.

| Property | Value |
|---|---|
| Pixel size | exactly the print size at 300 ppi, for example 3600×5400 for 12×18 |
| Bit depth | 16-bit if the renderer can stay unrounded until the last step, else 8-bit. The plan for sub-project 4 checks this first. The compositor works in `uint8` today. |
| Colour | sRGB, profile embedded |
| Compression | none |
| Orientation | rotated to feed when the paper row says so |

- Dom prints at 100% in Canon Professional Print & Layout, centred, with the row's
  preset. Print & Layout converts sRGB to the paper profile.
- `PRINT.txt` lists paper, sheet, print size, profile, intent and preset. Dom checks
  it against the print dialog.
- Prepare also renders a soft proof that simulates PT-101, with Canon's profile
  installed by the driver. Dom approves the look the paper will give.
- **One-time test sheet:** PT-101 with the map palette, fine hillshade, thin tracks,
  small type and a photo. It picks perceptual or relative colorimetric intent for the
  paper table.

`FINAL_FORMATS` gains `tif`. `MAX_OUTPUT_PIXELS` (120 MP) holds: 16×20 at 300 ppi is
28.8 MP.

## 7. The customer package

Finish writes to `out/customer/`, zips it, and copies the zip to
`~/Library/Mobile Documents/com~apple~CloudDocs/Tecopa Deliveries/`. It then reveals
the zip in Finder. Dom makes the link with Share → Copy Link. No script makes the link.

| File | Content |
|---|---|
| `<title>-<size>.jpg` | The full print image, 300 ppi, sRGB, high-quality JPEG |
| `<title>-4x5.jpg` | 1080×1350 |
| `<title>-9x16.jpg` | 1080×1920 |
| `<title>-9x16.mp4` | The 9:16 film, `light_motion="auto"` |

- The stills show the whole poster, photos included, centred on a plain background
  from the map palette. The photo layout is not solved again per canvas.
- File names come from the title, slugified. This removes the "tecopa_tecopa"
  repeat (sample-kit finding #10).
- `share_labels = false` in `order.toml` removes place names from the stills and the
  film. The default is `true`. Terrain can still show where a place is.
- Wallpapers and mockups stay available. They are not in the package.

**Target:** Finish in about 3 minutes. The light-motion film takes 77–81 s of that.

## Amendments

- **Invariant 6** becomes: "The zoom cap at the final dpi, with at most 2× upsampling.
  A 422 past 2× is correct." Tests that assert today's cap change with it.
- **`docs/scope.md`, pillar 2** ("the file is the whole record"): for orders, the
  record lives in `work/` as the record PNG, with the photos. The customer's files
  carry no record. Dom makes Edition N+1 from the order folder. Add a dated
  amendment blockquote to `scope.md`. Do not rewrite its body.

## Errors

| Case | Behaviour |
|---|---|
| Tracks outside the lower 48 | Prepare stops and names the reason |
| No 3DEP layer covers the plate | A finer layer that does not cover all the US ground is skipped. A plate mostly outside US data stops Prepare. |
| Past 2× upsampling at the ordered size | Widen the frame. Warn below 40% fill. |
| Plate build fails | Stop. Keep the build log in `work/`. Remove the partial plate. |
| Photo has no spot | The photo goes to the unplaced tray. Finish refuses until it is placed or dropped. |
| Photo too small | Warning in the report and in the studio |
| State changed after approval | Finish refuses and asks for a new approval |
| iCloud Drive missing | Finish writes the zip to `out/customer/` and says so |

## Testing

- **Unit (CI):** nestled framing, orientation choice, paper-row scoring, the 2× rule
  and frame widening, EXIF GPS and time matching, open-ground placement and band
  fallback, file naming, the approval hash.
- **Pipeline (CI, no network):** Prepare and Finish on a fixture order with a stubbed
  plate build, the same trick as `tests/conftest.py`'s synthetic region. Check every
  output file, the TIFF's size, profile and dpi tag, and that a second Prepare keeps
  manual changes.
- **Acceptance (Mac, once per sub-project):** three real orders. A compact home
  ground, a long north–south trip, and an east–west road trip. Each with phone
  photos, one camera photo without GPS, and one photo without a time zone.
- **Print (once):** the test sheet, then one real 12×18 on PT-101.

## Docs to update

`CLAUDE.md` (router row for orders, invariant 6), `docs/architecture.md`,
`docs/changing-things.md` (new section: Run an order), `docs/scope.md` (amendment),
`docs/decisions.md` (new dated section), `README.md`.

## Build order

Each sub-project gets its own plan and ships on its own.

1. **Plate per order:** order folder, `order.py prepare` (plate only), finer DEM
   with the coverage check, 2× rule, projection choice, tile cache.
2. **Framing and paper table:** `papers.toml`, nestled framing, size and orientation.
3. **Photos:** spot finding, HEIC, open-ground layout, band, the studio tray and drag,
   approval.
4. **Print output:** TIFF, `PRINT.txt`, soft proof, the test sheet.
5. **Package:** JPG, stills, film, naming, zip, iCloud copy, `share_labels`.

## Out of scope

Customer self-service, a web order form, payment, Alaska and Hawaii, the 17" roll,
full bleed, a queue of orders, making the iCloud link from a script.

## Open, for Dom

- Prices for 8×10 and 16×20. A second look at $80 for 12×18 once sheet and ink cost
  are known.
- Photo limits, after testing.
- Rendering intent, from the test sheet.
