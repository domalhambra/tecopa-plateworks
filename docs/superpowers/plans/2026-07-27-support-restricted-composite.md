# Restrict the ink composite to its support

Date: 2026-07-27 · lands on `5a0094e` (route-ink cache) · Mac-local, real `lassen_ca` plate

Third and last step of the proof-loop optimization arc, after the base-layer cache
(`fb634b2`, `1a4ea88`) and the route-ink cache (`5a0094e`). Unlike either cache, this one
speeds up **the final** as well as the proof: it is on the painter, not the reuse path.

## The gate, measured first

Both caches are proof-only, and with terrain and ink both served from cache, what is left
of a warm furniture knob is `_composite_ink_layer` — two full-sheet alpha blends,
`img*(1-op) + col*op`, over a raster that is non-zero on ~1% of a poster's pixels.

Measured on this Mac, real `lassen_ca`, 18x24 at 200 dpi, weave on, three crossing dated
journeys, both caches live:

| | wall | composite | share |
|---|---|---|---|
| cold | 8.97s | 0.52s | 5.8% |
| warm furniture knob | 1.29s | 0.51s | **39.5%** |
| terrain knob (base miss) | 8.33s | 0.52s | 6.2% |

Worth recording that the earlier estimate for this step — taken on a 4-core container —
read "cold 47.7s, furniture knob 7.7s, most of that 7.7s arithmetic over empty sheet."
This Mac is ~6x faster and the composite is 39.5% of a warm knob here, not "most" of it.
The lever was real; its size was overstated. Measure the gate on the host you care about.

## Why it is byte-identical, not merely close

The same float argument the sparse packing already rests on. Off the ribbon
`gaussian_filter` has finite support, so `op` is exactly `0.0` — not small, zero. The
blend there is `img * 1.0 + col * 0.0`, which **is** `img` in float32. So the pixels off
the support cannot move, and skipping them cannot change the picture.

Two details checked rather than assumed:

- **Signed zero.** `-0.0 * 1.0 + 0.0` flips to `+0.0`, which the dense form would do and
  the restricted form would not. Unreachable here: `img` is `uint8/255.0`, so the only
  zero it can hold is `+0.0`, and the final `uint8` cast collapses both anyway.
- **NaN.** `NaN != 0` is True, so a NaN pixel is *inside* the support and gets blended
  exactly as the dense form blends it. Consistent, not merely safe.

`_ink_support` is extracted rather than inlined twice, because `_ink_pack` drops `gf` and
the colour field off *its* support and the composite is only sound in doing so if it
blends over exactly the same pixels. Two drifting definitions of "the support" is the bug
the shared function forecloses; a test asserts they agree.

## Proof

Inertness was proven **before** measuring the win, because a change to the most exacting
painter in the engine either is byte-identical or needs a revision (`relief_rev` /
`profile_rev` recipe in `docs/relief-passes.md`), never a merge on faith.

A git worktree at `5a0094e` and the changed tree were rendered through the *same* 19-spec
matrix — spanning the casing branch (halo off / default / ceiling), the colour-field
branch (none / elevation / grade), the weave (one layer per journey vs one summed), the
worn-width gate (1 / 2 / 3 journeys), the oblique warp, the bleed seam and both light
modes — with SHA256 over raw pixel bytes, both reading the same real plate:

```
96  dpi   MATRIX_SHA bf202466d1d3e45779cf457d3186ba4464bf0d113be8286bc54dd48a523bf898
300 dpi   MATRIX_SHA 5c69a2ed4768d1e062fa0137a4d0be1f36558bb237622b507120f000a6bc2957
```

Identical on both sides at both tiers — the proof tier and the *final* tier, where the
forever-contract actually lives. Note 19 cases collapse to **17 distinct** posters:
`flat` and `colour_none` are the defaults, so they equal `plain`. No revision is needed
and `MANIFEST_VERSION` stays 1: nothing about the file changed.

## Result

| | before | after |
|---|---|---|
| composite | 0.51s | **0.04s** (−92%) |
| warm furniture knob | 1.29s | **0.87s** (−33%) |
| cold / final | 8.97s | 8.64s (−4%) |

## Tests

`tests/test_hot_paths.py` section 6, which keeps the dense blend inline verbatim and
asserts the restricted one agrees — the same shape as the four vectorization rewrites
above it. Four claims, deliberately not redundant:

1. the dense blend changes **nothing** off the support (the claim the restriction rests
   on, asserted against the *old* code — if this ever fails, the restriction is unsound);
2. restricted == dense, bit-for-bit, across eight branch combinations;
3. the composite and the packing share one support definition;
4. `_ink_tracks` still does not mutate the base sheet — the composite now works in place,
   and a time-lapse inks many journey prefixes onto one base.

Plus two edge cases surfaced by the adversarial pass: an empty support (a spec that inks
nothing), and a **non-contiguous sheet** — `reshape(-1, 3)` is a view only on a
contiguous array, and without the guard every drop of ink would land in a discarded copy
and vanish silently. That test was verified to fail with the guard removed, so it is not
vacuous.

## Not done here

**Threading the support through the cache hit — measured, declined.** `_ink_support` is
7.7 ms/call on an 18x24 at 200 dpi (1.25% support), so recomputing it costs ~23 ms of the
40 ms the composite now takes: over half of what is left *of the composite*. On a hit
`_ink_unpack` already holds the exact indices, so carrying them on `_InkLayer` would
reclaim most of it. Not done, because it is ~23 ms of an 870 ms warm knob — 2.6% — in
exchange for a new optional field and a coupling between unpack and composite. Recorded so
the next person does not have to re-measure it.

The remaining ~0.87s of a warm knob is labels + overlays + profile, not the route. That is
the next gate to measure if the proof loop needs to get faster still — and it is a much
bigger one than anything left in the ink chain.
