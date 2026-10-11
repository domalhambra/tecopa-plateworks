# Panel Sets and the Size Preview Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A client sends tracks, Dom runs one command, and the client gets a PDF of their own map at every size that suits it: 11 × 17, 17 × 22, two panels, three panels.

**Architecture:** A set is one `CompositionSpec` with two new fields, `panels` and `panel_gap_in`. `rasterize` paints the whole sheet once and a new module, `app/panels.py`, is the one source of where a panel and a gap strip are. A new order step, `scripts/order.py preview`, frames each size, builds one coarse plate, renders screen-size maps and writes a PDF with Pillow.

**Tech Stack:** Python 3.14, FastAPI, Pillow 12, numpy, rasterio (`.venv`). The studio is plain ES modules with no build step. The `tecopa` tool is Swift (SwiftPM, ArgumentParser).

**Spec:** `../specs/2026-10-11-print-sizes-panel-sets-and-size-preview-design.md`

**Branch:** `build/panel-sets-and-size-preview`. Never commit to `main`. A merge and a push need Dom's yes.

---

## Rules for every task

- Read `CLAUDE.md` in the repo root first. Its fifteen invariants hold.
- TDD: write the failing test, see it fail, write the code, see it pass.
- Run tests with `.venv/bin/python -m pytest`. Never install anything into `.venv`.
- Before a task is done, run `.venv/bin/python -m pytest -n auto -m "not slow" -q`. Compare the failure set with the base, not the totals.
- Commit with paths: `git commit -m "<message>" -- <paths>`. Present tense, say why. End each message with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Never commit a font. Never re-stamp `sources.json`. Never write under `regions/`.
- A customer's tracks never go into the repo. Order folders live under `$TECOPA_ORDERS_DIR`.
- If a pinned test counts spec fields or proof fields and fails only because of the new fields, change the count and say so in the commit.

## Decisions made while planning

Five read-only passes over the code found facts that the spec did not have. Each decision below refines the spec. The spec is amended in the same commit as this plan.

| # | Decision | Why |
|---|---|---|
| 1 | `order finish` is not built, and Prepare renders no proof. The spec's Finish lines for a set become requirements on that sub-project. This plan stops at `order.toml`, Prepare, the preview, and the engine's zip. | `scripts/order.py` has one command, `prepare`. Nothing writes a TIFF or `PRINT.txt`. |
| 2 | The zip of a set holds one PNG (or one PDF page) per panel. | `FINAL_FORMATS` is `png` and `pdf`. The engine has no TIFF writer. |
| 3 | "A set refuses a film" is enforced at `/api/timelapse/submit` and `/api/wallpapers/submit`. `validate` refuses a wallpaper output. | A film is a route, not an output kind. `OUTPUT_KINDS` is `("print", "wallpaper")`. |
| 4 | The panel mark uses the `body` type role at the credit line's size. | `TYPE_ROLES` has no `caption` role. |
| 5 | The proof form fields are `panels` and `panel_gap`. The spec fields are `panels` and `panel_gap_in`. | The route already names `bleed` for `bleed_in`. |
| 6 | The per-file manifest key is `"panel": {"index": k, "of": n}`. It is present only on a set. | All panels share one spec, so the number cannot be a spec field. |
| 7 | The zip is byte-deterministic: stored, with 1980 dates. Its name is `<stem>_panels.zip`. Members are `<stem>_1of3.png`. | Invariant 3. `scripts/pack_region.py` has the pattern. |
| 8 | The wall tone of a gap strip is `(236, 232, 224)`. | One constant in `app/panels.py`. |
| 9 | A set's furniture scale comes from one panel's area. | `_furniture_scale` reads the sheet's area, and a 74 × 17 sheet would draw furniture at 183 %. |
| 10 | The watermark word is a parameter. On a set it is drawn once on each panel. | The word "PROOF" is a literal, and a two-panel sheet's centre is the gap. |
| 11 | A photo box and a marker label stay inside the panel that holds their anchor. | Neither consults the label keep-out. |
| 12 | The fit rule is: the tracks span at least `SET_MIN_FILL` of the sheet's **width**, and every panel holds a track. The spec said "on both sides". | A thin east-west route spans 60 % of the width and 6 % of the height. "Both sides" refuses exactly the routes a set is for. |
| 13 | The orientation of each size is the one with the larger smaller-side share. | No code chooses an orientation today. This is "less wasted ground" as one number. |
| 14 | A preview map of a set is rendered at 50 dpi, so a panel is 1,100 px on its long side. A single sheet is 1,600 px on its long side. The spec said "about 2,400 px" for a set. | At 2,400 px a 70 in set is 34 dpi and place names are 6 px high. |
| 15 | The whole preview uses one projection. Prepare does not read `preview.json`. The preview report gives the lines to write in `order.toml`. | `order_epsg` depends on the aspect, and a frame from one projection is not a rectangle in another. Prepare uses the same framing functions. |
| 16 | `orientation = "landscape"` on a set means panels 22 in across. `"portrait"` means 17 in across. | One key for both kinds of size. |
| 17 | The tool needs no code for a zip. It writes the reply's bytes to `out` unchanged. Tests pin that. The catalog goes from 33 to 34 with `order_preview`. | `Render.save` has no extension or format logic. |
| 18 | `panels` and `panel_gap_in` are masked in the terrain key and the ink key. | Neither reaches `_paint_terrain` or the route ink. Labels are drawn outside the cached unit. |
| 19 | The memory gate renders 59 × 22 in on `rifle_aspen`. | It is the largest set (116.8 megapixels), and that plate is 95 km wide at 10 m. |

## File structure

| File | Responsibility |
|---|---|
| `app/panels.py` (new) | Panel geometry: sheet sizes, panel rectangles, gap strips, seam bands, the cut, the wall tone. Imports nothing from `app`. |
| `app/spec.py` | The two fields and their rules in `validate`. |
| `app/render.py` | Seam keep-outs, furniture on panel 1, a keyline and a mark per panel, the watermark word, the furniture retune, the two cache masks. |
| `app/main.py` | The two proof fields, wall-tone proofs, the zip of a set, the `panel` manifest key, reprint, inspect, continue, the two refusals. |
| `app/static/*` | The size menu, the gap control, the gap strips in the frame tool, the zip download, the library card. |
| `app/order.py` | `size = "two" / "three"`, `gap`, `sizes` in `order.toml`. |
| `app/orderplate.py` | `track_shares`. |
| `app/orderprep.py` | The cache environment as a function. `_build` takes a root and an id. The report line of a set. |
| `app/orderpreview.py` (new) | The preview: candidates, the fit rule, the preview plate, the maps, `preview.json`, the report. |
| `app/previewpdf.py` (new) | The PDF pages, with Pillow. |
| `app/sizes.py` (new) and `config/sizes.toml` (new) | Size names and prices as data. |
| `scripts/order.py` | The `preview` command. |
| `scripts/measure_final.py` (new) | The memory gate. |
| `tools/tecopa/` | `order_preview`, and tests that a zip is written unchanged. |

---

### Task 1: The memory gate

**Goal:** One 116.8 megapixel final renders on Dom's Mac with a peak memory under 16 GB, measured by `scripts/measure_final.py`.

> **USER-ORDERED GATE — NON-SKIPPABLE.** This task was requested by the user in the current conversation. It MUST NOT be closed by walking around it, by declaring it "verified inline", or by substituting a cheaper check. Close only after every item in `acceptanceCriteria` has been re-validated independently, with output captured.

**Files:**
- Create: `scripts/measure_final.py`
- Test: `tests/test_measure_final.py`

**Acceptance Criteria:**
- [ ] `scripts/measure_final.py --region rifle_aspen --w 59 --h 22` prints one JSON line with `pixels_mp`, `seconds`, `peak_gb`, `limit_gb` and `pass`.
- [ ] `pixels_mp` is 116.8 and `pass` is `true` (peak under 16 GB).
- [ ] The JSON line is copied into this plan under "What changed while it ran".
- [ ] If `pass` is `false`, stop. Do not start task 2. Report to Dom: the build moves to approach B.

**Verify:** `.venv/bin/python scripts/measure_final.py --region rifle_aspen --w 59 --h 22` → exit 0 and `"pass": true`

**Steps:**

- [ ] **Step 1: Write the failing test**

```python
# tests/test_measure_final.py
import pytest

from scripts import measure_final as mf


def test_the_crop_is_centred_and_has_the_sheet_aspect():
    crop = mf.centred_crop((0.0, 0.0, 100_000.0, 60_000.0), 59 / 22, 50_000.0)
    w, h = crop[2] - crop[0], crop[3] - crop[1]
    assert abs(w / h - 59 / 22) < 1e-9
    assert abs((crop[0] + crop[2]) / 2 - 50_000.0) < 1e-6
    assert abs((crop[1] + crop[3]) / 2 - 30_000.0) < 1e-6
    assert w <= 100_000.0 and h <= 60_000.0


def test_a_region_that_is_too_small_is_refused_by_name():
    with pytest.raises(SystemExit, match="too small"):
        mf.centred_crop((0.0, 0.0, 40_000.0, 40_000.0), 59 / 22, 88_500.0)


def test_peak_is_reported_in_gigabytes():
    assert mf.peak_gb(8 * 1024 ** 3, "darwin") == 8.0      # macOS reports bytes
    assert mf.peak_gb(8 * 1024 ** 2, "linux") == 8.0       # Linux reports KiB
```

- [ ] **Step 2: Run it and see it fail**

Run: `.venv/bin/python -m pytest tests/test_measure_final.py -q`
Expected: FAIL, `No module named 'scripts.measure_final'` (or an import error).

- [ ] **Step 3: Write the script**

```python
# scripts/measure_final.py
"""Render one large final and print its peak memory: the gate for panel sets.

A set is painted as one sheet and then cut, so its largest sheet (59 x 22 in at
300 dpi, 116.8 megapixels) must fit in memory. This renders that sheet on a real
plate and prints one JSON line. Exit 0 when the peak is under the limit."""
import argparse
import json
import os
import resource
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import numpy as np  # noqa: E402

from app.spec import FINAL_DPI, MAX_UPSAMPLE, CompositionSpec  # noqa: E402


def centred_crop(bounds, aspect, min_w):
    """The largest crop of `aspect` (width / height) centred in `bounds`."""
    bw, bh = bounds[2] - bounds[0], bounds[3] - bounds[1]
    w = min(bw, bh * aspect)
    if w < min_w:
        raise SystemExit(f"region too small: the sheet needs {min_w / 1000:.1f} km "
                         f"across and the region holds {w / 1000:.1f} km")
    h = w / aspect
    cx, cy = (bounds[0] + bounds[2]) / 2, (bounds[1] + bounds[3]) / 2
    return (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)


def peak_gb(ru_maxrss, platform=sys.platform):
    """ru_maxrss is bytes on macOS and KiB on Linux."""
    return round(ru_maxrss / (1024 ** 3 if platform == "darwin" else 1024 ** 2), 2)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--region", default="rifle_aspen")
    ap.add_argument("--w", type=float, default=59.0, help="sheet width, inches")
    ap.add_argument("--h", type=float, default=22.0, help="sheet height, inches")
    ap.add_argument("--limit-gb", type=float, default=16.0)
    a = ap.parse_args(argv)
    from app import render
    region_dir = os.path.join(ROOT, "regions", a.region)
    with open(os.path.join(region_dir, "region.json")) as f:
        cfg = json.load(f)
    floor_w = cfg["native_resolution_m"] / MAX_UPSAMPLE * round(a.w * FINAL_DPI) * 1.001
    crop = centred_crop(cfg["bounds"], a.w / a.h, floor_w)
    track = np.array([[crop[0] + 2000.0, crop[1] + 2000.0],
                      [crop[2] - 2000.0, crop[3] - 2000.0]])
    spec = CompositionSpec(
        region_id=cfg["id"], crs=cfg["crs"], crop=crop, print_w_in=a.w, print_h_in=a.h,
        native_resolution_m=cfg["native_resolution_m"], tracks=[track], hotspots=[],
        seed=7, title_text="Memory gate", contours=True,
        labels=os.path.isfile(os.path.join(region_dir, "labels.json")),
        biome=os.path.isfile(os.path.join(region_dir, "landcover.tif")))
    started = time.monotonic()
    img = render.rasterize(spec, dpi=FINAL_DPI, region_dir=region_dir,
                           watermark=False, cfg=cfg)
    peak = peak_gb(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    ok = peak < a.limit_gb
    print(json.dumps({"region": a.region, "sheet_in": [a.w, a.h],
                      "pixels_mp": round(img.size[0] * img.size[1] / 1e6, 1),
                      "seconds": round(time.monotonic() - started, 1),
                      "peak_gb": peak, "limit_gb": a.limit_gb, "pass": ok}))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_measure_final.py -q`
Expected: `3 passed`

- [ ] **Step 5: Run the gate and record it**

Run: `.venv/bin/python scripts/measure_final.py --region rifle_aspen --w 59 --h 22`
Expected: one JSON line, `"pixels_mp": 116.8`, `"pass": true`, exit 0. It can take some minutes.

Copy the JSON line into the section "What changed while it ran" at the end of this plan. If `pass` is `false`, stop and report.

- [ ] **Step 6: Commit**

```bash
git add scripts/measure_final.py tests/test_measure_final.py
git commit -m "Measure the peak memory of one large final, the gate for panel sets" -- scripts/measure_final.py tests/test_measure_final.py docs/superpowers/plans/2026-10-11-panel-sets-and-size-preview.md
```

---

### Task 2: The spec fields, panel geometry and validation

**Goal:** `CompositionSpec` carries `panels` and `panel_gap_in`, `validate` refuses every wrong set, and `app/panels.py` gives the rectangles and the cut.

**Files:**
- Create: `app/panels.py`
- Modify: `app/spec.py` (imports, the end of the dataclass, `validate` after the bleed checks)
- Modify: `app/render.py` (`BASE_KEY_MASK_ALWAYS`, `INK_KEY_MASK_ALWAYS`)
- Test: `tests/test_panels.py`

**Acceptance Criteria:**
- [ ] `panels.sheet_sizes(3, 2)` is `[(70.0, 17.0), (55.0, 22.0)]`.
- [ ] At 300 dpi every panel is 6600 × 5100 or 5100 × 6600 px, for gaps 0, 2 and 4.
- [ ] `panels.cut` of a cut set (gap 0) joins back into the sheet, byte for byte.
- [ ] `validate` raises `SpecError` for: `panels` 4, gap 1, a gap on a single sheet, a set with a wrong sheet, a set with bleed, a set as a wallpaper.
- [ ] A spec with `panels` at 1 validates as before, and `spec_to_json` writes both fields.
- [ ] The seven `tests/fixtures/manifest_*_v1.json` files load with `panels == 1`.
- [ ] `tests/test_base_cache.py` and `tests/test_ink_cache.py` pass.

**Verify:** `.venv/bin/python -m pytest tests/test_panels.py tests/test_spec.py tests/test_base_cache.py tests/test_ink_cache.py tests/test_server_foundation.py -q` → all pass

**Steps:**

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_panels.py
import glob
import json

import numpy as np
import pytest
from PIL import Image

from app import panels, provenance, serialize
from app.spec import CompositionSpec, SpecError

SHAPES = [(2, "wide"), (3, "wide"), (2, "tall"), (3, "tall")]


def set_spec(n=3, gap=2.0, shape="wide", **over):
    """A set that passes validate: the sheet of the shape, and a crop at 1x of a
    10 m plate (so the zoom cap holds at 300 dpi)."""
    w, h = panels.sheet_sizes(n, gap)[0 if shape == "wide" else 1]
    cw = 10.0 * w * 300
    kw = dict(region_id="r", crs="EPSG:32612",
              crop=(0.0, 0.0, cw, cw * h / w), print_w_in=w, print_h_in=h,
              native_resolution_m=10.0, tracks=[np.array([[10.0, 10.0], [cw - 10.0, 10.0]])],
              hotspots=[], seed=7, panels=n, panel_gap_in=gap)
    kw.update(over)
    return CompositionSpec(**kw)


def test_the_two_sheets_of_a_set():
    assert panels.sheet_sizes(3, 2) == [(70.0, 17.0), (55.0, 22.0)]
    assert panels.sheet_sizes(2, 0) == [(44.0, 17.0), (34.0, 22.0)]
    assert panels.sheet_sizes(3, 4) == [(74.0, 17.0), (59.0, 22.0)]


@pytest.mark.parametrize("n,shape", SHAPES)
@pytest.mark.parametrize("gap", panels.GAPS_IN)
def test_every_panel_is_a_full_sheet_at_300_dpi(n, shape, gap):
    spec = set_spec(n, gap, shape).validate(300)
    rects = panels.panel_rects_px(spec, 300)
    want = (6600, 5100) if shape == "wide" else (5100, 6600)
    assert [(r[2] - r[0], r[3] - r[1]) for r in rects] == [want] * n
    assert rects[0][0] == 0 and rects[-1][2] == spec.pixel_size(300)[0]
    assert [r[2] - r[0] for r in panels.gap_rects_px(spec, 300)] == (
        [round(gap * 300)] * (n - 1) if gap else [])


def test_panels_and_gaps_tile_the_sheet_at_an_odd_dpi():
    spec = set_spec(3, 2.0, "wide")
    dpi = 41.37
    rects = panels.panel_rects_px(spec, dpi)
    gaps = panels.gap_rects_px(spec, dpi)
    edges = sorted(rects + gaps)
    assert edges[0][0] == 0
    assert all(a[2] == b[0] for a, b in zip(edges, edges[1:]))   # no overlap, no hole


def test_a_cut_set_joins_back_into_the_sheet():
    spec = set_spec(3, 0.0, "wide")
    dpi = 10
    w, h = spec.pixel_size(dpi)
    rng = np.random.default_rng(7)
    sheet = Image.fromarray(rng.integers(0, 255, (h, w, 3), dtype=np.uint8))
    parts = panels.cut(sheet, spec, dpi)
    joined = np.concatenate([np.asarray(p) for p in parts], axis=1)
    assert np.array_equal(joined, np.asarray(sheet))


def test_a_window_set_drops_the_gap_strips_and_paints_them_for_a_proof():
    spec = set_spec(2, 2.0, "tall")
    dpi = 10
    w, h = spec.pixel_size(dpi)
    sheet = Image.new("RGB", (w, h), (10, 20, 30))
    parts = panels.cut(sheet, spec, dpi)
    assert [p.size for p in parts] == [(170, 220), (170, 220)]
    shown = np.asarray(panels.paint_gaps(sheet, spec, dpi))
    assert (shown[:, 170:190] == panels.WALL_TONE).all()
    assert (shown[:, :170] == (10, 20, 30)).all() and (shown[:, 190:] == (10, 20, 30)).all()
    assert np.asarray(sheet)[0, 175].tolist() == [10, 20, 30]     # the input is not changed


def test_a_single_sheet_is_its_own_panel():
    spec = set_spec(3, 2.0, "wide", panels=1, panel_gap_in=0.0)
    assert not panels.is_set(spec)
    assert panels.panel_size_in(spec) == (70.0, 17.0)
    assert panels.frame_rects_px(spec, 10, (0, 0, 700, 170)) == [(0, 0, 700, 170)]
    assert panels.furniture_trim_px(spec, 10, (5, 5, 695, 165)) == (5, 5, 695, 165)
    assert panels.span_px_at(spec, 300, 10, 700) == (0, 700)


def test_a_set_gives_panel_one_to_the_furniture_and_a_span_to_each_anchor():
    spec = set_spec(3, 2.0, "wide")
    assert panels.furniture_trim_px(spec, 10, (0, 0, 700, 170)) == (0, 0, 220, 170)
    assert panels.span_px_at(spec, 300, 10, 700) == (240, 460)     # in panel 2
    assert panels.span_px_at(spec, 232, 10, 700) == (240, 460)     # in gap 1: the nearer panel
    assert panels.span_px_at(spec, 225, 10, 700) == (0, 220)
    assert panels.seam_bands_px(spec, 10, 3) == [(217, 0, 243, 170), (457, 0, 483, 170)]
    cut = set_spec(2, 0.0, "tall")
    assert panels.seam_bands_px(cut, 10, 3) == [(167, 0, 173, 220)]


@pytest.mark.parametrize("over,words", [
    ({"panels": 4}, "panels must be 1, 2 or 3"),
    ({"panels": 0}, "panels must be 1, 2 or 3"),
    ({"panel_gap_in": 1.0}, "panel_gap_in must be 0, 2 or 4"),
    ({"panel_gap_in": float("nan")}, "panel_gap_in must be 0, 2 or 4"),
    ({"print_w_in": 68.0}, "a set of 3 panels"),
    ({"bleed_in": 0.125}, "a set takes no bleed"),
    ({"output_kind": "wallpaper", "screen_ppi": 300.0}, "a set is a print"),
    ({"panels": "3"}, "panels must be a whole number"),
    ({"panel_gap_in": "2"}, "panel_gap_in must be a number"),
])
def test_a_wrong_set_is_a_spec_error(over, words):
    with pytest.raises(SpecError, match=words):
        set_spec(3, 2.0, "wide", **over).validate(300)


def test_a_gap_on_a_single_sheet_is_refused():
    with pytest.raises(SpecError, match="a single sheet has no gap"):
        set_spec(3, 2.0, "wide", panels=1).validate(300)


def test_the_wrong_sheet_message_names_both_sheets():
    with pytest.raises(SpecError, match=r"70x17 or 55x22 in, not 68x17"):
        set_spec(3, 2.0, "wide", print_w_in=68.0).validate(300)


def test_both_fields_are_always_written_and_default_when_missing():
    d = serialize.spec_to_json(set_spec(3, 2.0, "wide"))
    assert d["panels"] == 3 and d["panel_gap_in"] == 2.0
    del d["panels"], d["panel_gap_in"]
    back = serialize.spec_from_json(d)
    assert back.panels == 1 and back.panel_gap_in == 0.0


def test_every_frozen_manifest_reads_as_a_single_sheet():
    paths = sorted(glob.glob("tests/fixtures/manifest_*_v1.json"))
    assert len(paths) == 7
    for path in paths:
        spec = provenance.manifest_to_spec(json.load(open(path)))
        assert spec.panels == 1 and spec.panel_gap_in == 0.0, path
```

- [ ] **Step 2: Run them and see them fail**

Run: `.venv/bin/python -m pytest tests/test_panels.py -q`
Expected: FAIL, `cannot import name 'panels' from 'app'`.

- [ ] **Step 3: Write `app/panels.py`**

```python
# app/panels.py
"""Panel geometry for a set: the one source of where a panel and a gap strip are.

A set is one sheet in the spec (its hung size, gaps included), painted once and then
cut. Every caller that needs a seam asks this module: the cut, the proof's wall tone,
the label keep-out, the furniture and the studio's restore. It imports nothing from
`app`, so `app.spec` can use it in validate()."""
from PIL import ImageDraw

PANEL_SHORT_IN = 17.0          # the roll's width
PANEL_LONG_IN = 22.0
PANEL_COUNTS = (1, 2, 3)
GAPS_IN = (0.0, 2.0, 4.0)      # 0 is a cut set: every part of the map is printed
WALL_TONE = (236, 232, 224)    # a gap strip in a proof or a preview


def sheet_sizes(panels, gap_in) -> list:
    """The two sheets a set can have, as (width, height) in inches: panels 22 in
    across, then panels 17 in across."""
    n, g = int(panels), float(gap_in)
    return [(n * PANEL_LONG_IN + (n - 1) * g, PANEL_SHORT_IN),
            (n * PANEL_SHORT_IN + (n - 1) * g, PANEL_LONG_IN)]


def is_set(spec) -> bool:
    return spec.panels > 1


def panel_size_in(spec) -> tuple:
    """(width, height) of one panel in inches. A single sheet is its own panel."""
    if not is_set(spec):
        return (spec.print_w_in, spec.print_h_in)
    h = float(spec.print_h_in)
    across = PANEL_LONG_IN if abs(h - PANEL_SHORT_IN) < 1e-6 else PANEL_SHORT_IN
    return (across, h)


def panel_spans_in(spec) -> list:
    """[(x0, x1)] in inches from the sheet's left edge, one for each panel."""
    pw, _ = panel_size_in(spec)
    step = pw + (float(spec.panel_gap_in) if is_set(spec) else 0.0)
    return [(k * step, k * step + pw) for k in range(spec.panels)]


def panel_rects_px(spec, dpi) -> list:
    """[(x0, y0, x1, y1)] in sheet pixels, right and bottom exclusive. Each edge is
    rounded on its own, so the panels and the gap strips tile the sheet at any dpi."""
    h = round(spec.print_h_in * dpi)
    return [(round(x0 * dpi), 0, round(x1 * dpi), h) for x0, x1 in panel_spans_in(spec)]


def gap_rects_px(spec, dpi) -> list:
    """The strips between panels. A cut set has none."""
    rects = panel_rects_px(spec, dpi)
    return [(a[2], 0, b[0], a[3]) for a, b in zip(rects, rects[1:]) if b[0] > a[2]]


def seam_bands_px(spec, dpi, edge) -> list:
    """What a place name must stay clear of: each gap strip, or each seam of a cut
    set, grown by `edge` pixels on both sides."""
    rects = panel_rects_px(spec, dpi)
    return [(a[2] - edge, 0, b[0] + edge, a[3]) for a, b in zip(rects, rects[1:])]


def span_px_at(spec, x_px, dpi, out_w) -> tuple:
    """(lo, hi) in pixels of the panel that holds x, or of the nearest panel when x
    is behind a gap. A single sheet is the whole canvas."""
    if not is_set(spec):
        return (0, out_w)

    def distance(r):
        return 0 if r[0] <= x_px < r[2] else min(abs(x_px - r[0]), abs(x_px - r[2]))
    best = min(panel_rects_px(spec, dpi), key=distance)
    return (best[0], best[2])


def furniture_trim_px(spec, dpi, trim) -> tuple:
    """The box the furniture is placed in: panel 1 of a set, else the trim box."""
    return panel_rects_px(spec, dpi)[0] if is_set(spec) else tuple(trim)


def frame_rects_px(spec, dpi, trim) -> list:
    """One box for each printed piece: the panels of a set, else the trim box."""
    return panel_rects_px(spec, dpi) if is_set(spec) else [tuple(trim)]


def cut(img, spec, dpi) -> list:
    """The sheet as one image for each panel. The gap strips are dropped."""
    return [img.crop(r) for r in panel_rects_px(spec, dpi)]


def paint_gaps(img, spec, dpi, tone=WALL_TONE):
    """A copy of the sheet with each gap strip in the wall tone, so a proof shows the
    set as it hangs. A single sheet and a cut set come back unchanged."""
    gaps = gap_rects_px(spec, dpi) if is_set(spec) else []
    if not gaps:
        return img
    out = img.copy()
    d = ImageDraw.Draw(out)
    for x0, y0, x1, y1 in gaps:
        d.rectangle([x0, y0, x1 - 1, y1 - 1], fill=tone)
    return out
```

- [ ] **Step 4: Add the two fields and their rules to `app/spec.py`**

At the top of `app/spec.py`, with the other imports:

```python
from app import panels as panel_geo
```

At the end of the `CompositionSpec` field list, after `dry_lakes: bool = False`:

```python
    # panel sets (2026-10-11): a set is one sheet -- its hung size, gaps included --
    # painted once and cut into `panels` pieces of 17 x 22 in. panel_gap_in is the
    # unprinted strip between two neighbours (0 = a cut set). app/panels.py owns the
    # geometry. Both are always written to the manifest.
    panels: int = 1
    panel_gap_in: float = 0.0
```

In `validate`, directly after the check that raises `"bleed is a print-trim concept -- this output has no trimmer"`:

```python
        # panel sets: a fixed menu of counts, gaps and sheets, so every panel is a
        # full 17 x 22 in. A NaN gap fails the membership test, so it is refused too.
        if self.panels not in panel_geo.PANEL_COUNTS:
            raise SpecError("panels must be 1, 2 or 3")
        if not any(abs(self.panel_gap_in - g) < 1e-9 for g in panel_geo.GAPS_IN):
            raise SpecError("panel_gap_in must be 0, 2 or 4")
        if self.panels == 1 and self.panel_gap_in:
            raise SpecError("panel_gap_in is for a set -- a single sheet has no gap")
        if self.panels > 1:
            if self.output_kind != "print":
                raise SpecError("a set is a print -- a wallpaper has no panels")
            if self.bleed_in:
                raise SpecError("a set takes no bleed")
            sizes = panel_geo.sheet_sizes(self.panels, self.panel_gap_in)
            if not any(abs(self.print_w_in - w) < 1e-6 and abs(self.print_h_in - h) < 1e-6
                       for w, h in sizes):
                want = " or ".join(f"{w:g}x{h:g}" for w, h in sizes)
                raise SpecError(
                    f"a set of {self.panels} panels with a {self.panel_gap_in:g} in gap "
                    f"is {want} in, not {self.print_w_in:g}x{self.print_h_in:g}")
```

- [ ] **Step 5: Mask both fields in the two cache keys**

In `app/render.py`, add this as the last entry of `BASE_KEY_MASK_ALWAYS`:

```python
    # panel sets -- the cut, the seam keep-out and the per-panel furniture; the
    # terrain is painted across the whole sheet, gap strips included
    "panels", "panel_gap_in",
```

Add this as the last entry of `INK_KEY_MASK_ALWAYS`:

```python
    # panel sets -- the route is inked across the whole sheet, gap strips included
    "panels", "panel_gap_in",
```

- [ ] **Step 6: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_panels.py tests/test_spec.py tests/test_base_cache.py tests/test_ink_cache.py tests/test_server_foundation.py -q`
Expected: all pass. `test_every_masked_field_leaves_the_terrain_byte_identical` and its ink twin are slow and prove the two masks.

- [ ] **Step 7: Run the fast suite, then commit**

Run: `.venv/bin/python -m pytest -n auto -m "not slow" -q`
Expected: no new failure.

```bash
git add app/panels.py tests/test_panels.py
git commit -m "A set is one spec: two fields, their rules, and one module for panel geometry" -- app/panels.py app/spec.py app/render.py tests/test_panels.py
```

---

### Task 3: Seams: place names, photo boxes and marker labels

**Goal:** No place name is cut by a seam or sits behind a gap strip, and a photo box and a marker label stay inside the panel that holds their anchor.

**Files:**
- Modify: `app/render.py` (`_label_keepout`, `_draw_photos`, `_draw_label`, `_draw_markers`, one import)
- Modify: `tests/conftest.py` (`_SLOW_MODULES`)
- Test: `tests/test_panel_render.py` (slow, DEM-backed), `tests/test_panel_furniture.py` (fast)

**Acceptance Criteria:**
- [ ] `_label_keepout` of a set holds each seam band, 0.32 in wide on both sides of each gap strip.
- [ ] `_label_keepout` of a single sheet is unchanged.
- [ ] With labels and furniture off, each panel of a set equals the matching window of the same crop with `panels` at 1.
- [ ] A name anchored on a seam is drawn with `panels` at 1 and is not drawn inside the seam band of a set.
- [ ] A marker label next to a seam ends inside its own panel.

**Verify:** `.venv/bin/python -m pytest tests/test_panel_render.py tests/test_panel_furniture.py tests/test_poster_furniture.py tests/test_labels.py -q` → all pass

**Steps:**

- [ ] **Step 1: Write the fast failing tests**

```python
# tests/test_panel_furniture.py
import numpy as np
from PIL import Image, ImageDraw

from app import panels, render
from app.spec import CompositionSpec


def _set(n=3, gap=2.0, shape="wide", **kw):
    w, h = panels.sheet_sizes(n, gap)[0 if shape == "wide" else 1]
    base = dict(region_id="t", crs="EPSG:32610", crop=(0.0, 0.0, 1000.0 * w, 1000.0 * h),
                print_w_in=w, print_h_in=h, native_resolution_m=10, tracks=[], hotspots=[],
                seed=7, panels=n, panel_gap_in=gap, title_text="Tecopa")
    base.update(kw)
    return CompositionSpec(**base)


def _keepout(spec, dpi):
    w, h = spec.pixel_size(dpi)
    d = ImageDraw.Draw(Image.new("RGBA", (w, h)))
    return render._label_keepout(spec, d, w, h, dpi)


def test_the_keepout_of_a_set_holds_each_seam_band():
    spec = _set(3, 2.0)
    dpi = 40
    edge = round(render.GEO_EDGE_IN * dpi)
    rects = _keepout(spec, dpi)
    for band in panels.seam_bands_px(spec, dpi, edge):
        assert band in rects
    gap = panels.gap_rects_px(spec, dpi)[0]
    band = panels.seam_bands_px(spec, dpi, edge)[0]
    assert band[0] == gap[0] - edge and band[2] == gap[2] + edge


def test_the_keepout_of_a_single_sheet_has_no_band():
    single = _set(3, 2.0, panels=1, panel_gap_in=0.0)
    h = single.pixel_size(40)[1]
    assert not [r for r in _keepout(single, 40) if r[1] == 0 and r[3] == h]


def test_a_marker_label_stays_inside_its_panel():
    spec = _set(2, 2.0, "tall")
    dpi = 40
    w, h = spec.pixel_size(dpi)
    lo, hi = panels.span_px_at(spec, 600, dpi, w)            # an anchor in panel 1
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img, "RGBA")
    render._draw_label(d, "A long marker label", hi - 20, h // 2, render._font(14),
                       w, h, x_lo=lo, x_hi=hi)
    xs = np.nonzero(np.asarray(img)[..., 3])[1]
    assert xs.min() >= lo and xs.max() < hi


def test_a_marker_label_on_a_single_sheet_is_placed_as_before():
    w, h = 400, 200
    a = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    b = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    render._draw_label(ImageDraw.Draw(a, "RGBA"), "Camp", 380, 100, render._font(14), w, h)
    render._draw_label(ImageDraw.Draw(b, "RGBA"), "Camp", 380, 100, render._font(14), w, h,
                       x_lo=0, x_hi=w)
    assert np.array_equal(np.asarray(a), np.asarray(b))
```

- [ ] **Step 2: Write the slow failing tests**

```python
# tests/test_panel_render.py
import json
import os

import numpy as np

from app import panels, render
from app.spec import CompositionSpec
from tests.conftest import synthetic_region

REGION_DIR = synthetic_region("lassen_ca")
DPI = 40


def _cfg():
    return json.load(open(os.path.join(REGION_DIR, "region.json")))


def _spec(n=2, gap=2.0, **kw):
    """Two panels 17 in across on the middle of the plate: 36 x 22 in at gap 2."""
    cfg = _cfg(); bx = cfg["bounds"]
    w, h = panels.sheet_sizes(2, gap)[1]
    cx = (bx[0] + bx[2]) / 2; cy = (bx[1] + bx[3]) / 2
    half = 27000.0
    crop = (cx - half, cy - half * h / w, cx + half, cy + half * h / w)
    base = dict(region_id="lassen_ca", crs=cfg["crs"], crop=crop, print_w_in=w,
                print_h_in=h, native_resolution_m=10,
                tracks=[np.array([[crop[0] + 3000, crop[1] + 3000],
                                  [crop[2] - 3000, crop[3] - 3000]])],
                hotspots=[], seed=7, title_text="-", compass=False, keyline=False,
                panels=n, panel_gap_in=gap if n > 1 else 0.0)
    base.update(kw)
    return CompositionSpec(**base)


def _render(spec, labels=None):
    return np.asarray(render.rasterize(spec, dpi=DPI, region_dir=REGION_DIR, cfg=_cfg(),
                                       hydro={"lakes": [], "rivers": []}, labels=labels))


def _seam_labels(spec):
    """One summit on the middle of the gap, and one range that crosses it."""
    cx = (spec.crop[0] + spec.crop[2]) / 2; cy = (spec.crop[1] + spec.crop[3]) / 2
    return {"crs": _cfg()["crs"], "features": [
        {"name": "Seam Peak", "kind": "summit", "rank": 100, "coords": [[cx, cy + 6000]]},
        {"name": "Seam Range", "kind": "range", "rank": 100,
         "coords": [[cx - 5000, cy - 6000], [cx, cy - 6000], [cx + 5000, cy - 6000]]},
    ]}


def test_each_panel_is_the_matching_window_of_the_unbroken_sheet():
    as_set = _spec(2, 2.0)
    unbroken = _spec(1, 2.0)
    a, b = _render(as_set), _render(unbroken)
    assert a.shape == b.shape
    for x0, y0, x1, y1 in panels.panel_rects_px(as_set, DPI):
        assert np.array_equal(a[y0:y1, x0:x1], b[y0:y1, x0:x1])


def test_no_place_name_is_drawn_in_a_seam_band():
    for gap in (2.0, 0.0):
        as_set = _spec(2, gap, labels=True)
        unbroken = _spec(1, gap, labels=True)
        names = _seam_labels(as_set)
        edge = round(render.GEO_EDGE_IN * DPI)
        band = panels.seam_bands_px(as_set, DPI, edge // 2)[0]
        x0, x1 = band[0], band[2]
        # the control: with one panel the two names do paint in the band
        plain = _render(_spec(1, gap))
        assert (_render(unbroken, names)[:, x0:x1] != plain[:, x0:x1]).any()
        # the set: nothing of a name is in the band
        bare = _render(_spec(2, gap))
        assert np.array_equal(_render(as_set, names)[:, x0:x1], bare[:, x0:x1]), gap
```

Add the new slow module to `tests/conftest.py`, in `_SLOW_MODULES`:

```python
    "test_output_fitness", "test_wallpaper", "test_panel_render",
```

The second test compares a set with names against the same set without names. If the engine draws a point symbol at a summit's anchor (and not only its name), that symbol is tied to the ground and can be in the band: in that case keep the range in `_seam_labels` and remove the summit. Read `_draw_labels` before you decide.

- [ ] **Step 3: Run them and see them fail**

Run: `.venv/bin/python -m pytest tests/test_panel_furniture.py tests/test_panel_render.py -q`
Expected: FAIL. The keep-out has no band, `_draw_label` takes no `x_lo`, and a name paints in the band of a set.

- [ ] **Step 4: Change `app/render.py`**

With the other `from app import …` lines at the top:

```python
from app import panels as panel_geo
```

Replace the body of `_label_keepout` (keep its docstring):

```python
    tx0, ty0, tx1, ty1 = trim or (0, 0, out_w, out_h)
    # the furniture sits in panel 1 of a set, so its keep-out does too
    fx0, fy0, fx1, fy1 = panel_geo.furniture_trim_px(spec, dpi, (tx0, ty0, tx1, ty1))
    keepout = _furniture_stack_rects(spec, d, fx0, fy1, dpi)
    if spec.top_clear_frac > 0:
        keepout.append((0, 0, out_w, round(spec.top_clear_frac * out_h)))
    if spec.bottom_clear_frac > 0:
        keepout.append((0, out_h - round(spec.bottom_clear_frac * out_h), out_w, out_h))
    if spec.profile:
        keepout.append(_profile_rect(spec, d, (fx0, fy0, fx1, fy1), dpi))
    if panel_geo.is_set(spec):
        # each seam acts as a sheet edge: no name is cut by one or hidden behind a gap
        keepout += panel_geo.seam_bands_px(spec, dpi, round(GEO_EDGE_IN * dpi))
    return keepout
```

Replace `_draw_label`:

```python
def _draw_label(d, text, x, cy, font, out_w, out_h, x_lo=0, x_hi=None):
    """A label on a soft cream plate, left-anchored at x and vertically centred on cy.
    x_lo and x_hi are the panel of a set: the plate stays inside it."""
    l, t, rt, b = d.textbbox((0, 0), text, font=font)
    tw, th = rt - l, b - t
    pad = max(2, round(th * 0.3))
    x = min(x, (out_w if x_hi is None else x_hi) - tw - 2*pad - 1)   # keep the plate inside
    if x_lo:
        x = max(x, x_lo)
    y = float(np.clip(cy - th/2 - pad, 0, out_h - th - 2*pad - 1))
    d.rounded_rectangle([x, y, x + tw + 2*pad, y + th + 2*pad],
                        radius=pad, fill=LABEL_PLATE + (220,))
    d.text((x + pad - l, y + pad - t), text, fill=LABEL_INK + (255,), font=font)
```

In `_draw_markers`, replace the `_draw_label(...)` call:

```python
        if label:
            lo, hi = panel_geo.span_px_at(spec, cx, dpi, out_w)
            _draw_label(dd, label, cx + r + dia*0.25, cy, label_font, out_w, out_h,
                        x_lo=lo, x_hi=hi)
```

In `_draw_photos`, replace the line that sets `fx`:

```python
        # a photo box never crosses a seam: it stays in the panel that holds its anchor
        lo, hi = panel_geo.span_px_at(spec, ax, dpi, out_w)
        fx = int(np.clip(ax + box * 0.35, lo, hi - fw - 1))
```

- [ ] **Step 5: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_panel_furniture.py tests/test_panel_render.py tests/test_poster_furniture.py tests/test_labels.py -q`
Expected: all pass.

- [ ] **Step 6: Run the fast suite, then commit**

Run: `.venv/bin/python -m pytest -n auto -m "not slow" -q`

```bash
git add tests/test_panel_render.py tests/test_panel_furniture.py
git commit -m "A seam acts as a sheet edge for place names, photo boxes and marker labels" -- app/render.py tests/conftest.py tests/test_panel_render.py tests/test_panel_furniture.py
```

---

### Task 4: Furniture on a set

**Goal:** A set draws its title block, compass, scale bar and elevation strip once, inside panel 1, with a keyline and a panel mark on each panel and a watermark word that the caller can set.

**Files:**
- Modify: `app/render.py` (`_furniture_scale`, `_paint_overlays`, `rasterize`, `_label_keepout`, new `_panel_mark_rects` and `_draw_panel_marks`)
- Test: `tests/test_panel_furniture.py`

**Acceptance Criteria:**
- [ ] `_furniture_scale` of a set equals `_furniture_scale` of a 17 × 22 single sheet.
- [ ] `_paint_overlays` of a set paints nothing inside a gap strip.
- [ ] Each panel has a keyline of its own and a mark `k / n` in its lower right corner.
- [ ] The title block is inside panel 1.
- [ ] Each panel mark is a label keep-out.
- [ ] `rasterize(..., watermark=True, watermark_text="PREVIEW")` draws the word on each panel, and the default word stays "PROOF".
- [ ] `tests/test_poster_furniture.py` and `tests/test_timelapse.py` pass unchanged.

**Verify:** `.venv/bin/python -m pytest tests/test_panel_furniture.py tests/test_poster_furniture.py tests/test_bleed.py tests/test_wallpaper.py -q` → all pass

**Steps:**

- [ ] **Step 1: Write the failing tests** (append to `tests/test_panel_furniture.py`)

```python
def _overlays(spec, dpi, **kw):
    w, h = spec.pixel_size(dpi)
    blank = Image.new("RGBA", (w, h), (128, 128, 128, 255))
    out = render._paint_overlays(blank, spec, np.zeros((h, w)), w, h, dpi, **kw)
    return np.any(np.asarray(out) != 128, axis=2)


def test_a_set_sizes_its_furniture_as_one_panel_does():
    single = _set(3, 2.0, panels=1, panel_gap_in=0.0, print_w_in=17, print_h_in=22,
                  crop=(0.0, 0.0, 17000.0, 22000.0))
    for n, shape in ((2, "wide"), (3, "wide"), (2, "tall"), (3, "tall")):
        assert render._furniture_scale(_set(n, 4.0, shape)) == render._furniture_scale(single)


def test_nothing_is_painted_in_a_gap_strip():
    spec = _set(3, 2.0)
    dpi = 40
    painted = _overlays(spec, dpi, watermark=True)
    for x0, y0, x1, y1 in panels.gap_rects_px(spec, dpi):
        assert not painted[y0:y1, x0:x1].any()


def test_each_panel_has_its_own_keyline_and_mark():
    spec = _set(3, 2.0)
    dpi = 40
    painted = _overlays(spec, dpi)
    inset = round(render.KEYLINE_INSET_IN * dpi)
    d = ImageDraw.Draw(Image.new("RGBA", spec.pixel_size(dpi)))
    frames = panels.panel_rects_px(spec, dpi)
    marks = render._panel_mark_rects(spec, d, frames, dpi)
    assert len(marks) == 3
    for (x0, y0, x1, y1), (mx0, my0, mx1, my1) in zip(frames, marks):
        assert painted[y0 + inset, x0 + inset:x1 - inset].all()          # the top keyline
        assert painted[y0 + inset:y1 - inset, x1 - 1 - inset].all()      # the right keyline
        assert x0 < mx0 and mx1 <= x1 and my1 <= y1                      # the mark is in the panel
        assert mx0 > (x0 + x1) / 2 and my0 > (y0 + y1) / 2               # lower right
        assert painted[my0:my1, mx0:mx1].any()


def test_the_title_block_is_inside_panel_one():
    spec = _set(3, 2.0, keyline=False)
    dpi = 40
    painted = _overlays(spec, dpi)
    frames = panels.panel_rects_px(spec, dpi)
    d = ImageDraw.Draw(Image.new("RGBA", spec.pixel_size(dpi)))
    marks = render._panel_mark_rects(spec, d, frames, dpi)
    for (x0, y0, x1, y1), (mx0, my0, mx1, my1) in list(zip(frames, marks))[1:]:
        outside_mark = painted[y0:y1, x0:x1].copy()
        outside_mark[my0 - y0:my1 - y0, mx0 - x0:mx1 - x0] = False
        assert not outside_mark.any()        # panels 2 and 3 carry the mark and nothing more
    x0, y0, x1, y1 = frames[0]
    assert painted[(y0 + y1) // 2:y1, x0:(x0 + x1) // 2].any()           # lower left of panel 1


def test_each_panel_mark_is_a_label_keepout():
    spec = _set(2, 0.0, "tall")
    dpi = 40
    d = ImageDraw.Draw(Image.new("RGBA", spec.pixel_size(dpi)))
    marks = render._panel_mark_rects(spec, d, panels.panel_rects_px(spec, dpi), dpi)
    rects = _keepout(spec, dpi)
    assert all(m in rects for m in marks)


def test_the_watermark_word_is_drawn_on_each_panel():
    spec = _set(2, 2.0, "tall", keyline=False, compass=False, title_text="-")
    dpi = 40
    proof = _overlays(spec, dpi, watermark=True)
    preview = _overlays(spec, dpi, watermark=True, watermark_text="PREVIEW")
    for x0, y0, x1, y1 in panels.panel_rects_px(spec, dpi):
        top = slice(y0, y0 + (y1 - y0) // 2)
        assert proof[top, x0:x1].any() and preview[top, x0:x1].any()
    assert not np.array_equal(proof, preview)
```

- [ ] **Step 2: Run them and see them fail**

Run: `.venv/bin/python -m pytest tests/test_panel_furniture.py -q`
Expected: FAIL. `_panel_mark_rects` does not exist, and the furniture scale of a set is larger than one panel's.

- [ ] **Step 3: Change `_furniture_scale`**

Replace its last two lines:

```python
    # a set hangs as panels of 17 x 22 in, so its furniture is sized for one panel
    w, h = panel_geo.panel_size_in(spec)
    s = (w * h / FURNITURE_BASE_IN2) ** 0.5
    return min(max(s, FURNITURE_SCALE_MIN), FURNITURE_SCALE_MAX) * spec.furniture_scale
```

- [ ] **Step 4: Add the panel mark**

Place these two functions directly above `_paint_overlays`:

```python
def _panel_mark_rects(spec, d, frames, dpi):
    """The plate of each panel mark (`2 / 3`), in the lower right corner of its
    panel: [(x0, y0, x1, y1)] in pixels. The credit line's size, the body face."""
    fdpi = dpi * _furniture_scale(spec)
    font = _font(max(7, round(_pt_to_px(spec.label_pt * 0.62, fdpi))))
    inset = round(TITLE_INSET_IN * fdpi)
    rects = []
    for k, (x0, y0, x1, y1) in enumerate(frames):
        l, t, r, b = d.textbbox((0, 0), f"{k + 1} / {len(frames)}", font=font)
        pad = max(2, round((b - t) * 0.3))
        rects.append((x1 - inset - (r - l) - 2 * pad, y1 - inset - (b - t) - 2 * pad,
                      x1 - inset, y1 - inset))
    return rects


def _draw_panel_marks(img, spec, frames, dpi):
    """`1 / 3`, `2 / 3`, `3 / 3`: a loose panel can be named and hung in order."""
    d = ImageDraw.Draw(img, "RGBA")
    fdpi = dpi * _furniture_scale(spec)
    font = _font(max(7, round(_pt_to_px(spec.label_pt * 0.62, fdpi))))
    for k, (x0, y0, x1, y1) in enumerate(_panel_mark_rects(spec, d, frames, dpi)):
        text = f"{k + 1} / {len(frames)}"
        l, t, r, b = d.textbbox((0, 0), text, font=font)
        pad = max(2, round((b - t) * 0.3))
        d.rectangle([x0, y0, x1, y1], fill=LABEL_PLATE + (235,))
        d.text((x0 + pad - l, y0 + pad - t), text, fill=LABEL_INK + (255,), font=font)
    return img
```

In `_label_keepout`, replace the `if panel_geo.is_set(spec):` block from task 3:

```python
    if panel_geo.is_set(spec):
        # each seam acts as a sheet edge: no name is cut by one or hidden behind a gap
        keepout += panel_geo.seam_bands_px(spec, dpi, round(GEO_EDGE_IN * dpi))
        keepout += _panel_mark_rects(spec, d, panel_geo.panel_rects_px(spec, dpi), dpi)
    return keepout
```

- [ ] **Step 5: Replace `_paint_overlays`** (keep its docstring, and add one sentence to it: "On a set the furniture is placed in panel 1, and each panel gets a keyline, a mark and the watermark.")

```python
def _paint_overlays(img, spec, lum, out_w, out_h, dpi, watermark=False, ctx=None,
                    profile=None, paint=None, trim=None, watermark_text="PROOF"):
    if paint is None:
        paint = spec
    tx0, ty0, tx1, ty1 = trim or (0, 0, out_w, out_h)
    ftrim = panel_geo.furniture_trim_px(spec, dpi, (tx0, ty0, tx1, ty1))
    frames = panel_geo.frame_rects_px(spec, dpi, (tx0, ty0, tx1, ty1))
    img = _draw_markers(img, paint, lum, out_w, out_h, dpi, ctx=ctx)
    img = _draw_photos(img, paint, out_w, out_h, dpi, ctx=ctx)   # personal photos: the top layer
    if spec.profile:
        img = _draw_profile(img, spec, out_w, out_h, dpi, profile, trim=ftrim)
    if spec.keyline:
        for frame in frames:
            img = _draw_keyline(img, out_w, out_h, dpi, trim=frame)
    img = _draw_compass(img, spec, out_w, out_h, dpi, trim=ftrim)  # above title
    img = _draw_title_block(img, spec, out_w, out_h, dpi, trim=ftrim)
    if panel_geo.is_set(spec):
        img = _draw_panel_marks(img, spec, frames, dpi)
    if watermark:
        # scale to each printed piece (the old fixed 120 px offset + default font was
        # invisible at poster sizes) and center properly; translucent so the proof
        # stays readable. Upper third, not dead center: starter_crop centers the
        # journey mid-sheet, and the mark was parking on the corridor being judged.
        d = ImageDraw.Draw(img, "RGBA")
        for fx0, fy0, fx1, fy1 in frames:
            tw, th = fx1 - fx0, fy1 - fy0
            wm_font = _font(max(24, round(tw * 0.09)))
            l, t, rt, b = d.textbbox((0, 0), watermark_text, font=wm_font)
            d.text((fx0 + (tw - (rt - l)) / 2 - l, fy0 + th * 0.24 - t), watermark_text,
                   fill=(255, 255, 255, 80), font=wm_font)
    return img.convert("RGB")
```

- [ ] **Step 6: Pass the word through `rasterize`**

Change the signature:

```python
def rasterize(spec: CompositionSpec, dpi: int, region_dir: str,
              watermark: bool = False, hydro=None, cfg=None, labels=None,
              base_cache=None, ink_cache=None,
              terrain_override=None, watermark_text: str = "PROOF") -> Image.Image:
```

Change its last line:

```python
    return _paint_overlays(img, spec, lum, out_w, out_h, dpi, watermark=watermark, ctx=ctx,
                           profile=profile, paint=paint, trim=trim,
                           watermark_text=watermark_text)
```

- [ ] **Step 7: Leave the panel marks out of the window test**

A set now draws a mark on each panel, and no switch turns it off. In `tests/test_panel_render.py`, replace `test_each_panel_is_the_matching_window_of_the_unbroken_sheet`:

```python
def test_each_panel_is_the_matching_window_of_the_unbroken_sheet():
    from PIL import Image, ImageDraw
    as_set = _spec(2, 2.0)
    unbroken = _spec(1, 2.0)
    a, b = _render(as_set).copy(), _render(unbroken).copy()
    assert a.shape == b.shape
    frames = panels.panel_rects_px(as_set, DPI)
    d = ImageDraw.Draw(Image.new("RGBA", (a.shape[1], a.shape[0])))
    for mx0, my0, mx1, my1 in render._panel_mark_rects(as_set, d, frames, DPI):
        a[my0:my1 + 1, mx0:mx1 + 1] = 0          # the panel mark is the one thing a set adds
        b[my0:my1 + 1, mx0:mx1 + 1] = 0
    for x0, y0, x1, y1 in frames:
        assert np.array_equal(a[y0:y1, x0:x1], b[y0:y1, x0:x1])
```

- [ ] **Step 8: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_panel_furniture.py tests/test_poster_furniture.py tests/test_bleed.py tests/test_wallpaper.py tests/test_panel_render.py -q`
Expected: all pass.

- [ ] **Step 9: Run the fast suite, then commit**

Run: `.venv/bin/python -m pytest -n auto -m "not slow" -q`

```bash
git commit -m "A set draws its furniture once in panel 1, with a keyline and a mark on each panel" -- app/render.py tests/test_panel_furniture.py tests/test_panel_render.py
```

---

### Task 5: The furniture retune

**Goal:** The furniture is sized for a 17 × 22 sheet, and the smallest furniture text on an 11 × 17 is at least 6 pt.

**Files:**
- Modify: `app/render.py` (`FURNITURE_BASE_IN2`, `FURNITURE_SCALE_MIN`, the comment at the constant, the `_furniture_scale` docstring)
- Modify: `tests/test_poster_furniture.py` (`test_furniture_scale_tracks_sheet_size`, `test_furniture_slider_multiplies_the_auto_scale`, two new tests)
- Modify: `docs/decisions.md`

**Acceptance Criteria:**
- [ ] `_furniture_scale` is exactly 1.0 for 17 × 22 and 0.80 for 11 × 17.
- [ ] `13 pt × 0.62 × 0.80` is at least 6 pt, held by a test.
- [ ] No test names 18 × 24 as the furniture base.
- [ ] `docs/decisions.md` records the retune and the drift of an older reprint.

**Verify:** `.venv/bin/python -m pytest tests/test_poster_furniture.py tests/test_panel_furniture.py -q` → all pass

**Steps:**

- [ ] **Step 1: Write the failing tests** (append to `tests/test_poster_furniture.py`)

```python
def test_the_two_sheets_on_the_menu_set_the_furniture_scale():
    """The menu is 17 x 22 and 11 x 17 (decisions, 2026-10-10). The large sheet is
    the design size. The small sheet stops at the floor."""
    assert render.FURNITURE_BASE_IN2 == 17.0 * 22.0
    assert render._furniture_scale(_spec(print_w_in=17, print_h_in=22)) == 1.0
    assert render._furniture_scale(_spec(print_w_in=22, print_h_in=17)) == 1.0
    assert render._furniture_scale(_spec(print_w_in=11, print_h_in=17)) == render.FURNITURE_SCALE_MIN


def test_the_smallest_furniture_text_on_the_smallest_sheet_is_six_points():
    """The credit line is the smallest furniture text: label_pt x 0.62. At the floor
    it must still be legible on paper."""
    spec = _spec(print_w_in=11, print_h_in=17)
    assert spec.label_pt * 0.62 * render._furniture_scale(spec) >= 6.0
```

- [ ] **Step 2: Run them and see them fail**

Run: `.venv/bin/python -m pytest tests/test_poster_furniture.py -q`
Expected: the first new test FAILS on `FURNITURE_BASE_IN2 == 17.0 * 22.0`.

- [ ] **Step 3: Change the constants in `app/render.py`**

```python
FURNITURE_BASE_IN2 = 17.0 * 22.0   # the sheet all furniture sizes are designed on:
                                   # the large sheet of the two-size menu (2026-10-11)
FURNITURE_SCALE_MIN = 0.80         # the 11 x 17: smaller, with a 6 pt credit line
FURNITURE_SCALE_MAX = 2.0          # oversize sheets: grow, never into novelty
```

In the `_furniture_scale` docstring, replace the two mentions of 18x24 so it reads:

```python
    """Furniture grows with the sheet (Dom): a larger sheet hangs farther from the
    eye, so the compass, cartouche and scale bar scale with the sheet's linear size
    (sqrt of area) relative to the 17x22 they are designed on -- then the client's
    furniture_scale slider multiplies the auto-appropriate size. A set is sized as one
    of its panels. A pure function of the spec, so proof == final at any DPI
    (invariant 1)."""
```

- [ ] **Step 4: Change the two tests that pin the old base**

In `tests/test_poster_furniture.py`, two tests assert the old base: `test_furniture_scale_tracks_sheet_size` and `test_furniture_slider_multiplies_the_auto_scale`. In both, replace each expected value with the same expression the code uses, so no number depends on the base:

```python
def _auto(w, h):
    """The scale the engine gives a w x h sheet before the slider."""
    s = (w * h / render.FURNITURE_BASE_IN2) ** 0.5
    return min(max(s, render.FURNITURE_SCALE_MIN), render.FURNITURE_SCALE_MAX)
```

- An assertion `render._furniture_scale(<18 x 24 spec>) == 1.0` becomes `== pytest.approx(_auto(18, 24))`.
- An assertion with `(864 / 432) ** 0.5` (a 24 × 36 sheet) becomes `pytest.approx(_auto(24, 36))`, times the slider value where the test has one.
- An assertion `== 1.4` with slider 1.4 on 18 × 24 becomes `pytest.approx(_auto(18, 24) * 1.4)`.

Keep each test's sheets and its slider values. Add `import pytest` if the file does not have it.

- [ ] **Step 5: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_poster_furniture.py tests/test_panel_furniture.py tests/test_credit_and_names.py tests/test_bleed.py -q`
Expected: all pass.

- [ ] **Step 6: Record the decision**

Add a section at the end of the dated sections of `docs/decisions.md`, before the "not done" table:

```markdown
## 2026-10-11 (print sizes, panel sets and the size preview)

| Decision | Why | Source |
|---|---|---|
| The furniture is designed on 17×22, not 18×24. The floor for a small sheet is 80 %, not 75 %. A reprint of an older file draws its furniture about 7 % larger. | The menu is 17×22 and 11×17. The 11×17 was a reduced 18×24 with a 6 pt credit line at the old floor. Invariant 7 allows the drift. | `superpowers/specs/2026-10-11-print-sizes-panel-sets-and-size-preview-design.md` §4 |
```

- [ ] **Step 7: Run the fast suite, then commit**

Run: `.venv/bin/python -m pytest -n auto -m "not slow" -q`

```bash
git commit -m "Furniture is designed on 17x22, and the 11x17 floor is 80 %" -- app/render.py tests/test_poster_furniture.py docs/decisions.md
```

---

### Task 6: The API: proof fields, the wall tone, the zip of a set

**Goal:** `/api/proof` takes `panels` and `panel_gap`, a proof of a set shows each gap strip in the wall tone, and a final of a set is a deterministic zip of one file per panel, each with a `panel` key in its manifest.

**Files:**
- Modify: `app/main.py` (imports, `_render_to_blob`, new `_encode_delivery` and helpers, `proof`, `_render_refine_to_blob`, `final`, `final_submit`, `_proof_form_for`, the `prefill` dict in `continue_poster`)
- Modify: `tests/conftest.py` (`_SLOW_TESTS`)
- Test: `tests/test_panel_api.py`

**Acceptance Criteria:**
- [ ] A proof with `panels=2`, `panel_gap=2`, `print_w=36`, `print_h=22` answers 200 with a 3456 × 2112 image whose gap strip is the wall tone.
- [ ] A proof of a set with a wrong sheet answers 422 and names both sheets.
- [ ] `_encode_delivery` of a set returns a zip of `…_1of2.png` and `…_2of2.png`, and two calls give the same bytes.
- [ ] Each member's manifest holds `"panel": {"index": k, "of": n}` and the full set spec.
- [ ] `_proof_form_for` returns `panels` and `panel_gap`.
- [ ] `/api/final/submit` of a set ends in a job whose result is `application/zip`.

**Verify:** `.venv/bin/python -m pytest tests/test_panel_api.py tests/test_debug.py tests/test_main.py -q` → all pass

**Steps:**

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_panel_api.py
import io
import json
import os
import time
import zipfile

import numpy as np
from fastapi.testclient import TestClient
from PIL import Image

from app import main, panels, provenance
from tests.test_panels import set_spec

REGION_DIR = "regions/lassen_ca"
SET = {"panels": 2, "panel_gap": 2, "print_w": 36, "print_h": 22}


def _client():
    return TestClient(main.app)


def _upload(c):
    data = open("tests/fixtures/sample.gpx", "rb").read()
    return c.post("/api/upload", files=[("files", ("a.gpx", data, "application/gpx+xml"))]).json()


def _crop(j, km_wide=56.0, ar=36 / 22):
    """A crop in overview pixels, centred on the plate. 56 km holds a 36 in sheet at
    300 dpi inside the 2x rule of a 10 m plate."""
    cfg = json.load(open(os.path.join(REGION_DIR, "region.json")))
    region_w = cfg["bounds"][2] - cfg["bounds"][0]
    ovw, ovh = j["overview_size"]
    cw = ovw * (km_wide * 1000.0 / region_w); ch = cw / ar
    x0 = ovw * 0.5 - cw / 2; y0 = ovh * 0.5 - ch / 2
    return {"x0": x0, "y0": y0, "x1": x0 + cw, "y1": y0 + ch}


def _proof(c, **over):
    j = _upload(c)
    r = c.post("/api/proof", data={"session_id": j["session"], **_crop(j), "title": "Set",
                                   **SET, **over})
    return j, r


def test_a_proof_of_a_set_shows_the_gap_in_the_wall_tone():
    c = _client()
    _, r = _proof(c)
    assert r.status_code == 200, r.text
    img = np.asarray(Image.open(io.BytesIO(r.content)).convert("RGB"))
    assert img.shape == (2112, 3456, 3)                      # 22 x 36 in at 96 dpi
    assert (img[:, 1632:1824] == panels.WALL_TONE).all()     # 17 in, then a 2 in strip
    assert not (img[:, 1600:1632] == panels.WALL_TONE).all()


def test_a_set_with_a_wrong_sheet_is_a_422_that_names_both_sheets():
    c = _client()
    j = _upload(c)
    r = c.post("/api/proof", data={"session_id": j["session"], **_crop(j, ar=34 / 22),
                                   **SET, "print_w": 34})
    assert r.status_code == 422
    assert "46x17 or 36x22 in" in r.json()["detail"]


def test_a_single_sheet_proof_is_not_touched():
    c = _client()
    j = _upload(c)
    data = {"session_id": j["session"], **_crop(j, km_wide=40.0, ar=0.75),
            "print_w": 6, "print_h": 8}
    a = c.post("/api/proof", data=data)
    b = c.post("/api/proof", data={**data, "panels": 1, "panel_gap": 0})
    assert a.status_code == b.status_code == 200 and a.content == b.content


def test_the_proof_form_carries_both_fields():
    form = main._proof_form_for(set_spec(3, 2.0, "wide"))
    assert form["panels"] == 3 and form["panel_gap"] == 2.0
    assert type(form["panels"]) is int and type(form["panel_gap"]) is float


def _fake_sheet(spec, dpi=10):
    w, h = spec.pixel_size(dpi)
    rng = np.random.default_rng(3)
    return Image.fromarray(rng.integers(0, 255, (h, w, 3), dtype=np.uint8))


def test_the_delivery_of_a_set_is_a_zip_of_one_file_per_panel():
    spec = set_spec(2, 2.0, "tall", region_id="lassen_ca")
    manifest = provenance.build_manifest(spec, [])
    sheet = _fake_sheet(spec)
    data = main._encode_delivery(sheet, spec, "png", manifest, 10)
    again = main._encode_delivery(sheet, spec, "png", manifest, 10)
    assert data == again                                      # invariant 3
    z = zipfile.ZipFile(io.BytesIO(data))
    assert z.namelist() == ["tecopa_lassen_ca_1of2.png", "tecopa_lassen_ca_2of2.png"]
    assert all(i.date_time == (1980, 1, 1, 0, 0, 0) for i in z.infolist())
    parts = panels.cut(sheet, spec, 10)
    for k, name in enumerate(z.namelist(), 1):
        png = z.read(name)
        assert np.array_equal(np.asarray(Image.open(io.BytesIO(png))), np.asarray(parts[k - 1]))
        m = provenance.extract(png)
        assert m["panel"] == {"index": k, "of": 2}
        assert m["spec"]["panels"] == 2 and m["spec"]["panel_gap_in"] == 2.0
    assert main._delivery_name(spec, "png") == "tecopa_lassen_ca_panels.zip"
    assert main._delivery_media(spec, "png") == "application/zip"


def test_the_delivery_of_a_single_sheet_is_the_file_itself():
    spec = set_spec(2, 2.0, "tall", region_id="lassen_ca", panels=1, panel_gap_in=0.0)
    manifest = provenance.build_manifest(spec, [])
    sheet = _fake_sheet(spec)
    assert main._encode_delivery(sheet, spec, "png", manifest, 10) == main._encode_final(
        sheet, "png", manifest, dpi=10)
    assert "panel" not in provenance.extract(main._encode_delivery(sheet, spec, "png", manifest, 10))
    assert main._delivery_name(spec, "png") == "tecopa_lassen_ca.png"
    assert main._delivery_media(spec, "pdf") == "application/pdf"


def test_a_share_copy_of_a_set_carries_no_manifest():
    spec = set_spec(2, 0.0, "tall", region_id="lassen_ca")
    z = zipfile.ZipFile(io.BytesIO(main._encode_delivery(_fake_sheet(spec), spec, "png", None, 10)))
    assert all(provenance.extract(z.read(n)) is None for n in z.namelist())


def _wait(c, jid, seconds=600):
    for _ in range(seconds * 4):
        s = c.get(f"/api/jobs/{jid}").json()
        if s["state"] in ("done", "error"):
            return s
        time.sleep(0.25)
    raise AssertionError("the job did not end")


def test_a_final_of_a_set_is_a_zip_job():
    c = _client()
    j, r = _proof(c)
    assert r.status_code == 200, r.text
    jid = c.post("/api/final/submit", data={"session_id": j["session"]}).json()["job"]
    s = _wait(c, jid)
    assert s["state"] == "done", s
    out = c.get(s["result"])
    assert out.headers["content-type"] == "application/zip"
    assert "_panels.zip" in out.headers["content-disposition"]
    z = zipfile.ZipFile(io.BytesIO(out.content))
    assert len(z.namelist()) == 2
    for name in z.namelist():
        assert Image.open(io.BytesIO(z.read(name))).size == (5100, 6600)
```

Mark the one heavy test slow in `tests/conftest.py`, inside `_SLOW_TESTS`:

```python
    "test_panel_api": {
        "test_a_final_of_a_set_is_a_zip_job",
    },
```

- [ ] **Step 2: Run them and see them fail**

Run: `.venv/bin/python -m pytest tests/test_panel_api.py -q -m "not slow"`
Expected: FAIL. `main` has no `_encode_delivery`, and the proof ignores `panels`.

- [ ] **Step 3: Add the delivery helpers to `app/main.py`**

With the other `from app import …` lines:

```python
from app import panels as panel_geo
```

Make sure `zipfile` is imported at the top (it is used by the wallpaper bundle). Place this block directly under `_encode_final`:

```python
ZIP_EPOCH = (1980, 1, 1, 0, 0, 0)     # every member has the same date: same bytes each time


def _panel_manifest(manifest, index, count):
    """One panel's manifest: the set's own, plus which panel this file is. Any one
    panel can then reprint the whole set."""
    if manifest is None:
        return None
    return {**manifest, "panel": {"index": index, "of": count}}


def _delivery_name(spec, fmt: str) -> str:
    """The download name of a final: the file, or for a set the zip of its panels."""
    if panel_geo.is_set(spec):
        return download_name(spec, "_panels", "zip")
    return download_name(spec, fmt=fmt)


def _delivery_media(spec, fmt: str) -> str:
    return "application/zip" if panel_geo.is_set(spec) else FINAL_FORMATS[fmt][1]


def _encode_delivery(img, spec, fmt: str, manifest, dpi) -> bytes:
    """The bytes a final delivers. A single sheet is one file. A set is painted as
    one sheet, cut, and zipped: one file for each panel, stored, with fixed dates."""
    if not panel_geo.is_set(spec):
        return _encode_final(img, fmt, manifest, dpi=dpi)
    parts = panel_geo.cut(img, spec, dpi)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
        for k, part in enumerate(parts, 1):
            info = zipfile.ZipInfo(download_name(spec, f"_{k}of{len(parts)}", fmt),
                                   date_time=ZIP_EPOCH)
            info.create_system = 3
            info.external_attr = 0o644 << 16
            z.writestr(info, _encode_final(part, fmt, _panel_manifest(manifest, k, len(parts)),
                                           dpi=dpi))
    return buf.getvalue()
```

`download_name` is defined lower in the file. That is fine: these functions call it at request time.

- [ ] **Step 4: Use the helpers in the two final routes**

Replace the body of `_render_to_blob`:

```python
def _render_to_blob(spec, region_dir, key, fmt="png", manifest=None):
    dpi = spec.final_dpi()
    img = render.rasterize(spec, dpi=dpi, region_dir=region_dir, watermark=False)
    BLOBS.put(key, _encode_delivery(img, spec, fmt, manifest, dpi))
    return key                                         # job result = the blob key
```

In `final_submit`, the blob key becomes:

```python
    jid = QUEUE.submit(_render_to_blob, spec, region.dir,
                       f"{session_id}/{_delivery_name(spec, fmt)}", fmt,
                       _final_manifest(spec, sources, embed_spec, lineage, region_pack=rp))
```

In `final` (the synchronous route), change three places:

```python
    key = f"{session_id}/{_delivery_name(spec, fmt)}"
```

```python
    BLOBS.put(key, _encode_delivery(img, spec, fmt,
                                    _final_manifest(spec, sources, embed_spec, lineage,
                                                    region_pack=rp), dpi))
```

```python
    return FileResponse(BLOBS.path(key), media_type=_delivery_media(spec, fmt),
                        filename=_delivery_name(spec, fmt))
```

`/api/jobs/{jid}/result` already serves a key that ends in `.zip` as `application/zip`.

- [ ] **Step 5: Add the two proof fields**

At the end of the `proof` signature, after `bleed: float = Form(0.0)`:

```python
                custom_ppi: float = Form(0.0), bleed: float = Form(0.0),
                panels: int = Form(1), panel_gap: float = Form(0.0)):
```

In the `style` dict of `proof`, add two entries:

```python
         "label_place": label_place, "track_weave": track_weave,
         "panels": panels, "panel_gap_in": panel_gap}
```

In `proof`, directly after `session.update(session_id, spec=spec)` and its log line, and before the bleed crop:

```python
    # a set is shown as it hangs: each gap strip in the wall tone
    img = panel_geo.paint_gaps(img, spec, _proof_dpi(spec))
```

In `_render_refine_to_blob`, add the same line directly after its `render.rasterize(...)` call, with the worker's own dpi variable:

```python
    img = panel_geo.paint_gaps(img, spec, dpi)
```

In `_proof_form_for`, add two entries to the `form` dict:

```python
        "output": spec.output_kind, "bleed": f(spec.bleed_in),
        "panels": int(spec.panels), "panel_gap": f(spec.panel_gap_in),
```

In `continue_poster`, add two entries to the `prefill` dict, next to `print_h_in`:

```python
        "panels": spec.panels, "panel_gap_in": spec.panel_gap_in,
```

- [ ] **Step 6: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_panel_api.py tests/test_debug.py tests/test_main.py -q -m "not slow"`
Expected: all pass.

Run: `.venv/bin/python -m pytest tests/test_panel_api.py::test_a_final_of_a_set_is_a_zip_job tests/test_editions.py -q`
Expected: all pass. This renders one 71 megapixel final and takes some minutes. If a test in `tests/test_editions.py` fails only because it counts the proof fields (`test_proof_form_restores_a_styled_poster` asserts a count of fields that moved), read it, add the two fields to its list if they belong, and change the count.

- [ ] **Step 7: Run the fast suite, then commit**

Run: `.venv/bin/python -m pytest -n auto -m "not slow" -q`

```bash
git add tests/test_panel_api.py
git commit -m "A proof shows a set as it hangs, and a final of a set is a zip of one file per panel" -- app/main.py tests/conftest.py tests/test_panel_api.py tests/test_editions.py
```

---

### Task 7: The API: reprint, inspect, continue and the two refusals

**Goal:** Any panel file reprints the whole set, `/api/reprint/inspect` names the panel, and a set is refused by the film and wallpaper routes with a 422.

**Files:**
- Modify: `app/main.py` (`reprint`, `reprint_inspect`, `wallpapers_submit`, `timelapse_submit`, new `_refuse_set`)
- Modify: `tests/test_editions.py` (`_WRONG_TYPES`, one new test)
- Modify: `tests/conftest.py` (`_SLOW_TESTS`)
- Modify: `docs/MANIFEST.md`
- Test: `tests/test_panel_api.py`

**Acceptance Criteria:**
- [ ] `/api/reprint` of panel 2 of a set returns `application/zip` whose panels are pixel-identical to the first final's.
- [ ] `/api/reprint/inspect` of a panel file returns `panels`, `panel_gap_in` and `panel`.
- [ ] `/api/timelapse/submit` and `/api/wallpapers/submit` answer 422 for a session that holds a set.
- [ ] A crafted manifest with `panels` 7, a gap of 1, a string for either field, or a set with a wrong sheet is a 422 on `/api/reprint` and `/api/continue`, never a 500.
- [ ] `docs/MANIFEST.md` documents the two spec fields and the `panel` key.

**Verify:** `.venv/bin/python -m pytest tests/test_panel_api.py tests/test_editions.py tests/test_provenance.py -q` → all pass

**Steps:**

- [ ] **Step 1: Write the failing tests** (append to `tests/test_panel_api.py`)

```python
def test_a_set_is_refused_by_the_film_and_wallpaper_routes():
    c = _client()
    j, r = _proof(c)
    assert r.status_code == 200, r.text
    film = c.post("/api/timelapse/submit", data={"session_id": j["session"]})
    assert film.status_code == 422 and "set of panels" in film.json()["detail"]
    wall = c.post("/api/wallpapers/submit", data={"session_id": j["session"],
                                                  "presets": "ig_portrait"})
    assert wall.status_code == 422 and "set of panels" in wall.json()["detail"]


def test_inspect_names_the_panel_of_a_set():
    spec = set_spec(3, 2.0, "wide", region_id="lassen_ca")
    manifest = provenance.build_manifest(spec, [])
    z = zipfile.ZipFile(io.BytesIO(main._encode_delivery(_fake_sheet(spec), spec, "png",
                                                         manifest, 10)))
    png = z.read(z.namelist()[1])
    body = _client().post("/api/reprint/inspect",
                          files={"file": ("p.png", png, "image/png")}).json()
    assert body["panels"] == 3 and body["panel_gap_in"] == 2.0
    assert body["panel"] == {"index": 2, "of": 3}
    assert body["print_size_in"] == [70.0, 17.0]


def test_inspect_of_a_single_sheet_says_one_panel():
    c = _client()
    j = _upload(c)
    c.post("/api/proof", data={"session_id": j["session"], **_crop(j, 40.0, 0.75),
                               "print_w": 6, "print_h": 8})
    png = c.post("/api/final", data={"session_id": j["session"]}).content
    body = c.post("/api/reprint/inspect", files={"file": ("p.png", png, "image/png")}).json()
    assert body["panels"] == 1 and body["panel_gap_in"] == 0.0 and body["panel"] is None


def test_any_panel_reprints_the_whole_set():
    c = _client()
    j, r = _proof(c)
    assert r.status_code == 200, r.text
    first = c.post("/api/final", data={"session_id": j["session"]})
    assert first.headers["content-type"] == "application/zip"
    z1 = zipfile.ZipFile(io.BytesIO(first.content))
    panel_two = z1.read(z1.namelist()[1])
    again = c.post("/api/reprint", files={"file": ("two.png", panel_two, "image/png")})
    assert again.status_code == 200, again.text
    assert again.headers["content-type"] == "application/zip"
    assert "_panels.zip" in again.headers["content-disposition"]
    z2 = zipfile.ZipFile(io.BytesIO(again.content))
    assert z2.namelist() == z1.namelist()
    for name in z1.namelist():
        a = np.asarray(Image.open(io.BytesIO(z1.read(name))).convert("RGB"))
        b = np.asarray(Image.open(io.BytesIO(z2.read(name))).convert("RGB"))
        assert np.array_equal(a, b), name
        assert provenance.extract(z2.read(name))["panel"] == provenance.extract(z1.read(name))["panel"]
```

Add the heavy test to `_SLOW_TESTS["test_panel_api"]` in `tests/conftest.py`:

```python
    "test_panel_api": {
        "test_a_final_of_a_set_is_a_zip_job",
        "test_any_panel_reprints_the_whole_set",
    },
```

In `tests/test_editions.py`, add three rows to `_WRONG_TYPES`:

```python
    ("panels", "3"), ("panels", 2.5), ("panel_gap_in", "2"),
```

and add this test below `test_a_crafted_field_type_is_a_422_on_both_file_verbs`:

```python
@pytest.mark.parametrize("fields", [
    {"panels": 7}, {"panel_gap_in": 1.0}, {"panels": 2}, {"panel_gap_in": 2.0},
    {"panels": 3, "panel_gap_in": 4.0, "bleed_in": 0.125},
], ids=["count", "gap", "sheet", "gap-on-a-single", "bleed"])
def test_a_crafted_set_is_a_422_on_both_file_verbs(fields):
    """A set has a fixed menu. A file that claims another is refused, never rendered."""
    c = _client()
    m = _valid_manifest()
    m["spec"].update(fields)
    png = _embed(m)
    for verb in ("/api/continue", "/api/reprint"):
        r = c.post(verb, files={"file": ("x.png", png, "image/png")})
        assert r.status_code == 422, f"{verb}: {r.status_code} {r.text[:200]}"
        assert isinstance(r.json()["detail"], str)
```

- [ ] **Step 2: Run them and see them fail**

Run: `.venv/bin/python -m pytest tests/test_panel_api.py -q -m "not slow"`
Expected: FAIL. The film route accepts a set, and inspect has no `panels` key.

- [ ] **Step 3: Refuse a set at the film and wallpaper routes**

Place this next to `_require_format` in `app/main.py`:

```python
def _refuse_set(spec, what: str):
    """A set is a print of two or three panels. It has no film and no wallpaper."""
    if panel_geo.is_set(spec):
        raise HTTPException(422, f"A set of panels has no {what}. Choose one sheet first.")
```

In `wallpapers_submit`, directly after the line that calls `_require_stamped(session_id)`:

```python
    _refuse_set(spec, "wallpaper bundle")
```

In `timelapse_submit`, directly after the line that calls `_require_stamped(session_id)`:

```python
    _refuse_set(spec, "film")
```

In `reprint`, directly before the branch that reads `manifest.get("animation")`:

```python
    if isinstance(manifest.get("animation"), dict):
        _refuse_set(spec, "film")
```

- [ ] **Step 4: Make reprint deliver a set**

In `reprint`, replace the encode and the return of the still branch:

```python
    out = _encode_delivery(img, spec, fmt,
                           _final_manifest(spec, manifest.get("sources", []), embed_spec,
                                           manifest.get("lineage", []),
                                           region_pack=provenance.region_pack_block(
                                               region.dir, labels=spec.labels,
                                               biome=spec.biome, dry_lakes=spec.dry_lakes)),
                           spec.final_dpi())
    return StreamingResponse(io.BytesIO(out), media_type=_delivery_media(spec, fmt),
                             headers={"Content-Disposition":
                                      f'attachment; filename="{_delivery_name(spec, fmt)}"'})
```

- [ ] **Step 5: Name the panel in inspect**

In the dict that `reprint_inspect` returns, add after `"print_size_in"`:

```python
        # a set: how many panels, the gap, and which panel this file is (None for
        # a single sheet). Read raw, as every key here is: inspect builds no spec.
        "panels": spec_d.get("panels", 1),
        "panel_gap_in": spec_d.get("panel_gap_in", 0.0),
        "panel": manifest.get("panel"),
```

- [ ] **Step 6: Document the manifest**

In `docs/MANIFEST.md`, add a row to the "Top-level keys" table:

```markdown
| `panel`            | conditional | which panel of a set this file is (below) |
```

Add two bullets to the `spec` field list, next to `print_w_in`:

```markdown
- `panels` — 1, 2 or 3 (default 1). Above 1 the file is one panel of a set, and `print_w_in` × `print_h_in` is the hung size of the whole set, gaps included
- `panel_gap_in` — 0, 2 or 4 (default 0). The unprinted strip between two panels, in inches. 0 is a cut set
```

Add a section before "Schema evolution":

```markdown
## `panel` — one panel of a set

Present only when `spec.panels` is above 1.

    "panel": {"index": 2, "of": 3}

Every panel of a set carries the same `spec`. `index` counts from 1, from the left.
A reprint from any one panel renders the whole set again and returns a zip of all
its panels. The panels are 17 × 22 in each. `app/panels.py` derives each panel's
rectangle from `spec.panels`, `spec.panel_gap_in` and the sheet size.
```

- [ ] **Step 7: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_panel_api.py tests/test_provenance.py -q -m "not slow"`
Expected: all pass.

Run: `.venv/bin/python -m pytest tests/test_panel_api.py::test_any_panel_reprints_the_whole_set tests/test_editions.py -q`
Expected: all pass. Two 71 megapixel renders: allow ten minutes.

- [ ] **Step 8: Run the fast suite, then commit**

Run: `.venv/bin/python -m pytest -n auto -m "not slow" -q`

```bash
git commit -m "Any panel reprints its whole set, inspect names the panel, and a set has no film" -- app/main.py tests/conftest.py tests/test_panel_api.py tests/test_editions.py docs/MANIFEST.md
```

---

### Task 8: The studio

**Goal:** The studio can frame, proof and download a set: two new sizes, a gap control, gap strips in the frame tool, a zip download and a library card that names the panel.

**Files:**
- Modify: `app/static/index.html` (the size select, a new `gapField`)
- Modify: `app/static/store.js` (`panels`, `panelGap`)
- Modify: `app/static/compose.js` (`applyPrintSize`, `applyOutputVisibility`, `reframe`, `ensurePrintSize`, `restorePagePrefs`, `applyPrefill`, the gap wiring)
- Modify: `app/static/api.js` (`proof`)
- Modify: `app/static/proof.js` (`sizeLabel`, the `api.proof` call, `acceptFinal`)
- Modify: `app/static/canvas.js` (`drawCrop`)
- Modify: `app/static/controls.js` (one entry, the size entry's help and keywords)
- Modify: `app/static/app.js` (`STATIC_CONTROL_TARGETS`, `attachStaticHelp`)
- Modify: `app/static/ui.js` (`updateSaveFileNote`), `app/static/social.js` (the mockup guard), `app/static/library.js` (the card)
- Test: `tests/test_static_registry.py` (one new test)

**Acceptance Criteria:**
- [ ] The size menu has "Two panels" and "Three panels". Choosing one shows the gap control and hides the bleed control.
- [ ] The frame on the map has the set's shape and shows each gap strip.
- [ ] A proof of a set arrives with the wall tone in each gap.
- [ ] "Accept" on a set downloads a file whose name ends in `_panels.zip`.
- [ ] A panel file dropped on the library card shows "3 panels, 70×17 in" and "Panel 2 of 3".
- [ ] `node --check` passes for each edited module, and `tests/test_static_registry.py` passes.

**Verify:** `for f in store compose api proof canvas controls app ui social library; do node --check app/static/$f.js || echo FAIL $f; done; .venv/bin/python -m pytest tests/test_static_registry.py -q` → no `FAIL` line, all tests pass. Then the browser check in step 12.

**Steps:**

- [ ] **Step 1: Write the failing test** (append to `tests/test_static_registry.py`)

```python
def test_the_studio_sends_a_set_with_the_engines_own_field_names():
    """The two set fields have one name each on the wire. A typo here would send a
    set as a single sheet with no error, because FastAPI ignores an unknown field."""
    import inspect
    from app import main
    params = inspect.signature(main.proof).parameters
    assert "panels" in params and "panel_gap" in params
    api = (STATIC / "api.js").read_text(encoding="utf-8")
    assert re.search(r"\bpanels: panels > 1 \? panels : undefined", api)
    assert re.search(r"\bpanel_gap: panels > 1 \? panelGap : undefined", api)
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert '<option value="panels:2">Two panels</option>' in html
    assert '<option value="panels:3">Three panels</option>' in html
    assert 'id="gapField"' in html and 'id="gap"' in html
    store = (STATIC / "store.js").read_text(encoding="utf-8")
    assert re.search(r"^  panels: 1,", store, re.M) and re.search(r"^  panelGap: 2,", store, re.M)
```

Run: `.venv/bin/python -m pytest tests/test_static_registry.py -q`
Expected: the new test FAILS.

- [ ] **Step 2: `index.html`**

Add two options to `<select id="size">`:

```html
                  <option value="17,22">17 × 22 in</option>
                  <option value="11,17">11 × 17 in</option>
                  <option value="panels:2">Two panels</option>
                  <option value="panels:3">Three panels</option>
```

Add the gap row directly after the `sizeField` div:

```html
              <div class="field" id="gapField" hidden>
                <label>Gap between panels</label>
                <div class="segmented" data-for="gap" role="radiogroup" aria-label="Gap between panels">
                  <button type="button" role="radio" data-val="0">None</button>
                  <button type="button" role="radio" data-val="2">2 in</button>
                  <button type="button" role="radio" data-val="4">4 in</button>
                </div>
                <select id="gap" class="sr-only" tabindex="-1" aria-hidden="true">
                  <option value="0">None</option><option value="2">2 in</option><option value="4">4 in</option>
                </select>
              </div>
```

- [ ] **Step 3: `store.js`**

In `state`, directly after the `orientation` line:

```js
  panels: 1,              // 1 = a single sheet; 2 or 3 = a set of 17 × 22 in panels
  panelGap: 2,            // inches between two panels on the wall: 0 (a cut set), 2 or 4
```

Change the comment on `LS_KEY` to list `panelGap` with the other keys.

- [ ] **Step 4: `compose.js`**

Change the module state line:

```js
let segOutput = null, segOrient = null, segGap = null;
```

In `initCompose`, directly after the `$('size').onchange` line:

```js
  segGap = wireSegmented($('gapField').querySelector('.segmented'), (v) => {
    state.panelGap = Number(v); savePref('panelGap', state.panelGap); reframe();
  });
```

Replace `applyPrintSize`:

```js
export function applyPrintSize() {
  if (state.output === 'wallpaper') {
    state.panels = 1;
    const p = activePreset();
    if (p) { state.printW = p.px[0] / p.ppi; state.printH = p.px[1] / p.ppi; }
    return;
  }
  const v = $('size').value;
  const landscape = state.orientation === 'auto' ? trackAspectIsWide() : state.orientation === 'landscape';
  if (v.startsWith('panels:')) {
    // a set: the sheet is the hung size. Landscape = panels 22 in across.
    const n = Number(v.slice(7)), g = state.panelGap;
    state.panels = n;
    state.printW = n * (landscape ? 22 : 17) + (n - 1) * g;
    state.printH = landscape ? 17 : 22;
    return;
  }
  state.panels = 1;
  const [a, b] = v.split(',').map(Number);
  state.printW = landscape ? Math.max(a, b) : Math.min(a, b);
  state.printH = landscape ? Math.min(a, b) : Math.max(a, b);
}
```

Replace `applyOutputVisibility`:

```js
export function applyOutputVisibility() {
  const wp = state.output === 'wallpaper';
  const set = !wp && state.panels > 1;
  $('sizeField').hidden = wp;
  $('gapField').hidden = !set;
  $('bleedField').hidden = wp || set;      // a set takes no bleed
  $('wpPresetField').hidden = !wp;
  $('customDeviceField').hidden = !(wp && state.wpPreset === 'custom');
  $('orientField').hidden = wp;
  $('titleField').hidden = wp;
}
```

Replace `reframe`:

```js
function reframe() {
  applyPrintSize(); applyOutputVisibility();
  canvas.refitForSize(); markers.refreshOutOfFrame(); updateFrameFeasibility();
  stalePicture(); proof.scheduleAutoProof(); proof.refreshProofUI();
}
```

Replace `ensurePrintSize`:

```js
function ensurePrintSize(w, h, panels = 1, gap = 0) {
  if (!w || !h) return;
  if (panels > 1) {
    // a set restores from its own two fields, never as an odd single sheet
    $('size').value = `panels:${panels}`;
    state.panelGap = gap;
    segGap && segGap.reflect(String(gap));
    state.orientation = h === 17 ? 'landscape' : 'portrait';
    segOrient && segOrient.reflect(state.orientation);
    return;
  }
  const mn = Math.min(w, h), mx = Math.max(w, h);
  const fmt = (n) => (Number.isInteger(n) ? String(n) : String(Math.round(n * 100) / 100));
  const val = `${fmt(mn)},${fmt(mx)}`;
  const sel = $('size');
  if (![...sel.options].some((o) => o.value === val)) {
    const o = document.createElement('option');
    o.value = val; o.textContent = `${fmt(mn)} × ${fmt(mx)} in`;
    sel.appendChild(o);
  }
  sel.value = val;
  state.orientation = w > h ? 'landscape' : 'portrait';
  segOrient && segOrient.reflect(state.orientation);
}
```

In `applyPrefill`, change the call:

```js
    ensurePrintSize(p.print_w_in, p.print_h_in, p.panels || 1, p.panel_gap_in || 0);
```

In `restorePagePrefs`, directly after the `prefs.orient` line:

```js
  if ([0, 2, 4].includes(prefs.panelGap)) state.panelGap = prefs.panelGap;
```

and directly before its last line (`applyPrintSize(); applyOutputVisibility();`):

```js
  segGap && segGap.reflect(String(state.panelGap));
```

- [ ] **Step 5: `api.js`**

In `proof`, add two options to the destructured argument:

```js
                              output = 'print', wpPreset = '',
                              customDevice = null, panels = 1, panelGap = 0 } = {}) {
```

Change the `bleed` line and add two fields below it:

```js
    bleed: output === 'print' && panels === 1 && style.bleedIn ? style.bleedIn : undefined,
    // a set (2 or 3 panels): sent only for a set, so a single sheet's request is unchanged
    panels: panels > 1 ? panels : undefined,
    panel_gap: panels > 1 ? panelGap : undefined,
```

- [ ] **Step 6: `proof.js`**

In the `api.proof(...)` call, add the two values:

```js
        output: state.output, wpPreset: state.wpPreset, customDevice: state.customDevice,
        panels: state.panels, panelGap: state.panelGap });
```

Replace the last line of `sizeLabel`:

```js
  const sheet = `${state.printW}×${state.printH}`;
  return state.panels > 1 ? `${state.panels} panels (${sheet} hung)` : sheet;
```

In `acceptFinal`, replace from the `toast('Queuing final render…'` line to the end of the `try` block:

```js
  const isSet = state.output !== 'wallpaper' && state.panels > 1;
  const kind = isSet ? `${state.panels} panels` : fmt.toUpperCase();
  toast('Queuing final render…', 'working');
  try {
    const { job } = await api.submitFinal(state.session, fmt, state.embedSpec);
    const result = await jobs.track(job, {
      kind: 'final', label: `Final ${kind}`,
      runningMsg: 'Rendering the full-resolution final…',
      onState: (s) => toast(s === 'running' ? 'Rendering the full-resolution final…'
        : s === 'queued' ? 'Queued…' : s === 'error' ? 'Final render failed.' : '', 'working'),
    });
    if (result) {
      // a set arrives as one zip with a file for each panel
      const filename = await downloadFinal(result, isSet ? 'zip' : fmt);
      jobs.markDownloaded(job, filename);
      state.lastFinal = { url: result, fmt: isSet ? 'zip' : fmt };
      const da = $('downloadAgain'); if (da) da.hidden = false;
      toast(isSet ? `Final downloaded: a zip of ${state.panels} panel files.` : `Final ${kind} downloaded.`, 'ok');
    }
  } catch (e) { toast('Final failed: ' + e.message, 'error'); }
```

- [ ] **Step 7: `canvas.js`**

In `drawCrop`, directly after the "box + corner handles" block (after the `for` loop that draws the four handles):

```js
  // a set: show each gap strip, so the part a window set hides is plain while framing
  if (state.panels > 1) {
    const fw = x1 - x0, across = state.printH === 17 ? 22 : 17, g = state.panelGap;
    for (let k = 1; k < state.panels; k++) {
      const sx = x0 + fw * (k * (across + g) - g) / state.printW;
      const sw = fw * g / state.printW;
      if (sw >= 1) {
        ctx.fillStyle = 'rgba(236,232,224,0.85)';
        ctx.fillRect(sx, y0, sw, y1 - y0);
      }
      ctx.strokeStyle = stroke; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(sx, y0); ctx.lineTo(sx, y1); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(sx + sw, y0); ctx.lineTo(sx + sw, y1); ctx.stroke();
    }
  }
```

- [ ] **Step 8: `controls.js` and `app.js`**

In `controls.js`, replace the `help` and `keywords` of the `size` entry:

```js
    help: 'The paper size in inches, or a set of two or three 17 × 22 panels. Bigger sheets need a wider map crop to stay sharp.',
    keywords: ['size', 'dimensions', '17x22', '11x17', 'paper', 'panels', 'diptych', 'triptych'] },
```

Add one entry directly after the `size` entry:

```js
  { id: 'gap', path: 'panelGap', section: 'compose', panel: 'Page', label: 'Gap between panels',
    type: 'segmented', default: 2, affectsProof: true, geometry: true,
    visibleWhen: (s) => s.output !== 'wallpaper' && s.panels > 1,
    options: [{ value: 0, label: 'None' }, { value: 2, label: '2 in' }, { value: 4, label: '4 in' }],
    help: 'The space on the wall between two panels. None prints every part of the map. With 2 or 4 in the map runs on behind the gap, so lines stay straight and that strip is not printed.',
    keywords: ['gap', 'panels', 'frames', 'diptych', 'triptych'] },
```

In `app.js`, add `gap` to the jump map:

```js
const STATIC_CONTROL_TARGETS = {
  output: 'outputField', size: 'size', gap: 'gapField', orientation: 'orientField', bleed: 'bleed',
  title: 'titleInput', finalFormat: 'formatField', embedSpec: 'embedSpecChk',
};
```

and one line to `attachStaticHelp`, after the `sizeField` line:

```js
  H('gapField', controls.control('gap').help);
```

- [ ] **Step 9: `ui.js`**

In `updateSaveFileNote`, add a branch before the last `else`:

```js
  } else if (state.output !== 'wallpaper' && state.panels > 1) {
    el.textContent = `Each panel PNG in the zip is a save file for the whole set: the set reprints from any one of them, for as long as its terrain plate survives. Keep them — next year the set becomes Edition ${state.edition + 1}.`;
  } else {
```

`ui.js` imports `state` already. Call sites do not change.

- [ ] **Step 10: `social.js`**

At the top of the function that holds the `if (state.lastFinal) {` block shown in the file (the wall-art mockup staging), before its first `await`:

```js
    if (state.panels > 1) {
      toast('A set has no wall-art mockup yet. Choose one sheet for a mockup.', 'info');
      if (btn) btn.disabled = false;
      return;
    }
```

- [ ] **Step 11: `library.js`**

In `renderProvenance`, replace the `const size = …` line:

```js
  const dims = info.print_size_in && info.print_size_in[0] ? `${info.print_size_in[0]}×${info.print_size_in[1]} in` : '—';
  const isSet = (info.panels || 1) > 1;
  const size = isSet ? `${info.panels} panels, ${dims}` : dims;
  const panelRow = info.panel ? `<div class="provenance-row"><span>Panel</span><b>${info.panel.index} of ${info.panel.of}</b></div>` : '';
```

Insert `${panelRow}` directly after the "Print size" row in the template. Change the reprint button's text:

```js
      <button class="ghost" id="pvReprint" type="button" ${info.region_available ? '' : 'disabled'}>${isSet ? 'Reprint the set' : 'Reprint PNG'}</button>
```

`api.reprint` takes its file name from the server's `Content-Disposition`, so a set saves as `…_panels.zip` with no other change.

- [ ] **Step 12: Check, then drive the studio**

Run: `for f in store compose api proof canvas controls app ui social library; do node --check app/static/$f.js || echo FAIL $f; done`
Expected: no output.

Run: `.venv/bin/python -m pytest tests/test_static_registry.py -q`
Expected: all pass.

Cross-check each new `$('id')` against `index.html`: `gapField`, `gap`. Then drive the real studio (start the engine with `tecopa engine start`, open `http://127.0.0.1:8848/`):

1. Load `tests/fixtures/sample.gpx`. Choose "Two panels". The gap control appears, the bleed control is hidden, and the frame shows one gap strip.
2. Set the gap to "None". The strip becomes one line. Set it to "4 in". The strip is wider and the frame is wider.
3. Wait for the proof. Each panel has a keyline and a mark, and the gap is the wall tone.
4. `tecopa studio errors` shows no error.
5. Choose "17 × 22 in". The gap control is hidden and the bleed control is back.

Record what you saw in the commit message. Do not click "Accept" on a set here: the smoke test in task 13 renders one.

- [ ] **Step 13: Commit**

```bash
git commit -m "The studio frames, proofs and downloads a set of two or three panels" -- app/static tests/test_static_registry.py
```

---

### Task 9: Orders: a set in `order.toml` and in Prepare

**Goal:** `order.toml` takes `size = "two"` or `"three"`, a `gap` and a `sizes` list, and Prepare frames and builds the plate for the hung sheet.

**Files:**
- Modify: `app/order.py` (`parse_size`, new `parse_order_size`, `parse_gap`, `parse_sizes`, `Order`, `load`)
- Modify: `app/orderprep.py` (the state keys, `write_report`)
- Modify: `tests/test_order.py`, `tests/test_orderprep.py`

**Acceptance Criteria:**
- [ ] `size = "three"`, `orientation = "landscape"` and no `gap` give `print_in() == (70.0, 17.0)`. `"portrait"` gives `(55.0, 22.0)`.
- [ ] `gap = 1` and `size = "four"` raise `OrderError` that names the accepted values.
- [ ] `gap` is ignored for a single sheet, and a single-sheet order's `inputs_hash` is the same as before this change.
- [ ] Prepare of a set writes `panels` and `gap` to `state.json`, and the report reads `Print: 3 panels, 55 x 22 in hung, 2 in gap`.
- [ ] `sizes = ["11x17", "three"]` loads, and `sizes = ["big"]` raises `OrderError`.

**Verify:** `.venv/bin/python -m pytest tests/test_order.py tests/test_orderprep.py tests/test_orderplate.py -q` → all pass

**Steps:**

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_order.py`:

```python
def test_a_set_is_named_by_a_word():
    assert order.parse_order_size("11x17") == ((11.0, 17.0), 1)
    assert order.parse_order_size(" Two ") == ((17.0, 22.0), 2)
    assert order.parse_order_size("three") == ((17.0, 22.0), 3)
    with pytest.raises(order.OrderError, match='"two" or "three"'):
        order.parse_order_size("four")


def test_the_gap_is_zero_two_or_four():
    assert [order.parse_gap(g) for g in (0, 2, 4, 2.0)] == [0.0, 2.0, 4.0, 2.0]
    for bad in (1, "2", True, 3.5, None):
        with pytest.raises(order.OrderError, match="gap must be 0, 2 or 4"):
            order.parse_gap(bad)


def test_a_set_order_has_the_hung_sheet(tmp_path):
    d = _order(tmp_path, 'title = "Long walk"\nsize = "three"\norientation = "landscape"\n')
    o = order.load(d)
    assert (o.panels, o.gap) == (3, 2.0)
    assert o.print_in() == (70.0, 17.0)
    d2 = _order(tmp_path / "b", 'title = "Long walk"\nsize = "three"\ngap = 4\n')
    assert order.load(d2).print_in() == (59.0, 22.0)        # portrait is the default
    d3 = _order(tmp_path / "c", 'title = "Long walk"\nsize = "two"\ngap = 0\n')
    assert order.load(d3).print_in() == (34.0, 22.0)


def test_a_wrong_gap_stops_the_order(tmp_path):
    d = _order(tmp_path, 'title = "Long walk"\nsize = "two"\ngap = 1\n')
    with pytest.raises(order.OrderError, match="gap must be 0, 2 or 4"):
        order.load(d)


def test_the_gap_of_a_single_sheet_is_ignored(tmp_path):
    plain = order.load(_order(tmp_path, 'title = "T"\nsize = "11x17"\n'))
    gapped = order.load(_order(tmp_path / "b", 'title = "T"\nsize = "11x17"\ngap = 4\n'))
    assert (gapped.panels, gapped.gap) == (1, 0.0)
    assert gapped.print_in() == plain.print_in() == (11.0, 17.0)


def test_the_hash_of_a_single_sheet_order_did_not_change(tmp_path):
    import hashlib
    o = order.load(_order(tmp_path, 'title = "T"\nsize = "11x17"\n'))
    h = hashlib.sha256()
    for data, name in o.payloads():
        h.update(name.encode()); h.update(hashlib.sha256(data).digest())
    h.update(repr((o.size, o.orientation)).encode())
    assert o.inputs_hash() == h.hexdigest()


def test_the_hash_of_a_set_follows_the_count_and_the_gap(tmp_path):
    def digest(name, toml):
        return order.load(_order(tmp_path / name, toml)).inputs_hash()
    two = digest("a", 'title = "T"\nsize = "two"\n')
    assert two != digest("b", 'title = "T"\nsize = "three"\n')
    assert two != digest("c", 'title = "T"\nsize = "two"\ngap = 4\n')
    assert two != digest("d", 'title = "T"\nsize = "17x22"\n')


def test_the_sizes_list_is_checked(tmp_path):
    o = order.load(_order(tmp_path, 'title = "T"\nsizes = ["11x17", "three"]\n'))
    assert o.sizes == ("11x17", "three")
    assert order.load(_order(tmp_path / "b", 'title = "T"\n')).sizes == ()
    for k, bad in enumerate(('sizes = ["big"]', 'sizes = "three"', 'sizes = []')):
        with pytest.raises(order.OrderError, match="sizes must be a list"):
            order.load(_order(tmp_path / f"bad{k}", f'title = "T"\n{bad}\n'))
```

`_order(tmp_path, toml, files)` in this file makes `<path>/2026-10-001-smith` with `parents=True`, so `tmp_path / "b"` works as it is.

Append to `tests/test_orderprep.py`:

```python
def test_a_set_order_prepares_for_the_hung_sheet(tmp_path, tools):
    d = _make_order(tmp_path, bbox=WIDE, size="three")
    state = op.prepare(str(d), tools, log=lambda s: None)
    assert state["print_in"] == [55.0, 22.0]
    assert (state["panels"], state["gap"]) == (3, 2.0)
    frame = state["frame"]
    assert abs((frame[2] - frame[0]) / (frame[3] - frame[1]) - 55 / 22) < 1e-6
    report = (d / "work" / "report.txt").read_text()
    assert "Print: 3 panels, 55 x 22 in hung, 2 in gap" in report


def test_a_single_sheet_report_line_is_as_before(tmp_path, tools):
    d = _make_order(tmp_path)
    state = op.prepare(str(d), tools, log=lambda s: None)
    assert (state["panels"], state["gap"]) == (1, 0.0)
    assert "Print: 12 x 18 in\n" in (d / "work" / "report.txt").read_text()
```

- [ ] **Step 2: Run them and see them fail**

Run: `.venv/bin/python -m pytest tests/test_order.py tests/test_orderprep.py -q`
Expected: FAIL, `module 'app.order' has no attribute 'parse_order_size'`.

- [ ] **Step 3: Change `app/order.py`**

With the imports:

```python
from app import panels as panel_geo
```

With the constants:

```python
SET_SIZES = {"two": 2, "three": 3}     # a set of 17 x 22 in panels (spec, 2026-10-11)
DEFAULT_GAP = 2.0                      # inches between two panels on the wall
SIZE_KEYS = ("11x17", "17x22", "two", "three")     # what a preview can offer
```

In `parse_size`, replace the first error:

```python
        raise OrderError(f'size {text!r} is not like 11x17, and is not "two" or "three"')
```

Below `parse_size`:

```python
def parse_order_size(text) -> tuple:
    """'11x17' -> ((11.0, 17.0), 1). 'two' -> ((17.0, 22.0), 2): a set, by its panel."""
    key = str(text).strip().lower()
    if key in SET_SIZES:
        return ((panel_geo.PANEL_SHORT_IN, panel_geo.PANEL_LONG_IN), SET_SIZES[key])
    return (parse_size(text), 1)


def parse_gap(value) -> float:
    """The gap of a set, in inches: 0, 2 or 4."""
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or float(value) not in panel_geo.GAPS_IN):
        raise OrderError(f"gap must be 0, 2 or 4 (inches), not {value!r}")
    return float(value)


def parse_sizes(value) -> tuple:
    """The sizes a preview must offer, from order.toml. () means the fit rule decides."""
    if value is None:
        return ()
    if (not isinstance(value, list) or not value
            or any(not isinstance(v, str) or v not in SIZE_KEYS for v in value)):
        raise OrderError(f"sizes must be a list of {', '.join(SIZE_KEYS)}, not {value!r}")
    return tuple(value)
```

In `Order`, add three fields after `notes` (defaults keep every existing caller):

```python
    notes: str
    panels: int = 1          # 2 or 3: a set of 17 x 22 in panels
    gap: float = 0.0         # inches between two panels; 0.0 for a single sheet
    sizes: tuple = ()        # the preview's override list
```

Replace `print_in` and the last line of `inputs_hash`:

```python
    def print_in(self) -> tuple:
        """(width, height) in inches as printed. A set gives its hung sheet, gaps
        included: landscape is panels 22 in across, portrait is 17 in across."""
        short, long_ = self.size
        landscape = self.orientation == "landscape"
        if self.panels > 1:
            across = long_ if landscape else short
            return (self.panels * across + (self.panels - 1) * self.gap,
                    short if landscape else long_)
        return (long_, short) if landscape else (short, long_)
```

```python
        h.update(repr((self.size, self.orientation)).encode())
        if self.panels > 1:        # a single sheet's hash is what it always was
            h.update(repr((self.panels, self.gap)).encode())
        return h.hexdigest()
```

Check `print_in` for a single sheet against the old body before you replace it: portrait must still return `(short, long_)`.

In `load`, replace the `return Order(...)`:

```python
    size, panels = parse_order_size(cfg.get("size", DEFAULT_SIZE))
    gap = parse_gap(cfg.get("gap", DEFAULT_GAP)) if panels > 1 else 0.0
    return Order(dir=folder, title=title,
                 subtitle=str(cfg.get("subtitle", "")).strip(),
                 size=size, orientation=orientation, notes=str(cfg.get("notes", "")),
                 panels=panels, gap=gap, sizes=parse_sizes(cfg.get("sizes")))
```

- [ ] **Step 4: Change `app/orderprep.py`**

In `prepare`, in the `write_state(order, {...})` call, add two keys next to `"print_in"`:

```python
        "panels": order.panels, "gap": order.gap,
```

In `write_report`, replace the `Print:` line of `lines`:

```python
             _print_line(state),
```

and add above `write_report`:

```python
def _print_line(state) -> str:
    size = f"{state['print_in'][0]:g} x {state['print_in'][1]:g} in"
    if state.get("panels", 1) > 1:
        return f"Print: {state['panels']} panels, {size} hung, {state.get('gap', 0):g} in gap"
    return f"Print: {size}"
```

The early return in `prepare` for a plate that is current calls `write_report` with the stored state. `state.get` keeps a state file from before this change readable.

- [ ] **Step 5: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_order.py tests/test_orderprep.py tests/test_orderplate.py -q`
Expected: all pass.

- [ ] **Step 6: Run the fast suite, then commit**

Run: `.venv/bin/python -m pytest -n auto -m "not slow" -q`

```bash
git commit -m "An order can be a set: size two or three, a gap, and Prepare frames the hung sheet" -- app/order.py app/orderprep.py tests/test_order.py tests/test_orderprep.py
```

---

### Task 10: The preview: candidates and the fit rule

**Goal:** `app/orderpreview.py` turns the tracks into one entry for each size: its orientation, its frame, whether it is offered, and why not.

**Files:**
- Create: `app/orderpreview.py`
- Modify: `app/orderplate.py` (new `track_shares`)
- Test: `tests/test_orderpreview.py`

**Acceptance Criteria:**
- [ ] `candidates("three")` gives the portrait sheet 55 × 22 and the landscape sheet 70 × 17, both at a 2 in gap.
- [ ] A compact loop offers the two single sheets and not "three", and the refusal names the width share.
- [ ] A thin east-west route offers "three" in landscape.
- [ ] Two short tracks far apart do not offer "three": the report says which panel holds no track. A straight two-point track across the sheet is not refused (the rule follows the line, not its vertices).
- [ ] `sizes = ["three"]` offers "three" with a warning and refuses the other three sizes.
- [ ] A `PlateError` from the 2× rule refuses that size with the error's own text, and `sizes` does not override it.
- [ ] A route end that lies behind a gap strip is listed on the entry as `ends_behind`, by gap number.

**Verify:** `.venv/bin/python -m pytest tests/test_orderpreview.py tests/test_orderplate.py -q` → all pass

**Steps:**

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_orderpreview.py
import numpy as np
import pytest

from app import orderpreview as opv
from app.orderplate import PlateError, nestled_frame, track_shares

KM = 1000.0


def _line(x0, y0, x1, y1):
    return np.array([[x0 * KM, y0 * KM], [x1 * KM, y1 * KM]])


def _bounds(tracks):
    pts = np.concatenate(tracks)
    return (pts[:, 0].min(), pts[:, 1].min(), pts[:, 0].max(), pts[:, 1].max())


def _plan(tracks, **kw):
    return {e["key"]: e for e in opv.plan_sizes(_bounds(tracks), tracks, **kw)}


def test_the_shares_of_a_frame():
    assert track_shares((0, 0, 30, 10), (0, 0, 100, 50)) == (0.3, 0.2)


def test_the_two_orientations_of_each_size():
    three = {c.orientation: c for c in opv.candidates("three")}
    assert three["portrait"].print_in == (55.0, 22.0) and three["landscape"].print_in == (70.0, 17.0)
    assert three["portrait"].gap == three["landscape"].gap == 2.0 and three["portrait"].panels == 3
    small = {c.orientation: c for c in opv.candidates("11x17")}
    assert small["portrait"].print_in == (11.0, 17.0) and small["landscape"].print_in == (17.0, 11.0)
    assert small["portrait"].gap == 0.0 and small["portrait"].panels == 1


def test_a_compact_loop_gets_the_single_sheets_and_no_three_panel_set():
    loop = [np.array([[0, 0], [10 * KM, 0], [10 * KM, 10 * KM], [0, 10 * KM], [0, 0]], float)]
    plan = _plan(loop)
    assert plan["11x17"]["offered"] and plan["17x22"]["offered"]
    assert not plan["three"]["offered"]
    assert plan["three"]["why"] == "the tracks span 24% of the sheet's width, under 30%"
    # two panels 17 in across are 36 x 22 in: the loop spans 37 % of that width
    assert plan["two"]["offered"] and plan["two"]["width_share"] == 0.367


def test_a_thin_east_west_route_gets_three_panels_in_landscape():
    plan = _plan([_line(0, 0, 200, 5)])
    three = plan["three"]
    assert three["offered"], three["why"]
    assert three["orientation"] == "landscape" and three["print_in"] == [70.0, 17.0]
    assert three["width_share"] == 0.6
    assert plan["17x22"]["orientation"] == "landscape"


def test_a_north_south_route_gets_no_set():
    plan = _plan([_line(0, 0, 5, 200)])
    assert plan["17x22"]["orientation"] == "portrait"
    assert not plan["two"]["offered"] and not plan["three"]["offered"]


def test_a_panel_with_no_track_refuses_the_set():
    ends = [_line(0, 0, 8, 6), _line(192, 0, 200, 6)]       # two day walks, 190 km apart
    plan = _plan(ends)
    assert not plan["three"]["offered"]
    assert plan["three"]["why"] == "panel 2 holds no track"
    assert plan["two"]["offered"], plan["two"]["why"]


def test_the_rule_follows_the_line_and_not_its_vertices():
    cand = [c for c in opv.candidates("three") if c.orientation == "landscape"][0]
    track = [_line(0, 0, 200, 5)]                             # two vertices, at the ends
    frame = nestled_frame(_bounds(track), cand.aspect)
    assert opv.panels_with_track(track, frame, cand) == [True, True, True]


def test_a_route_end_behind_a_gap_is_named_by_its_gap():
    cand = [c for c in opv.candidates("two") if c.orientation == "landscape"][0]   # 46 x 17 in
    frame = (0.0, 0.0, 46 * KM, 17 * KM)                      # 1 km of ground for each inch
    ends_in_the_gap = [_line(5, 8, 23, 8)]                    # it stops at 23 in: gap 1 is 22-24
    assert opv.gaps_hiding_ends(ends_in_the_gap, frame, cand) == [1]
    assert opv.gaps_hiding_ends([_line(5, 8, 40, 8)], frame, cand) == []    # it only crosses
    assert opv.gaps_hiding_ends([_line(5, 30, 23, 30)], frame, cand) == []  # outside the frame
    cut = opv.Candidate("two", 2, "landscape", (44.0, 17.0), 0.0)
    assert opv.gaps_hiding_ends(ends_in_the_gap, (0.0, 0.0, 44 * KM, 17 * KM), cut) == []
    entry = opv.judge(cand, frame, (5 * KM, 8 * KM, 23 * KM, 8 * KM), ends_in_the_gap)
    assert entry["ends_behind"] == [1]


def test_the_sizes_list_overrides_the_fit_rule_with_a_warning():
    loop = [np.array([[0, 0], [10 * KM, 0], [10 * KM, 10 * KM], [0, 10 * KM], [0, 0]], float)]
    plan = _plan(loop, forced=("three",))
    assert plan["three"]["offered"] and "of the sheet's width" in plan["three"]["warning"]
    for key in ("11x17", "17x22", "two"):
        assert not plan[key]["offered"]
        assert plan[key]["why"] == "it is not in the sizes list of order.toml"


def test_terrain_too_coarse_refuses_a_size_and_the_list_cannot_force_it():
    def widen(cand, frame):
        if cand.key == "three":
            raise PlateError("The terrain data is still too coarse for this print size.")
        return frame
    plan = _plan([_line(0, 0, 200, 5)], widen=widen, forced=("three", "17x22"))
    assert not plan["three"]["offered"]
    assert plan["three"]["why"] == "The terrain data is still too coarse for this print size."
    assert plan["17x22"]["offered"]


def test_a_widened_frame_is_judged_as_widened():
    def widen(cand, frame):                                   # the 2x rule doubled the frame
        cx, cy = (frame[0] + frame[2]) / 2, (frame[1] + frame[3]) / 2
        w, h = frame[2] - frame[0], frame[3] - frame[1]
        return (cx - w, cy - h, cx + w, cy + h)
    plan = _plan([_line(0, 0, 200, 5)], widen=widen)
    assert plan["three"]["width_share"] == 0.3 and plan["three"]["offered"]
    plan = _plan([_line(0, 0, 200, 5)], widen=lambda c, f: widen(c, widen(c, f)))
    assert not plan["three"]["offered"]                      # 15 % of the width
```

- [ ] **Step 2: Run them and see them fail**

Run: `.venv/bin/python -m pytest tests/test_orderpreview.py -q`
Expected: FAIL, `cannot import name 'orderpreview'`.

- [ ] **Step 3: Add `track_shares` to `app/orderplate.py`**, directly below `track_fill`:

```python
def track_shares(track_bounds_m, frame) -> tuple:
    """(width share, height share): how much of the frame the tracks' box spans on
    each side. track_fill is the larger of the two."""
    tw = track_bounds_m[2] - track_bounds_m[0]
    th = track_bounds_m[3] - track_bounds_m[1]
    return (tw / (frame[2] - frame[0]), th / (frame[3] - frame[1]))
```

- [ ] **Step 4: Write `app/orderpreview.py`**

```python
# app/orderpreview.py
"""The size preview of an order: frame the tracks at every size, offer the sizes that
suit them, and show each one on a coarse plate.

Spec: docs/superpowers/specs/2026-10-11-print-sizes-panel-sets-and-size-preview-design.md,
section 5. This file never imports app.main, and it imports the renderer only inside
render_maps, so the framing can be tested with no DEM."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from app.order import ORIENTATIONS, SIZE_KEYS, parse_order_size
from app.orderplate import PlateError, nestled_frame, track_shares

SET_MIN_FILL = 0.30        # a set is offered when the tracks span this share of its width
PREVIEW_GAP_IN = 2.0       # every set is framed and shown at this gap


@dataclass(frozen=True)
class Candidate:
    key: str               # "11x17", "17x22", "two" or "three"
    panels: int
    orientation: str       # "portrait" or "landscape"
    print_in: tuple        # (width, height) in inches: for a set, the hung sheet
    gap: float

    @property
    def aspect(self) -> float:
        return self.print_in[0] / self.print_in[1]


def candidates(key) -> list:
    """The two orientations of one size. Landscape on a set is panels 22 in across."""
    (short, long_), panels = parse_order_size(key)
    gap = PREVIEW_GAP_IN if panels > 1 else 0.0
    out = []
    for orientation in ORIENTATIONS:
        landscape = orientation == "landscape"
        if panels > 1:
            across = long_ if landscape else short
            size = (panels * across + (panels - 1) * gap, short if landscape else long_)
        else:
            size = (long_, short) if landscape else (short, long_)
        out.append(Candidate(key, panels, orientation, size, gap))
    return out


def choose(cands, bounds_m) -> Candidate:
    """The orientation with less wasted ground: the one whose nestled frame the
    tracks fill more on their weaker side. A tie keeps the first, portrait."""
    return max(cands, key=lambda c: min(track_shares(bounds_m, nestled_frame(bounds_m, c.aspect))))


def _samples(tracks_m, step) -> np.ndarray:
    """Points along every track, at most `step` metres apart, so a long straight
    leg counts on every panel it crosses."""
    out = []
    for t in tracks_m:
        t = np.asarray(t, float).reshape(-1, 2)
        if len(t) < 2:
            out.append(t)
            continue
        dist = np.concatenate([[0.0], np.cumsum(np.hypot(*np.diff(t, axis=0).T))])
        at = np.linspace(0.0, dist[-1], max(2, int(dist[-1] / step) + 1))
        out.append(np.column_stack([np.interp(at, dist, t[:, 0]), np.interp(at, dist, t[:, 1])]))
    return np.concatenate(out) if out else np.empty((0, 2))


def panels_with_track(tracks_m, frame, cand) -> list:
    """For each panel of a set, True when some part of a track lies on it."""
    w_in = cand.print_in[0]
    pts = _samples(tracks_m, (frame[2] - frame[0]) / 500.0)
    xs = (pts[:, 0] - frame[0]) / (frame[2] - frame[0]) * w_in
    ys = (pts[:, 1] - frame[1]) / (frame[3] - frame[1])
    inside = (ys >= 0.0) & (ys <= 1.0)
    across = (w_in - (cand.panels - 1) * cand.gap) / cand.panels
    step = across + cand.gap
    return [bool(np.any(inside & (xs >= k * step) & (xs <= k * step + across)))
            for k in range(cand.panels)]


def gaps_hiding_ends(tracks_m, frame, cand) -> list:
    """The gaps of a window set, numbered from 1, that hide a route end: the first
    or the last point of a track. A route end is tied to the ground, so only the
    frame can move it. A cut set and a single sheet hide nothing."""
    if cand.panels == 1 or not cand.gap:
        return []
    w_in = cand.print_in[0]
    step = (w_in - (cand.panels - 1) * cand.gap) / cand.panels + cand.gap
    hidden = set()
    for t in tracks_m:
        t = np.asarray(t, float).reshape(-1, 2)
        for x, y in ((t[0], t[-1]) if len(t) else ()):
            if not frame[1] <= y <= frame[3]:
                continue
            at = (x - frame[0]) / (frame[2] - frame[0]) * w_in
            hidden.update(k for k in range(1, cand.panels) if k * step - cand.gap < at < k * step)
    return sorted(hidden)


def judge(cand, frame, bounds_m, tracks_m) -> dict:
    """One size's entry: its frame, its shares, and the fit rule's answer."""
    w_share, h_share = track_shares(bounds_m, frame)
    entry = {"key": cand.key, "panels": cand.panels, "orientation": cand.orientation,
             "print_in": [float(v) for v in cand.print_in], "gap": cand.gap,
             "frame": [float(v) for v in frame],
             "fill": round(max(w_share, h_share), 3), "width_share": round(w_share, 3),
             "offered": True, "why": "", "warning": "", "blocked": False,
             "ends_behind": gaps_hiding_ends(tracks_m, frame, cand)}
    if cand.panels > 1:
        empty = [str(k + 1) for k, has in enumerate(panels_with_track(tracks_m, frame, cand))
                 if not has]
        if round(w_share, 3) < SET_MIN_FILL:
            entry.update(offered=False, why=f"the tracks span {w_share:.0%} of the sheet's "
                                            f"width, under {SET_MIN_FILL:.0%}")
        elif empty:
            entry.update(offered=False, why=f"panel {' and '.join(empty)} holds no track")
    return entry


def plan_sizes(bounds_m, tracks_m, widen=None, forced=()) -> list:
    """One entry for each size, in menu order.

    `widen(cand, frame)` returns the frame the real print would get under the 2x
    rule, or raises PlateError when the terrain cannot hold the size. `forced` is
    the `sizes` list of order.toml: it overrides the fit rule, never the terrain."""
    entries = []
    for key in SIZE_KEYS:
        cand = choose(candidates(key), bounds_m)
        frame = nestled_frame(bounds_m, cand.aspect)
        try:
            if widen is not None:
                frame = widen(cand, frame)
            entry = judge(cand, frame, bounds_m, tracks_m)
        except PlateError as ex:
            entry = judge(cand, frame, bounds_m, tracks_m)
            entry.update(offered=False, why=str(ex), blocked=True)
        if forced and not entry["blocked"]:
            if key in forced:
                entry.update(offered=True, warning=entry["why"], why="")
            else:
                entry.update(offered=False, why="it is not in the sizes list of order.toml")
        entries.append(entry)
    return entries
```

- [ ] **Step 5: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_orderpreview.py tests/test_orderplate.py -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add app/orderpreview.py tests/test_orderpreview.py
git commit -m "The preview frames every size and offers a set only when the route suits it" -- app/orderpreview.py app/orderplate.py tests/test_orderpreview.py
```

---

### Task 11: The preview: the coarse plate and the maps

**Goal:** `orderpreview.preview()` builds one coarse plate under `work/preview/`, renders each offered size at screen size with the word PREVIEW, and writes `work/preview/preview.json`.

**Files:**
- Modify: `app/orderprep.py` (new `cache_env`, `_build` takes `root` and `rid`)
- Modify: `app/orderpreview.py`
- Modify: `tests/conftest.py` (`_SLOW_MODULES`)
- Test: `tests/test_orderpreview.py` (stub subprocesses), `tests/test_orderpreview_render.py` (slow, DEM-backed)

**Acceptance Criteria:**
- [ ] `preview()` builds a plate with the id `preview_<slug>` under `work/preview/plate/`, and the order's own `work/plate/` is not changed.
- [ ] The preview plate's grid follows the preview's pixels: it is 10 m or coarser for the test order.
- [ ] `render_maps` writes one PNG for each offered size: a single sheet is 1,600 px on its long side, and a set is 50 dpi (3,500 × 850 px for three panels at 70 × 17 in).
- [ ] A set's map has the wall tone in each gap strip.
- [ ] `work/preview/preview.json` holds `epsg`, `plate`, `sizes` and `seconds`.
- [ ] A second `prepare` after a `preview` still says "Plate is current".
- [ ] Prepare of a window set warns when a route end is behind a gap: "A route end is behind gap 1."

**Verify:** `.venv/bin/python -m pytest tests/test_orderpreview.py tests/test_orderprep.py tests/test_orderpreview_render.py -q` → all pass

**Steps:**

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_orderpreview.py`:

```python
import json
import os

from app import orderprep as op
from tests.test_orderprep import WIDE, _make_order, _snapshot, tools  # noqa: F401


def _fake_render(calls):
    def render(entries, tracks, plate_dir, title, out_dir):
        calls.append({"plate_dir": plate_dir, "title": title, "tracks": len(tracks),
                      "keys": [e["key"] for e in entries if e["offered"]]})
        for e in entries:
            if e["offered"]:
                e["image"], e["dpi"] = os.path.join(out_dir, e["key"] + ".png"), opv.preview_dpi(e)
    return render


def _preview(d, tools, calls=None, pdfs=None):
    calls = [] if calls is None else calls
    pdfs = [] if pdfs is None else pdfs
    return opv.preview(str(d), tools, log=lambda s: None, render=_fake_render(calls),
                       write_pdf=lambda path, entries, names, title: pdfs.append(path))


def test_the_dpi_of_a_preview_map():
    assert opv.preview_dpi({"panels": 1, "print_in": [17.0, 22.0]}) == pytest.approx(1600 / 22)
    assert opv.preview_dpi({"panels": 1, "print_in": [17.0, 11.0]}) == pytest.approx(1600 / 17)
    assert opv.preview_dpi({"panels": 3, "print_in": [70.0, 17.0]}) == 50.0


def test_the_preview_plate_holds_every_offered_frame():
    entries = [{"offered": True, "frame": [0, 0, 10, 10], "panels": 1, "print_in": [17.0, 22.0]},
               {"offered": True, "frame": [-5, 2, 30, 8], "panels": 3, "print_in": [70.0, 17.0]},
               {"offered": False, "frame": [-99, -99, 99, 99], "panels": 2, "print_in": [46.0, 17.0]}]
    assert opv.union_frame(entries) == (-5, 0, 30, 10)
    # the finest ground per pixel that any offered map needs
    assert opv.preview_need_m(entries) == pytest.approx(min(10 / 17 / (1600 / 22), 35 / 70 / 50.0))


def test_preview_builds_one_coarse_plate_beside_the_orders_own(tmp_path, tools):
    d = _make_order(tmp_path, bbox=WIDE, size="11x17")
    calls, pdfs = [], []
    state = _preview(d, tools, calls, pdfs)
    plate = state["plate"]
    assert plate["id"] == "preview_2026_10_001_smith" and plate["kind"] == "built"
    assert plate["root"] == str(d / "work" / "preview" / "plate")
    assert os.path.isfile(d / "work" / "preview" / "plate" / plate["id"] / "region.json")
    assert plate["grid_m"] >= 10.0                           # the preview's pixels, not a print's
    assert not (d / "work" / "plate").exists()               # the order's own plate is not built
    assert [e["key"] for e in state["sizes"]] == ["11x17", "17x22", "two", "three"]
    assert calls[0]["plate_dir"] == os.path.join(plate["root"], plate["id"])
    assert calls[0]["keys"] == [e["key"] for e in state["sizes"] if e["offered"]]
    assert calls[0]["tracks"] == 1 and calls[0]["title"] == "Smith home ground"
    saved = json.loads((d / "work" / "preview" / "preview.json").read_text())
    assert saved["epsg"] == state["epsg"] and saved["plate"] == plate
    assert len(saved["sizes"]) == 4 and saved["seconds"] >= 0
    assert pdfs == [str(d / "out" / "preview" / "smith_home_ground-preview.pdf")]


def test_a_preview_does_not_touch_a_prepared_order(tmp_path, tools):
    d = _make_order(tmp_path, bbox=WIDE, size="11x17")
    op.prepare(str(d), tools, log=lambda s: None)
    before = _snapshot(d / "work" / "plate")
    state_before = (d / "work" / "state.json").read_text()
    _preview(d, tools)
    assert _snapshot(d / "work" / "plate") == before
    assert (d / "work" / "state.json").read_text() == state_before
    lines = []
    op.prepare(str(d), tools, log=lines.append)
    assert any("Plate is current" in l for l in lines)


def test_a_preview_can_run_again(tmp_path, tools):
    d = _make_order(tmp_path, bbox=WIDE, size="11x17")
    first = _preview(d, tools)
    second = _preview(d, tools)
    assert second["plate"]["id"] == first["plate"]["id"]
    assert [e["frame"] for e in second["sizes"]] == [e["frame"] for e in first["sizes"]]


def test_a_folder_with_no_track_stops_the_preview(tmp_path, tools):
    d = _make_order(tmp_path, bbox=WIDE)
    (d / "in" / "trip.gpx").write_text("<gpx></gpx>")
    with pytest.raises(opv.OrderError, match="no track points"):
        _preview(d, tools)
```

If `slugify("Smith home ground")` in `app/regionbuild.py` gives another spelling than `smith_home_ground`, use what it gives. Read `slugify` first.

```python
# tests/test_orderpreview_render.py
import json
import os

import numpy as np
from PIL import Image

from app import orderpreview as opv
from app import panels
from app.ingest import Track
from tests.conftest import synthetic_region

REGION_DIR = synthetic_region("lassen_ca")


def _tracks():
    b = json.load(open(os.path.join(REGION_DIR, "region.json")))["bounds"]
    cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
    coords = np.array([[cx - 15000.0, cy - 2000.0], [cx, cy + 2000.0], [cx + 15000.0, cy - 2000.0]])
    return [Track("t-0", coords, "2024-06-01")]


def test_each_offered_size_is_drawn_at_screen_size_with_its_gaps(tmp_path):
    tracks = _tracks()
    pts = tracks[0].coords
    bounds = (pts[:, 0].min(), pts[:, 1].min(), pts[:, 0].max(), pts[:, 1].max())
    entries = opv.plan_sizes(bounds, [t.coords for t in tracks])
    by_key = {e["key"]: e for e in entries}
    assert by_key["three"]["offered"] and by_key["three"]["orientation"] == "landscape"
    opv.render_maps(entries, tracks, REGION_DIR, "Lassen walk", str(tmp_path))
    for e in entries:
        if not e["offered"]:
            assert "image" not in e
            continue
        img = Image.open(e["image"])
        w_in, h_in = e["print_in"]
        if e["panels"] == 1:
            assert max(img.size) == 1600
        else:
            assert img.size == (round(w_in * 50), round(h_in * 50))
        assert abs(img.size[0] / img.size[1] - w_in / h_in) < 0.01
    three = np.asarray(Image.open(by_key["three"]["image"]).convert("RGB"))
    assert three.shape == (850, 3500, 3)
    assert (three[:, 1100:1200] == panels.WALL_TONE).all()      # 22 in, then a 2 in strip
    assert not (three[:, 1000:1100] == panels.WALL_TONE).all()
    plain = np.asarray(Image.open(by_key["17x22"]["image"]).convert("RGB"))
    assert len(np.unique(plain.reshape(-1, 3), axis=0)) > 500   # a real picture, not a flat fill
```

Add `"test_orderpreview_render"` to `_SLOW_MODULES` in `tests/conftest.py`.

- [ ] **Step 2: Run them and see them fail**

Run: `.venv/bin/python -m pytest tests/test_orderpreview.py -q`
Expected: FAIL, `module 'app.orderpreview' has no attribute 'preview'`.

- [ ] **Step 3: Refactor `app/orderprep.py`**

Add `cache_env` above `prepare`. Move the lines of `prepare` that make `cache`, `cache_dir` and `env` into it, with their comments, unchanged:

```python
def cache_env() -> tuple:
    """(env, cache_dir) for a prep subprocess: the HyRiver caches under the orders
    root, and the folder the subprocess runs in. Prepare and the preview share it."""
    # absolute: a relative TECOPA_ORDERS_DIR would resolve against the
    # subprocess's cwd (the repo root), not ours
    cache = os.path.abspath(cache_path())
    cache_dir = os.path.dirname(cache)
    os.makedirs(cache_dir, exist_ok=True)
    # async_retriever's own request cache (py3dep) follows HYRIVER_CACHE_NAME
    # above; pygeoogc's separate HTTP cache (pynhd/pygeohydro's NHD and NLCD
    # REST calls) defaults under the repo's own cache/ too, and needs its own
    # env var to move (.venv-prep/.../pygeoogc/utils.py, HYRIVER_CACHE_NAME_HTTP).
    env = dict(os.environ, HYRIVER_CACHE_NAME=cache,
               HYRIVER_CACHE_NAME_HTTP=os.path.join(cache_dir, "http_cache.sqlite"))
    # pygeoogc.core.ArcGISRESTful (pynhd's NHD queries) writes a retry log to a
    # hardcoded "cache/failed_ids*.txt", relative to the process's cwd, with no
    # env override at all (docs/changing-things.md, Run an order). _build runs the
    # prep subprocess with its cwd here instead of the repo root, so that write
    # lands beside the shared cache too; pre-create the folder so a retry never
    # meets a missing directory.
    os.makedirs(os.path.join(cache_dir, "cache"), exist_ok=True)
    return env, cache_dir
```

In `prepare`, replace those moved lines with one line:

```python
        env, cache_dir = cache_env()
```

Change `_build` so it can build beside the order's own plate. New signature and first lines:

```python
def _build(order, tools, frame, epsg, grid, env, log, cwd=None, root=None, rid=None):
    """Build a plate. By default it is the order's own, under work/plate/<order id>/.
    `root` and `rid` name another place and id: the preview's coarse plate.
    (Keep the rest of the existing docstring.)"""
    rid = rid or order.id
    root = root or order.plate_root
```

In the body of `_build`, replace every `order.plate_root` with `root`. There are four: `"out_root"` in `params`, the `os.makedirs`, the `shutil.rmtree`, the `regions_root=` argument of `run_build`, and `"root"` in the `plate` dict. `order.id` is already read through `rid`. Leave `order.work_dir` (the build log) and `order.title` as they are.

Run: `.venv/bin/python -m pytest tests/test_orderprep.py -q`
Expected: all pass. This step changes no behaviour.

- [ ] **Step 4: Add the preview to `app/orderpreview.py`**

Replace the import block at the top of the file:

```python
from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import dataclass

import numpy as np

from app import panels as panel_geo
from app.geo import RegionGeo
from app.ingest import load_tracks, lonlat_extent
from app.order import (ORIENTATIONS, SIZE_KEYS, OrderError, load, orders_root,
                       parse_order_size, refuse_inside_repo)
from app.orderplate import (ALBERS_EPSG, MAX_UPSAMPLE, PLATE_PAD_M, PlateError, choose_grid,
                            conus_covered, nestled_frame, order_epsg, plate_bounds,
                            project_bbox, to_lonlat_bbox, track_shares)
from app.regionbuild import slugify
from app.spec import CompositionSpec
```

Append to the file:

```python
PREVIEW_SINGLE_PX = 1600   # the long side of a single sheet's map
PREVIEW_SET_DPI = 50.0     # a set: 1,100 px along a panel's long side
# the look of a new poster in the studio (the defaults in app/static/store.js)
PREVIEW_LOOK = dict(soft_light=0.35, haze_strength=0.15, water_depth=0.5,
                    label_place="smart", track_weave=True)


def preview_dpi(entry) -> float:
    if entry["panels"] > 1:
        return PREVIEW_SET_DPI
    return PREVIEW_SINGLE_PX / max(entry["print_in"])


def union_frame(entries) -> tuple:
    """The box that holds every offered frame."""
    frames = [e["frame"] for e in entries if e["offered"]]
    return (min(f[0] for f in frames), min(f[1] for f in frames),
            max(f[2] for f in frames), max(f[3] for f in frames))


def preview_need_m(entries) -> float:
    """Metres of ground per pixel of the finest preview map."""
    return min((e["frame"][2] - e["frame"][0]) / (e["print_in"][0] * preview_dpi(e))
               for e in entries if e["offered"])


def preview_epsg(tracks_lonlat) -> int:
    """One projection for every size: Albers when any size's frame needs it, else
    the tracks' own UTM zone."""
    codes = [order_epsg(tracks_lonlat, c.aspect) for key in SIZE_KEYS for c in candidates(key)]
    return ALBERS_EPSG if ALBERS_EPSG in codes else codes[0]


def load_tracks_m(payloads, epsg) -> list:
    """Every track of the order in the preview's projection. A file that does not
    parse is left out, as Prepare leaves it out."""
    geo = RegionGeo(crs=f"EPSG:{epsg}", bounds=(0.0, 0.0, 1.0, 1.0), overview_size=(1, 1))
    tracks = []
    for data, name in payloads:
        try:
            tracks += load_tracks(data, geo, filename=name)
        except Exception:
            continue
    return tracks


def render_maps(entries, tracks, plate_dir, title, out_dir) -> None:
    """Draw each offered size at screen size with the word PREVIEW, as
    out_dir/<key>.png, and record `image` and `dpi` on its entry."""
    from app import render          # here, so the framing needs no renderer
    with open(os.path.join(plate_dir, "region.json")) as f:
        cfg = json.load(f)
    labels = os.path.isfile(os.path.join(plate_dir, "labels.json"))
    os.makedirs(out_dir, exist_ok=True)
    for e in entries:
        if not e["offered"]:
            continue
        dpi = preview_dpi(e)
        spec = CompositionSpec(
            region_id=cfg["id"], crs=cfg["crs"], crop=tuple(e["frame"]),
            print_w_in=e["print_in"][0], print_h_in=e["print_in"][1],
            native_resolution_m=cfg["native_resolution_m"],
            tracks=[t.coords for t in tracks], track_days=[t.day for t in tracks],
            hotspots=[], seed=7, title_text=title, labels=labels,
            panels=e["panels"], panel_gap_in=e["gap"], **PREVIEW_LOOK)
        img = render.rasterize(spec, dpi=dpi, region_dir=plate_dir, watermark=True,
                               watermark_text="PREVIEW", cfg=cfg)
        img = panel_geo.paint_gaps(img, spec, dpi)
        path = os.path.join(out_dir, f"{e['key']}.png")
        img.save(path, "PNG")
        e["image"], e["dpi"] = path, round(dpi, 2)


def _preview_plate(order, tools, union, epsg, need, env, cache_dir, log) -> dict:
    """A curated plate when one holds the frames in this projection, else one coarse
    plate built under work/preview/plate/."""
    from app.orderprep import (COARSE_LAYERS_M, COARSE_NEED_M, _build, curated_regions,
                               read_coverage)
    bounds = plate_bounds(union)
    for r in curated_regions(tools.curated_root):
        b = r["bounds"]
        if (int(str(r["crs"]).split(":")[1]) == epsg
                and bounds[0] >= b[0] and bounds[1] >= b[1]
                and bounds[2] <= b[2] and bounds[3] <= b[3]
                and r["native_resolution_m"] <= need * MAX_UPSAMPLE):
            log(f"Reusing curated plate {r['id']} for the preview.")
            return {"id": r["id"], "root": tools.curated_root, "kind": "curated",
                    "grid_m": float(r["native_resolution_m"])}
    cov = read_coverage(tools, to_lonlat_bbox(bounds, epsg, pad_m=PLATE_PAD_M), env,
                        layers=COARSE_LAYERS_M if need >= COARSE_NEED_M else None)
    grid = choose_grid(need, cov)
    if grid["widen"]:
        raise PlateError("The terrain data here is too coarse even for a preview.")
    plate, _ = _build(order, tools, union, epsg, grid, env, log, cwd=cache_dir,
                      root=os.path.join(order.work_dir, "preview", "plate"),
                      rid="preview_" + order.id[len("order_"):])
    return plate


def _dump(path, data) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, indent=2, sort_keys=True)
        f.write("\n")
    os.replace(tmp, path)


def preview(order_dir, tools, log=print, render=None, write_pdf=None) -> dict:
    """Frame every size, build one coarse plate, draw the offered sizes and write the
    PDF. `render` and `write_pdf` are for tests: stand-ins for the two slow steps."""
    from app.orderprep import PREP_VENV_HELP, _plan_grid, cache_env
    refuse_inside_repo(orders_root())
    order = load(order_dir)
    payloads = order.payloads()
    tracks_ll = lonlat_extent(payloads)["bbox"]
    if tracks_ll is None:
        raise OrderError(f"no track points in {order.in_dir}")
    if not conus_covered(tracks_ll):
        raise PlateError("These tracks are outside the lower 48 states.")
    if not os.path.exists(tools.prep_python):
        raise PlateError(f"The prep venv is missing: {tools.prep_python}. "
                         f"Set it up with {PREP_VENV_HELP}.")
    started = time.monotonic()
    epsg = preview_epsg(tracks_ll)
    bounds_m = project_bbox(tracks_ll, epsg)
    tracks = load_tracks_m(payloads, epsg)
    if not tracks:
        raise OrderError(f"no track points in {order.in_dir}")
    env, cache_dir = cache_env()

    def widen(cand, frame):
        return _plan_grid(tools, frame, epsg, cand.print_in[0], env)[0]

    entries = plan_sizes(bounds_m, [t.coords for t in tracks], widen=widen, forced=order.sizes)
    offered = [e for e in entries if e["offered"]]
    if not offered:
        raise PlateError("No size can be offered: " + "; ".join(
            f"{e['key']}: {e['why']}" for e in entries))
    log(f"Offering {', '.join(e['key'] for e in offered)}.")
    plate = _preview_plate(order, tools, union_frame(entries), epsg,
                           preview_need_m(entries), env, cache_dir, log)
    work = os.path.join(order.work_dir, "preview")
    (render or render_maps)(entries, tracks, os.path.join(plate["root"], plate["id"]),
                            order.title, work)
    pdf = os.path.join(order.dir, "out", "preview", f"{slugify(order.title)}-preview.pdf")
    if write_pdf is not None:
        write_pdf(pdf, entries, None, order.title)
    state = {"epsg": epsg, "plate": plate, "sizes": entries, "pdf": pdf,
             "seconds": round(time.monotonic() - started, 1)}
    _dump(os.path.join(work, "preview.json"), state)
    return state
```

`RegionGeo` is a dataclass in `app/geo.py` with the three fields `crs`, `bounds`, `overview_size`. If its constructor differs, read it and match it. Task 12 gives `write_pdf` its default and adds the report.

- [ ] **Step 5: Prepare warns when a window set hides a route end**

Append to `tests/test_orderprep.py`:

```python
def _two_tracks_that_meet(w, s, e, n):
    """Two tracks that both end at the middle of the box: the middle of a two-panel set."""
    mx, my = (w + e) / 2, (s + n) / 2
    seg = lambda a, b: "<trk><trkseg>" + "".join(
        f'<trkpt lat="{lat}" lon="{lon}"/>' for lon, lat in (a, b)) + "</trkseg></trk>"
    return ('<?xml version="1.0"?><gpx version="1.1" creator="t" '
            'xmlns="http://www.topografix.com/GPX/1/1">'
            + seg((w, s), (mx, my)) + seg((mx, my), (e, n)) + "</gpx>")


def test_prepare_warns_when_a_route_end_is_behind_a_gap(tmp_path, tools):
    d = _make_order(tmp_path, bbox=WIDE, size="two")
    (d / "in" / "trip.gpx").write_text(_two_tracks_that_meet(*WIDE))
    state = op.prepare(str(d), tools, log=lambda s: None)
    assert any("A route end is behind gap 1." in w for w in state["warnings"])
    (d / "order.toml").write_text('title = "Smith home ground"\nsize = "two"\ngap = 0\n')
    state = op.prepare(str(d), tools, log=lambda s: None)
    assert not any("behind gap" in w for w in state["warnings"])     # a cut set hides nothing
```

In `prepare` in `app/orderprep.py`, directly above the line `track_m = project_bbox(tracks, epsg)`:

```python
    if order.panels > 1 and order.gap:
        # a route end is tied to the ground: only the frame can move it out of a gap
        from app.orderpreview import Candidate, gaps_hiding_ends, load_tracks_m
        cand = Candidate("", order.panels, order.orientation, (pw, ph), order.gap)
        ends = [t.coords for t in load_tracks_m(payloads, epsg)]
        for k in gaps_hiding_ends(ends, frame, cand):
            warnings.append(f"A route end is behind gap {k}. Move the frame, or use "
                            f"gap = 0 to print every part of the map.")
```

The import is inside the function because `app.orderpreview` imports from `app.orderprep` inside its own functions. Run `tests/test_orderprep.py` and see the new test pass.

- [ ] **Step 6: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_orderpreview.py tests/test_orderprep.py -q`
Expected: all pass.

Run: `.venv/bin/python -m pytest tests/test_orderpreview_render.py -q`
Expected: 1 passed.

- [ ] **Step 7: Run the fast suite, then commit**

Run: `.venv/bin/python -m pytest -n auto -m "not slow" -q`

```bash
git add tests/test_orderpreview_render.py
git commit -m "The preview builds one coarse plate beside the order's own and draws each offered size" -- app/orderpreview.py app/orderprep.py tests/conftest.py tests/test_orderpreview.py tests/test_orderprep.py tests/test_orderpreview_render.py
```

---

### Task 12: The preview: the PDF, the prices and the command

**Goal:** `scripts/order.py preview <folder>` writes `out/preview/<title>-preview.pdf` with a wall page and one page for each offered size, prints a report, and takes each size's name and price from `config/sizes.toml`.

**Files:**
- Create: `config/sizes.toml`, `app/sizes.py`, `app/previewpdf.py`
- Modify: `app/orderpreview.py` (the PDF default, `write_preview_report`)
- Modify: `scripts/order.py` (the `preview` command)
- Test: `tests/test_sizes.py`, `tests/test_previewpdf.py`, `tests/test_orderpreview.py`

**Acceptance Criteria:**
- [ ] `sizes.load()` returns four rows. "two" and "three" have the price "Price on request".
- [ ] A sizes file with an unknown key, a repeated key, or a missing key raises `OrderError`.
- [ ] `previewpdf.write` makes a PDF with one page more than the number of offered sizes.
- [ ] Each page is 11 × 8.5 in. The wall page draws every offered size at one scale.
- [ ] `scripts/order.py preview <folder>` exits 0 and prints a report that lists each size as offered or not, with the `order.toml` lines for each offered size.
- [ ] `scripts/order.py prepare <folder>` behaves as before, and an error from either command names its own command.
- [ ] The three real track sets are previewed, and each run's time and offered sizes are recorded in this plan.

**Verify:** `.venv/bin/python -m pytest tests/test_sizes.py tests/test_previewpdf.py tests/test_orderpreview.py tests/test_orderprep.py -q` → all pass

**Steps:**

- [ ] **Step 1: Read the layout standard**

Read `/Users/dom/Documents/Claude/00-09 System/00 Resources/print-documents.md`. It is the workspace's standard for a PDF. Where it gives a paper tone, an ink colour, a margin or a type size that fits this page, use its value in place of the constant in step 4, and name each value you took in the commit message. The product's name on the page is "Tecopa Plateworks", in full (invariant 14).

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_sizes.py
import pytest

from app import sizes
from app.order import OrderError


def test_the_repo_file_has_the_four_sizes():
    rows = sizes.load()
    assert list(rows) == ["11x17", "17x22", "two", "three"]
    assert rows["11x17"] == {"name": "11 × 17 in", "price": "$69"}
    assert rows["17x22"]["price"] == "$99"
    assert rows["two"] == {"name": "Two panels", "price": sizes.NO_PRICE}
    assert rows["three"]["price"] == "Price on request"


def _write(tmp_path, body):
    p = tmp_path / "sizes.toml"
    p.write_text(body)
    return str(p)


ROWS = "".join(f'[[size]]\nkey = "{k}"\nname = "{k}"\n' for k in ("11x17", "17x22", "two", "three"))


def test_a_price_is_optional(tmp_path):
    rows = sizes.load(_write(tmp_path, ROWS + '[[size]]\n'.replace("[[size]]\n", "")))
    assert all(r["price"] == sizes.NO_PRICE for r in rows.values())


@pytest.mark.parametrize("body,words", [
    (ROWS + '[[size]]\nkey = "four"\nname = "Four"\n', "is not one of"),
    (ROWS + '[[size]]\nkey = "two"\nname = "Again"\n', "is there twice"),
    (ROWS.replace('[[size]]\nkey = "three"\nname = "three"\n', ""), "has no row for three"),
    (ROWS.replace('name = "two"', 'name = ""'), "needs a name"),
])
def test_a_wrong_sizes_file_is_named(tmp_path, body, words):
    with pytest.raises(OrderError, match=words):
        sizes.load(_write(tmp_path, body))
```

```python
# tests/test_previewpdf.py
import re

from PIL import Image

from app import previewpdf as pdf

NAMES = {"11x17": {"name": "11 × 17 in", "price": "$69"},
         "17x22": {"name": "17 × 22 in", "price": "$99"},
         "two": {"name": "Two panels", "price": "Price on request"},
         "three": {"name": "Three panels", "price": "Price on request"}}


def _entry(tmp_path, key, panels, w, h, gap=0.0, offered=True):
    path = tmp_path / f"{key}.png"
    Image.new("RGB", (round(w * 20), round(h * 20)), (120, 140, 110)).save(path)
    return {"key": key, "panels": panels, "orientation": "landscape" if w > h else "portrait",
            "print_in": [float(w), float(h)], "gap": gap, "offered": offered,
            "image": str(path), "why": "" if offered else "the tracks span 15% of the sheet's width"}


def _entries(tmp_path):
    return [_entry(tmp_path, "11x17", 1, 11, 17), _entry(tmp_path, "17x22", 1, 17, 22),
            _entry(tmp_path, "two", 2, 46, 17, 2.0, offered=False),
            _entry(tmp_path, "three", 3, 70, 17, 2.0)]


def test_the_caption_of_a_size():
    e = {"key": "three", "panels": 3, "print_in": [70.0, 17.0], "gap": 2.0}
    assert pdf.caption(e, NAMES) == ["Three panels",
                                     "3 panels of 17 × 22 in, 70 × 17 in hung, 2 in gaps",
                                     "Price on request"]
    e = {"key": "11x17", "panels": 1, "print_in": [11.0, 17.0], "gap": 0.0}
    assert pdf.caption(e, NAMES) == ["11 × 17 in", "11 × 17 in", "$69"]


def test_sizes_are_packed_into_rows_of_wall():
    wide = [{"print_in": [11.0, 17.0]}, {"print_in": [17.0, 22.0]},
            {"print_in": [46.0, 17.0]}, {"print_in": [70.0, 17.0]}]
    rows = pdf.wall_rows(wide, 100.0)
    assert [[e["print_in"][0] for e in row] for row in rows] == [[11.0, 17.0, 46.0], [70.0]]


def test_every_page_is_letter_landscape(tmp_path):
    offered = [e for e in _entries(tmp_path) if e["offered"]]
    wall = pdf.wall_page(offered, NAMES, "Lassen walk")
    one = pdf.size_page(offered[2], NAMES, "Lassen walk")
    assert wall.size == one.size == (1650, 1275)
    assert wall.getcolors(maxcolors=1 << 20) and len(wall.getcolors(maxcolors=1 << 20)) > 4


def test_the_pdf_has_a_wall_page_and_a_page_for_each_offered_size(tmp_path):
    out = tmp_path / "out" / "preview" / "lassen-preview.pdf"
    pages = pdf.write(str(out), _entries(tmp_path), NAMES, "Lassen walk")
    assert pages == 4                                         # the wall, then three sizes
    data = out.read_bytes()
    assert data.startswith(b"%PDF")
    assert len(re.findall(rb"/Type\s*/Page\b(?!s)", data)) == 4
```

Append to `tests/test_orderpreview.py`:

```python
def test_the_report_lists_each_size_and_the_lines_for_order_toml(tmp_path, tools):
    d = _make_order(tmp_path, bbox=WIDE, size="11x17")
    state = _preview(d, tools)
    report = (d / "work" / "preview" / "report.txt").read_text()
    assert report.startswith("Order: Smith home ground\n")
    assert f"Preview: {state['pdf']}" in report
    assert "Plate: preview_2026_10_001_smith (built)," in report
    small = [e for e in state["sizes"] if e["key"] == "11x17"][0]
    assert (f'- 11 × 17 in, {small["orientation"]}, 11 x 17 in: offered' in report
            or f'- 11 × 17 in, {small["orientation"]}, 17 x 11 in: offered' in report)
    assert f'order.toml: size = "11x17", orientation = "{small["orientation"]}"' in report
    assert "- Three panels" in report and "not offered" in report


def test_the_command_prints_the_preview_report(tmp_path, tools, capsys, monkeypatch):
    from scripts import order as order_cli
    d = _make_order(tmp_path, bbox=WIDE, size="11x17")
    monkeypatch.setattr(opv, "render_maps", _fake_render([]))
    monkeypatch.setattr(opv.previewpdf, "write", lambda path, entries, names, title: 1)
    assert order_cli.main(["preview", str(d)], tools=tools) == 0
    out = capsys.readouterr().out
    assert "Order: Smith home ground" in out and "Sizes:" in out


def test_each_command_names_itself_when_it_stops(tmp_path, tools, capsys):
    from scripts import order as order_cli
    d = _make_order(tmp_path, bbox=WIDE)
    (d / "order.toml").write_text('size = "11x17"\n')          # no title
    assert order_cli.main(["preview", str(d)], tools=tools) == 1
    assert "preview stopped: order.toml needs a title" in capsys.readouterr().err
    assert order_cli.main(["prepare", str(d)], tools=tools) == 1
    assert "prepare stopped: order.toml needs a title" in capsys.readouterr().err
```

- [ ] **Step 3: Write `config/sizes.toml` and `app/sizes.py`**

```toml
# config/sizes.toml
# The sizes a preview can offer, in menu order. Dom owns the names and the prices.
# A row with no price prints "Price on request".
# The two single-sheet prices are the decision of 2026-10-10 (docs/decisions.md).

[[size]]
key = "11x17"
name = "11 × 17 in"
price = "$69"

[[size]]
key = "17x22"
name = "17 × 22 in"
price = "$99"

[[size]]
key = "two"
name = "Two panels"

[[size]]
key = "three"
name = "Three panels"
```

```python
# app/sizes.py
"""The names and prices of the sizes, as data. Dom owns config/sizes.toml."""
import os
import tomllib

from app.order import SIZE_KEYS, OrderError

NO_PRICE = "Price on request"


def default_path() -> str:
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "config", "sizes.toml")


def load(path=None) -> dict:
    """{key: {"name", "price"}} in menu order. Every size must have a row."""
    path = path or default_path()
    try:
        with open(path, "rb") as f:
            cfg = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError) as ex:
        raise OrderError(f"config/sizes.toml cannot be read: {ex}") from ex
    rows = {}
    for row in cfg.get("size", []):
        key = row.get("key")
        if key not in SIZE_KEYS:
            raise OrderError(f"config/sizes.toml: {key!r} is not one of {', '.join(SIZE_KEYS)}")
        if key in rows:
            raise OrderError(f"config/sizes.toml: {key!r} is there twice")
        name = str(row.get("name", "")).strip()
        if not name:
            raise OrderError(f"config/sizes.toml: {key!r} needs a name")
        rows[key] = {"name": name, "price": str(row.get("price", "")).strip() or NO_PRICE}
    missing = [k for k in SIZE_KEYS if k not in rows]
    if missing:
        raise OrderError(f"config/sizes.toml has no row for {', '.join(missing)}")
    return {k: rows[k] for k in SIZE_KEYS}
```

- [ ] **Step 4: Write `app/previewpdf.py`**

```python
# app/previewpdf.py
"""The preview PDF of an order: one wall page, then one page for each offered size.

Pillow writes it, so there is no new dependency and no link in the file. The client
answers with a choice. Names and prices come from config/sizes.toml."""
import os

from PIL import Image, ImageDraw

PAGE_IN = (11.0, 8.5)        # US Letter, landscape
PAGE_DPI = 150
MARGIN_IN = 0.6
PAPER = (250, 248, 243)
INK = (38, 33, 26)
SOFT = (110, 102, 92)
ROW_IN = 100.0               # a row of wall holds this many real inches
SPACING_IN = 8.0             # between two sizes on the wall
SOFA_IN = 84.0               # a 7 ft sofa, for scale
BRAND = "Tecopa Plateworks"
NOTE = ("This is a preview. The final map is drawn from finer terrain data, "
        "and a place name can sit in another position.")


def _px(inches) -> int:
    return round(inches * PAGE_DPI)


def _font(pt, role="body"):
    from app import render       # the engine's own font chain; no font is in the repo
    return render._font(max(8, round(pt * PAGE_DPI / 72.0)), role)


def _hung(entry) -> str:
    return f"{entry['print_in'][0]:g} × {entry['print_in'][1]:g} in"


def caption(entry, names) -> list:
    """The three lines under a size: its name, what hangs, its price."""
    row = names[entry["key"]]
    what = _hung(entry)
    if entry["panels"] > 1:
        what = (f"{entry['panels']} panels of 17 × 22 in, {what} hung, "
                f"{entry['gap']:g} in gaps")
    return [row["name"], what, row["price"]]


def wall_rows(offered, row_in=ROW_IN) -> list:
    """Pack the sizes left to right into rows of wall, in menu order."""
    rows, row, used = [], [], 0.0
    for e in offered:
        w = e["print_in"][0]
        if row and used + SPACING_IN + w > row_in:
            rows.append(row)
            row, used = [], 0.0
        used += (SPACING_IN if row else 0.0) + w
        row.append(e)
    if row:
        rows.append(row)
    return rows


def _page(title, kicker):
    img = Image.new("RGB", (_px(PAGE_IN[0]), _px(PAGE_IN[1])), PAPER)
    d = ImageDraw.Draw(img)
    m = _px(MARGIN_IN)
    d.text((m, m), title, fill=INK, font=_font(20, "title"))
    d.text((m, m + _px(0.42)), f"{BRAND} · {kicker}", fill=SOFT, font=_font(10))
    d.text((m, img.size[1] - m - _px(0.14)), NOTE, fill=SOFT, font=_font(8))
    return img, d


def _lines(d, x, y, lines):
    """A name in ink, then its details in the soft tone. Returns the next y."""
    for k, text in enumerate(lines):
        d.text((x, y), text, fill=INK if k == 0 else SOFT, font=_font(11 if k == 0 else 9))
        y += _px(0.2 if k == 0 else 0.17)
    return y


CAPTION_IN = 0.62            # the height of a caption block


def wall_page(offered, names, title):
    """Every offered size on one wall at one scale, with a sofa for scale."""
    img, d = _page(title, "every size on one wall, at one scale")
    m = _px(MARGIN_IN)
    top, bottom = m + _px(0.85), img.size[1] - m - _px(0.3)
    rows = wall_rows(offered, max(ROW_IN, max(e["print_in"][0] for e in offered)))
    row_in = max(max(sum(e["print_in"][0] for e in r) + SPACING_IN * (len(r) - 1) for r in rows),
                 SOFA_IN)
    scale = (img.size[0] - 2 * m) / row_in

    def height(s):
        return sum(round(max(e["print_in"][1] for e in r) * s) + _px(CAPTION_IN)
                   for r in rows) + _px(0.5)
    while height(scale) > bottom - top:       # every row, its captions and the sofa must fit
        scale *= 0.95
    y = top
    for row in rows:
        row_h = round(max(e["print_in"][1] for e in row) * scale)
        x = m
        for e in row:
            w, h = round(e["print_in"][0] * scale), round(e["print_in"][1] * scale)
            thumb = Image.open(e["image"]).convert("RGB").resize((w, h), Image.LANCZOS)
            img.paste(thumb, (x, y + (row_h - h) // 2))
            _lines(d, x, y + row_h + _px(0.08), caption(e, names))
            x += w + round(SPACING_IN * scale)
        y += row_h + _px(CAPTION_IN)
    sofa = round(SOFA_IN * scale)
    d.line([(m, y + _px(0.12)), (m + sofa, y + _px(0.12))], fill=INK, width=3)
    for end in (m, m + sofa):
        d.line([(end, y + _px(0.06)), (end, y + _px(0.18))], fill=INK, width=3)
    d.text((m, y + _px(0.22)), "A 7 ft sofa, for scale", fill=SOFT, font=_font(9))
    return img


def size_page(entry, names, title):
    """One size, its map as large as the page allows."""
    img, d = _page(title, names[entry["key"]]["name"])
    m = _px(MARGIN_IN)
    top, bottom = m + _px(0.85), img.size[1] - m - _px(0.3) - _px(CAPTION_IN)
    box_w, box_h = img.size[0] - 2 * m, bottom - top
    art = Image.open(entry["image"]).convert("RGB")
    scale = min(box_w / art.size[0], box_h / art.size[1])
    w, h = round(art.size[0] * scale), round(art.size[1] * scale)
    img.paste(art.resize((w, h), Image.LANCZOS), (m + (box_w - w) // 2, top + (box_h - h) // 2))
    _lines(d, m, bottom + _px(0.1), caption(entry, names))
    return img


def write(path, entries, names, title) -> int:
    """Write the PDF and return its page count. A size that is not offered has no page."""
    offered = [e for e in entries if e["offered"]]
    pages = [wall_page(offered, names, title)] + [size_page(e, names, title) for e in offered]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    pages[0].save(path, "PDF", save_all=True, append_images=pages[1:],
                  resolution=PAGE_DPI, quality=90, subsampling=0)
    return len(pages)
```

- [ ] **Step 5: Give the preview its PDF and its report**

In `app/orderpreview.py`, add to the imports:

```python
from app import previewpdf, sizes
```

In `preview()`, replace the three lines from `if write_pdf is not None:` to the `state = {…}` assignment:

```python
    names = sizes.load()
    (write_pdf or previewpdf.write)(pdf, entries, names, order.title)
    state = {"epsg": epsg, "plate": plate, "sizes": entries, "pdf": pdf,
             "seconds": round(time.monotonic() - started, 1)}
    _dump(os.path.join(work, "preview.json"), state)
    write_preview_report(order, state, names)
    return state
```

In `tests/test_orderpreview.py`, the stand-in in `_preview` already takes `(path, entries, names, title)`.

Add to `app/orderpreview.py`:

```python
def write_preview_report(order, state, names) -> str:
    """What the preview decided, and the lines to write in order.toml for each size
    the client can choose. Prepare then frames that size with the same rule."""
    plate = state["plate"]
    lines = [f"Order: {order.title}", f"Preview: {state['pdf']}",
             f"Plate: {plate['id']} ({plate['kind']}), {plate['grid_m']:g} m grid", "Sizes:"]
    for e in state["sizes"]:
        what = (f"{names[e['key']]['name']}, {e['orientation']}, "
                f"{e['print_in'][0]:g} x {e['print_in'][1]:g} in")
        if not e["offered"]:
            lines.append(f"- {what}: not offered, {e['why']}.")
            continue
        toml = f'size = "{e["key"]}", orientation = "{e["orientation"]}"'
        if e["panels"] > 1:
            toml += f", gap = {e['gap']:g}"
        lines.append(f"- {what}: offered, tracks fill {e['fill']:.0%}. order.toml: {toml}")
        if e["warning"]:
            lines.append(f"  Warning: {e['warning']}.")
        for k in e["ends_behind"]:
            lines.append(f"  Warning: a route end is behind gap {k}.")
    lines.append(f"Time: {state['seconds']:g} s")
    text = "\n".join(lines) + "\n"
    path = os.path.join(order.work_dir, "preview", "report.txt")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)
    return text
```

- [ ] **Step 6: Add the command to `scripts/order.py`**

Replace `main`:

```python
def main(argv=None, tools=None) -> int:
    """`tools` is for tests only: stub subprocesses in place of the real ones."""
    ap = argparse.ArgumentParser(prog="order.py", description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prepare", help="build or reuse the order's plate and frame the tracks")
    p.add_argument("folder", help="the order folder, holding in/ and order.toml")
    v = sub.add_parser("preview", help="frame every size, build a coarse plate and "
                                       "write the preview PDF")
    v.add_argument("folder", help="the order folder, holding in/ and order.toml")
    args = ap.parse_args(argv)
    folder = os.path.abspath(os.path.expanduser(args.folder))
    run, report = {"prepare": (prepare, ("work", "report.txt")),
                   "preview": (preview, ("work", "preview", "report.txt"))}[args.cmd]
    try:
        run(folder, tools or default_tools(ROOT))
    except (OrderError, PlateError, RuntimeError, SpecError) as ex:
        print(f"{args.cmd} stopped: {ex}", file=sys.stderr)
        return 1
    with open(os.path.join(folder, *report)) as f:
        print(f.read(), end="")
    return 0
```

Add the imports beside the existing ones:

```python
from app.orderpreview import preview
from app.spec import SpecError
```

Update the module docstring's first line so it names both commands.

- [ ] **Step 7: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_sizes.py tests/test_previewpdf.py tests/test_orderpreview.py tests/test_orderprep.py tests/test_orderpreview_render.py -q`
Expected: all pass.

- [ ] **Step 8: Run the fast suite, then commit**

Run: `.venv/bin/python -m pytest -n auto -m "not slow" -q`

```bash
git add config/sizes.toml app/sizes.py app/previewpdf.py tests/test_sizes.py tests/test_previewpdf.py
git commit -m "order.py preview writes the PDF: one wall page, a page for each size, prices from data" -- config/sizes.toml app/sizes.py app/previewpdf.py app/orderpreview.py scripts/order.py tests/test_sizes.py tests/test_previewpdf.py tests/test_orderpreview.py
```

- [ ] **Step 9: Preview the three real track sets** (the coordinator does this, not a builder agent: it reads the network and needs `.venv-prep`)

Make three order folders under `~/Tecopa Orders/_preview-check/`, outside the repo. They are the three sets of 2026-09-24:

| Folder | Tracks |
|---|---|
| `home-compact` | The smallest GPX in `~/Documents/Claude/Artifacts/tecopa-sample-kit/00-source-gpx/` |
| `north-south` | A GPX with one track through `(-118.29, 36.58)`, `(-118.60, 37.10)`, `(-119.05, 37.65)` |
| `east-west` | A GPX with one track through `(-119.81, 39.53)`, `(-116.40, 40.20)`, `(-111.89, 40.76)` |

Each gets `in/<name>.gpx` and an `order.toml` with one line, `title = "<name>"`. Run, for each:

```bash
.venv/bin/python scripts/order.py preview "$HOME/Tecopa Orders/_preview-check/home-compact"
```

Open each PDF and look at every page. Record in "What changed while it ran": the seconds, the offered sizes, and anything wrong on a page. The target is under 300 s for each. A slower run is recorded and reported to Dom. It does not fail the task.

---

### Task 13: The `tecopa` tool

**Goal:** `tecopa order preview <folder>` starts the preview as a tracked run, and tests pin that the tool writes the zip of a set to `out` unchanged.

**Files:**
- Modify: `tools/tecopa/Sources/TecopaKit/Orders.swift`, `Render.swift`, `Reprint.swift`, `ScriptRunner.swift`
- Modify: `tools/tecopa/Sources/tecopa/Commands.swift`
- Modify: `tools/tecopa/Tests/TecopaKitTests/OrdersTests.swift`, `RenderTests.swift`, `ReprintTests.swift`, `MCPServerTests.swift`, `PlatesTests.swift`, `CommandPathTests.swift`
- Modify: `tools/tecopa/smoke_test.sh`

**Acceptance Criteria:**
- [ ] `Catalog.all` has 34 entries, and `order_preview` is in the `writes` set.
- [ ] `order_preview` starts `[".venv/bin/python", "scripts/order.py", "preview", <folder>]` as a tracked run and returns the run id at once.
- [ ] `render_final`, `render_fetch` and `reprint` write an `application/zip` reply to `out` byte for byte, and still refuse an existing file before any request.
- [ ] `swift test --package-path tools/tecopa` passes.
- [ ] `tools/tecopa/smoke_test.sh` ends `PASS`, and its new block shows that the tool's zip of a set and a zip made by hand are the same bytes.

**Verify:** `swift test --package-path tools/tecopa 2>&1 | tail -3` → `Executed N tests, with 0 failures`

**Steps:**

- [ ] **Step 1: Write the failing tests**

In `OrdersTests.swift`, add (it mirrors `testOrderPrepareStartsTheScriptInTheAppVenvAsATrackedRun`):

```swift
    func testOrderPreviewStartsTheScriptAsATrackedRun() async throws {
        let world = FakeWorld()
        world.folder(order)
        let runtime = world.runtime()
        let (envelope, failure) = await Catalog.call("order_preview", runtime, ["folder": .string(order)])
        XCTAssertNil(failure)
        XCTAssertEqual(world.detached.map { Array($0.arguments.dropFirst(5)) },
                       [["/repo/.venv/bin/python", "scripts/order.py", "preview", order]])
        XCTAssertEqual(world.detached.first?.cwd, "/repo")
        let written = try JSONValue.parse(
            try XCTUnwrap(world.written.first { $0.path.hasSuffix(".json") }).data)
        XCTAssertEqual(written["command"]?.stringValue, "order_preview")
        XCTAssertEqual(envelope["data"], .object([
            "run": .string(run), "pid": .int(4001), "log": .string("\(runs)/\(run).log"),
            "hint": .string("Run `tecopa runs show \(run)`.")]))
        // the call returns at once, and it writes only the run's own two files
        XCTAssertEqual(world.commands, [])
        XCTAssertEqual(world.written.map(\.path), ["\(runs)/\(run).log", "\(runs)/\(run).json"])
    }
```

In the same file, change the three places that list the order entries:

- In `testOrderPrepareNeedsAnAbsolutePathToAFolderThatExists`, the loop becomes `for name in ["order_prepare", "order_preview", "order_status"]`.
- In `testOrderStatusIsReadOnlyAndOrderPrepareIsNot`, the name list becomes `["order_prepare", "order_preview", "order_status"]`, add `XCTAssertEqual(Catalog.named("order_preview")?.readOnly, false)`, and the parameter loop covers the three names.

In `MCPServerTests.swift`: add `"order_preview"` to the `writes` set, change `XCTAssertEqual(tools.count, 33)` to `34`, and change the schema loop `for name in ["order_prepare", "order_status"]` to include `"order_preview"`.

In `PlatesTests.swift`, add a walk for the new entry to the `walks` dictionary, as a copy of the `order_prepare` walk with the key `order_preview`.

In `CommandPathTests.swift`, in `testTheFolderOfAnOrderCommandIsMadeAbsolute`, parse `["order", "preview", …]` as `OrderCommand.Preview` the same way the test parses `prepare`.

In `RenderTests.swift`, add:

```swift
    func testAZipOfPanelsIsWrittenToOutUnchanged() async {
        // a set comes back as one zip; the tool has no format logic, so the bytes
        // and the path are the caller's
        let zip = Data([0x50, 0x4B, 0x03, 0x04, 0x00, 0xFF, 0x0A])
        let world = engine()
        world.serveData("GET /api/jobs/cd34/result", 200, "application/zip", zip)
        let (data, failure) = await call("render_final", world, [
            "session": .string("ab12"), "out": .string("/out/set.zip")])
        XCTAssertNil(failure)
        XCTAssertEqual(world.written, [.init(path: "/out/set.zip", data: zip)])
        XCTAssertEqual(data?["bytes"]?.intValue, 7)

        let later = engine()
        later.serveData("GET /api/jobs/cd34/result", 200, "application/zip", zip)
        let (fetched, fetchFailure) = await call("render_fetch", later, [
            "job": .string("cd34"), "out": .string("/out/late.zip")])
        XCTAssertNil(fetchFailure)
        XCTAssertEqual(later.written, [.init(path: "/out/late.zip", data: zip)])
        XCTAssertEqual(fetched?["bytes"]?.intValue, 7)
    }
```

In `ReprintTests.swift`, add (use the file's own `call` helper and its `lassen` constant):

```swift
    func testReprintWritesTheZipOfASet() async {
        let zip = Data([0x50, 0x4B, 0x03, 0x04, 0x01, 0x02])
        let world = engine()
        world.serveData("POST /api/reprint", 200, "application/zip", zip)
        let (data, failure) = await call("reprint", world, [
            "file": lassen, "out": .string("/out/set.zip")])
        XCTAssertNil(failure)
        XCTAssertEqual(world.written, [.init(path: "/out/set.zip", data: zip)])
        XCTAssertEqual(data?["out"]?.stringValue, "/out/set.zip")
    }
```

If either file's `call` helper has another name or shape, use the one the neighbouring tests use.

- [ ] **Step 2: Run them and see them fail**

Run: `swift test --package-path tools/tecopa 2>&1 | tail -15`
Expected: the order tests and the count FAIL (`order_preview` is unknown). The two zip tests can pass already: they pin behaviour that exists.

- [ ] **Step 3: Add the entry and the command**

In `Orders.swift`, change the entries list and add the entry below `prepareEntry`:

```swift
    static let entries: [CatalogEntry] = [prepareEntry, previewEntry, statusEntry]
```

```swift
    static let previewEntry = CatalogEntry(
        name: "order_preview",
        summary: "Start the size preview for one order folder with scripts/order.py, as a tracked run: "
            + "frame the tracks at every size, build one coarse plate, and write the preview PDF under "
            + "out/preview/. It takes minutes and reads the network.",
        readOnly: false,
        parameters: [folderParameter],
        text: Runs.startedText
    ) { runtime, arguments in
        let folder = try folder(arguments, runtime)
        return try ScriptRunner.start("scripts/order.py", ["preview", folder], command: "order_preview", runtime)
    }
```

Change the file's doc comment to "The three entries of an order: Prepare and the size preview as tracked runs, and the order's own state read back."

In `ScriptRunner.swift`, change the comment on the last row of `table`:

```swift
        "scripts/order.py": .script(.app),              // order prepare, order preview
```

In `Commands.swift`, in `OrderCommand`: change `subcommands` to `[Prepare.self, Preview.self, Status.self]`, change the abstract to "Prepare a customer order, preview its sizes, or read what Prepare decided.", and add:

```swift
    struct Preview: AsyncParsableCommand {
        static let configuration = CommandConfiguration(
            commandName: "preview",
            abstract: "Start the size preview as a tracked run: every size that suits the tracks, as one PDF.")
        @OptionGroup var global: GlobalOptions
        @OptionGroup var order: Folder
        func run() async throws { try await execute("order_preview", global, order.arguments) }
    }
```

In `Render.swift`, change two summaries so a caller knows what a set returns:

```swift
        summary: "Render the final poster from tracks or from a session, and write it to out. "
            + "A set of panels is written as one zip, with a file for each panel.",
```

```swift
        summary: "Write the file of a job that is done to out. A job that is not done is refused. "
            + "The file of a set of panels is a zip.",
```

In `Reprint.swift`, change the `reprint` summary:

```swift
        summary: "Render a poster file again from its own manifest, and write it to out. "
            + "A film is rendered as a job. One panel of a set gives the whole set, as a zip.",
```

If a test pins one of these three summaries as a literal, change the literal.

- [ ] **Step 4: Run the Swift tests**

Run: `swift test --package-path tools/tecopa 2>&1 | tail -5`
Expected: `Executed N tests, with 0 failures`.

- [ ] **Step 5: Add the smoke test block**

In `tools/tecopa/smoke_test.sh`, add `order_preview` to the tool names that block 6 checks. Then add this block directly after block 7 (the phase 2 block), before block 8. It uses `$ENGINE`, `$GPX`, `$WORK` and `$SID` from block 7:

```bash
# 7b. Panel sets: the tool's zip of a set and a zip made by hand are the same bytes
CROP="$(curl -s "$ENGINE/api/debug/sessions/$SID/starter_crop?print_w=36&print_h=22")"
grep -q '"starter_crop"' <<<"$CROP" || fail "no starter crop for a 36 by 22 in set: $CROP"
read -r PX0 PY0 PX1 PY1 <<<"$(/usr/bin/python3 -c 'import json,sys; print(*json.load(sys.stdin)["starter_crop"])' <<<"$CROP")"
CODE="$(curl -s -o /dev/null -w '%{http_code}' -F "session_id=$SID" -F "x0=$PX0" -F "y0=$PY0" \
  -F "x1=$PX1" -F "y1=$PY1" -F "title=Smoke set" -F "print_w=36" -F "print_h=22" \
  -F "panels=2" -F "panel_gap=2" "$ENGINE/api/proof")"
[[ "$CODE" == 200 ]] || fail "the proof of a set by hand answered $CODE"
SUBMIT="$(curl -s -F "session_id=$SID" "$ENGINE/api/final/submit")"
grep -q '"job"' <<<"$SUBMIT" || fail "the final of a set by hand was refused: $SUBMIT"
JID="$(/usr/bin/python3 -c 'import json,sys; print(json.load(sys.stdin)["job"])' <<<"$SUBMIT")"
STATE=""
for _ in $(seq 1 300); do
  STATE="$(curl -s "$ENGINE/api/jobs/$JID")"
  case "$STATE" in *'"done"'*) break ;; *'"state":"error"'*) fail "the final of a set by hand failed: $STATE" ;; esac
  sleep 2
done
case "$STATE" in *'"done"'*) ;; *) fail "the final of a set by hand did not end in 600 seconds: $STATE" ;; esac
curl -sf -o "$WORK/hand.zip" "$ENGINE/api/jobs/$JID/result" || fail "the zip by hand could not be saved"
"$TECOPA" render final --tracks "$GPX" --set "title=Smoke set" --set "print_w=36" --set "print_h=22" \
  --set "panels=2" --set "panel_gap=2" --out "$WORK/tool.zip" >/dev/null \
  || fail "tecopa render final of a set failed"
cmp -s "$WORK/hand.zip" "$WORK/tool.zip" || fail "the tool's zip of a set differs from the zip made by hand"
[[ "$(unzip -Z1 "$WORK/tool.zip" | wc -l | tr -d ' ')" == 2 ]] || fail "the zip of a two-panel set does not hold two files"
"$TECOPA" render final --tracks "$GPX" --set "panels=2" --set "panel_gap=2" --set "print_w=36" \
  --set "print_h=22" --out "$WORK/tool.zip" >/dev/null 2>&1 && fail "tecopa wrote over an existing zip"
echo "  a set of two panels, byte-identical, and no overwrite: OK"
```

Change the last line of the script to `echo "PASS: phases 1 to 4, and panel sets"`.

- [ ] **Step 6: Build, install and run the smoke test** (the coordinator does this: it starts the engine, and the first run of a rebuilt binary can raise a macOS prompt that only Dom answers)

```bash
tools/tecopa/build.sh --install
```

```bash
tools/tecopa/smoke_test.sh
```

Expected: `PASS: phases 1 to 4, and panel sets`. The new block renders two 71 megapixel finals: allow ten minutes. If block 7b fails at the starter crop or the proof with a 422 about the zoom cap, the plate is too small for the set: record the message and report. Do not weaken the check.

- [ ] **Step 7: Commit**

```bash
git commit -m "tecopa order preview, and tests that the zip of a set is written unchanged" -- tools/tecopa
```

---

### Task 14: Documents, the whole suite and the open print checks

**Goal:** Every document says what the code now does, both suites pass, and the three checks that need paper are listed as open for Dom.

**Files:**
- Modify: `docs/architecture.md`, `docs/changing-things.md`, `docs/decisions.md`, `docs/README.md`
- Modify: `docs/superpowers/specs/2026-10-11-print-sizes-panel-sets-and-size-preview-design.md` (status, and "Changes made while it was built")
- Modify: `docs/superpowers/specs/2026-09-24-order-pipeline-design.md` (one dated amendment blockquote)
- Modify: `docs/superpowers/specs/2026-10-09-tecopa-cli-and-mcp-design.md` (the command table)
- Modify: this plan ("What changed while it ran")

**Acceptance Criteria:**
- [ ] `docs/architecture.md` has a module-map row for `app/panels.py`, `app/orderpreview.py`, `app/previewpdf.py` and `app/sizes.py`, and `config/sizes.toml` is named.
- [ ] `docs/changing-things.md`, "Run an order", has the preview step, the set sizes and the `gap` key. "Build the tecopa tool" names `order preview` and says that a set is written as a zip.
- [ ] `docs/decisions.md` holds the decisions of the spec and of this plan under 2026-10-11.
- [ ] The spec's status says what is built and what waits for paper.
- [ ] `.venv/bin/python -m pytest -n auto -q` (the full suite) has no failure that the base does not have.
- [ ] `swift test --package-path tools/tecopa` has 0 failures.
- [ ] This plan lists the three open print checks, each with what Dom must look at.

**Verify:** `.venv/bin/python -m pytest -n auto -q 2>&1 | tail -3` → no new failure; `swift test --package-path tools/tecopa 2>&1 | tail -2` → `0 failures`

**Steps:**

- [ ] **Step 1: `docs/architecture.md`**

Add four rows to the module map, next to the order modules:

```markdown
| `app/panels.py` | Panel geometry for a set: the sheets, the panel rectangles, the gap strips, the seam bands, the cut, the wall tone. The one source of where a seam is. Imports nothing from `app`. | `tests/test_panels.py`, `tests/test_panel_render.py`, `tests/test_panel_furniture.py`, `tests/test_panel_api.py` |
| `app/orderpreview.py` | The size preview of an order: the two orientations of each size, the fit rule, the coarse preview plate, the screen-size maps, `preview.json`, the report. | `tests/test_orderpreview.py`, `tests/test_orderpreview_render.py` |
| `app/previewpdf.py` | The preview PDF: a wall page and a page for each offered size, written with Pillow. | `tests/test_previewpdf.py` |
| `app/sizes.py` | Size names and prices, read from `config/sizes.toml`. | `tests/test_sizes.py` |
```

In the shape diagram, add one line under the final's line: a set is one sheet, painted once and cut by `app/panels.py` into a zip of panels. In the row for `scripts/order.py`, name both commands. In the row for `tools/tecopa/`, say that `Orders.swift` holds three order commands.

- [ ] **Step 2: `docs/changing-things.md`**

In "Run an order", replace step 2 and add a step before Prepare:

```markdown
2. Write `order.toml`: `title` (required), `size`, `orientation` (`portrait` or
   `landscape`). `size` is `"11x17"` (the default), `"17x22"`, `"two"` or `"three"`.
   `"two"` and `"three"` are a set of 17 × 22 in panels: `landscape` hangs them 22 in
   across, `portrait` 17 in across. A set also takes `gap`: 0, 2 (the default) or 4,
   the inches of wall between two panels. 0 prints every part of the map. With 2 or 4
   the map runs on behind the gap.
3. To let the client choose a size, run
   `.venv/bin/python scripts/order.py preview "<folder>"` first. It needs no `size`.
   It frames every size, builds one coarse plate under `work/preview/`, and writes
   `out/preview/<title>-preview.pdf`: every size that suits the tracks on one wall,
   then a page for each. The report lists each size as offered or not, with the lines
   to write in `order.toml`. A `sizes = ["11x17", "three"]` line overrides the fit
   rule. Names and prices are in `config/sizes.toml`. The preview is not the proof: a
   coarse plate can place a name in another position.
   `tecopa order preview "<folder>"` runs the same script as a tracked run.
```

Number the later steps on from 4. At the end of the section, add the test files `tests/test_orderpreview.py`, `tests/test_previewpdf.py` and `tests/test_sizes.py` to the list.

In "Build the tecopa tool", add to the list of render notes:

```markdown
- A set of panels (`--set panels=2 --set panel_gap=2`, with the set's own `print_w`
  and `print_h`) is written as one zip, with a file for each panel. Give `--out` a
  `.zip` name. `reprint` of one panel file gives the whole set, as a zip.
```

Add a short section after "Add a spec knob or studio control":

```markdown
## Change a panel set

`app/panels.py` is the only place that works out where a panel or a gap strip is.
The sheet in the spec is the hung size, gaps included. `rasterize` paints it once.
The furniture goes in panel 1, each panel gets a keyline and a mark, and each seam is
a label keep-out. A set has four sheets for each gap, and `validate` refuses any
other. A set is a print: the film and wallpaper routes answer 422. Tests:
`tests/test_panels.py`, `tests/test_panel_furniture.py` (fast),
`tests/test_panel_render.py`, `tests/test_panel_api.py` (slow parts render 71
megapixels).
```

- [ ] **Step 3: `docs/decisions.md`**

Add rows to the 2026-10-11 section that task 5 opened: one row for each of the twelve decisions in the spec's table, and one row for each planning decision of this plan that changes behaviour (numbers 1, 2, 3, 9, 12, 13, 14, 15, 16). Use the spec's and this plan's own words for Decision and Why. The Source of a spec decision is the spec's section. The Source of a planning decision is this plan.

In the "not done" table at the end, add:

```markdown
| 2026-10-11 | One TIFF per panel, `PRINT.txt` for a set, the hanging guide, the customer package of a set. | `order finish` is not built. These are requirements on that sub-project. | `superpowers/specs/2026-10-11-print-sizes-panel-sets-and-size-preview-design.md` §6 |
| 2026-10-11 | Buy links, the Ghost pages and set prices on the site. | A separate design: how a client sends tracks and pays. | the same spec, §14 |
```

- [ ] **Step 4: The three specs and the index**

In the spec of 2026-10-11, change the Status line to say: built on the branch `build/panel-sets-and-size-preview`, with the date, the plan's path, and "Three checks wait for paper (see the plan)". Add a section "Changes made while it was built" that points to this plan's decision table and lists what the build itself changed.

In `2026-09-24-order-pipeline-design.md`, add one blockquote under the heading of section 2, and change nothing else:

```markdown
> Amended 2026-10-11: a fourth command, `preview`, runs before Prepare when the client
> has not chosen a size. `size` also takes `"two"` and `"three"`, a set of 17 × 22 in
> panels, with a `gap` key. See `2026-10-11-print-sizes-panel-sets-and-size-preview-design.md`.
```

In `2026-10-09-tecopa-cli-and-mcp-design.md`, add a row to the command table below `order prepare`:

```markdown
| | `order preview` | Runs `scripts/order.py preview` | Yes |
```

In `docs/README.md`, change the row of the 2026-10-11 spec to say it is built, and change the row of this plan to end "The plan and build record."

`tests/test_docs.py` checks that every quoted path in a README row exists. Run it.

- [ ] **Step 5: Run everything**

```bash
.venv/bin/python -m pytest tests/test_docs.py -q
```

```bash
.venv/bin/python -m pytest -n auto -q 2>&1 | tail -5
```

```bash
swift test --package-path tools/tecopa 2>&1 | tail -3
```

Expected: the docs test passes, the full suite has no failure that the base (`main` at `cc97826`: 1452 passed, 16 skipped) does not have, and the Swift suite has 0 failures. Copy the three result lines into "What changed while it ran".

- [ ] **Step 6: Record the open print checks in this plan**

Under "What changed while it ran", write the section "Open: three checks that need paper". Each needs Dom, a printer and a ruler. No agent can close them.

| Check | Make it with | Dom looks at |
|---|---|---|
| The 11 × 17 furniture | A final of any journey at 11 × 17 | The credit line and the scale bar labels can be read at arm's length. If not, raise `FURNITURE_SCALE_MIN`. |
| The 17 × 22 furniture | The same journey at 17 × 22 | The title block and the compass look the right size, now 7 % larger than before. |
| One real set | Two panels at a 2 in gap, hung 2 in apart | A ruler laid along a road or a ridge line continues true across the gap. Each panel's keyline and mark are inside the paper. |

- [ ] **Step 7: Commit**

```bash
git commit -m "docs: panel sets, the furniture retune and the size preview, with the build record" -- docs
```

---

## What changed while it ran

This section is the build record. Each task adds what it measured or changed here.

### The memory gate (task 1)

```json
{"region": "rifle_aspen", "sheet_in": [59.0, 22.0], "pixels_mp": 116.8, "seconds": 47.0, "peak_gb": 14.07, "limit_gb": 16.0, "pass": true}
```

The gate passes: the 116.8 megapixel sheet rendered in 47 seconds with a peak of 14.07 GB, under the 16 GB limit.

The coordinator ran the gate a second time, on its own, for the gate's rule:

```
{"region": "rifle_aspen", "sheet_in": [59.0, 22.0], "pixels_mp": 116.8, "seconds": 44.4, "peak_gb": 15.29, "limit_gb": 16.0, "pass": true}
```

Both runs pass. The two peaks are 14.07 GB and 15.29 GB, so the margin under 16 GB is
between 0.7 and 1.9 GB: thin. The peak changes from run to run because the relief
passes run at the same time. Pillow also prints a `DecompressionBombWarning` at 108.8
megapixels. It is a warning below 179 megapixels, and the largest set is 116.8. A task
that makes the final of a set larger must run this gate again.
