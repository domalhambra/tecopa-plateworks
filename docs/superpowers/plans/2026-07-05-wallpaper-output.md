# TrailPrint — Desktop & Mobile Wallpaper Output (design + implementation plan)

_2026-07-05 · Status: **implemented** (2026-07-06, all four phases; verified by the
test suite and a Playwright end-to-end drive of the wizard). The "Decision points for
Dom" defaults below shipped as chosen and remain cheap to revise. Still open:
by-eye wallpaper goldens on a machine with real DEMs (this container renders
synthetic terrain only)._

---

## Context — why this feature

Every visual decision in TrailPrint to date has been tuned by eye on a backlit sRGB
screen, while the shipping product is paper (see the print-calibration gap discussed
2026-07-05). Wallpapers invert that liability into an asset: **screens are the one
medium the current look is already calibrated for.** The subtle tonal work — terrain
depth, aerial haze, salt-pan lift, cast shadows, grain — renders on a client's monitor
or phone exactly as it was approved.

Product intent: a client who buys (or composes) a poster can also carry the same
journey on every screen they own. One accepted composition → a bundle of
pixel-perfect PNGs for their monitor, laptop, and phone.

## The one design idea: a screen is a sheet with a known ppi

The engine's deepest invariant is *physical units, never pixels* — and a screen **has**
physical units. A 27″ 4K monitor is a 23.5×13.2 in sheet at 163 ppi; an iPhone 16 Pro
is a 2.56×5.55 in sheet at 460 ppi. So a wallpaper is not a new kind of output — it is
a print whose sheet size is derived from the device (`print_w_in = px_w / ppi`) and
whose **final dpi is the device's ppi** instead of 300.

Everything then falls out of the existing seam with almost no new math:

- `pixel_size(ppi)` returns the device's exact native pixels (3840×2160, 1179×2556…)
  because `round((px_w/ppi) * ppi) == px_w`.
- A 2.6 pt track is *literally 2.6 pt on the client's screen*. Physical styling stays
  meaningful.
- The map-scale denominator (`crop_w / (print_w_in·0.0254)`) stays physically true, so
  terrain-depth keying and the stats scale ratio behave identically.
- Proof vs final is still "one spec, two dpi": final at `ppi`, proof at
  `ppi · (96/300)` — the same 32 % preview ratio prints use.
- The zoom cap, off-DEM guard, 120 MP ceiling, determinism, and provenance/reprint all
  work unchanged once the hardcoded `FINAL_DPI` is generalized (below).

**No pixel fields are added to the spec.** The device preset resolves to
(`print_w_in`, `print_h_in`, `screen_ppi`) at spec-build time; pixels remain a
render-time derivation, exactly as today.

## Product shape (v1)

- **Peer output type in the Frame step**: a `Print | Wallpaper` segment. Wallpaper
  mode swaps the size `<select>` for grouped device presets and hides the orientation
  control (the preset defines orientation).
- **Bundle after accept**: once a proof is accepted, a multi-select of device presets
  renders the same composition at every selected size (crop refit per aspect,
  center-preserving) and downloads a zip. This is the client deliverable — "your
  journey on all your screens" — and is a direct payoff of invariant 1.
- **Wallpapers are clean by default**: no keyline, no cartouche, no compass, no scale
  bar. GNIS labels and markers remain available (user toggles). Phone presets keep
  auto-placed labels out of the lock-screen clock zone.
- **PNG only** (sRGB profile embedded — correct for screens). PDF is refused with the
  existing honest-422 pattern. Provenance manifest embeds as usual, so a wallpaper PNG
  is reprintable/re-derivable like any poster.

### Device presets (v1 starter set)

| id | name | px | ppi | class | top_clear_frac |
|---|---|---|---|---|---|
| `desktop_fhd` | Desktop FHD 24″ | 1920×1080 | 92 | desktop | 0 |
| `desktop_qhd` | Desktop QHD 27″ | 2560×1440 | 109 | desktop | 0 |
| `desktop_4k` | Desktop 4K 27″ | 3840×2160 | 163 | desktop | 0 |
| `ultrawide` | Ultrawide 34″ | 3440×1440 | 110 | desktop | 0 |
| `macbook_air` | MacBook Air 13″ | 2560×1664 | 224 | desktop | 0 |
| `macbook_pro_14` | MacBook Pro 14″ | 3024×1964 | 254 | desktop | 0 |
| `macbook_pro_16` | MacBook Pro 16″ | 3456×2234 | 254 | desktop | 0 |
| `iphone` | iPhone (Pro/16) | 1179×2556 | 460 | phone | 0.18 |
| `iphone_max` | iPhone Pro Max | 1290×2796 | 460 | phone | 0.18 |
| `android` | Android flagship | 1440×3120 | 500 | phone | 0.18 |
| `android_fhd` | Android FHD+ | 1080×2400 | 400 | phone | 0.18 |
| `ipad` | iPad Pro 13″ | 2064×2752 | 264 | tablet | 0.10 |

The table lives in one place server-side (`app/wallpaper.py`) and is served to the
client via `GET /api/wallpapers/presets` — the frontend never hardcodes it.
Feasibility per region is the same math as print (a 4K sheet needs ≥ 38.4 km of crop
at 10 m data — fine for every current region; phone portrait needs ≥ ~12 km width).

## Design by module

### `app/spec.py`

New fields (all with defaults → `serialize.py`'s known-fields filter gives free
forward/backward compat for old sessions and embedded manifests):

- `output_kind: str = "print"` — `"print" | "wallpaper"`; validate rejects others.
- `screen_ppi: float = 0.0` — required > 0 (bounds ~72–600) when wallpaper; must be
  0/ignored for print.
- `keyline: bool = True` — the keyline frame finally gets a toggle (it is currently
  un-disable-able, `render.py:1104`); wallpaper spec-build sets it False.
- `top_clear_frac: float = 0.0` — fraction of sheet height at the top kept clear of
  *auto-placed* geography labels (phone clock zone). Bounds 0–0.35.
- `final_dpi() -> float` — `FINAL_DPI (300)` for print, `screen_ppi` for wallpaper.
  **This is the generalization point**: everything in `main.py` that hardcodes
  `FINAL_DPI` for validate/render/encode switches to `spec.final_dpi()`.

`validate(dpi)` gains only the new-field checks; aspect ±2 %, zoom cap, 120 MP ceiling
apply as-is (an 8K dual-monitor canvas is 33 MP — well under the ceiling).

### `app/wallpaper.py` (new, small)

- `PRESETS` — the table above.
- `spec_for_preset(base_spec, preset, region) -> CompositionSpec` — derive
  `print_w_in/h_in = px/ppi`, set `output_kind/screen_ppi/keyline/top_clear_frac`,
  clear `title_text` (cartouche off), `compass=False`, keep the user's style fields,
  labels toggle, and track/marker data; **refit the crop to the preset aspect**
  center-preserving via a new `geo.refit_crop_aspect(crop, aspect, region)` (the
  server-side twin of `canvas.js refitForSize`, clamped to region bounds). Raises the
  existing `SpecError` family when the refit is infeasible (zoom cap / off-DEM), so
  the API layer reports per-preset failures honestly instead of silently clamping.

### `app/render.py`

- `_draw_keyline` honored only when `spec.keyline` (one-line guard at `render.py:1104`).
- `_draw_labels` keep-out: when `top_clear_frac > 0`, add a full-width band
  `[0, top_clear_frac·out_h]` to the existing keep-out boxes (same mechanism as the
  cartouche keep-out at `render.py:943-945`). Markers/photos are user-placed and are
  left alone.
- Nothing else changes: furniture that is off draws nothing; `_furniture_scale`,
  terrain depth, shadows, and every ground-unit blur already key on physical size and
  scale denominator, which remain true values.

### `app/main.py`

- Replace hardcoded `FINAL_DPI` in `_build_spec`'s validate (`main.py:447`),
  `_render_to_blob` (`:92`), `/api/final` (`:500`), `/api/reprint` (`:610,615`) with
  `spec.final_dpi()`. Proof dpi becomes `spec.final_dpi() * (PROOF_DPI/FINAL_DPI)`
  (unchanged = 96 for print).
- `/api/proof` accepts `output_kind` + `wallpaper_preset` (preset id) alongside the
  existing form fields; wallpaper builds the spec through `spec_for_preset`.
- `_encode_final`: wallpaper + `pdf` → 422 (reuse `_require_format` pattern); PNG
  metadata `dpi=(screen_ppi, screen_ppi)`; sRGB profile and provenance embed as today.
- **Bundle**: `GET /api/wallpapers/presets`; `POST /api/wallpapers/submit`
  (stamped-spec gate via `_require_stamped`, body = preset ids + `embed_spec`) →
  one `ThreadJobQueue` job that renders each preset's spec at its ppi, zips
  `trailprint_<region>_<preset>_<w>x<h>.png` files (each with its own manifest), and
  stores the zip in blobs; result via the existing `/api/jobs/{id}` → `/result` flow.
  Infeasible presets are skipped and named in the job result payload.

### `app/static/` (wizard)

- Frame step: `Print | Wallpaper` segmented control (same pattern as the orientation
  segment, `index.html:100-109`). Wallpaper mode: preset `<select>` grouped
  Desktop/Laptop/Phone/Tablet fed from `/api/wallpapers/presets`; orientation control
  hidden; the aim rectangle locks to the preset's aspect (`canvas.js` already locks to
  `printW/printH` — it just receives the derived inches); the client zoom-floor math
  (`refitForSize`, `cropBelowFloor`, `sizeInfeasibleForRegion`) uses the preset's ppi
  instead of the literal 300.
- Proof step: format control collapses to PNG for wallpapers; after accept, a
  "Wallpaper bundle" card with preset checkboxes → submit → poll → download zip.
- Style panel unchanged — every knob keeps meaning on a screen-sheet.

### Provenance / reprint

- New fields ride the manifest automatically (`spec_to_json` dumps all fields;
  `spec_from_json`/`manifest_to_spec` tolerate old manifests → defaults).
  `MANIFEST_VERSION` stays 1 — the change is additive; a v1 print manifest reprints
  bit-identically (frozen fixture test still passes untouched).
- Add a **frozen wallpaper manifest fixture** (`tests/fixtures/manifest_wallpaper_v1.json`)
  the day this ships — same forever-contract discipline as posters: a wallpaper PNG
  must re-render at its exact native pixels from the file alone.

## Decision points for Dom (defaults chosen — cheap to reverse before build)

1. **Peer output + post-accept bundle** (chosen) vs. wallpaper only as a post-poster
   companion. The peer path costs one wizard segment and covers both stories.
2. **Clean by default** (chosen): no keyline/cartouche/compass on wallpapers; labels
   and markers opt-in as today. Alternative: offer the cartouche as a toggle for
   desktop wallpapers — deferred, easy to add later (it's just `title_text` + the
   existing furniture code).
3. **Preset list**: the 12 above. Custom pixel dimensions are **deferred** (presets
   only in v1) — free-form px×ppi input adds UI + validation surface for little v1 value.
4. **Bundle in v1** (chosen) — it is the actual client value; cutting it saves ~1 task
   but reduces the feature to "a weird print size."
5. **Positioning/pricing** (free add-on to a poster purchase vs. standalone digital
   product) — pure product call, nothing in this plan depends on it.

## Implementation plan (TDD, in order)

**Phase 1 — engine** (~no UI)
1. `spec.py`: new fields, bounds, `final_dpi()`; tests — wallpaper spec at
   `dpi=screen_ppi` yields exact native pixels; bad `output_kind`/`screen_ppi` → 422-able
   `SpecError`; print behavior byte-identical (existing suite untouched).
2. `render.py`: `spec.keyline` guard + `top_clear_frac` label keep-out; tests — keyline
   absent when off; no auto label box intersects the clock band; goldens unaffected.
3. `geo.refit_crop_aspect` + `app/wallpaper.py` (`PRESETS`, `spec_for_preset`); tests —
   center preserved, region-clamped, infeasible preset raises, aspect within ±2 %.

**Phase 2 — API**
4. `main.py` `final_dpi()` generalization + `/api/proof` wallpaper params + PNG-only +
   ppi in PNG metadata; tests — proof/final round-trip at native px, pdf→422,
   `dpi==(163,163)` for `desktop_4k`.
5. Bundle endpoints + zip job; tests — zip contains selected presets at exact px, each
   with a valid manifest; infeasible preset reported, not silently dropped.
6. Reprint: wallpaper PNG → `/api/reprint` re-renders pixel-identically; frozen
   wallpaper manifest fixture.

**Phase 3 — wizard**
7. Frame-step segment, preset picker, ppi-aware floor math, aspect-locked aim.
8. Bundle card + zip download. Verify by driving the app (Playwright/Chromium, as the
   wizard work was verified before).

**Phase 4 — quality**
9. Golden wallpapers (one `desktop_4k`, one `iphone` from `tests/fixtures/sample.gpx`,
   downscaled like the poster goldens), README + quality-bar additions, handoff update.

Adversarial review (the `Workflow` tool pattern) after Phases 1–2 and 3, per repo
convention — it has caught real bugs every session.

## Verification

- `pytest -q` green (existing 190+ tests untouched by design — print path is
  byte-identical when `output_kind=="print"`).
- Drive the app end-to-end: upload `sample.gpx` → Wallpaper → `desktop_4k` → proof →
  final; assert the PNG is exactly 3840×2160, carries sRGB + manifest;
  `/api/reprint/inspect` reads it back; bundle zip for {4k, iphone} contains both at
  native px with the phone's labels clear of the top band.
- By-eye check of one desktop and one phone wallpaper on real terrain (rebuild a DEM
  first — synthetic CI DEMs are not for judging looks).

## Out of scope (later)

- Custom pixel dimensions; per-device dark/night variant (OLED-friendly palette is a
  real idea — the Night theme exists in the wizard shell, not the render engine);
  parallax-safe overscan margins for iOS depth effect; automated delivery
  (email/link) of bundles; cartouche-on-wallpaper toggle.
