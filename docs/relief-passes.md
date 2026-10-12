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

So end to end, a new technique is: a spec field, a `@relief_extra` reader, a
`register_relief_pass` call, and one `CONTROLS` entry.

> **Two corrections since this was written.** The *manifest omission* step above is
> retired: `serialize.spec_to_json` now emits **every** field, so there is nothing to
> omit at a default — read-tolerance (`spec_from_json` drops unknowns and defaults
> missing fields) is what keeps old files opening, and it needs no cooperation from a
> new pass. What still binds is the pre-feature default itself: the `enabled` predicate
> must be false there, so the pass never runs (rule 3 below).
>
> And the registry no longer ships **empty**. `app/looks.py` (v1.13) is the seam's first
> shipped module, and it is the worked example this document describes in the
> hypothetical: two spec knobs (`soft_light`, `haze_strength`), two `@relief_extra`
> readers, a `"light"` pass that re-blends the hillshade toward the MDOW
> multi-directional light as an exact multiplicative correction, and a `"finish"` pass
> that sinks low ground into the cool Imhof haze. Both are gated at 0.0, so the shipped
> registry is still a strict no-op at the spec defaults. Read it alongside this page —
> it is shorter than the explanation.

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
and a pass that allocated a fresh sheet would hand that saving back. A 300 dpi 18×24
sheet is 48.8 million pixels on its padded window, so one RGB plane is 585 MB and one
scalar plane is 195 MB.

**The array a pass returns belongs to the chain.** The chain writes into it: the colour
plane becomes the lit sheet in its own buffer, the tonal curve runs in the plane the
`finish` stage hands back, and the grain is multiplied into the plane the `grade` stage
hands back. So return the argument, or a new array that nothing else holds. Do not
return an array that a cache or a module keeps, and do not keep the argument to read
after the pass returns. At `color` and `finish` the chain copies a read-only array or a
view into another array before it writes, and that render loses the saving. At `grade`
it writes what comes back, as it always has.

## What the frame gives you

`ReliefFrame` carries the terrain *and every expensive intermediate the core already
paid for*. Reach for these before computing your own:

- `frame.elev` — NaN-repaired float32 elevation on the padded render window
- `frame.norm` — 0..1 elevation over the plate's range
- `frame.terrain()` — `(slope, aspect)`, computed once and shared by the core's lights
  and by every `color` and `light` pass. The core frees it after its last light (see
  Memory), so a `finish` or `grade` pass that calls it pays for one more gradient pass.
  The values are the same ones
- `frame.light_from(az, alt)` — a hillshade on that shared field, any bearing
- `frame.tex`, `frame.val` — the texture high-pass and valley-depth fields
- `frame.cast`, `frame.ao` — the ray-marched cast shadow and sky occlusion
  (`None` when the shadow knob is off — check before using)
- `frame.res_m`, `frame.px(metres)` — the resolution, and the ground→pixel conversion
- `frame.seed` — the only legal source of randomness

**Wide blurs go through `relief._blur(array, sigma_px)`, not `gaussian_filter`.**
scipy's kernel is O(σ) taps per pixel per axis, and cartographic radii are wide — the
sky-occlusion pass reaches 3200 ground metres. `_blur` computes anything wider than
`BLUR_PYRAMID_SIGMA_PX` on a decimated pyramid whose grid lands on a *fixed ground
resolution*, so it stays DPI-stable (invariant 1) while costing a fraction of the
exact filter.

## Memory

A final holds its whole padded window in memory, so every full-sheet array counts. A
scalar float32 plane is 4 bytes a pixel and an RGB plane is 12. The padded window is
1.25 times the output, so that is 5 and 15 bytes for each output pixel. On the largest
sheet a set renders (59×22 in at 300 dpi, 116.8 megapixels) one RGB plane is 1.76 GB.

Measured on 2026-10-11 with tracemalloc on a 17×22 in final of `rifle_aspen`, with
land cover, contours and place names on, in bytes of live arrays for each output pixel:

| Sheet | Before the trim | After | Where the peak is now |
|---|---|---|---|
| The spec defaults | 135.5 | 75.3, 76.5 and 77.3 (1, 2 and 4 relief workers) | the four heavy passes and the light they build |
| Journey Light with the golden grade | 160.6 | 80.4 | the journey sun's hillshade |
| Terrain depth on (`elko_bonneville`) | 135.5 | 75.3 | the four heavy passes and the light they build |
| High relief 0.5 | 142.7 | 79.3 | the four heavy passes and the light they build |
| `soft_light` 0.35 and `haze_strength` 0.15 | 135.5 | 95.3 | the soft-light pass |

The old peak was the tonal curve, and only about 25 of its bytes were in use there. The
soft-light pass was not changed: its own planes are now the peak of a sheet that uses
it.

The chain keeps these rules, and a new pass must keep them too:

- **Composite an RGB plane in bands of rows**: `for rows in relief._bands(img.shape[0])`.
  The temporaries of the expression are then the size of a band (256 rows), not of the
  sheet. A block may be banded only when each output pixel depends on that pixel's own
  inputs and on nothing else: arithmetic, a clip, a sum along the channel axis,
  `np.interp`. A blur and a gradient read neighbours. A std, a percentile, a min and a
  max read the whole array. An RNG draw depends on the shape it is asked for. Compute
  those for the whole sheet first, and slice the result in the loop.
  `test_the_band_size_does_not_move_a_pixel` in `tests/test_relief.py` holds the rule:
  one band and many bands must give the same bytes. Make sure it reaches a new banded
  block.
- **Do not give a band of a scalar plane a name** (`wb = weight[rows]`). The name
  outlives the loop, and the view keeps the whole plane alive after its `del`. Index
  the plane where it is used.
- **Delete a full-sheet plane at its last reader**, and say in a comment what the
  `del` saves.
- **The frame's own planes are not freed early.** `elev`, `norm`, `tex`, `val`, `cast`
  and `ao` are 30 bytes for each output pixel from the fan-out to the end, because the
  registry cannot know which pass reads which. The core frees only the slope and aspect
  field (10 bytes), and `frame.terrain()` builds it again for a pass that asks.
- **The land cover is handed over as a function.** `relief.base_colour` calls it once
  and its two planes (20 bytes) are freed when the blend returns.

tracemalloc counts live arrays. The process footprint is higher: on macOS the allocator
keeps freed blocks counted against the process, and the libraries allocate outside
Python.

## When a change moves pixels on the existing chain

A different dtype, a cheaper filter, a retuned constant — these change posters already
printed when they are re-rendered. Under the retired forever-contract they needed a
revision gate; since 2026-07-27 (`docs/superpowers/specs/2026-07-27-retire-the-forever-
contract-design.md`) they simply ship: `engine_version` in the manifest records which
build painted a file, and drift is recorded rather than prevented. What such a change
still owes: determinism within the build (invariant 3), DPI-stability (a faithful
proof→final scale), and an honest bounded-difference check against the previous chain
so the change is a decision, not an accident.

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

`tests/test_relief_passes.py` covers the seam itself: it pins exactly what ships, tests
the mechanics against an emptied registry (an empty registry is byte-identical, a
registered no-op changes nothing, each stage reaches the picture, the frame carries what
it promises), and restores the shipped passes afterwards. `tests/test_looks.py` covers
the shipped module, and is the template for a new one. For a new pass, add:

- a byte-identity test at the pre-feature default (the whole point of rule 3);
- a proof-vs-final MAD test if the pass draws anything with a size (rule 1) — see
  `test_render.py::test_proof_relief_is_a_faithful_scale_of_final` for the shape of it;
- a golden fixture only once the look is settled.

Run `pytest -q -m "not slow"` for the fast tier, then the full suite before release.
