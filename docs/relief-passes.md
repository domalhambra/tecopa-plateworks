# Adding a relief technique

How a new terrain-rendering module gets into the picture without editing the function
every shipped poster's pixels come out of.

## Why there is a seam at all

Three techniques have been added to `relief.shaded_relief` so far — terrain depth
(multidirectional light, multiscale texture, aerial perspective, salt pan), cast
shadows + sky occlusion, and Journey Light (a golden split-tone from the journey's own
sun). Each arrived the same way: three or four new parameters on the signature, a new
`if knob > 0:` block spliced into the middle of the composition chain, and a matching
edit at the call site in `render._paint_base`.

That is a lot of pressure on one function. `shaded_relief` is where every poster ever
printed got its terrain, and the forever-contract says those bytes must survive every
future upgrade. The more the chain is edited in place, the more each edit has to be
re-argued against the frozen fixtures.

So the fourth technique registers instead.

## The three moving parts

**1. A knob on the spec.** Same rules as every other picture decision: a field on
`CompositionSpec` whose default is the pre-feature no-op, bounds in `STYLE_BOUNDS` if
it is numeric, and *omitted from the manifest at that default* (`app/provenance.py`) so
every existing poster re-stamps byte-identically. Nothing new here — this is the
additive-defaults rule the whole file format rests on.

**2. A reader, so the knob reaches the relief layer.** `relief.py` deliberately knows
nothing about `CompositionSpec` — it is the lower layer. Register a reader in
`render.py` and the value arrives in `frame.extras`:

```python
@relief_extra("hachure")
def _hachure_knob(spec):
    return spec.rock_hachure          # 0.0 = off, the pre-feature default
```

**3. The pass itself.** A function `(array, frame) -> array` registered at a stage:

```python
def _rock_hachure(img, frame):
    """Swiss-style rock drawing on the steeps (Imhof / swisstopo)."""
    strength = frame.extras["hachure"]
    slope, aspect = frame.terrain()          # already computed — do not re-gradient
    steep = np.clip((slope_grade(slope) - 0.6) / 0.4, 0.0, 1.0)
    ...
    return img

relief.register_relief_pass(
    "grade", "rock-hachure", _rock_hachure,
    enabled=lambda frame: frame.extras.get("hachure", 0.0) > 0,
)
```

That is the whole integration. `shaded_relief` is not touched, so no shipped poster can
move, and the frozen `manifest_*_v1.json` fixtures cannot be disturbed by the plumbing.

**And a slider, if the studio should expose it.** `app/static/controls.js` is the same
kind of registry on the front end — one entry gives the inspector row, the command
palette, preset diffing, "reset to default", and the proof-staling rule. Mirror the
`STYLE_BOUNDS` range and the spec default so the client and the server agree.

So end to end, a new technique is: a spec field, a manifest omission at its default, a
`@relief_extra` reader, a `register_relief_pass` call, and one `CONTROLS` entry.

## The stages

Passes run in composition order. Pick the latest stage that can still express the
technique — the later it runs, the less of the existing chain it can disturb.

| Stage | It receives | Runs |
|---|---|---|
| `color` | base RGB, 0..1 | after the hypsometric ramp and the biome tint, before any light |
| `light` | the scalar light plane | after hillshade / valley / cast shadow / AO, before light meets colour |
| `finish` | composed RGB, 0..1 | after the texture blend and the atmosphere, before the tonal curve |
| `grade` | composed RGB, 0..1 | after the tonal curve, before the paper grain |

A pass **may write its argument in place** — the whole engine composites in place now,
and a pass that allocated a fresh sheet would hand that saving back (a 300 dpi 18×24
RGB plane is ~260 MB).

## What the frame gives you

`ReliefFrame` carries the terrain *and every expensive intermediate the core already
paid for*. Reach for these before computing your own:

- `frame.elev` — NaN-repaired float32 elevation on the padded render window
- `frame.norm` — 0..1 elevation over the plate's range
- `frame.terrain()` — `(slope, aspect)`, computed once and shared
- `frame.light_from(az, alt)` — a hillshade on that shared field, any bearing
- `frame.tex`, `frame.val` — the texture high-pass and valley-depth fields
- `frame.cast`, `frame.ao` — the ray-marched cast shadow and sky occlusion
  (`None` when the shadow knob is off — check before using)
- `frame.res_m`, `frame.px(metres)` — the resolution, and the ground→pixel conversion
- `frame.seed` — the only legal source of randomness

## The four rules a pass must keep

These are the engine's invariants, restated for this seam. A pass that breaks one is a
bug even if the sheet looks good.

1. **Size everything in ground metres, never pixels** — go through `frame.px()`.
   A pixel-sized feature looks bold in the proof and vanishes in the final. This bug
   class has shipped more than once.
2. **Be deterministic.** Any RNG derives from `frame.seed` (see `relief.grain` for the
   pattern). Same spec + seed → identical image, forever.
3. **Be a strict no-op at the pre-feature default.** Not "almost the same" — the
   `enabled` predicate must be false, so the pass never runs and never touches a byte.
4. **Never read plate data.** The frame is the whole world. Region-level assets are
   `render`'s business; a pass that reaches for one breaks reprint-from-manifest.

## Verifying it

`tests/test_relief_passes.py` covers the seam itself: the registry ships empty, an
empty registry is byte-identical, a registered no-op changes nothing, each stage
reaches the picture, and the frame carries what it promises. For a new pass, add:

- a byte-identity test at the pre-feature default (the whole point of rule 3);
- a proof-vs-final MAD test if the pass draws anything with a size (rule 1) — see
  `test_render.py::test_proof_relief_is_a_faithful_scale_of_final` for the shape of it;
- a golden fixture only once the look is settled.

Run `pytest -q -m "not slow"` for the fast tier, then the full suite before release.
