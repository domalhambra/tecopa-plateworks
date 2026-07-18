# TrailPrint — Profile Rev 2 + Bleed/Trim (design + implementation plan)

_2026-07-17 · Status: **proposed** (not yet built). Companion to the 2026-07-17
output-fitness red-team §5, which recorded both items as known-deferred, now due.
Two independent tranches = two PRs; Tranche A has no blockers, Tranche B's **code**
has no blockers (only its final config values wait on the print lab — see the
questionnaire: `docs/superpowers/quality/2026-07-17-print-lab-questionnaire.md`)._

**Goal:** Fix the profile strip's layout law (physical, collision-proof, imperial)
behind an additive `profile_rev` gate, and give print finals real trim+bleed
geometry (`bleed_in`) with real terrain in the bleed band — with every existing
poster reprinting byte-identically.

**Architecture:** Tranche A introduces one shared pure geometry function
(`_profile_rect`) that both the strip painter and the label keep-out read, with the
legacy formula preserved verbatim as rev 1. Tranche B introduces one seam
(`sheet_geometry`) that derives a *paint-spec* (crop + sheet grown by the bleed;
ground-per-inch is invariant, so every content painter registers by construction)
and a *trim box* that all furniture measures from; at `bleed_in = 0` the paint-spec
IS the spec and the trim box IS the canvas — the no-op is provable, not asserted.

**Tech stack:** Python 3.12 · FastAPI · Pillow · rasterio · numpy · pytest ·
vanilla-JS wizard. No new dependencies.

---

## Part 0 — Design

### Decisions taken (revisit any of these before its tranche lands)

| # | Decision | Rationale | To reverse |
|---|----------|-----------|------------|
| 1 | Rev 2 = physical inset + measured stacking + **feet labels**, one `profile_rev` key | The metre labels on a miles cartouche live in the same painter; a separate `units` field would spend a second forever-key on the same fix | Drop the unit change in Task A3 (two lines); a future `units` field stays possible |
| 2 | Build bleed **fully parameterized now**; the lab conversation tunes values | The red-team's own framing: blocked on a conversation, not on more coding. `bleed_in` is data; 0.125 in is the offered value, not a constant | Ship Tranche B through Task B4 only (the no-op refactor) and hold B5+ |
| 3 | PDF = full-bleed page via the existing Pillow path; **no pikepdf** | Most web-to-print labs take exact-size full-bleed files and cut centered; TrimBox/BleedBox stamping is a small additive post-step *if* a lab asks for PDF/X | Add a `pikepdf` post-encode task later; nothing here forecloses it |
| 4 | **Proof is served trim-only** (bleed band cropped off the proof PNG) | The wizard's crop/marker registration assumes proof px ≡ `spec.crop`; trim-cropping keeps that exact with zero client math changes, and the proof remains a faithful scale of the final's *trim box* — which is what the cut produces | Remove the crop in `/api/proof` and add client-side trim mapping instead (bigger change; not recommended) |

### Approaches considered

**Tranche A.** (a) *Constant swap only* — replace `MARGIN_FRAC` with a physical
inset constant: fixes the units violation but the strip and cartouche still anchor
to the same corner independently, so collision survives. (b) *Full keep-out
registry* — every furniture painter registers its rect: general, but heavier than
four fixed elements need, and it perturbs painters that don't have a bug.
**(c) Chosen: shared measured geometry** — the repo's own `_title_block_metrics`
pattern ("shared … so they can't drift"): a pure `_profile_rect` consulted by the
painter *and* the label keep-out, with the cartouche+compass stack height measured
by the painters' own arithmetic.

**Tranche B.** (a) *Thread a paint-crop parameter through every content painter* —
~15 signatures change; high diff surface, each one a byte-identity risk.
(b) *Render at trim then extend edges* — mirrored/stretched bleed; rejected on
principle (invented terrain adjacent: the DEM is right there).
**(c) Chosen: derived paint-spec + trim box** — content painters already map
`spec.crop → full canvas` (`render.py:404`), and uniform physical bleed leaves
ground-per-inch unchanged, so `replace(spec, crop=grown, print_*_in=grown,
bleed_in=0)` makes all content correct with zero content-painter edits. Only
furniture (keyline, cartouche, compass, strip, watermark) learns the trim datum —
a defaulted `trim=None` parameter that is the identity at bleed 0.

### Invariants preserved (how)

- **Reprint byte-identity** — both new fields default to the pre-feature value and
  are omitted from the manifest at that default (`serialize.spec_to_json`); the
  rev-1 branch of `_profile_rect` is the shipped arithmetic verbatim;
  `sheet_geometry` returns the spec object itself at bleed 0.
- **Invariant 1 (proof == final)** — all new geometry is physical-inches × dpi;
  the trim-only proof equals the final's trim window at proof scale (asserted).
- **Invariant 2 (physical units)** — the strip's last raster-fraction values die
  with rev 1; bleed is inches end to end.
- **Invariant 5 (no invented terrain)** — the paint-spec's grown crop flows into
  the existing off-DEM probe, so a bleed band overhanging the DEM refuses with the
  same honest 422.
- **Zoom cap / MP ceiling** — the cap is judged on the *trim* mapping (gpp is
  bleed-invariant, so toggling bleed can never flip a crop across the cap); the MP
  ceiling stays on the *canvas* (that is what gets allocated).

### Known accepted nuances (documented, not hidden)

- The oblique shear and `_furniture_scale` read the paint-spec's slightly larger
  sheet on bleed posters (≤ ~1.4% at 0.125 in on 18×24) — deterministic, identical
  at proof and final, invisible at print. Recorded here so a future reader knows it
  was chosen, not missed.
- The labels keep-out for the furniture stack (`render.py:1560`) remains the
  hand-tuned approximation for rev-1 posters; rev 2 adds the exact strip rect.
- Proof trim-crop can differ from `round(trim_in × proof_dpi)` by ±1 px (double
  rounding); the proof is a fit-to-screen image, registration is fractional.
- A time-lapse of a bleed poster renders full-canvas frames (film = the sheet).
  Films are screen artifacts; if this ever matters, trim-crop the frames at encode.

### Out of scope (deliberately)

- pikepdf / PDF-X TrimBox stamping and CMYK output intents (await the lab).
- Printer's marks / slug. A `units` spec field. Crop-mark rendering.
- The full margin-frame layout variant (changes crop-aspect semantics; recorded
  as out of scope since the v1 quality bar).
- iOS parallax overscan, wallpaper goldens (tracked separately in the red-team §5).

---

## Part 1 — File map

| File | Tranche | Change |
|------|---------|--------|
| `app/spec.py` | A+B | `PROFILE_REVS`, `profile_rev` field + validation; `BLEED_MAX_IN`, `bleed_in` field + validation; `pixel_size` → canvas; zoom cap → trim px; `ground_per_pixel` → trim px |
| `app/serialize.py` | A+B | omit `profile_rev` at 1, `bleed_in` at 0 |
| `app/render.py` | A | `PROFILE_INSET_IN`, `PROFILE_GAP_IN`, `_furniture_stack_top`, `_profile_rect`, `_draw_profile` refactor (rev-1 verbatim / rev-2 physical + feet), keep-out in `_draw_labels` |
| `app/render.py` | B | `sheet_geometry`; `rasterize` seam; `trim=`/`paint=` params on `_paint_overlays`, `_draw_keyline`, `_draw_title_block`, `_draw_compass`, `_draw_profile` |
| `app/timelapse.py` | B | thread `sheet_geometry` through the three frame generators |
| `app/main.py` | A+B | `/api/proof`: `profile_rev` Form (default 2), `bleed` Form (default 0), proof trim-crop; `/api/continue` prefill: `profileRev`, `bleed` |
| `app/static/api.js` | A+B | proof payload: `profile_rev`, `bleed` |
| `app/static/app.js` + `state.js` + `index.html` | A+B | style state + restore for `profileRev`; bleed `<select>` in the size step |
| `tests/test_profile_rev.py` | A | new suite (geometry identity, rev-2 properties, collision sweep, serialize, validate) |
| `tests/test_bleed.py` | B | new suite (validate, geometry seam, furniture datum, encoders, off-DEM, serialize) |
| `tests/test_main.py` | B | proof-is-trim / final-is-canvas endpoint assertions |
| `docs/superpowers/quality/2026-07-17-print-lab-questionnaire.md` | B | already committed with this plan — the conversation that pins the config values |
| `docs/superpowers/quality/2026-07-02-v1-quality-bar.md` | B | close the open bleed line by pointing here |

Run tests with `pytest -q` from the repo root (conftest hydrates synthetic DEMs).
Test helpers `_cfg`/`_spec`/`_render` below follow `tests/test_journey_light.py:26-54`.

---

## Part 2 — Tranche A: profile revision 2 (PR 1)

### Task A1: the `profile_rev` spec gate

Files:
- Modify: `app/spec.py` (constants near line 81; field after `profile_height_in` ~line 204; validation after the `label_place` check ~line 286)
- Modify: `app/serialize.py` (`spec_to_json`, after the profile block ~line 78)
- Create: `tests/test_profile_rev.py`

Step 1: Write the failing tests

```python
# tests/test_profile_rev.py
"""Profile revision 2 -- the contract suite.

- rev 1 (the default; every pre-feature manifest) reproduces the shipped strip
  geometry VERBATIM (there is no engine version to hide behind);
- rev 2 is physical (invariant 2), measured against the cartouche+compass stack it
  shares the corner with (no overpaint at ANY furniture_scale), and labels feet;
- the field is omitted from the manifest at 1 (additive contract) and validated
  as a strict enum member.
"""
import json
import os

import numpy as np
import pytest
from PIL import Image, ImageDraw

from app import render, serialize
from app.spec import CompositionSpec, SpecError, PROFILE_REVS

REGION_DIR = "regions/lassen_ca"


def _cfg():
    return json.load(open(os.path.join(REGION_DIR, "region.json")))


def _spec(print_w_in=9, print_h_in=12, **kw):
    cfg = _cfg()
    bx = cfg["bounds"]
    cx, cy = (bx[0] + bx[2]) / 2, (bx[1] + bx[3]) / 2
    gw = 27000.0
    gh = gw * print_h_in / print_w_in          # crop aspect == print aspect
    crop = (cx - gw / 2, cy - gh / 2, cx + gw / 2, cy + gh / 2)
    xs = np.linspace(cx - gw * 0.3, cx + gw * 0.3, 40)
    ys = np.linspace(cy - gh * 0.3, cy + gh * 0.3, 40)
    base = dict(region_id="lassen_ca", crs=cfg["crs"], crop=crop,
                print_w_in=print_w_in, print_h_in=print_h_in,
                native_resolution_m=10,
                tracks=[np.column_stack([xs, ys])], hotspots=[],
                track_days=["2023-07-15"], seed=7)
    base.update(kw)
    return CompositionSpec(**base)


def _d():
    return ImageDraw.Draw(Image.new("RGB", (8, 8)))


def test_default_is_rev_1_and_validates():
    s = _spec(profile=True)
    assert s.profile_rev == 1
    s.validate(96)


@pytest.mark.parametrize("bad", [0, 3, -1, 1.5, True, "2"])
def test_rev_outside_the_enum_422s(bad):
    with pytest.raises(SpecError):
        _spec(profile=True, profile_rev=bad).validate(96)


def test_manifest_omits_rev_at_1_and_carries_it_at_2():
    at1 = serialize.spec_to_json(_spec(profile=True))
    assert "profile_rev" not in at1          # pre-feature manifests re-stamp byte-identically
    at2 = serialize.spec_to_json(_spec(profile=True, profile_rev=2))
    assert at2["profile_rev"] == 2
    # a manifest written before the feature refills the default
    assert serialize.spec_from_json(at1).profile_rev == 1
    assert serialize.spec_from_json(at2).profile_rev == 2
```

Step 2: Run to verify failure

Run: `pytest tests/test_profile_rev.py -q`
Expected: FAIL — `TypeError: ... unexpected keyword argument 'profile_rev'` /
`ImportError: cannot import name 'PROFILE_REVS'`.

Step 3: Implement

`app/spec.py`, after the `LABEL_PLACE_MODES` block (~line 81):

```python
# Profile revision (v1.12): rev 1 is the strip as shipped -- layout inset borrowed
# from the DEM-read margin constant (proportional to the sheet, the one furniture
# not in physical units) with metre labels and an overpaint risk against the
# cartouche stack at high furniture_scale (red-team 2026-07-17 §5). Rev 2 is the
# corrected painter: physical inset, stacked clear of the MEASURED cartouche +
# compass, feet labels (the cartouche speaks MI). The manifest has no engine
# version, so the rev is the gate: default 1, omitted from the manifest at 1 --
# every pre-feature manifest re-stamps byte-identically; new proofs stamp 2 (the
# label_place / track_weave pattern).
PROFILE_REVS = (1, 2)
```

Field, directly under `profile_height_in` (~line 204):

```python
    profile_rev: int = 1                     # strip layout revision; see PROFILE_REVS
```

Validation, after the `label_place` membership check (~line 286). `True in (1, 2)`
is `True` (bool is an int subclass), so exclude bools explicitly — the `edition`
precedent:

```python
        if isinstance(self.profile_rev, bool) or self.profile_rev not in PROFILE_REVS:
            raise SpecError(f"profile_rev must be one of {PROFILE_REVS}")
```

`app/serialize.py`, after the profile omission block (~line 78):

```python
    # profile revision (v1.12): 1 is the pre-feature strip, omitted so every earlier
    # manifest re-stamps byte-identically; spec_from_json refills the default.
    if d["profile_rev"] == 1:
        del d["profile_rev"]
```

Step 4: Run: `pytest tests/test_profile_rev.py tests/test_spec.py tests/test_provenance.py -q`
Expected: PASS (existing suites prove no drift).

Step 5: Commit: `git add -A && git commit -m "spec: profile_rev additive gate (default 1, omitted from manifest)"`

### Task A2: shared strip geometry — rev 1 verbatim

Files:
- Modify: `app/render.py` (constants at the furniture block ~line 978; new functions above `_draw_profile` ~line 1817; `_draw_profile` body 1829-1834)
- Test: `tests/test_profile_rev.py`

Step 1: Write the failing tests (append)

```python
def test_rev1_rect_is_the_shipped_formula_verbatim(dpi=300):
    """The byte-identity anchor: rev 1 must reproduce the exact legacy arithmetic
    (render.py@36f1155:1829-1834). Computed here from first principles so a painter
    'cleanup' can't silently move a pre-feature poster's strip."""
    spec = _spec(profile=True, title_text="LASSEN TRAVERSE")
    out_w, out_h = spec.pixel_size(dpi)
    fs = render._furniture_scale(spec)
    ph = max(1, round(spec.profile_height_in * dpi * fs))
    pw = min(out_w - 2 * round(out_w * render.MARGIN_FRAC), round(ph * 3.4))
    inset = round(out_h * render.MARGIN_FRAC) + round(0.01 * out_h)
    expect = (inset, out_h - inset - ph, inset + pw, out_h - inset)
    got = render._profile_rect(spec, _d(), (0, 0, out_w, out_h), dpi)
    assert got == expect


def test_rev1_render_unchanged_by_the_refactor():
    """_draw_profile now routes through _profile_rect; a rev-1 render must be
    pixel-identical to itself across calls (determinism) and must still paint in
    the lower-left (the shipped placement)."""
    spec = _spec(profile=True)
    a = np.asarray(render.rasterize(spec, 96, REGION_DIR).convert("RGB"))
    b = np.asarray(render.rasterize(spec, 96, REGION_DIR).convert("RGB"))
    assert np.array_equal(a, b)
    off = np.asarray(render.rasterize(_spec(profile=False), 96, REGION_DIR).convert("RGB"))
    h, w, _ = off.shape
    assert not np.array_equal(off[int(h * 0.8):, :int(w * 0.5)],
                              a[int(h * 0.8):, :int(w * 0.5)])
```

Step 2: Run: `pytest tests/test_profile_rev.py -q`
Expected: FAIL — `AttributeError: module 'app.render' has no attribute '_profile_rect'`.

Step 3: Implement

`app/render.py`, add to the furniture constants block (after `TITLE_INSET_IN`, ~line 978):

```python
PROFILE_INSET_IN = 0.35         # rev-2 strip inset from the sheet corner: physical,
                                # the TITLE_INSET_IN datum -- the strip is furniture
                                # like the rest (invariant 2; rev 1 kept the shipped
                                # MARGIN_FRAC proportion for byte-identity)
PROFILE_GAP_IN = 0.16           # clear air between the cartouche stack and the strip
```

New functions above `_draw_profile` (~line 1817):

```python
def _furniture_stack_top(spec, d, ty1, dpi):
    """Sheet y of the topmost painted pixel of the bottom-left furniture stack
    (cartouche plate + compass disc + the N label above the rose), computed with the
    painters' OWN arithmetic (_draw_title_block / _draw_compass) so it can't drift
    from what they draw. ty1 is the bottom of the furniture datum (the trim box's
    bottom once bleed lands; the sheet bottom until then). Returns ty1 when there is
    no stack (no title, no compass)."""
    fdpi = dpi * _furniture_scale(spec)
    inset = round(TITLE_INSET_IN * fdpi)
    m = _title_block_metrics(spec, d, dpi)
    top = ty1 - inset - m["bh"] if m else ty1
    if spec.compass:
        R = COMPASS_DIAMETER_IN * fdpi / 2.0
        base_y = ty1 - inset - ((m["bh"] + round(0.16 * fdpi)) if m else 0)
        cy = base_y - R
        f = _font(max(10, round(_pt_to_px(11.5, fdpi))))
        nl, nt, nr, nb = d.textbbox((0, 0), "N", font=f)
        nh = nb - nt
        pad = max(2, round(nh * 0.22))
        top = min(top, round(cy - R - nh - round(0.05 * fdpi)) - pad)
    return top


def _profile_rect(spec, d, trim, dpi):
    """(x0, y0, x1, y1) of the elevation-profile strip -- the ONE geometry that the
    painter AND the label keep-out read, so they can't drift (the
    _title_block_metrics pattern). trim is the furniture datum box (the full sheet
    until bleed lands). Rev 1 reproduces the shipped proportional layout VERBATIM:
    the manifest names no engine version, so old posters' pixels are the contract.
    Rev 2 is physical (invariant 2) and measured: inset in inches, stacked clear of
    the cartouche + compass at any furniture_scale, height clamped so the strip can
    never climb past the keyline."""
    tx0, ty0, tx1, ty1 = trim
    tw, th = tx1 - tx0, ty1 - ty0
    fs = _furniture_scale(spec)
    ph = max(1, round(spec.profile_height_in * dpi * fs))
    if getattr(spec, "profile_rev", 1) < 2:
        pw = min(tw - 2 * round(tw * MARGIN_FRAC), round(ph * 3.4))
        inset = round(th * MARGIN_FRAC) + round(0.01 * th)
        x0, y1 = tx0 + inset, ty1 - inset
        return x0, y1 - ph, x0 + pw, y1
    fdpi = dpi * fs
    inset = round(PROFILE_INSET_IN * fdpi)
    gap = round(PROFILE_GAP_IN * fdpi)
    y1 = min(ty1 - inset, _furniture_stack_top(spec, d, ty1, dpi) - gap)
    y_top_min = ty0 + round(KEYLINE_INSET_IN * dpi) + max(1, round(0.05 * fdpi))
    ph = max(1, min(ph, y1 - y_top_min))
    x0 = tx0 + inset
    pw = min(tw - 2 * inset, round(ph * 3.4))
    return x0, y1 - ph, x0 + pw, y1
```

`_draw_profile`: replace the five geometry lines (1829-1834, from `fs = ...` through
`x1, y0 = ...`) with:

```python
    x0, y0, x1, y1 = _profile_rect(spec, ImageDraw.Draw(img, "RGBA"), 
                                   (0, 0, out_w, out_h), dpi)
    ph = y1 - y0
```

(The trim tuple becomes a real parameter in Task B4; until then the datum is the
sheet.) The rest of the body (`pad`, the overlay, polygon, ticks, labels) is
untouched in this task.

Step 4: Run: `pytest tests/test_profile_rev.py tests/test_journey_light.py -q`
Expected: PASS — including the existing `test_profile_off_is_noop_on_and_draws`.

Step 5: Commit: `git commit -am "render: shared _profile_rect geometry; rev 1 preserves the shipped strip verbatim"`

### Task A3: the rev-2 painter — physical, stacked, feet

Files:
- Modify: `app/render.py` (`_draw_profile` label lines ~1856-1858)
- Test: `tests/test_profile_rev.py`

Step 1: Write the failing tests (append)

```python
@pytest.mark.parametrize("dpi", [96, 300])
def test_rev2_rect_is_physical_and_dpi_stable(dpi):
    spec = _spec(profile=True, profile_rev=2, title_text="LASSEN TRAVERSE")
    out_w, out_h = spec.pixel_size(dpi)
    x0, y0, x1, y1 = render._profile_rect(spec, _d(), (0, 0, out_w, out_h), dpi)
    fdpi = dpi * render._furniture_scale(spec)
    assert x0 == round(render.PROFILE_INSET_IN * fdpi)      # inches, not sheet fractions
    # invariant 1: physical geometry -> proof and final agree to within rounding
    assert abs(x0 / dpi - render.PROFILE_INSET_IN * render._furniture_scale(spec)) < 2 / dpi


SIZES = [(9, 12), (12, 16), (18, 24), (24, 36)]


@pytest.mark.parametrize("wh", SIZES)
@pytest.mark.parametrize("slider", [0.6, 1.0, 1.6])
@pytest.mark.parametrize("ph_in", [0.6, 0.9, 2.5])
@pytest.mark.parametrize("title", ["LASSEN TRAVERSE", ""])
def test_rev2_strip_clears_the_stack_at_every_offered_extreme(wh, slider, ph_in, title):
    """The red-team's overpaint (furniture_scale >= ~1.3) made into a tripwire:
    across the full offered size menu x the full slider bounds x the profile-height
    bound, the rev-2 strip never intersects the cartouche+compass stack and never
    escapes the keyline. Pure geometry (no render), so the sweep is cheap."""
    w, h = wh
    spec = _spec(print_w_in=w, print_h_in=h, profile=True, profile_rev=2,
                 furniture_scale=slider, profile_height_in=ph_in,
                 title_text=title, compass=True)
    d = _d()
    for dpi in (96, 300):
        out_w, out_h = spec.pixel_size(dpi)
        x0, y0, x1, y1 = render._profile_rect(spec, d, (0, 0, out_w, out_h), dpi)
        stack_top = render._furniture_stack_top(spec, d, out_h, dpi)
        assert y1 < stack_top                      # never overpaints the stack
        kl = round(render.KEYLINE_INSET_IN * dpi)
        assert x0 >= kl and y0 >= kl and x1 <= out_w - kl and y1 <= out_h - kl
        assert x1 > x0 and y1 > y0                 # still a real strip


def test_rev2_labels_feet_and_render_differs_from_rev1():
    r1 = np.asarray(render.rasterize(_spec(profile=True), 96, REGION_DIR).convert("RGB"))
    r2 = np.asarray(render.rasterize(_spec(profile=True, profile_rev=2), 96,
                                     REGION_DIR).convert("RGB"))
    assert not np.array_equal(r1, r2)
    assert np.array_equal(
        r2, np.asarray(render.rasterize(_spec(profile=True, profile_rev=2), 96,
                                        REGION_DIR).convert("RGB")))  # deterministic
```

Step 2: Run: `pytest tests/test_profile_rev.py -q`
Expected: the sweep may already pass (geometry landed in A2); the feet/render test
FAILS — rev 2 currently renders identically except placement… verify the labels
test fails on the `m`→`ft` assertion path (render differs is already true from
placement; keep the test — it pins determinism too). If everything passes, the
label change below is still required by the design; the determinism test guards it.

Step 3: Implement — in `_draw_profile`, replace the two label draws (~1856-1858):

```python
    # rev 2 labels feet: the cartouche speaks MI (render.NICE_MILES), and a mixed-
    # units sheet was the red-team's recorded product gap. Rev 1 keeps metres --
    # its pixels are the pre-feature contract.
    if getattr(spec, "profile_rev", 1) >= 2:
        top_lbl, bot_lbl = f"{round(emax * 3.28084):,} ft", f"{round(emin * 3.28084):,} ft"
    else:
        top_lbl, bot_lbl = f"{round(emax):,} m", f"{round(emin):,} m"
    d.text((ax0, ay0 - round(ph * 0.02)), top_lbl, font=fnt,
           fill=GEO_LABEL_INK + (255,))
    d.text((ax0, ay1 - round(ph * 0.20)), bot_lbl, font=fnt,
           fill=GEO_LABEL_INK + (200,))
```

Step 4: Run: `pytest tests/test_profile_rev.py -q` — Expected: PASS.

Step 5: Commit: `git commit -am "render: profile rev 2 -- physical inset, measured stack clearance, feet labels"`

### Task A4: exact label keep-out for the rev-2 strip

Files:
- Modify: `app/render.py` (`_draw_labels` keep-out construction, ~line 1560)
- Test: `tests/test_profile_rev.py`

Step 1: Failing test (append)

```python
def test_rev2_strip_rect_joins_the_label_keepout():
    """Auto geography names must treat the strip as occupied ground. Rendered proof:
    labels on + a name-dense synthetic region is not guaranteed, so assert at the
    seam -- the keep-out list _draw_labels builds must contain the exact strip rect."""
    spec = _spec(profile=True, profile_rev=2, labels=True,
                 title_text="LASSEN TRAVERSE")
    dpi = 96
    out_w, out_h = spec.pixel_size(dpi)
    rect = render._profile_rect(spec, _d(), (0, 0, out_w, out_h), dpi)
    assert rect in render._label_keepout(spec, _d(), out_w, out_h, dpi)
```

Step 2: Run — Expected: FAIL — no `_label_keepout`.

Step 3: Implement — extract the keep-out construction in `_draw_labels`
(~lines 1555-1569) into a function directly above it, and call it:

```python
def _label_keepout(spec, d, out_w, out_h, dpi):
    """The occupied rects auto label placement must avoid. The furniture-stack
    estimate and the clear bands are the shipped arithmetic verbatim; rev 2 adds
    the strip's EXACT rect (shared geometry -- _profile_rect -- so painter and
    keep-out can't drift)."""
    fs = _furniture_scale(spec)
    keepout = ([(0, out_h - round(2.5 * fs * dpi), round(3.4 * fs * dpi), out_h)]
               if spec.title_text.strip() or spec.compass else [])
    if spec.top_clear_frac > 0:
        keepout.append((0, 0, out_w, round(spec.top_clear_frac * out_h)))
    if spec.bottom_clear_frac > 0:
        keepout.append((0, out_h - round(spec.bottom_clear_frac * out_h), out_w, out_h))
    if spec.profile and getattr(spec, "profile_rev", 1) >= 2:
        keepout.append(_profile_rect(spec, d, (0, 0, out_w, out_h), dpi))
    return keepout
```

**Copy the guard condition for the first rect from the existing line 1560 exactly**
(it is conditioned on the stack existing — mirror whatever `if`/ternary ships there
today so rev-1 output is untouched), then in `_draw_labels` replace lines
1555-1569's construction with `keepout = _label_keepout(spec, d, out_w, out_h, dpi)`
(using the function's existing draw context; create one if none is in scope at
that point).

Step 4: Run: `pytest tests/test_profile_rev.py tests/test_smart_labels_and_weave.py tests/test_labels.py -q` — Expected: PASS.

Step 5: Commit: `git commit -am "render: rev-2 strip rect joins the label keep-out (shared geometry)"`

### Task A5: wire the gate — API default 2, continue restores the poster's own rev

Files:
- Modify: `app/main.py` (`/api/proof` Form params ~line 840; style dict ~line 854; `/api/continue` prefill ~line 1520)
- Modify: `app/static/api.js` (proof payload ~line 109), `app/static/app.js` (style builder ~line 332; restore ~line 339)

Step 1: Failing test — append to `tests/test_profile_rev.py` (endpoint level;
mirror the session-setup helper pattern already used by `tests/test_main.py`'s
proof tests):

```python
def test_new_proofs_stamp_rev_2_and_continue_restores_rev_1(client, session_with_track):
    """NEW posters get the corrected strip by default (the label_place precedent);
    a CONTINUED rev-1 poster re-proofs as rev 1 -- layout continuity is the
    poster's, not the server's. Uses the endpoint fixtures from test_main."""
    sid = session_with_track
    r = client.post("/api/proof", data={"session_id": sid, "x0": ..., "profile": "true"})
    assert r.status_code == 200
    # the stamped spec is session state; read it back the way test_main does
    ...
```

**Note:** write this test by copying the nearest existing `/api/proof` test in
`tests/test_main.py` (fixture names differ from this sketch — use theirs), adding
`"profile": "true"` and asserting the stamped session spec has `profile_rev == 2`,
then posting `"profile_rev": "1"` and asserting 1 sticks, and `"profile_rev": "3"`
422s.

Step 2: Run — Expected: FAIL (unknown form field is ignored by FastAPI, so the
first assertion fails: stamped rev is 1).

Step 3: Implement

`app/main.py` `/api/proof` signature (after `profile_height_in`, ~line 840):

```python
                profile_rev: int = Form(2),
```

Style dict (~line 854, beside `profile_height_in`):

```python
             "profile_height_in": profile_height_in, "profile_rev": profile_rev,
```

(The style dict's keys are spec field names — the same pass-through every other
knob uses; `validate()` enum-gates it.) New posters thus default to rev 2 while
the spec/manifest still omit rev 1 — exactly the `label_place`/`track_weave`
comment two lines up.

`/api/continue` prefill (~line 1520, beside `"profile":`):

```python
                  "profileRev": spec.profile_rev,
```

`app/static/api.js` proof payload (after `profile_height_in`, ~line 109):

```javascript
    profile_rev: style.profileRev != null ? style.profileRev : undefined,
```

`app/static/app.js` — in the style builder (the object at ~line 332 containing
`profile: !!s.profile, profileHeight: ...`):

```javascript
    profileRev: s.profileRev,
```

and in the continue-restore block (~line 328-339 where `state.style.profile` is
set from the payload):

```javascript
  state.style.profileRev = p.profileRev ?? 1;   // a pre-rev poster continues as rev 1
```

Step 4: Run: `pytest tests/test_profile_rev.py tests/test_main.py tests/test_editions.py -q` — Expected: PASS.

Step 5: Commit: `git commit -am "api/ui: new proofs stamp profile_rev 2; continue restores the poster's own rev"`

### Task A6: tranche close-out

Step 1: Run the full suite: `pytest -q` — Expected: PASS, no skips beyond the
pre-existing ones.

Step 2: Render one by-eye mockup for Dom (worst-case stack):

```
python - <<'EOF'
import sys; sys.path.insert(0, ".")
from tests.test_profile_rev import _spec
from app import render
s = _spec(print_w_in=18, print_h_in=24, profile=True, profile_rev=2,
          furniture_scale=1.6, title_text="LASSEN TRAVERSE")
render.rasterize(s, 130, "regions/lassen_ca").save("/tmp/rev2-mockup.png")
EOF
```

Step 3: Update `docs/superpowers/assessments/2026-07-17-output-fitness-redteam.md`
§5: append `— **shipped** (profile_rev 2, see the 2026-07-17 plan)` to the
profile-strip bullet.

Step 4: Commit: `git commit -am "docs: profile rev 2 shipped; red-team §5 updated"` — then open **PR 1**.

---

## Part 3 — Tranche B: bleed/trim (PR 2)

### Task B1: the `bleed_in` spec field — canvas vs trim, honestly

Files:
- Modify: `app/spec.py` (constant near `TOP_CLEAR_MAX` ~line 41; field after `bottom_clear_frac` ~line 176; `pixel_size` ~line 222; `ground_per_pixel` ~line 231; `validate` — output-kind block ~line 252 and zoom cap ~line 320)
- Create: `tests/test_bleed.py`

Step 1: Failing tests

```python
# tests/test_bleed.py
"""Bleed/trim (v1.12) -- the contract suite.

- bleed_in 0 (the default; every pre-feature manifest) is the EXACT pre-feature
  sheet: sheet_geometry returns the spec object itself, the trim box is the canvas;
- the canvas is trim + 2*bleed; the zoom cap is judged on the TRIM mapping
  (ground-per-pixel is bleed-invariant, so toggling bleed can't flip a crop across
  the cap); the MP ceiling is judged on the CANVAS (that is what gets allocated);
- bleed is print-only (a screen has no trimmer) and the bleed band is REAL terrain
  (off-DEM refusal extends to it -- invariant 5);
- furniture measures from the trim box; the proof is served trim-only.
"""
import json
import os

import numpy as np
import pytest
from PIL import Image, ImageDraw

from app import render, serialize
from app.spec import CompositionSpec, SpecError, BLEED_MAX_IN

REGION_DIR = "regions/lassen_ca"
# _cfg/_spec: same helpers as tests/test_profile_rev.py (import them from there)
from tests.test_profile_rev import _cfg, _spec


def test_default_zero_and_bounds():
    s = _spec()
    assert s.bleed_in == 0.0
    s.validate(96)
    _spec(bleed_in=0.125).validate(96)
    for bad in (-0.1, BLEED_MAX_IN + 0.01, float("nan")):
        with pytest.raises(SpecError):
            _spec(bleed_in=bad).validate(96)


def test_bleed_is_print_only():
    with pytest.raises(SpecError):
        _spec(bleed_in=0.125, output_kind="wallpaper", screen_ppi=460,
              print_w_in=2.62, print_h_in=5.7).validate(96)


def test_canvas_is_trim_plus_bleed_and_cap_is_trim_judged():
    s = _spec(print_w_in=9, print_h_in=12, bleed_in=0.125)
    assert s.pixel_size(96) == (round(9.25 * 96), round(12.25 * 96))
    assert s.pixel_size(300) == (2775, 3675)
    # ground_per_pixel is bleed-invariant (trim mapping)
    assert abs(_spec().ground_per_pixel(300) - s.ground_per_pixel(300)) < 1e-9
    # a crop that clears the zoom cap without bleed must clear it WITH bleed
    tight = _spec()          # 27 km over 9 in @300 -> 10 m/px, exactly at the floor
    tight.validate(300)
    _spec(bleed_in=0.125).validate(300)
```

Step 2: Run: `pytest tests/test_bleed.py -q`
Expected: FAIL — unknown field `bleed_in` / no `BLEED_MAX_IN`.

Step 3: Implement

`app/spec.py` constant (near `TOP_CLEAR_MAX`):

```python
# Bleed (v1.12): extra printed sheet past the trim line on EVERY side so the lab's
# cut never shows paper. The delivered canvas is trim + 2*bleed; spec.crop stays the
# TRIM ground window (what the wizard framed) and the painter derives the bleed band
# from it. US convention is 0.125 in, large format up to 0.25; 0.5 is past any real
# lab's ask and bounds what a crafted manifest can grow the canvas by. The actual
# offered value is pinned by the print-lab conversation
# (docs/superpowers/quality/2026-07-17-print-lab-questionnaire.md).
BLEED_MAX_IN = 0.5
```

Field (after `bottom_clear_frac`, ~line 176):

```python
    # bleed (v1.12): inches of REAL rendered terrain past the trim on every side --
    # never mirrored pixels (the DEM window has always read past the crop). 0 (the
    # default, omitted from the manifest) is byte-identical pre-feature output.
    # Print-class only; validate() refuses it on a wallpaper.
    bleed_in: float = 0.0
```

`pixel_size` / `ground_per_pixel`:

```python
    def pixel_size(self, dpi: int) -> tuple:
        # the DELIVERED canvas: trim + 2*bleed per axis (bleed 0 -> the classic sheet)
        return (round((self.print_w_in + 2 * self.bleed_in) * dpi),
                round((self.print_h_in + 2 * self.bleed_in) * dpi))

    def ground_per_pixel(self, dpi: int) -> float:
        # judged on the TRIM mapping: bleed grows canvas pixels AND ground by the
        # same ratio, so this is bleed-invariant by construction
        return (self.crop[2] - self.crop[0]) / max(1, round(self.print_w_in * dpi))
```

`validate()` — after the wallpaper `screen_ppi` block (~line 252):

```python
        if not (math.isfinite(self.bleed_in) and 0.0 <= self.bleed_in <= BLEED_MAX_IN):
            raise SpecError(f"bleed_in must be between 0 and {BLEED_MAX_IN}")
        if self.bleed_in > 0 and self.output_kind != "print":
            raise SpecError("bleed is a print-trim concept — this output has no trimmer")
```

and the zoom cap (~line 320) becomes trim-judged (identical arithmetic at bleed 0):

```python
        gpp = min(cw / max(1, round(self.print_w_in * dpi)),
                  ch / max(1, round(self.print_h_in * dpi)))
```

Step 4: Run: `pytest tests/test_bleed.py tests/test_spec.py tests/test_wallpaper.py -q` — Expected: PASS.

Step 5: Commit: `git commit -am "spec: bleed_in -- canvas = trim + 2*bleed, zoom cap trim-judged, print-only"`

### Task B2: manifest omission at 0

Files: Modify `app/serialize.py`; test in `tests/test_bleed.py`.

Step 1: Failing test (append):

```python
def test_manifest_omits_bleed_at_zero_and_round_trips():
    assert "bleed_in" not in serialize.spec_to_json(_spec())
    j = serialize.spec_to_json(_spec(bleed_in=0.125))
    assert j["bleed_in"] == 0.125
    assert serialize.spec_from_json(j).bleed_in == 0.125
    assert serialize.spec_from_json(serialize.spec_to_json(_spec())).bleed_in == 0.0
```

Step 2: Run — FAIL. Step 3: `app/serialize.py`, after the `bottom_clear_frac` block:

```python
    # bleed (v1.12): 0 is the pre-feature sheet, omitted so every earlier manifest
    # re-stamps byte-identically; spec_from_json refills the 0.0 default.
    if not d["bleed_in"]:
        del d["bleed_in"]
```

Step 4: Run: `pytest tests/test_bleed.py tests/test_provenance.py -q` — PASS.
Step 5: Commit: `git commit -am "serialize: bleed_in omitted from the manifest at 0 (additive contract)"`

### Task B3: `sheet_geometry` — the one bleed seam

Files: Modify `app/render.py` (new function above `rasterize`; `rasterize` body ~1895-1909); test in `tests/test_bleed.py`.

Step 1: Failing tests (append):

```python
def test_sheet_geometry_identity_at_zero():
    """The no-op proof: at bleed 0 the paint-spec IS the spec (same object -- no
    copy, no drift surface) and the trim box IS the canvas."""
    s = _spec()
    paint, trim = render.sheet_geometry(s, 96)
    assert paint is s
    assert trim == (0, 0, *s.pixel_size(96))


def test_sheet_geometry_grows_crop_by_the_bleed_ground_band():
    s = _spec(print_w_in=9, print_h_in=12, bleed_in=0.125)
    paint, trim = render.sheet_geometry(s, 300)
    gpi = (s.crop[2] - s.crop[0]) / s.print_w_in
    b = 0.125 * gpi
    assert paint.crop == pytest.approx((s.crop[0] - b, s.crop[1] - b,
                                        s.crop[2] + b, s.crop[3] + b))
    assert (paint.print_w_in, paint.print_h_in) == (9.25, 12.25)
    assert paint.bleed_in == 0.0                      # no consumer can double-apply
    assert paint.pixel_size(300) == s.pixel_size(300)  # one canvas, two views
    bpx = round(0.125 * 300)
    w, h = s.pixel_size(300)
    assert trim == (bpx, bpx, w - bpx, h - bpx)


def test_bleed_render_is_bigger_deterministic_and_offdem_honest():
    s0, s1 = _spec(), _spec(bleed_in=0.125)
    r0 = render.rasterize(s0, 96, REGION_DIR)
    r1 = render.rasterize(s1, 96, REGION_DIR)
    assert r1.size == s1.pixel_size(96) and r1.size != r0.size
    assert np.array_equal(np.asarray(r1),
                          np.asarray(render.rasterize(s1, 96, REGION_DIR)))
    # invariant 5 extends to the bleed band: a crop hugging the region edge that
    # renders at bleed 0 must refuse when the band would overhang the DEM
    cfg = _cfg(); bx = cfg["bounds"]
    gw = 27000.0; gh = gw * 12 / 9
    edge = _spec(crop=(bx[0], bx[1], bx[0] + gw, bx[1] + gh), bleed_in=0.25)
    from app.spec import OffDemError
    with pytest.raises(OffDemError):
        render.rasterize(edge, 96, REGION_DIR)
```

(If the edge crop already refuses at bleed 0 on the synthetic DEM, nudge it inward
until bleed 0 renders and bleed 0.25 refuses — the point is the *delta*.)

Step 2: Run — FAIL (no `sheet_geometry`).

Step 3: Implement — `app/render.py`, above `rasterize` (add `replace` to the
existing `dataclasses` import on line 4):

```python
def sheet_geometry(spec, dpi):
    """(paint_spec, trim_px) -- the ONE bleed seam. paint_spec is what the CONTENT
    painters see: at bleed 0 it IS spec (identity -- the provable no-op); at bleed
    > 0 the sheet and the crop grow by the bleed on every side (ground-per-inch is
    invariant, so every content painter registers by construction -- the crop has
    always mapped to the full canvas). bleed_in is zeroed on paint_spec so nothing
    can double-apply it. trim_px is the trim box on the canvas: the datum ALL sheet
    furniture measures from (trim-box-relative furniture, red-team 2026-07-17 §5);
    at bleed 0 it is exactly the canvas, so every pre-feature poster is untouched."""
    out_w, out_h = spec.pixel_size(dpi)
    if not spec.bleed_in:
        return spec, (0, 0, out_w, out_h)
    gpi = (spec.crop[2] - spec.crop[0]) / spec.print_w_in
    b = spec.bleed_in * gpi
    paint = replace(spec,
                    crop=(spec.crop[0] - b, spec.crop[1] - b,
                          spec.crop[2] + b, spec.crop[3] + b),
                    print_w_in=spec.print_w_in + 2 * spec.bleed_in,
                    print_h_in=spec.print_h_in + 2 * spec.bleed_in,
                    bleed_in=0.0)
    bpx = round(spec.bleed_in * dpi)
    return paint, (bpx, bpx, out_w - bpx, out_h - bpx)
```

`rasterize` becomes:

```python
def rasterize(spec: CompositionSpec, dpi: int, region_dir: str,
              watermark: bool = False, hydro=None, cfg=None, labels=None) -> Image.Image:
    spec.validate(dpi)
    if cfg is None:                        # callers holding regions.Region pass .cfg
        with open(os.path.join(region_dir, "region.json")) as f:
            cfg = json.load(f)
    # bleed seam: content paints the grown sheet; furniture measures from the trim
    paint, trim = sheet_geometry(spec, dpi)
    out_w, out_h = paint.pixel_size(dpi)
    base_rgb, lum, ctx = _paint_base(paint, dpi, region_dir, cfg, hydro=hydro, labels=labels)
    track_colors = _track_color_arrays(paint, region_dir, cfg)
    profile = _profile_data(paint, region_dir, cfg)
    img = _paint_journey(base_rgb, paint, out_w, out_h, dpi, groups=None, ctx=ctx,
                         track_colors=track_colors)
    return _paint_overlays(img, spec, lum, out_w, out_h, dpi, watermark=watermark,
                           ctx=ctx, profile=profile, paint=paint, trim=trim)
```

with `_paint_overlays` gaining defaulted params (full furniture threading is B4;
in this task just accept-and-default them):

```python
def _paint_overlays(img, spec, lum, out_w, out_h, dpi, watermark=False, ctx=None,
                    profile=None, paint=None, trim=None):
    if paint is None:
        paint = spec
    if trim is None:
        trim = (0, 0, out_w, out_h)
```

and, inside, the two GROUND-ANCHORED painters switch to `paint` (they map crop →
canvas): `_draw_markers(img, paint, …)` and `_draw_photos(img, paint, …)`. The
furniture calls keep `spec` (they gain `trim` in B4).

Step 4: Run: `pytest tests/test_bleed.py tests/test_render.py tests/test_registration.py tests/test_oblique.py -q` — Expected: PASS (bleed-0 identity carries the whole existing suite).

Step 5: Commit: `git commit -am "render: sheet_geometry bleed seam -- real terrain in the bleed, trim box derived"`

### Task B4: furniture measures from the trim box

Files: Modify `app/render.py` (`_draw_keyline` ~1048, `_draw_title_block` ~1151,
`_draw_compass` ~1264, `_draw_profile`, watermark block ~1883, `_label_keepout`);
`app/timelapse.py` (three `_paint_overlays` call sites: ~162, ~235, ~325). Test in
`tests/test_bleed.py`.

Step 1: Failing tests (append):

```python
def _blank(w, h):
    return Image.new("RGB", (w, h), (240, 238, 230))


def test_keyline_measures_from_the_trim_box():
    w, h, b = 900, 1200, 12                      # 12 px of bleed on a fake canvas
    dpi = 96
    plain = render._draw_keyline(_blank(w, h), w, h, dpi)
    inset = round(render.KEYLINE_INSET_IN * dpi)
    a = np.asarray(plain)
    assert (a[inset, inset:] != a[0, 0]).any()   # keyline at the sheet inset today
    shifted = render._draw_keyline(_blank(w + 2 * b, h + 2 * b), w + 2 * b, h + 2 * b,
                                   dpi, trim=(b, b, w + b, h + b))
    s = np.asarray(shifted)
    # the same keyline, translated by exactly the bleed: trim-relative furniture
    assert np.array_equal(np.asarray(plain)[inset:inset + 3, inset:inset + 3],
                          s[b + inset:b + inset + 3, b + inset:b + inset + 3])


def test_full_bleed_render_keeps_furniture_off_the_bleed_band():
    """End to end: on a bleed render, the outer band (everything past the trim box)
    contains terrain only -- no keyline ink. The keyline is the darkest furniture;
    assert the band is free of its ink color while the trim ring contains it."""
    s = _spec(bleed_in=0.125, title_text="LASSEN TRAVERSE", profile=True,
              profile_rev=2)
    img = np.asarray(render.rasterize(s, 96, REGION_DIR).convert("RGB"))
    bpx = round(0.125 * 96)
    kl = round(render.KEYLINE_INSET_IN * 96)
    ink = np.array(render.TERMINUS_INK)
    def has_ink(region):
        return (np.abs(region.astype(int) - ink).sum(axis=-1) < 60).any()
    assert not has_ink(img[:bpx, :])             # top bleed band: terrain only
    assert has_ink(img[bpx + kl, bpx + kl:img.shape[1] - bpx - kl])  # keyline row
```

Step 2: Run — FAIL (`_draw_keyline` has no `trim` param).

Step 3: Implement — each furniture painter gains `trim=None` defaulting to the
full canvas, and swaps its datum:

```python
def _draw_keyline(img, out_w, out_h, dpi, trim=None):
    """... Physical inset/width from the TRIM box (the sheet until bleed), so proof
    and final agree and the frame survives the lab's cut."""
    tx0, ty0, tx1, ty1 = trim or (0, 0, out_w, out_h)
    d = ImageDraw.Draw(img, "RGBA")
    inset = round(KEYLINE_INSET_IN * dpi)
    w = max(1, round(_pt_to_px(KEYLINE_PT, dpi)))
    d.rectangle([tx0 + inset, ty0 + inset, tx1 - 1 - inset, ty1 - 1 - inset],
                outline=TERMINUS_INK + (200,), width=w)
    return img
```

`_draw_title_block`: `trim=None` param; `tx0, ty0, tx1, ty1 = trim or (0, 0, out_w, out_h)`;
then `x, y = tx0 + inset, ty1 - inset - m["bh"]` (line 1160).

`_draw_compass`: same unpack; `base_y = ty1 - inset - (...)` and `cx = tx0 + inset + R`
(lines 1276-1279).

`_draw_profile`: pass the real `trim` through to `_profile_rect` (replacing the
`(0, 0, out_w, out_h)` placeholder from Task A2).

Watermark block in `_paint_overlays` (~1888-1892): center on the trim box —
`tx0 + (tw - (rt - l)) / 2 - l` and `ty0 + th * 0.24 - t` where
`tw, th = tx1 - tx0, ty1 - ty0`.

`_paint_overlays` passes `trim` to all five furniture calls. `_furniture_stack_top`
already takes `ty1` (Task A2) — `_profile_rect` hands it `trim[3]`.

`_label_keepout` (labels are painted from the paint-spec in `_paint_base`): the
furniture-stack estimate and strip rect are trim-anchored — give it a `trim=None`
param, offset the stack rect by `(tx0, …, ty1)` and pass
`(tx0, ty0, tx1, ty1)` to `_profile_rect`; `_paint_base` needs the trim for this
one call — thread it: `_paint_base(paint, dpi, region_dir, cfg, hydro=…,
labels=…, trim=trim)` → `_draw_labels(…, trim=trim)` → `_label_keepout(…, trim)`.
(Clear-band keepouts stay canvas-fractions: bleed is print-only and clear bands
are wallpaper furniture — the combination cannot validate.)

`app/timelapse.py` — at the top of each of the three frame generators:

```python
    paint, trim = render.sheet_geometry(spec, dpi)
```

then use `paint` wherever the generator hands the spec to CONTENT painting
(`_paint_base`, `_paint_journey`, prefix building), and add `paint=paint_frame,
trim=trim` to the three `render._paint_overlays(...)` calls (~162, ~235, ~325),
where `paint_frame` is the frame's prefix spec derived from `paint` instead of
`spec` (the prefix `replace(...)` that already exists — change its base). Films
of bleed posters render full-canvas frames (recorded nuance, Part 0).

Step 4: Run: `pytest tests/test_bleed.py tests/test_timelapse.py tests/test_poster_furniture.py tests/test_journey_light.py -q` — Expected: PASS (`last frame == still` still holds: both sides thread the same seam).

Step 5: Commit: `git commit -am "render: trim-box-relative furniture; timelapse threads the bleed seam"`

### Task B5: the deliverables — trim-only proof, full-bleed final

Files: Modify `app/main.py` (`/api/proof` after `rasterize` ~line 881; Form param);
test additions in `tests/test_main.py` + `tests/test_bleed.py`.

Step 1: Failing tests. In `tests/test_bleed.py`:

```python
def test_pdf_page_grows_by_the_bleed():
    """9x12 + 0.125 bleed @300 dpi -> 2775x3675 px -> 666x882 pt page. Follow the
    MediaBox assertion pattern of tests/test_main.py::test_async_final_pdf_via_job_queue."""
    import re
    from app.main import _encode_final
    s = _spec(print_w_in=9, print_h_in=12, bleed_in=0.125)
    img = render.rasterize(s, 300, REGION_DIR)
    pdf = _encode_final(img.convert("RGB"), "pdf")
    m = re.search(rb"/MediaBox\s*\[\s*0\s+0\s+(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)", pdf)
    assert m and (round(float(m.group(1))), round(float(m.group(2)))) == (666, 882)
```

In `tests/test_main.py`, extend the existing `/api/proof` test (reuse its session
fixture): post with `"bleed": "0.125"` and assert the returned PNG's size is the
**trim** size at proof dpi (±1 px per axis for double rounding), then submit a
final and assert the stored PNG's size is the **canvas** at 300 dpi and its
manifest carries `bleed_in`.

Step 2: Run — PDF test passes already if B1-B4 landed (page size follows the
canvas); the endpoint test FAILS (no `bleed` Form field; proof comes back canvas-sized).

Step 3: Implement — `/api/proof` signature (beside `output`):

```python
                bleed: float = Form(0.0),
```

style dict: `"bleed_in": bleed,` — and after the successful `rasterize` (~line 881):

```python
    # A proof is the picture you judge AT THE TRIM LINE: crop the bleed band off so
    # the wizard's crop/marker registration (proof px == spec.crop) keeps holding
    # exactly, with zero client math. The FINAL carries the bleed; the proof remains
    # a faithful scale of the final's trim box -- which is what the lab's cut
    # produces. (±1 px vs round(trim*dpi) from double rounding: fit-to-screen image,
    # fractional registration -- recorded in the 2026-07-17 plan.)
    if spec.bleed_in:
        b = round(spec.bleed_in * _proof_dpi(spec))
        w, h = img.size
        img = img.crop((b, b, w - b, h - b))
```

Step 4: Run: `pytest tests/test_bleed.py tests/test_main.py -q` — PASS.
Step 5: Commit: `git commit -am "api: bleed form field; trim-only proof, full-bleed final (PNG page + PDF MediaBox follow the canvas)"`

### Task B6: the wizard — one select in the size step

Files: Modify `app/static/index.html` (after `sizeField` ~line 116),
`app/static/app.js` (state default + wiring + restore + wallpaper hide),
`app/static/api.js` (payload), `app/main.py` (`/api/continue` prefill: `"bleed": spec.bleed_in`).

Step 1: `index.html`, after the `sizeField` div:

```html
                <div class="field" id="bleedField">
                  <label for="bleed">Print-shop bleed</label>
                  <div class="select-wrap">
                    <select id="bleed">
                      <option value="0">None — framing / wall print</option>
                      <option value="0.125">⅛ in full bleed (lab trims to size)</option>
                    </select>
                  </div>
                </div>
```

Step 2: `app.js` — default `state.style.bleedIn = 0`; an `onchange` beside the
size select's (`state.style.bleedIn = parseFloat(e.target.value) || 0`); hide
`bleedField` exactly where `sizeField` hides for wallpaper mode; restore path
(`~line 339` block): `state.style.bleedIn = p.bleed ?? 0;` and sync the select.
`api.js` proof payload: `bleed: style.bleedIn || undefined,`. `main.py` continue
prefill: `"bleed": spec.bleed_in,`.

Step 3: Manual check (no frontend tests exist — red-team §6): serve, pick ⅛ in,
proof, confirm the proof looks identical to bleed-none (trim-only), download a
final PNG and confirm `pixel dims = (W+0.25)×300`.

Step 4: Commit: `git commit -am "ui: print-shop bleed select; continue restores it; proof stays the trim picture"`

### Task B7: docs close-out

Step 1: `docs/superpowers/quality/2026-07-02-v1-quality-bar.md` — replace the
"Open: bleed/trim spec" clause with a pointer: bleed shipped behind `bleed_in`
(2026-07-17 plan); the offered value awaits the lab questionnaire's answers;
physical-proof color check still open.

Step 2: `docs/superpowers/assessments/2026-07-17-output-fitness-redteam.md` §5 —
mark the bleed bullet **shipped** (code) / **open** (lab values).

Step 3: Run `pytest -q` (full suite) — Expected: PASS.

Step 4: Commit: `git commit -am "docs: bleed shipped behind bleed_in; lab values tracked by the questionnaire"` — then open **PR 2**.

---

## Part 4 — Rollout

1. **PR 1 (Tranche A)** — no blockers; by-eye mockup (Task A6) attached for Dom.
2. **Print-lab conversation** — send the questionnaire
   (`docs/superpowers/quality/2026-07-17-print-lab-questionnaire.md`) any time;
   it blocks nothing in PR 2 except the *offered* value copy (⅛ in) and closes
   the physical-proof item.
3. **PR 2 (Tranche B)** — B1-B4 are the provable no-op refactor (land even if the
   lab stalls); B5-B7 turn the knob on.
4. **If the lab wants PDF/X** — a follow-up adds a `pikepdf` post-encode step
   stamping TrimBox/BleedBox (+ output intent) on the Pillow page; nothing in
   this plan forecloses it, and the raster bytes stay untouched.
