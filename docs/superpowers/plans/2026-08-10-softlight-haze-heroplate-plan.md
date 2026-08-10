# Soft Light + Atmospheric Haze + Hero Plate Implementation Plan

Goal: Expose the engine's existing multi-directional light and aerial haze as two
spec-carried Terrain knobs (the extension seam's first real passes), then ship an
operator-only CLI that performs a poster's terrain through Blender Cycles and
composites Tecopa's own ink over it.

Architecture: Phase 1 touches `shaded_relief()` not at all — a new `app/looks.py`
registers a `"light"`-stage pass (MDOW blend as an exact multiplicative correction)
and a `"finish"`-stage pass (Imhof haze), fed by two new `CompositionSpec` fields
whose server default 0.0 is a strict no-op; new sessions start them subtle-on
client-side (the `labelPlace` precedent). Phase 2 adds one additive-default override
to the terrain painter and a subprocess CLI: Blender renders the displaced, sun-lit
terrain under an orthographic camera over the exact crop; the engine paints water,
route, markers, labels, and furniture over it, and the output carries the source
manifest unchanged.

Tech Stack: Python 3.14 (engine), numpy/scipy (passes), FastAPI form params, vanilla
ES modules (studio), pytest (no JS runner — registry guards are text tests), Blender
≥ 4.2 LTS driven via `--background --python` (Phase 2 only, operator-installed).

Design approvals (Dom, 2026-08-10): new knobs with old posters untouched; subtle-on
for new posters; both sliders primary in the Terrain panel; hero plate as an
operator CLI. Design context: `docs/superpowers/assessments/2026-08-10-blender-render-viability.md`.

House rules that bind every task: TDD; granular present-tense commits explaining the
why; `node --input-type=module --check` on every edited JS module; every new control
carries exactly one `help:` sentence (`tests/test_static_registry.py` enforces);
determinism (same spec + seed + build → identical image) and DPI-stability for both
passes; the frozen `manifest_*_v1.json` fixtures must render unchanged.

---

## File Map

Phase 1 — the two knobs (one PR):

| File | Change | Responsibility |
|---|---|---|
| `app/spec.py` | modify (~l.92 `STYLE_BOUNDS`, ~l.233 dataclass tail) | the two spec fields + bounds; validation is automatic via the existing `STYLE_BOUNDS` loop |
| `app/looks.py` | **create** | the seam's first shipped module: two `@relief_extra` readers + two registered passes; an idempotent `register()` |
| `app/render.py` | modify (bottom of file) | one import line that loads `looks` after the module is fully initialized |
| `app/main.py` | modify (~l.994 proof Form params, ~l.1010 spec dict, ~l.1799 continue-prefill) | plumb `soft_light` / `haze_strength` through `/api/proof` and the continue prefill |
| `app/static/store.js` | modify (style defaults ~l.58, `SNAPSHOT_PATHS` ~l.146) | client subtle-on defaults (0.35 / 0.15); presets/history capture the new paths |
| `app/static/api.js` | modify (`proof()` payload ~l.98) | send the two knobs to the server |
| `app/static/compose.js` | modify (`applyPrefill` ~l.289) | continued posters restore their stored values (`?? 0`) |
| `app/static/controls.js` | modify (Terrain panel, between `shadow` and `oblique`) | two registry entries with help + keywords |
| `app/static/presets.js` | modify (`CURATED`) | Archival pins both to 0; Golden Hour haze 0.2; High Relief soft light 0.4 |
| `tests/test_looks.py` | **create** | no-op at 0, pixels move, determinism, DPI stability, composition with depth, frozen-manifest safety |
| `tests/test_relief_passes.py` | modify | the shipped registry is now exactly the looks passes; fixture restores them |
| `docs/relief-passes.md` | modify (one paragraph) | record that the seam ships two passes; note the omit-at-default wording is retired (spec_to_json emits every field) |

Phase 2 — hero plate CLI (second PR):

| File | Change | Responsibility |
|---|---|---|
| `app/render.py` | modify (`_paint_terrain` ~l.2160, `rasterize` ~l.2665) | extract `terrain_window()`; add additive-default `terrain_override=None` threaded to the `shaded_relief` call site |
| `scripts/hero_plate.py` | **create** | the operator CLI: read poster → refuse what v1 doesn't do → export window + color texture → drive Blender → composite → `…_hero.png` with the source manifest |
| `scripts/hero_scene.py` | **create** | the script Blender executes: displaced plane, ortho camera, sun with angular size, Cycles + denoise, EXR/PNG out |
| `tests/test_hero_plate.py` | **create** | geometry math, scene-script snapshot, composite-over-fake-base byte-checks, CLI refusals (no Blender needed in CI) |
| `README.md` | modify | one operator section: installing Blender, running a hero render, what the output honestly is |

Phase boundary: Phase 1 merges before Phase 2 starts; Phase 2 rebases on it.

---

## Phase 1 — Task 1: the spec fields and bounds

Files:
- Modify: `app/spec.py` (STYLE_BOUNDS ~l.92; dataclass after `track_weave` ~l.233)
- Test: `tests/test_looks.py` (new)

Step 1: Write the failing test

```python
# tests/test_looks.py
"""The seam's first shipped module (app/looks.py): soft multi-directional light and
atmospheric haze as spec knobs. The contract under test: 0.0 is a strict no-op (every
existing poster reprints byte-identically), the knobs move pixels deterministically,
the effect is DPI-stable, and the light pass composes exactly with the scale-keyed
depth blend rather than double-applying it."""
import numpy as np
import pytest

from app import looks, relief, render
from app.relief import registered_relief_passes, shaded_relief
from app.spec import CompositionSpec, STYLE_BOUNDS, SpecError


def _spec(**kw):
    base = dict(region_id="lassen_ca", crs="EPSG:32610",
                crop=(0.0, 0.0, 9000.0, 12000.0), print_w_in=18.0, print_h_in=24.0,
                native_resolution_m=10.0, tracks=[], hotspots=[])
    base.update(kw)
    return CompositionSpec(**base)


def test_spec_carries_the_two_knobs_with_noop_defaults():
    s = _spec()
    assert s.soft_light == 0.0 and s.haze_strength == 0.0
    assert STYLE_BOUNDS["soft_light"] == (0.0, 1.0)
    assert STYLE_BOUNDS["haze_strength"] == (0.0, 1.0)
    s.validate(dpi=96)                       # defaults pass validation


@pytest.mark.parametrize("field", ["soft_light", "haze_strength"])
@pytest.mark.parametrize("bad", [-0.1, 1.1, float("nan")])
def test_out_of_bounds_knob_is_refused(field, bad):
    s = _spec(**{field: bad})
    with pytest.raises(SpecError):
        s.validate(dpi=96)
```

Step 2: Run test to verify it fails

Run: `.venv/bin/python -m pytest tests/test_looks.py -q`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'soft_light'`
(and an ImportError for `app.looks` until Task 2; keep only these two tests in the
file for now).

Step 3: Write minimal implementation

In `app/spec.py`, extend `STYLE_BOUNDS` (after the `"profile_height_in"` entry):

```python
                # Looks (v1.13): soft multi-directional light + atmospheric haze --
                # the depth pass's own techniques, exposed as deliberate knobs.
                "soft_light": (0.0, 1.0), "haze_strength": (0.0, 1.0)}
```

In the dataclass, after `track_weave` (~l.233):

```python
    # Looks (v1.13): the two depth-pass techniques exposed as deliberate knobs, via
    # the relief extension seam (app/looks.py -- shaded_relief is untouched).
    # soft_light blends flanking lights around the principal azimuth (USGS MDOW)
    # so ridges running parallel to the sun still model; haze_strength sinks low
    # ground into the cool Imhof atmosphere. Both default 0.0 = strict no-op, so
    # every pre-feature manifest reprints byte-identically (read-tolerance fills
    # the missing fields); the SUBTLE-ON defaults for new posters live client-side
    # (store.js), the labelPlace precedent.
    soft_light: float = 0.0
    haze_strength: float = 0.0
```

No `validate()` edit is needed — the STYLE_BOUNDS loop (`for name, (lo, hi) in
STYLE_BOUNDS.items(): v = getattr(self, name)`) covers the new keys, and
`serialize.spec_to_json` enumerates dataclass fields, so both serialize automatically.

Step 4: Run test to verify it passes

Run: `.venv/bin/python -m pytest tests/test_looks.py -q`
Expected: PASS (the two tests; the import of `app.looks` comes in Task 2 — if you
kept the import line, create an empty `app/looks.py` now).

Step 5: Commit

```
git add app/spec.py tests/test_looks.py app/looks.py
git commit -m "Carry soft light and haze on the spec, defaulting to the shipped look

Two Looks knobs (v1.13) with server default 0.0 = strict no-op, so every
pre-feature manifest reprints byte-identically; bounds ride STYLE_BOUNDS
so validation and the client mirror stay one source of truth. The passes
themselves land next, through the relief extension seam."
```

---

## Phase 1 — Task 2: `app/looks.py` — the soft-light pass

Files:
- Create: `app/looks.py`
- Modify: `app/render.py` (bottom of file)
- Test: `tests/test_looks.py`

Step 1: Write the failing tests (append to `tests/test_looks.py`)

```python
@pytest.fixture
def terrain():
    """The seam tests' deterministic hill field (mirrors test_relief_passes)."""
    v, u = np.mgrid[0:70, 0:90].astype("float64")
    u /= 89.0
    v /= 69.0
    z = (0.5 + 0.5 * np.sin(2 * np.pi * 1.5 * u) * np.cos(2 * np.pi * 1.5 * v)
         + 0.4 * np.exp(-(((u - 0.5) ** 2 + (v - 0.5) ** 2) / 0.06)))
    return (1200.0 + 900.0 * z).astype("float32")


def _render(elev, **kw):
    return shaded_relief(elev, res_m=30.0, elev_min=1200.0, elev_max=2100.0, **kw)


def test_looks_registers_the_shipped_passes():
    assert registered_relief_passes("light") == ["soft-light"]
    assert registered_relief_passes("finish") == ["haze"]
    assert set(render.RELIEF_EXTRAS) == {"soft_light", "haze"}


def test_zero_knobs_are_byte_identical_to_an_empty_registry(terrain):
    """The additive-default rule, applied to the shipped passes themselves."""
    with_passes = _render(terrain, shadow=0.6,
                          extras={"soft_light": 0.0, "haze": 0.0})
    for stage in ("light", "finish"):
        for name in registered_relief_passes(stage):
            relief.unregister_relief_pass(stage, name)
    try:
        empty = _render(terrain, shadow=0.6)
    finally:
        looks.register()
    assert np.array_equal(with_passes, empty)


def test_soft_light_moves_pixels_and_is_deterministic(terrain):
    plain = _render(terrain)
    lit = _render(terrain, extras={"soft_light": 0.6})
    assert not np.array_equal(plain, lit)
    assert np.array_equal(lit, _render(terrain, extras={"soft_light": 0.6}))


def test_soft_light_full_knob_matches_the_core_blend(terrain):
    """knob k with depth 0 must equal the core's own MDOW blend at weight
    MULTIDIR_MAX*k' where the composed weight is 1-(1-0)(1-k) = k -- verified
    against a hand-built reference through the core's formulas."""
    k = 0.55                       # == MULTIDIR_MAX: same weight the depth pass uses
    ours = _render(terrain, extras={"soft_light": k})
    theirs = _render(terrain, depth=1.0)          # MDOW at MULTIDIR_MAX, but ALSO
    # depth adds texture/atmosphere/salt, so compare the light plane's effect only:
    # render with a probe pass capturing the light plane in both configurations.
    captured = {}
    def probe(arr, frame):
        captured[frame.extras.get("probe")] = arr.copy()
        return arr
    relief.register_relief_pass("light", "zz-probe", probe)   # runs after soft-light
    try:
        _render(terrain, extras={"soft_light": k, "probe": "knob"})
        _render(terrain, depth=1.0, extras={"probe": "depth"})
    finally:
        relief.unregister_relief_pass("light", "zz-probe")
    np.testing.assert_allclose(captured["knob"], captured["depth"],
                               rtol=0, atol=1e-6)


def test_soft_light_composes_with_depth_instead_of_double_applying(terrain):
    """At depth=1 the core already blended at MULTIDIR_MAX; a knob on top may only
    ADD the remaining headroom -- never darken below either input."""
    base = _render(terrain, depth=1.0)
    more = _render(terrain, depth=1.0, extras={"soft_light": 1.0})
    assert not np.array_equal(base, more)         # headroom exists above 0.55
    # and knob=0.0 with depth on is byte-identical (enabled gate)
    assert np.array_equal(base, _render(terrain, depth=1.0,
                                        extras={"soft_light": 0.0}))
```

Step 2: Run tests to verify they fail

Run: `.venv/bin/python -m pytest tests/test_looks.py -q`
Expected: FAIL — `AttributeError: module 'app.looks' has no attribute 'register'` /
empty registry assertions.

Step 3: Write the implementation

`app/looks.py`:

```python
# app/looks.py
"""The relief extension seam's first shipped module: the two depth-pass techniques
exposed as deliberate spec knobs (v1.13, approved by Dom 2026-08-10).

soft_light -- the USGS MDOW multi-directional blend `multidirectional_hillshade`
already implements, reachable today only through the scale-keyed depth ramp (zero at
county scale, where most posters live). The pass applies it as an exact multiplicative
correction on the "light" plane: light = f(hs)*S where f(h) = SHADOW_FLOOR +
(1-SHADOW_FLOOR)*h and S is the (multiplicative) valley/cast/AO factor, so swapping
hs for the blend is exactly light *= f(hs_new)/f(hs_cur). The knob COMPOSES with any
weight the depth ramp already blended (w = 1-(1-w_depth)(1-knob)) so corridor-scale
sheets never double-apply. The one approximation: the core clamps to CAST_LIGHT_FLOOR
before this stage runs, so pixels sitting exactly at the floor take the correction
from the clamped value; the pass re-clamps after, and the deviation is bounded,
deterministic, and dark-end only.

haze_strength -- the Imhof aerial perspective `_depth_atmosphere` already applies at
corridor scale, as a deliberate knob at any scale: low ground sinks toward the cool
HAZE colour by HAZE_KNOB_MAX * knob * (1-norm)**HAZE_GAMMA, stacking additively with
the depth pass's own AERIAL term when both run.

Both passes are gated `enabled` on knob > 0 -- a zero knob never runs, so the
shipped-registry state is a strict no-op at the spec defaults and every pre-feature
manifest renders byte-identically (tests/test_looks.py holds this line)."""
from __future__ import annotations
import numpy as np

from . import relief
from .relief import (CAST_LIGHT_FLOOR, HAZE, HILLSHADE_GAMMA, MULTIDIR_MAX,
                     SHADOW_FLOOR, register_relief_pass, shade_from)
from .render import relief_extra

HAZE_KNOB_MAX = 0.30      # haze on the lowest ground at knob 1.0 (deliberate, so it
                          # reaches past the depth ramp's automatic 0.18)
HAZE_GAMMA = 1.5          # the depth pass's own falloff curve, kept identical


@relief_extra("soft_light")
def _soft_light_knob(spec):
    return spec.soft_light


@relief_extra("haze")
def _haze_knob(spec):
    return spec.haze_strength


def _soft_light(light, frame):
    k = float(np.clip(frame.extras.get("soft_light", 0.0), 0.0, 1.0))
    slope, aspect = frame.terrain()                 # shared -- never re-gradient
    hs1 = shade_from(slope, aspect, frame.azimuth, frame.altitude) ** HILLSHADE_GAMMA
    hsm = relief.multidirectional_hillshade(
        frame.elev, frame.res_m, frame.azimuth, frame.altitude, frame.z_factor,
        terrain=(slope, aspect)) ** HILLSHADE_GAMMA
    d = float(np.clip(frame.depth, 0.0, 1.5))
    w_cur = MULTIDIR_MAX * min(d, 1.0) if d > 0 else 0.0   # what the core blended
    w_new = 1.0 - (1.0 - w_cur) * (1.0 - k)                # compose, never subtract
    if w_new <= w_cur:
        return light
    hs_cur = hs1 * (1.0 - w_cur) + hsm * w_cur
    hs_new = hs1 * (1.0 - w_new) + hsm * w_new
    f_cur = hs_cur
    f_cur *= (1.0 - SHADOW_FLOOR)
    f_cur += SHADOW_FLOOR
    f_new = hs_new
    f_new *= (1.0 - SHADOW_FLOOR)
    f_new += SHADOW_FLOOR
    f_new /= f_cur                                  # the exact correction, in place
    light *= f_new
    if frame.shadow > 0:                            # restore the core's floor clamp
        np.maximum(light, CAST_LIGHT_FLOOR, out=light)
    return light


def _haze(img, frame):
    k = float(np.clip(frame.extras.get("haze", 0.0), 0.0, 1.0))
    w = (HAZE_KNOB_MAX * k
         * np.clip(1.0 - frame.norm, 0.0, 1.0) ** HAZE_GAMMA)[..., None]
    haze_rgb = np.array(HAZE, np.float32)[None, None, :] / 255.0
    img *= (1.0 - w)
    img += haze_rgb * w
    return img


def register():
    """Idempotent (register replaces by name): the import-time call below sets the
    shipped state; tests that empty the registry call this to restore it."""
    register_relief_pass("light", "soft-light", _soft_light,
                         enabled=lambda f: f.extras.get("soft_light", 0.0) > 0)
    register_relief_pass("finish", "haze", _haze,
                         enabled=lambda f: f.extras.get("haze", 0.0) > 0)


register()
```

At the very bottom of `app/render.py` add:

```python
# The shipped relief-pass module registers on import. Imported HERE, at the bottom,
# because looks.py needs this module's relief_extra -- by this line the module object
# is fully populated, so the circular import resolves cleanly and deterministically.
from . import looks  # noqa: E402,F401
```

Step 4: Run tests to verify they pass

Run: `.venv/bin/python -m pytest tests/test_looks.py -q`
Expected: PASS. (The core computes `f(h)` via the same commutative in-place idiom —
if `test_soft_light_full_knob_matches_the_core_blend` shows atol ~1e-7 float noise,
that is the float32 associativity of the two construction orders: tighten the pass to
mirror the core's exact operation order shown above before loosening any tolerance.)

Step 5: Commit

```
git add app/looks.py app/render.py tests/test_looks.py
git commit -m "Register soft light through the seam as an exact light-plane correction

The MDOW blend already ships inside the scale-keyed depth ramp; this
exposes it as a deliberate knob without touching shaded_relief. Because
the light plane is f(hs) times multiplicative sink factors, swapping the
hillshade for the blend is exactly light *= f(hs_new)/f(hs_cur) -- and
the knob composes with whatever weight depth already blended, so a
corridor sheet can never double-apply. Enabled-gated at zero: the spec
default renders byte-identically to the empty registry."
```

---

## Phase 1 — Task 3: the haze pass + DPI stability

Files:
- Modify: `tests/test_looks.py` (the pass shipped in Task 2's module; tests only)

Step 1: Write the failing tests (append)

```python
def test_haze_sinks_low_ground_toward_the_haze_colour(terrain):
    plain = _render(terrain)
    hazed = _render(terrain, extras={"haze": 1.0})
    assert not np.array_equal(plain, hazed)
    assert np.array_equal(hazed, _render(terrain, extras={"haze": 1.0}))
    norm = (terrain - 1200.0) / 900.0
    low, high = norm < 0.15, norm > 0.85
    d = hazed.astype(int) - plain.astype(int)
    moved = np.abs(d).sum(axis=2)
    assert moved[low].mean() > 4 * max(moved[high].mean(), 0.25)
    # low ground moves TOWARD the cool haze: blue rises relative to red
    assert d[..., 2][low].mean() > d[..., 0][low].mean()


def test_both_knobs_are_dpi_stable(terrain):
    """One spec, painted at many sizes: the same ground at half the resolution must
    show the same effect (MAD of the upsampled coarse render vs fine, bounded like
    the engine's other proof-vs-final gates)."""
    from scipy.ndimage import zoom
    fine = shaded_relief(terrain, res_m=30.0, elev_min=1200.0, elev_max=2100.0,
                         extras={"soft_light": 0.6, "haze": 0.5})
    coarse_elev = zoom(terrain, 0.5, order=1)
    coarse = shaded_relief(coarse_elev, res_m=60.0, elev_min=1200.0,
                           elev_max=2100.0, extras={"soft_light": 0.6, "haze": 0.5})
    up = zoom(coarse.astype("float32"), (2.0 * fine.shape[0] / (2 * coarse.shape[0]),
                                         2.0 * fine.shape[1] / (2 * coarse.shape[1]),
                                         1.0), order=1)
    up = up[:fine.shape[0], :fine.shape[1]]
    mad = np.abs(up - fine.astype("float32")).mean()
    plain_fine = shaded_relief(terrain, res_m=30.0, elev_min=1200.0, elev_max=2100.0)
    plain_coarse = shaded_relief(coarse_elev, res_m=60.0, elev_min=1200.0,
                                 elev_max=2100.0)
    up0 = zoom(plain_coarse.astype("float32"),
               (fine.shape[0] / plain_coarse.shape[0],
                fine.shape[1] / plain_coarse.shape[1], 1.0), order=1)[:fine.shape[0],
                                                                     :fine.shape[1]]
    mad0 = np.abs(up0 - plain_fine.astype("float32")).mean()
    assert mad < mad0 + 2.0        # the knobs add no MORE dpi drift than the base look
```

Step 2: Run — Expected: `test_haze_...` PASS already (Task 2 shipped both passes);
`test_both_knobs_are_dpi_stable` must PASS too. If either fails, fix before moving
on — a red here means a pixel-unit leak (something not sized through `frame.px` /
`res_m`).

Step 3: Commit

```
git add tests/test_looks.py
git commit -m "Hold the haze pass to its direction and both knobs to DPI stability

Low ground must move toward the cool atmosphere and high ground stay
crisp, and neither knob may drift the proof away from the final any
further than the base look already does -- the same one-spec-many-sizes
gate the rest of the relief keeps."
```

---

## Phase 1 — Task 4: rework the seam tests' shipped-state assumptions

Files:
- Modify: `tests/test_relief_passes.py` (fixture ~l.34, `test_registry_ships_empty`
  ~l.49, `test_render_extras_registry_ships_empty_and_stays_no_op` ~l.178)

Step 1: Run the suite to see the breakage

Run: `.venv/bin/python -m pytest tests/test_relief_passes.py -q`
Expected: FAIL ×3 — `clean_registry` asserts "the registry must ship empty",
`test_registry_ships_empty`, and the RELIEF_EXTRAS test. These encoded the empty
shipped state; the shipped state is now "exactly the looks passes."

Step 2: Rework (complete replacements)

```python
from app import looks

SHIPPED = {"color": [], "light": ["soft-light"], "finish": ["haze"], "grade": []}


@pytest.fixture
def clean_registry():
    """Each test runs against an EMPTY registry (the seam's mechanics under test),
    then the shipped looks passes are restored, pass or fail."""
    for stage, names in registered_relief_passes().items():
        for name in names:
            unregister_relief_pass(stage, name)
    yield
    for stage, names in registered_relief_passes().items():
        for name in names:
            unregister_relief_pass(stage, name)
    looks.register()


def test_registry_ships_the_looks_passes():
    # The shipped state is no longer empty: the looks module (v1.13) registers the
    # soft-light and haze passes on import. Their zero-knob no-op is held by
    # tests/test_looks.py; THIS test pins exactly what ships, so a stray
    # registration (or a lost one) fails loudly.
    assert registered_relief_passes() == SHIPPED


def test_render_extras_registry_carries_the_looks_knobs():
    """render.relief_extra is the spec-side half of the seam: it ships with exactly
    the two looks readers, and they surface the spec's values."""
    from app import render
    from app.spec import CompositionSpec
    assert set(render.RELIEF_EXTRAS) == {"soft_light", "haze"}
    s = CompositionSpec(region_id="x", crs="EPSG:32610",
                        crop=(0, 0, 100, 100), print_w_in=18, print_h_in=24,
                        native_resolution_m=10.0, tracks=[], hotspots=[],
                        soft_light=0.4, haze_strength=0.2)
    assert render._relief_extras(s) == {"soft_light": 0.4, "haze": 0.2}
```

Step 3: Run the seam + looks suites

Run: `.venv/bin/python -m pytest tests/test_relief_passes.py tests/test_looks.py -q`
Expected: PASS, all.

Step 4: Commit

```
git add tests/test_relief_passes.py
git commit -m "Teach the seam tests that the shipped registry now carries the looks

The empty registry stopped being the shipped state the moment looks.py
registered the first real passes; the seam's mechanics still test against
an emptied registry, and the fixture now restores the shipped set instead
of assuming there is nothing to restore."
```

---

## Phase 1 — Task 5: server plumbing (`/api/proof` + continue prefill)

Files:
- Modify: `app/main.py` (~l.994 Form params; ~l.1010 spec-build dict; ~l.1799 prefill)
- Test: extend `tests/test_main.py` style-knob coverage

Step 1: Write the failing test — locate
`test_style_knobs_stamped_through_endpoint` in `tests/test_main.py` and add the two
fields to its posted form and its stamped-spec assertions
(`soft_light=0.35`, `haze_strength=0.2` → `spec.soft_light == 0.35`,
`spec.haze_strength == 0.2`). Follow the test's existing shape exactly — it already
posts `shadow_strength` and asserts it lands.

Step 2: Run: `.venv/bin/python -m pytest "tests/test_main.py::test_style_knobs_stamped_through_endpoint" -q`
Expected: FAIL — the endpoint ignores the unknown form fields, spec keeps 0.0.

Step 3: Implement, three anchors in `app/main.py`:

At ~l.994, beside `shadow_strength: float = Form(0.5), oblique: float = Form(0.0)`:

```python
                soft_light: float = Form(0.0), haze_strength: float = Form(0.0),
```

At ~l.1010, in the dict that builds the spec, beside `"shadow_strength": shadow_strength,`:

```python
             "soft_light": soft_light, "haze_strength": haze_strength,
```

At ~l.1799, in the continue-prefill style block beside `"shadow": spec.shadow_strength,`:

```python
                  "softLight": spec.soft_light, "haze": spec.haze_strength,
```

Step 4: Run: same test — Expected: PASS. Also run
`.venv/bin/python -m pytest tests/test_provenance.py -q -k frozen` — Expected: PASS
(frozen v1 manifests default the new fields to 0.0 and render unchanged).

Step 5: Commit

```
git add app/main.py tests/test_main.py
git commit -m "Stamp the looks knobs through the proof endpoint and the prefill

Two Form fields defaulting to the server no-op, the spec-build dict
entries, and the continue-prefill echo -- so a continued poster restores
exactly the light it was printed with, and a pre-feature file restores
the plain look."
```

---

## Phase 1 — Task 6: the studio (store, api, prefill, controls, presets)

Files:
- Modify: `app/static/store.js`, `app/static/api.js`, `app/static/compose.js`,
  `app/static/controls.js`, `app/static/presets.js`

Step 1: `store.js` — in the `style: {` literal, after `shadow: 0.5,` / `oblique: 0.0,`:

```javascript
    softLight: 0.35,      // Looks v1.13: MDOW blend weight. SUBTLE-ON for new
    haze: 0.15,           // posters (server default is 0 -- old files stay plain)
```

and in `SNAPSHOT_PATHS`, extend the style line:

```javascript
  'style.softLight', 'style.haze',
```

Step 2: `api.js` — in `proof()`'s `postForm` payload, beside
`terrain_depth: style.terrain, shadow_strength: style.shadow,`:

```javascript
    soft_light: style.softLight, haze_strength: style.haze,
```

Step 3: `compose.js` — in `applyPrefill`'s `Object.assign(state.style, {` block,
beside `shadow: s.shadow ?? state.style.shadow, oblique: s.oblique ?? 0,`:

```javascript
    softLight: s.softLight ?? 0, haze: s.haze ?? 0,
```

(`?? 0`, not the store default: a pre-feature poster restores the plain look it was
printed with.)

Step 4: `controls.js` — two Terrain entries between `shadow` and `oblique`:

```javascript
  { id: 'softLight', path: 'style.softLight', section: 'style', panel: 'Terrain', label: 'Soft light',
    type: 'slider', min: 0, max: 1, step: 0.05, default: 0.35, fmt: pct, affectsProof: true,
    help: 'Blends flanking lights around the sun so ridges running with it still model.',
    keywords: ['soft light', 'mdow', 'multidirectional', 'blend', 'flat ridges'] },
  { id: 'haze', path: 'style.haze', section: 'style', panel: 'Terrain', label: 'Atmospheric haze',
    type: 'slider', min: 0, max: 1, step: 0.05, default: 0.15, fmt: pct, affectsProof: true,
    help: 'Sinks the low valleys into a cool haze so the sheet reads deeper front to back.',
    keywords: ['haze', 'atmosphere', 'aerial perspective', 'depth', 'fog'] },
```

Step 5: `presets.js` — Archival snap adds `'style.softLight': 0, 'style.haze': 0`;
Golden Hour adds `'style.haze': 0.2`; High Relief adds `'style.softLight': 0.4`.

Step 6: Verify

Run: `for f in store api compose controls presets; do node --input-type=module --check < app/static/$f.js; done`
Expected: silence (all parse).
Run: `.venv/bin/python -m pytest tests/test_static_registry.py -q`
Expected: PASS (each new entry has exactly one help; no duplicate keys).

Step 7: Commit

```
git add app/static/store.js app/static/api.js app/static/compose.js \
        app/static/controls.js app/static/presets.js
git commit -m "Give the studio its Soft light and Atmospheric haze sliders, subtle-on

New sessions start at 0.35/0.15 (the labelPlace precedent: client
defaults enhance new posters while the server default keeps old files
plain), continued posters restore their own stored values, Archival pins
both back to plain, and both rows explain themselves behind their ?."
```

---

## Phase 1 — Task 7: end-to-end verification + PR

Step 1: Full fast tier — Run: `.venv/bin/python -m pytest -n auto -m "not slow" -q`
Expected: PASS (0 failed). Pay attention to `test_base_cache.py` /
`test_ink_cache.py`: the new fields enter both keys by masking-default —
`test_every_masked_field_leaves_the_terrain_byte_identical` enumerates the dataclass
and will exercise them; a failure there means a mask was wrongly extended (don't).

Step 2: Browser smoke (the repo's front-end practice): start the studio against the
synthetic plates (`tests/conftest.py` hydration; see the 2026-08-10 red-team
assessment's smoke-server pattern), upload `tests/fixtures/sample.gpx`, and verify:
both sliders present in Terrain with `?` sentences; moving each stales + re-proofs;
Archival preset returns them to 0; palette finds "Soft light" and "Atmospheric haze".

Step 3: Eyeball pass — render one proof at softLight 0 vs 0.6 and haze 0 vs 0.5 on
the REAL `lassen_ca` plate (Mac) before merging: the knobs are tasteful-by-eye
decisions, and a synthetic DEM is useless for judging them (CLAUDE.md). Tune
`HAZE_KNOB_MAX` / the client defaults by eye if needed — they are deliberately the
only two free constants.

Step 4: Push the branch, open the PR (one PR for all of Phase 1), and record the
session per the repo's logging convention.

---

## Phase 2 — Task 8: extract the terrain window + the override hook

Files:
- Modify: `app/render.py` (`_paint_terrain` ~l.2160; the `shaded_relief` call ~l.2216;
  `rasterize` ~l.2665)
- Test: `tests/test_hero_plate.py` (new)

Step 1: Write the failing test

```python
# tests/test_hero_plate.py
"""The hero-plate seams that run WITHOUT Blender: the terrain window export, the
terrain override (Cycles pixels under Tecopa ink), and the CLI's honest refusals.
The Cycles render itself is a documented manual smoke on the operator's Mac."""
import numpy as np
import pytest

from app import render
from app.spec import CompositionSpec

REGION_DIR = "regions/lassen_ca"


def _spec_for(region_dir=REGION_DIR, **kw):
    import json, os
    cfg = json.load(open(os.path.join(region_dir, "region.json")))
    w, s, e, n = cfg["bounds"]
    cx, cy = (w + e) / 2, (s + n) / 2
    half_w, half_h = 4500.0, 6000.0
    base = dict(region_id=cfg["id"], crs=cfg["crs"],
                crop=(cx - half_w, cy - half_h, cx + half_w, cy + half_h),
                print_w_in=18.0, print_h_in=24.0,
                native_resolution_m=cfg["native_resolution_m"],
                tracks=[np.array([[cx - 1000, cy - 1000], [cx + 1000, cy + 1000]])],
                hotspots=[])
    base.update(kw)
    return CompositionSpec(**base)


def test_terrain_window_is_registration_true():
    import json, os
    cfg = json.load(open(os.path.join(REGION_DIR, "region.json")))
    spec = _spec_for()
    elev, res_m, shape = render.terrain_window(spec, 96, REGION_DIR, cfg)
    assert elev.shape == shape and elev.dtype == np.float32
    assert not np.isnan(elev).any()
    # the window covers the crop at the render's ground resolution
    assert res_m == pytest.approx(spec.ground_per_pixel(96), rel=1e-6)


def test_terrain_override_slots_under_ink_and_labels():
    import json, os
    cfg = json.load(open(os.path.join(REGION_DIR, "region.json")))
    spec = _spec_for()
    normal = render.rasterize(spec, 96, REGION_DIR, cfg)
    elev, res_m, shape = render.terrain_window(spec, 96, REGION_DIR, cfg)
    fake = np.zeros(shape + (3,), dtype=np.uint8)
    fake[..., 0] = 200                      # unmistakable red terrain
    hero = render.rasterize(spec, 96, REGION_DIR, cfg, terrain_override=fake)
    a = np.asarray(normal).astype(int)
    b = np.asarray(hero).astype(int)
    assert a.shape == b.shape
    assert not np.array_equal(a, b)         # the terrain really was replaced
    # the route ink survives identically: the gold pixels' positions match
    gold = np.array(spec.track_rgb)
    mask_a = (np.abs(a[..., :3] - gold).sum(axis=2) < 60)
    mask_b = (np.abs(b[..., :3] - gold).sum(axis=2) < 60)
    overlap = (mask_a & mask_b).sum() / max(1, mask_a.sum())
    assert overlap > 0.85                   # registration held under the swap


def test_override_default_changes_nothing():
    import json, os
    cfg = json.load(open(os.path.join(REGION_DIR, "region.json")))
    spec = _spec_for()
    assert np.array_equal(np.asarray(render.rasterize(spec, 96, REGION_DIR, cfg)),
                          np.asarray(render.rasterize(spec, 96, REGION_DIR, cfg,
                                                      terrain_override=None)))
```

Step 2: Run: `.venv/bin/python -m pytest tests/test_hero_plate.py -q`
Expected: FAIL — `AttributeError: module 'app.render' has no attribute
'terrain_window'` / unexpected keyword `terrain_override`.

Step 3: Implement in `app/render.py` (exact work, guided by the call site):

1. Inside `_paint_terrain`, the code that computes the padded DEM window and its
   `res_m` before the `rgb = shaded_relief(...)` call (~l.2216) moves into a new
   module-level function `terrain_window(spec, dpi, region_dir, cfg) ->
   (elev_f32, res_m, shape)`; `_paint_terrain` calls it (byte-identical refactor —
   same expressions, same order).
2. `_paint_terrain(... , terrain_override=None)`: when the override is not None,
   validate `override.shape[:2] == elev.shape` and `dtype == uint8` (raise
   `ValueError` otherwise), skip `shaded_relief`, and continue the chain with
   `rgb = override.astype("float32") / 255.0` — hydro, contours, and everything
   after paint exactly as before. When None (the default), nothing changes.
3. Thread the kwarg: `rasterize(..., terrain_override=None)` → `_paint_base(...,
   terrain_override=...)` → `_paint_terrain`. The BASE CACHE must not serve an
   override render or cache one: in the cached path, bypass the cache entirely when
   `terrain_override is not None` (the caller-supplied-plate-data precedent —
   `test_caller_supplied_plate_data_bypasses_the_cache` shows the pattern).

Step 4: Run: `.venv/bin/python -m pytest tests/test_hero_plate.py tests/test_base_cache.py -q`
Expected: PASS (the synthetic-plate hydration makes `regions/lassen_ca` renderable
on a fresh clone; the base-cache suite proves the bypass didn't disturb the cache).

Step 5: Commit

```
git commit -am "Let a caller supply the terrain the sheet is painted over

terrain_window() exposes the exact padded window and ground resolution
the relief renders from, and terrain_override slots a caller's pixels
under the same hydro, ink, labels and furniture -- registration-true by
construction because both sides share one window. Default None changes
nothing, and an override render bypasses the base cache both ways."
```

---

## Phase 2 — Task 9: the Blender scene script

Files:
- Create: `scripts/hero_scene.py`
- Test: `tests/test_hero_plate.py` (snapshot of the generated parameters)

Step 1: Failing test (append):

```python
def test_scene_params_are_registration_true(tmp_path):
    from scripts.hero_plate import scene_params
    spec = _spec_for()
    p = scene_params(spec, samples=256)
    crop_w = spec.crop[2] - spec.crop[0]
    crop_h = spec.crop[3] - spec.crop[1]
    assert p["ortho_scale"] == pytest.approx(crop_w)
    assert p["plane_size"] == (pytest.approx(crop_w), pytest.approx(crop_h))
    assert p["resolution"] == spec.pixel_size(300)      # the FINAL's pixels
    assert p["sun"]["azimuth_deg"] == 315.0 and p["sun"]["altitude_deg"] == 45.0
    j = _spec_for(light_mode="journey", sun_azimuth_deg=140.0, sun_altitude_deg=22.0)
    assert scene_params(j, samples=256)["sun"]["azimuth_deg"] == 140.0
```

Step 2: Run — Expected: FAIL (`scripts.hero_plate` does not exist; Task 10 creates
it — write `scene_params` there first, it is pure math with no Blender import).

Step 3: `scripts/hero_scene.py` — the file Blender executes. It reads one JSON
sidecar (written by the CLI) naming the heightmap EXR, the color-texture PNG, the
output path, and the scene parameters; it must import nothing from `app/` (it runs
inside Blender's own Python):

```python
# scripts/hero_scene.py
"""Runs INSIDE Blender (blender --background --python scripts/hero_scene.py -- args).
Builds the hero-plate scene from the sidecar JSON written by scripts/hero_plate.py:
a plane in crop metres displaced by the exported heightmap, the engine's own
hypsometric/biome colour draped as an emission-free texture, one sun with a real
angular size (penumbra), an orthographic top-down camera over the exact crop, and a
Cycles render with denoising. Deliberately not deterministic -- a hero plate is a
performance; the archival record stays the manifest inside the source PNG."""
import json
import math
import sys

import bpy

args = sys.argv[sys.argv.index("--") + 1:]
side = json.load(open(args[0]))

scene = bpy.context.scene
scene.render.engine = "CYCLES"
scene.cycles.samples = side["samples"]
scene.cycles.use_denoising = True
scene.render.resolution_x, scene.render.resolution_y = side["resolution"]
scene.render.image_settings.file_format = "PNG"
scene.render.image_settings.color_depth = "16"
scene.render.filepath = side["out"]

for obj in list(bpy.data.objects):        # empty the default scene
    bpy.data.objects.remove(obj, do_unlink=True)

w_m, h_m = side["plane_size"]
bpy.ops.mesh.primitive_plane_add(size=1.0)
plane = bpy.context.active_object
plane.scale = (w_m / 2.0, h_m / 2.0, 1.0)
bpy.ops.object.transform_apply(scale=True)

mat = bpy.data.materials.new("plate")
mat.use_nodes = True
mat.cycles.displacement_method = "DISPLACEMENT"
nt = mat.node_tree
bsdf = nt.nodes["Principled BSDF"]
bsdf.inputs["Roughness"].default_value = 1.0
color = nt.nodes.new("ShaderNodeTexImage")
color.image = bpy.data.images.load(side["color_png"])
nt.links.new(color.outputs["Color"], bsdf.inputs["Base Color"])
height = nt.nodes.new("ShaderNodeTexImage")
height.image = bpy.data.images.load(side["height_exr"])
height.image.colorspace_settings.name = "Non-Color"
disp = nt.nodes.new("ShaderNodeDisplacement")
disp.inputs["Scale"].default_value = side["elev_range_m"] * side["z_exaggeration"]
nt.links.new(height.outputs["Color"], disp.inputs["Height"])
nt.links.new(disp.outputs["Displacement"], nt.nodes["Material Output"].inputs["Displacement"])
plane.data.materials.append(mat)
plane.cycles.use_adaptive_subdivision = True
sub = plane.modifiers.new("subdiv", "SUBSURF")
sub.subdivision_type = "SIMPLE"

sun = bpy.data.objects.new("sun", bpy.data.lights.new("sun", "SUN"))
bpy.context.collection.objects.link(sun)
sun.data.energy = 4.0
sun.data.angle = math.radians(side["sun"]["angular_size_deg"])
az = math.radians(side["sun"]["azimuth_deg"])
alt = math.radians(side["sun"]["altitude_deg"])
sun.rotation_euler = (math.pi / 2 - alt, 0.0, -az)   # bearing az, height alt

cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
bpy.context.collection.objects.link(cam)
cam.data.type = "ORTHO"
cam.data.ortho_scale = side["ortho_scale"]
cam.location = (0.0, 0.0, side["elev_range_m"] * 4.0)
scene.camera = cam

bpy.ops.render.render(write_still=True)
```

Step 4: `python -m pyflakes scripts/hero_scene.py` is NOT possible (bpy import);
instead: `python -c "import ast; ast.parse(open('scripts/hero_scene.py').read())"`
Expected: silence.

Step 5: Commit

```
git add scripts/hero_scene.py tests/test_hero_plate.py
git commit -m "Write the scene Blender performs a hero plate from

One sidecar JSON in, one 16-bit PNG out: the crop as a displaced plane in
real metres, the engine's own colour draped over it, a sun with genuine
angular size for penumbra, and an orthographic camera whose scale IS the
crop width -- registration by construction, not calibration."
```

---

## Phase 2 — Task 10: the CLI

Files:
- Create: `scripts/hero_plate.py`
- Test: `tests/test_hero_plate.py` (refusals + params, no Blender)

Step 1: Failing tests (append):

```python
def test_cli_refuses_what_v1_does_not_do(tmp_path):
    from scripts.hero_plate import check_supported, HeroError
    for bad in (_spec_for(output_kind="wallpaper", screen_ppi=254.0),
                _spec_for(bleed_in=0.125), _spec_for(oblique=0.5)):
        with pytest.raises(HeroError):
            check_supported(bad)
    check_supported(_spec_for())            # a plain print sails through


def test_find_blender_reports_the_install_path_honestly(monkeypatch, tmp_path):
    from scripts.hero_plate import find_blender, HeroError
    monkeypatch.delenv("TECOPA_BLENDER", raising=False)
    monkeypatch.setenv("PATH", str(tmp_path))       # nothing on it
    with pytest.raises(HeroError) as e:
        find_blender(None)
    assert "blender.org/download" in str(e.value)
```

Step 2: Run — Expected: FAIL (module missing).

Step 3: `scripts/hero_plate.py`:

```python
#!/usr/bin/env python3
# scripts/hero_plate.py
"""Hero plate: perform a poster's terrain through Blender Cycles, then let the
engine paint its own water, route, markers, labels and furniture over it.

Operator CLI, deliberately not an app feature (design 2026-08-10): stills only,
print only, flat sheet only. The output carries the SOURCE manifest unchanged --
the file stays a save file (/api/reprint returns the archival edition); the hero
pixels are a performance, recorded by engine_version like any other build's.

    source .venv/bin/activate
    python scripts/hero_plate.py poster.png [--blender /path] [--samples 512] \
        [--z 1.0] [--out hero.png] [--allow-plate-mismatch]

Requires a Blender >= 4.2 LTS the operator installed (https://blender.org/download);
found via --blender, TECOPA_BLENDER, or PATH."""
from __future__ import annotations
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from PIL import Image

from app import provenance, regions, render
from app.spec import FINAL_DPI

BLENDER_MIN = (4, 2)
SUN_ANGULAR_SIZE_DEG = 3.0      # ~6x the real sun: soft, readable penumbra


class HeroError(SystemExit):
    """A refusal with its reason as the exit message (never a traceback)."""


def check_supported(spec):
    if spec.output_kind != "print":
        raise HeroError("hero plates are prints; render the poster spec, not a wallpaper")
    if spec.bleed_in > 0:
        raise HeroError("hero v1 renders the trim sheet only -- re-export without bleed")
    if spec.oblique > 0:
        raise HeroError("hero v1 renders the flat sheet; High relief (oblique) is its own projection")


def find_blender(cli_path):
    cand = cli_path or os.environ.get("TECOPA_BLENDER") or shutil.which("blender")
    if not cand or not os.path.exists(cand):
        raise HeroError(
            "No Blender found. Install it (free) from https://blender.org/download,\n"
            "then pass --blender /path/to/blender or set TECOPA_BLENDER.")
    out = subprocess.run([cand, "--version"], capture_output=True, text=True, timeout=30)
    first = (out.stdout or "").splitlines()[0] if out.stdout else ""
    try:
        ver = tuple(int(p) for p in first.split()[1].split(".")[:2])
    except Exception:
        raise HeroError(f"Could not read a Blender version from {cand!r} ({first!r})")
    if ver < BLENDER_MIN:
        raise HeroError(f"Blender {ver[0]}.{ver[1]} is older than the "
                        f"{BLENDER_MIN[0]}.{BLENDER_MIN[1]} LTS floor -- please upgrade")
    return cand


def scene_params(spec, samples):
    crop_w = spec.crop[2] - spec.crop[0]
    crop_h = spec.crop[3] - spec.crop[1]
    if spec.light_mode == "journey":
        az, alt = spec.sun_azimuth_deg, spec.sun_altitude_deg
    else:
        az, alt = 315.0, 45.0
    return {"ortho_scale": crop_w, "plane_size": (crop_w, crop_h),
            "resolution": spec.pixel_size(FINAL_DPI), "samples": samples,
            "sun": {"azimuth_deg": az, "altitude_deg": alt,
                    "angular_size_deg": SUN_ANGULAR_SIZE_DEG}}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("poster")
    ap.add_argument("--blender", default=None)
    ap.add_argument("--samples", type=int, default=512)
    ap.add_argument("--z", type=float, default=1.0, help="vertical exaggeration")
    ap.add_argument("--out", default=None)
    ap.add_argument("--allow-plate-mismatch", action="store_true")
    a = ap.parse_args(argv)

    blender = find_blender(a.blender)
    reg = regions.discover()
    spec, manifest, region_dir, cfg = provenance.spec_from_manifest(
        open(a.poster, "rb").read(), reg,
        allow_plate_mismatch=a.allow_plate_mismatch)
    check_supported(spec)

    with tempfile.TemporaryDirectory(prefix="tecopa-hero-") as td:
        elev, res_m, shape = render.terrain_window(spec, FINAL_DPI, region_dir, cfg)
        lo, hi = float(np.nanmin(elev)), float(np.nanmax(elev))
        norm = (elev - lo) / max(1e-9, hi - lo)
        height_exr = os.path.join(td, "height.exr")
        _write_exr_gray(height_exr, norm.astype("float32"))
        # the engine's own colour (hypsometric + biome), unlit: knock the light out
        # by rendering the spec with shadow/depth/looks zeroed at a working dpi and
        # upsampling -- Cycles supplies ALL the light in a hero plate
        color_png = os.path.join(td, "color.png")
        _write_color_texture(color_png, spec, region_dir, cfg, shape)
        side = dict(scene_params(spec, a.samples))
        side.update({"height_exr": height_exr, "color_png": color_png,
                     "elev_range_m": hi - lo, "z_exaggeration": a.z,
                     "out": os.path.join(td, "cycles.png")})
        side_path = os.path.join(td, "scene.json")
        json.dump(side, open(side_path, "w"))
        print(f"Rendering {side['resolution'][0]}x{side['resolution'][1]} px "
              f"at {a.samples} samples -- this is Cycles, expect minutes-to-hours...")
        subprocess.run([blender, "--background", "--factory-startup", "--python",
                        os.path.join(os.path.dirname(__file__), "hero_scene.py"),
                        "--", side_path], check=True)
        cycles = np.asarray(Image.open(side["out"]).convert("RGB"))
        cycles = np.asarray(Image.fromarray(cycles).resize(
            (shape[1], shape[0]), Image.LANCZOS))
        sheet = render.rasterize(spec, FINAL_DPI, region_dir, cfg,
                                 terrain_override=cycles)
        out = a.out or os.path.splitext(a.poster)[0] + "_hero.png"
        provenance.embed_manifest(sheet, manifest, out)   # the SOURCE manifest, unchanged
        print(f"Hero plate written: {out}\n"
              f"The file still reprints its archival edition -- the hero pixels are a performance.")


if __name__ == "__main__":
    main()
```

`_write_exr_gray` / `_write_color_texture` and the exact `provenance` entry points
are resolved at implementation time against `provenance.py`'s real API (the manifest
re-embed helper the reprint path already uses; if EXR writing needs a dependency,
write a 16-bit grayscale PNG instead and set the displacement scale accordingly —
Blender reads both). These are the two knowingly-open joints in this plan; everything
else above is anchored code.

Step 4: Run: `.venv/bin/python -m pytest tests/test_hero_plate.py -q`
Expected: PASS (refusals + params + override tests; no Blender invoked).

Step 5: Commit

```
git add scripts/hero_plate.py tests/test_hero_plate.py
git commit -m "Drive a hero plate end to end from one reprintable PNG

Read through the one untrusted door, refuse what v1 honestly does not do,
export the exact window Cycles displaces, and composite the engine's own
ink over the performance. The output carries the source manifest
unchanged: the save file stays the save file."
```

---

## Phase 2 — Task 11: operator docs + manual smoke + PR

Step 1: README gains a "Hero plates (Blender)" section: install Blender (free,
blender.org), the one command, expected runtimes (CPU: possibly hours at 512
samples; Apple Silicon Metal: minutes), and the honesty paragraph (not
deterministic, not the archival record, the manifest inside still is).

Step 2: Manual smoke on the Mac (documented in the PR, not CI): run against a real
`lassen_ca` poster at `--samples 128` first; check registration by flipping between
the archival and hero files (the route must sit identically); then a full-samples
render for the eyeball verdict.

Step 3: Full fast tier + push + PR (second PR), session log per convention.

---

## Verification Matrix (what proves each promise)

| Promise | Held by |
|---|---|
| Old posters reprint untouched | server defaults 0.0 + `test_zero_knobs_are_byte_identical_to_an_empty_registry` + frozen-manifest suite |
| Determinism (invariant 3) | seeded/pure passes; identical-render assertions in `test_looks.py` |
| One spec, many sizes | `test_both_knobs_are_dpi_stable`; every length via `res_m`/`frame.px` |
| No double-apply with depth | weight composition + `test_soft_light_composes_with_depth…` |
| Registry/UI honesty | `tests/test_static_registry.py` (one help per control) + palette keywords |
| Hero registration | shared `terrain_window` + `test_terrain_override_slots_under_ink_and_labels` |
| Hero honesty | source manifest embedded unchanged; README + CLI output copy |
| Cache correctness | mask-derived keys untouched; override bypasses; existing cache suites |
