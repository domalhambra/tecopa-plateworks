# Print Sizes, Panel Sets and the Size Preview — Design

**Date:** 2026-10-11
**Status:** Approved by Dom (brainstorming session and written review, 2026-10-11). Amended the same day while the plan was written: see "Amended while planning" at the end. The plan is `../plans/2026-10-11-panel-sets-and-size-preview.md`. Nothing is built.
**Extends:** `2026-09-24-order-pipeline-design.md` (the order folder, Prepare, Finish, the customer package)
**Amends:** `2026-09-24-order-pipeline-design.md` §2 (a new step before Prepare), §4 (the sizes) and §7 (the package for a set). No invariant in `CLAUDE.md` changes.

## Goal

A client sends tracks. Dom runs one command. The client gets a PDF that shows their own
map at every size that suits it, on one wall at one scale. The client chooses a size and
buys it. The sizes are 11 × 17 in, 17 × 22 in, a set of two panels and a set of three
panels.

## Why

The order pipeline asks for the size first. The client must choose before a map exists.
Dom's goal (2026-10-11) puts the tracks first and the choice after a preview.

The menu is already 11 × 17 and 17 × 22 (decision of 2026-10-10). Two things are left.
The furniture is still sized for an 18 × 24 sheet. The engine cannot make a set.

## Words

| Word | Meaning |
|---|---|
| panel | One printed piece, 17 × 22 in, cut from the 17 in roll. |
| set | Two or three panels that hang side by side as one map. |
| single sheet | A print with one panel: 11 × 17 or 17 × 22. |
| sheet | The whole hung size in the spec. For a set, it includes the gaps. |
| gap | The distance on the wall between the visible map edges of two neighbours. |
| gap strip | The part of the sheet that lies between two panels. It is not printed. |
| seam | A panel edge that faces a neighbour. |
| window set | A set with a gap above 0. The map continues behind each gap strip. |
| cut set | A set with a gap of 0. Every part of the map is printed. |
| preview | The PDF a client sees before payment. It is not the proof. |

## Decisions (from brainstorming)

| # | Decision |
|---|---|
| 1 | The furniture is retuned for 17 × 22 and 11 × 17. Two test prints settle the numbers. |
| 2 | A panel hangs with its 22 in side across or its 17 in side across. The map frame decides. |
| 3 | A panel is always a full 17 × 22 in. A set has four shapes. |
| 4 | Dom chooses a window set or a cut set for each order. A cut set is a gap of 0. |
| 5 | The gap is 0, 2 or 4 in. The default is 2. |
| 6 | Furniture is drawn once for the set. Each panel carries a small mark such as `2 / 3`. |
| 7 | Dom runs the preview on his Mac. No hosted service. |
| 8 | The preview is one PDF. |
| 9 | Each preview map is screen size and carries a small "Preview" mark. |
| 10 | A fit rule decides which sets a preview offers. Dom can override it. |
| 11 | The engine paints a set as one sheet and then cuts it (approach A). |
| 12 | How a client sends tracks and pays is a separate, later design. |

## 1. The set in the spec

`CompositionSpec` gains two fields.

| Field | Values | Default |
|---|---|---|
| `panels` | 1, 2, 3 | 1 |
| `panel_gap_in` | 0, 2, 4 | 0 |

The sheet size is the hung size. No orientation field exists. The sheet size gives it.

| Shape | Sheet, with gap `g` | Largest, at `g` = 4 |
|---|---|---|
| Two panels, 22 in across | (44 + g) × 17 in | 73.4 megapixels |
| Three panels, 22 in across | (66 + 2g) × 17 in | 113.2 megapixels |
| Two panels, 17 in across | (34 + g) × 22 in | 75.2 megapixels |
| Three panels, 17 in across | (51 + 2g) × 22 in | 116.8 megapixels |

`validate` refuses each of these with a `SpecError`:

- `panels` is not 1, 2 or 3, or `panel_gap_in` is not 0, 2 or 4.
- `panels` is above 1 and the sheet is not one of the four shapes for that gap.
- `panels` is above 1 and the output is a wallpaper. A film is a route, not an output
  kind: the film route and the wallpaper bundle route refuse a set with a 422.
- `panels` is above 1 and `bleed_in` is above 0.
- `panels` is 1 and `panel_gap_in` is above 0.

The zoom cap (invariant 6) and `MAX_OUTPUT_PIXELS` apply to the whole sheet. They do not
change.

A file with no `panels` field reads as 1. `serialize.spec_from_json` already defaults a
missing field. The two fields are always written (invariant 7: no omit-at-default).

## 2. Panel geometry and the cut

A new module, `app/panels.py`, is the one source of panel geometry. It reads a spec and
returns the panel rectangles and the gap strips in sheet inches, and in pixels for a
given dpi. No other code works out where a seam is.

`rasterize` paints the whole sheet once, gap strips included. `panels.cut` then returns
one image per panel and drops the gap strips.

- A panel is 6,600 × 5,100 px or 5,100 × 6,600 px at 300 dpi, for every gap.
- With a gap of 0, the panels join back into the whole sheet, byte for byte.

**The proof** is one image of the whole sheet. Each gap strip is painted in a plain wall
tone, so the proof shows the set as it hangs.

**The final** for a set is a zip with one file per panel, PNG or PDF. The zip's name
ends in `_panels.zip`, and the members end in `_1of3`, `_2of3` and `_3of3`. The zip is
byte-deterministic. A single sheet's final does not change.

## 3. Labels and furniture

**Labels.** Each seam acts as a sheet edge. `_label_keepout` gains each gap strip and a
band `GEO_EDGE_IN` wide inside each seam. No name is cut by a seam. No name sits behind
a gap strip. Curved names obey the same rule.

**Furniture.**

- The title block, the compass, the scale bar and the elevation strip stay as one stack
  in the lower left of panel 1. The elevation strip ends inside panel 1.
- The keyline is drawn on each panel, not round the sheet.
- Each panel carries a panel mark, such as `2 / 3`, in its lower right corner. It uses
  the body type role at the credit line's size.
- A photo box never crosses a seam. Its leader line can.

**Things tied to the ground.** A route end, a marker or a hotspot cannot move. In a
window set, one can lie behind a gap strip. The proof shows it. The report names it, for
example "The north trailhead is behind gap 1." Dom then moves the frame.

## 4. The furniture retune

- `FURNITURE_BASE_IN2` changes from 18 × 24 to 17 × 22. A 17 × 22 sheet then draws
  furniture at 100 %, not 93 %.
- A set sizes its furniture as one 17 × 22 panel does. The `furniture_scale` control
  still multiplies it.
- `FURNITURE_SCALE_MIN` rises from 0.75. The first value is 0.80. Dom chooses the final
  value from a test print of an 11 × 17.
- A test holds the smallest furniture text on an 11 × 17 at 6 pt or more.

| | |
|---|---|
| Benefit | The 11 × 17 stops being a reduced 18 × 24. |
| Cost | One constant, one floor, one test, two test prints. |
| Risk of leaving it | Small type on the 11 × 17, the lowest-priced print. |

**Consequence.** A reprint of an older file draws its furniture about 7 % larger.
Invariant 7 allows this drift. `docs/decisions.md` records it.

## 5. The size preview

**The command.** `scripts/order.py preview <folder>`. It needs tracks in `in/` and a
title in `order.toml`. It needs no size. It can run again safely.

**Step 1: frame every size.** For 11 × 17, 17 × 22, two panels and three panels, the
command makes a frame with `orderplate.nestled_frame`, in both orientations. It keeps
the orientation with less wasted ground. A set is framed at a gap of 2 in.

**Step 2: the fit rule.** The two single sheets are always offered. A set is offered
when both of these are true:

- The tracks span at least `SET_MIN_FILL` of the sheet's width. The first value is
  0.30. Dom tunes it on real tracks. (The first draft said "on both sides". That
  refused a thin east-west route, which is the route a set is for.)
- Every panel holds some part of a track.

The 2× rule applies with no new code. A small area cannot hold a 66 in set. Its frame
widens, its fill drops below `SET_MIN_FILL`, and the set is not offered.

A `sizes` line in `order.toml` overrides the rule, for example
`sizes = ["11x17", "17x22", "three"]`.

**Step 3: the preview plate.** One plate covers every offered frame. Its grid follows
the preview's pixels, not a print's. The command uses a curated plate when one holds
the frames, as Prepare does.

**Step 4: the maps.** Each offered size is rendered at screen size: 1,600 px on the
long side for a single sheet, and 50 dpi for a set, so a panel is 1,100 px on its long
side. Each map carries the
engine's proof watermark, with the word "Preview". A set's map shows each gap strip in
the wall tone, as the proof does.

**Step 5: the PDF.** Pillow writes it. No new dependency.

- Page 1: every offered size on one wall at one scale, with a 7 ft sofa for scale.
- One page for each size: the map large, the name, the hung size, the panel count and
  the price.
- One line states that the preview is not the final map and that names can move.
- The layout follows `00-09 System/00 Resources/print-documents.md` in the workspace.

**Prices.** A new data file, `config/sizes.toml`, holds each size's name, sheet and
price. A size with no price prints "Price on request". Dom sets the set prices.

**The folder.**

    work/preview/        the preview plate, the frames, preview.json
    out/preview/         <title>-preview.pdf

`preview.json` lists each size: its frame, its fill, whether it is offered, and why not.

**After the choice.** The preview's report gives, for each offered size, the lines to
write in `order.toml`: the size, the orientation and the gap. Prepare then frames that
size with the same rule and builds the real plate for it only. Prepare does not read
`preview.json`: the whole preview uses one projection, and Prepare chooses its own.

**Limits.**

- The preview is not the proof. A coarse plate can place a name in another position.
- Pillow cannot write links. The PDF has no buy buttons. The client replies with a choice.
- The target run time is under 5 minutes. The plan measures it on the three real track
  sets of 2026-09-24.

## 6. The order steps

**`order.toml`.**

- `size` accepts `"11x17"`, `"17x22"`, `"two"` and `"three"`.
- `gap` accepts 0, 2 or 4 and defaults to 2. It is ignored for a single sheet.
- `sizes` is the override list for the preview.

**Prepare.** No new step. A set is a wider sheet. The plate's grid follows the hung
width. The report adds the "behind a gap" lines of §3.

**Finish.** `order finish` is not built yet (found while planning). The lines below
are requirements on that sub-project of the order pipeline. Until then a set order
ends at the engine's zip of panel files.

- `out/print/` gets one TIFF per panel, for example `<title>-three-1of3.tif`.
- `PRINT.txt` lists each panel, its feed direction on the roll, the hang order and the gap.
- `out/customer/` gets one JPG per panel and a one-page hanging guide. The guide gives
  the panel order and the gap.
- The share stills and the film come from the same crop as one unbroken sheet, with
  `panels` set to 1. A set refuses a film, and a still of a set needs no gap.

## 7. The studio

- The size menu gains "Two panels" and "Three panels".
- A gap control (0, 2, 4) appears for a set.
- The orientation control applies to a set as it does to a single sheet.
- The frame tool takes the set's shape and draws the gap strips.
- The final downloads as a zip.
- The library card reads, for example, "3 panels, 70 × 17 in".

## 8. The `tecopa` tool

- One new command, `tecopa order preview`, as a tracked run. The catalog goes from 33
  entries to 34.
- `render proof` needs no change. `--set panels=3` is one more field, and the tool
  still holds no field names.
- `render final`, `render fetch` and `reprint` write the zip of a set to `out`. The
  tool has no format logic, so this needs tests and no code.
  They still never overwrite a file.

## 9. The file

- `panels` and `panel_gap_in` ride the spec into the manifest.
- The panel number is a manifest key, not a spec field. All panels of a set share one spec.
- `/api/reprint` from any panel file rebuilds the whole set and returns the zip.
- `/api/reprint/inspect` shows the panel count, the gap and the panel number.
- `/api/continue` makes Edition N+1 of a set with no new code.
- Every file enters through `provenance.spec_from_manifest` (invariant 8). Its type
  gate covers the two new fields. A crafted value gets a 422, never a 500.
- `docs/MANIFEST.md` gains the two fields and the panel key.

## 10. Errors

| Condition | Result |
|---|---|
| A set with a wrong sheet, a bleed, a film or a wallpaper | 422 with the `SpecError` text |
| A set whose crop is past the 2× rule | 422, as for a single sheet |
| `size = "four"` or `gap = 1` in `order.toml` | `OrderError` that names the accepted values |
| A set forced with `sizes` when a panel has no track | The preview offers it and the report warns |
| No set passes the fit rule | The preview offers the two single sheets and says why |
| The preview plate build fails | The run ends `failed`, and the log names the source |

## 11. Tests

**The gate, before other code.** Render one 116.8 megapixel final and record peak
memory. Pass is under 16 GB on Dom's 32 GB Mac. A fail moves the build to approach B:
the rasterizer paints one panel at a time.

- **Geometry:** four shapes by three gaps. A cut set joins back into the sheet, byte
  for byte.
- **Seams:** with labels and furniture off, each panel equals the matching window of
  the same crop as one unbroken sheet (`panels` set to 1). No label box touches a seam
  band, on the demo regions.
- **Single sheets:** a spec with `panels` at 1 renders the same bytes as before. This
  test lands before the retune.
- **Refusals:** each line of §1 and §10. Crafted manifests with a wrong type or value.
- **The file:** a reprint from panel 2 rebuilds the set. Two renders of one spec give
  the same zip bytes.
- **The preview:** the fit rule on synthetic track boxes. The full command on the three
  real track sets, marked slow.
- **The tool:** a set final through `tecopa` is byte-identical to `curl`. No file is
  overwritten.
- **The studio:** `node --check` on each module, every `$('id')` matched, a browser run.

**Checks that need paper (Dom).**

- One 11 × 17 and one 17 × 22, for the furniture.
- One real set, hung at 2 in. A ruler across a gap shows that a line continues true.

## 12. Order of work

1. The memory gate.
2. The spec fields, `app/panels.py`, the cut, the manifest.
3. Labels, furniture, keyline, panel mark.
4. The furniture retune.
5. The studio.
6. The order steps and the hanging guide.
7. The preview: fit rule, preview plate, PDF, `config/sizes.toml`.
8. The tool and its smoke test.
9. Documents, decisions, print checks.

## 13. Approaches that were rejected

| Approach | Why not |
|---|---|
| B. One spec, painted one panel at a time | Every painter must learn a window of the sheet. It is the fallback if the memory gate fails. |
| C. One ordinary spec for each panel | Several relief passes normalise tone to their own crop. Two panels would show a tone step at the seam. |
| A hosted preview service | It reverses the decision of 2026-07-12 and opens a public upload door on the engine. |
| A free panel length | Panels such as 17 × 19 need custom frames, and the studio needs a free-shape frame tool. |

## 14. Not in this design

- How a client sends tracks and pays, buy links, the Ghost pages, and set prices on the site.
- Bleed for a set.
- Panels of other sizes, and panels stacked top to bottom.
- A hosted service.
- Any change to the Prints arm's panel rule. The two share the 17 × 22 panel and no code.

## 15. Open values (Dom sets them as data)

| Value | First value | Settled by |
|---|---|---|
| Set prices in `config/sizes.toml` | none: "Price on request" | Dom, after a set is printed |
| `FURNITURE_SCALE_MIN` | 0.80 | the 11 × 17 test print |
| `SET_MIN_FILL` | 0.30 | previews of real tracks |

## Amended while planning (2026-10-11)

Five read-only passes over the code found facts this design did not have. The plan's
table "Decisions made while planning" holds all nineteen. The ones that change what
this document said:

- **The fit rule** reads the sheet's width, not both sides (§5, step 2).
- **A set's preview map** is 50 dpi, not about 2,400 px (§5, step 4).
- **Prepare does not read `preview.json`.** The report gives the lines for `order.toml` (§5).
- **`order finish` is not built**, and Prepare renders no proof. The Finish lines of §6
  wait for that sub-project.
- **The engine has no TIFF writer.** The zip of a set holds PNG or PDF files (§2).
- **A film is a route.** Two routes refuse a set. `validate` refuses a wallpaper (§1).
- **No `caption` type role exists.** The panel mark uses the body role (§3).
- **A route end behind a gap** is named by the preview's report and by Prepare's
  warnings. An order has no markers or hotspots yet (§3).
