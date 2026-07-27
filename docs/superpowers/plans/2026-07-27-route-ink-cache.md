# Route-ink cache — implementation plan

Goal: stop re-inking a route that did not change. With terrain cached (Phase 1/2 of
`2026-07-26-base-layer-cache.md`), the route ink is what is left of a warm knob, and
for most knobs it is pure waste.

Architecture: the same shape as Phase 2, one layer up. `_composite_ink_layer` is split
at the seam where it first touches the sheet: everything above the seam (the coverage
rasters, the blurs, the grain, the colour field) is **base-independent** and cacheable;
everything below is two alpha blends against the live base. The key is derived by
**masking** known-inert spec fields, so a field added later lands in the key by default
and the worst case is a miss.

Tech Stack: Python 3.14, numpy, scipy, Pillow, pytest.

---

## Measurements this plan is built on

Taken on `lassen_ca`, 18×24 (the plate's practical worst case — the 10 m/px floor means
the crop cannot be narrower than 36 km), 3 journeys, synthetic DEM, 4-core container.
Absolute seconds are container-slow; the ratios and the *fractions* are what transfer.

**Where a warm knob goes now** (terrain served from the base cache, 200 dpi):

| | flat | High relief (oblique 0.6) |
|---|---|---|
| `_base_layer` (cached terrain + per-request labels) | 1.24 s | 1.48 s |
| `_paint_journey` | **10.44 s (89%)** | **11.87 s (89%)** |
| ⤷ `_ink_tracks` | 7.98 s | 10.62 s |
| ⤷ `_draw_termini` | 0.06 s | 0.10 s |

Inside one `_composite_ink_layer` pass: `_coverage` 0.25 / 0.66 s, its feather blur
0.47 / 0.53 s, `grain()` 0.24 / 0.32 s, **one** alpha blend 0.41 / 0.78 s (there are
two per layer, and every one of these runs 3–4 times per layer).

**How many knobs leave the ink alone** — the measurement this plan gates on. Perturbing
each of the base cache's 26 masked fields and repainting over a *fixed* base, with a
three-journey spec (a single journey makes `track_weave` and `track_days` no-ops and
they pass vacuously):

- **17 of 26** leave `_paint_journey` byte-identical: `marker_ring`,
  `photo_frame_style`, `photo_box_in`, `keyline`, `hotspots`, `labels`, `label_place`,
  `title_text`, `title_pt`, `label_pt`, `credit_text`, `edition`, `compass`,
  `furniture_scale`, `profile`, `profile_height_in`, `profile_rev`.
- 9 change it: `track_rgb`, `track_halo`, `track_max_darken`, `track_color_by`,
  `track_weave`, `marker_diameter_in`, `tracks`, `track_days`, `track_width_pt`.

That is a majority, not a handful, so the second layer is worth building.

Two of those 9 are recoverable by choosing the seam carefully, and one by choosing the
*cut point* carefully — see "What the seam buys" below. The result is **20 of 26**.

**The rasters are 99% zeros.** After the feather blur, 0.96% (flat) / 0.98% (oblique)
of pixels are non-zero — a route ribbon is a hairline on a 17.3 MP sheet. One dense
float32 plane is 69 MB; the same plane stored on its support is ~1 MB. That decides the
storage format and dissolves the memory objection outright.

---

## What the seam buys, and why it sits where it does

`_composite_ink_layer` currently computes and blends in one function. Split it:

```
_ink_layer(...)  -> the base-independent rasters      (cached)
_composite_ink_layer(img, spec, layer) -> two blends  (per request)
```

The seam is placed *below* three cheap scalar operations that were previously fused
into the expensive half, which is what recovers three more knobs:

| kept out of the layer | why it can be | knob recovered |
|---|---|---|
| `spec.track_halo` multiply | `casing_op = track_halo * clip(cas)` — the raster `cas` does not depend on the slider's *value* | `track_halo` |
| `spec.track_max_darken` clip | `op = clip(op_raw, 0, track_max_darken)` — applied after the layer | `track_max_darken` |
| terminus pins | `_draw_termini` reads `marker_diameter_in` but is outside `_ink_tracks` entirely | `marker_diameter_in` |

`track_rgb` stays in the key: with `track_color_by != "none"` it is the swatch
background *and* the off-DEM fallback inside `_track_color_field`, so it genuinely
reaches the layer. Masking it only when colouring is off would reintroduce exactly the
conditional mask Phase 2 dissolved, for one discrete swatch picker. Not worth it.

`track_halo == 0` skips the casing raster entirely, so the key carries the **boolean**
`track_halo > 0`, not the value.

So the ink key masks **20 of 26**: the 17 above plus `track_halo`,
`track_max_darken`, `marker_diameter_in`. Left in the key: `track_rgb`,
`track_color_by`, `track_weave`, `tracks`, `track_days`, `track_width_pt`.

### Why storage is sparse

The layer is stored on the **union support** of `cas != 0` and `op_raw != 0`, as flat
indices plus values, and expanded back to dense on read. Three reasons it is exact:

- `gaussian_filter` has finite support (`truncate=4.0`), so the coverage rasters are
  *exactly* 0.0 outside the ribbon, and `1 - exp(-K·0)` is exactly 0.0.
- Where `op == 0` the blend is `img*1.0 + col*0.0 == img` in float32, so anything
  stored (or not stored) off-support is irrelevant — `gf` and the colour field are only
  ever multiplied by `op`, and both are finite.
- The support is found from the *actual* dense arrays, not from theory, so
  `expand(sparse) == dense` is an assertable identity rather than an argument.

At ~1–2% support one entry is ~5–10 MB instead of ~200–400 MB dense. A route dense
enough to push the support past ~75% would be larger sparse than dense; the byte budget
refuses an oversized entry, and the refusal is logged rather than silent.

---

## File map

| File | Responsibility |
|---|---|
| `app/basecache.py` **(modify)** | Docstring only: the store now backs two layers. The `BaseCache` LRU is reused as-is. |
| `app/render.py` **(modify)** | `_InkLayer`, `_ink_layer` (extracted), `_composite_ink_layer` (blends only), `_ink_layers` (the cached list), `INK_KEY_MASK_ALWAYS`, `ink_cache_key`, and `ink_cache=` on `_ink_tracks` / `_paint_journey` / `rasterize`. |
| `app/main.py` **(modify)** | The `INK_CACHE` instance and its budget env var; wired into the two proof paths only. |
| `tests/test_ink_cache.py` **(new)** | The sparse round-trip, the mask contract (both the enumerating guard and the direct per-field byte-identity test), cached-vs-cold pixel equality, and the end-to-end proof hit. |
| `tests/conftest.py` **(modify)** | Classify the full-render ink-cache tests as `slow`. |
| `CLAUDE.md` **(modify)** | One line in the repo map. |

---

## Tasks

1. **Extract `_ink_layer`** — pure refactor, no cache. Prove inert against the golden
   poster matrix *before* wiring anything (the hard-won rule from Phase 2).
2. **The sparse `_InkLayer`** — encode/expand, with a round-trip equality test.
3. **The key and its mask contract** — `INK_KEY_MASK_ALWAYS`, `ink_cache_key`, the
   dataclass-enumerating guard, and the direct test that perturbing each masked field
   leaves `_ink_layer` byte-identical. The second is the one that can catch a wrong
   mask entry; the first only proves the mask is self-consistent.
4. **Route `_ink_tracks` through the cache** — `ink_cache=None` is the pre-cache path
   exactly, so `timelapse`, `mockups`, the wallpaper bundle and the final are untouched
   by construction. An explicit `groups` (a time-lapse prefix) is not cacheable and is
   refused, the `hydro is not None` precedent.
5. **Wire the two proof paths** — `TECOPA_INK_CACHE_MB`, default sized against the
   draft+refine **pair** (the 0-hits-out-of-4 lesson).
6. **Classify, document, measure.**

---

## Risks and how they are covered

| Risk | Cover |
|---|---|
| A spec field added later isn't classified and the cache serves stale ink | Mask-based key (unclassified ⇒ in the key ⇒ miss) + the dataclass-enumerating test |
| A wrong mask entry (the enumerating test can't catch this) | A direct test: perturb each masked field, repaint `_ink_layer`, assert byte-identical |
| The sparse encoding loses a value | Round-trip test asserts `expand(encode(dense))` is byte-identical to `dense`, on a real 3-journey layer |
| The split itself moves pixels | Proved inert before the cache is wired: digest matrix vs. a worktree at the previous commit, plus the golden matrix and the orphan drill |
| The ink cache hits while the base misses | Sound by construction — the layer depends on `ctx`, and `ctx` is a pure function of the base key's inputs, which are a component of the ink key |
| Memory | Sparse storage (~5–10 MB/entry), own byte budget, `TECOPA_INK_CACHE_MB=0` disables |

---

---

# Validation — what real-size measurement found

Run on an 18×24 of `lassen_ca` (synthetic DEM, 4-core container), three journeys, weave
on. Absolute seconds are container-slow; the ratios transfer.

| | cold | furniture knob | halo slider | width slider |
|---|---|---|---|---|
| plain, 96 dpi | 7.41 s | 1.63 s (4.5×) | 1.32 s (5.6×) | 2.05 s (3.6×) |
| plain, 200 dpi | 47.74 s | 7.72 s (6.2×) | 7.53 s (6.3×) | 17.00 s (2.8×) |
| High relief, 96 dpi | 10.24 s | 1.41 s (7.3×) | 1.44 s (7.1×) | 2.84 s (3.6×) |
| High relief, 200 dpi | 52.58 s | 9.97 s (5.3×) | 8.95 s (5.9×) | 19.35 s (2.7×) |

The width slider is the control: it is a route knob, so the terrain still hits and the
ink still misses, and its speedup is what the base cache alone already bought. The gap
between it and the furniture knob — 17.0 s → 7.7 s at 200 dpi — is this change.

**The budget had to be sized against the journey count, not the sheet.** This is the
same shape of mistake the base cache made once, found the same way. A weave stores one
strand per journey, so the entry grows with the chronicle:

| journeys | 96 dpi draft | 200 dpi refine | pair | dense would be |
|---|---|---|---|---|
| 1 | 0.4 MB | 2.2 MB | 2.6 MB | 255 MB |
| 3 | 1.4 MB | 6.7 MB | 8.1 MB | 765 MB |
| 10 | 4.6 MB | 22.4 MB | 27 MB | 2552 MB |
| 25 | 11.6 MB | 56.7 MB | **68 MB** | 6378 MB |
| 50 | 23.2 MB | 113.1 MB | **136 MB** | 12757 MB |

The first default, 64 MB, was picked from the 3-journey case and would have **refused a
25-journey chronicle outright** — the cache present, healthy-looking, and buying
nothing. Raised to 256 MB, which covers a 50-journey pair with room for a second
composition; past roughly 90 journeys at 200 dpi the pair exceeds it and the entry is
refused rather than thrashed, which now logs `event=basecache.refuse`.

The dense column is also the justification for the support-indexed storage in one
number: at 50 journeys the packed form is ~1% of the dense one, which is the difference
between a cacheable weave and an uncacheable one.

Still outstanding, and only doable on the Mac: the by-eye half — that the proof still
predicts the print on a *real* DEM — and re-running the orphan drill against real
plates, which has not happened since the base-layer cache landed in `fb634b2`.

## Not built here — the next lever

The blends themselves are the remaining cost, and they too are ~99% wasted: a full-sheet
`img*(1-op) + col*op` over a raster that is non-zero on 1% of pixels. Restricting the
composite to the support is byte-identical by the same float argument used above, and
unlike this cache it would speed up **the final** as well (39 MP at 300 dpi). It is a
larger and more delicate change to the most exacting painter in the engine, so it is
recorded here with its measurement rather than folded into this plan.
