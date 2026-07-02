# TrailPrint v1 — Quality Bar

_Seeded 2026-07-02 from the P0-hardening sessions (PRs #4–#7 + the V1-10 finish). This is
the definition-of-done gate the red-team said was missing (roadmap §2): a poster is
"client quality" when it matches the golden references by eye and every checklist item
below holds. **Status: seeded and code-enforced where noted; formal acceptance by Dom on
a physically printed proof is still open.**_

## 1. Golden reference

Committed under `docs/superpowers/quality/golden/` (downscaled to 1200 px; regenerate at
full size with the commands below — deterministic from committed inputs only):

| Reference | What it locks |
|---|---|
| `lassen_ca_wizard_18x24.png` | The full wizard path on real 3DEP terrain: `tests/fixtures/sample.gpx` → starter crop → 18×24 default-title render. Locks the approved V1-10 hybrid: worn-corridor widening (the 5-day corridor vs single-day branches), narrow paper halo, terminus pins, 10% paper-lift, marker/label/photo scale, title block + keyline. |
| `susanville_reno_relief_18x24.png` | The second region's terrain character (relief + real NHD water, no tracks) — the region that shipped un-renderable before P0-c. |

Regenerate: upload `tests/fixtures/sample.gpx`, render the starter crop at 18×24 with the
default title (seed 7 throughout — invariant 3 makes this reproducible on pinned deps).

**Open:** replace/augment with 3–5 posters from **real client tracks** once accepted, and
print one physical proof for Dom's sign-off (screen ≠ paper).

## 2. Render-geometry checklist (code-enforced)

- **Registration** — lon/lat → region CRS → DEM sampling hits the right ground:
  `tests/test_registration.py::test_control_point_elevation` (real DEM: downtown
  Susanville at ~1265 m) and `test_coordinate_chain_lands_on_dem` (every run).
- **North-up** — regions are UTM; the renderer never rotates. (Grid north ≠ true north
  by the UTM convergence angle, <1.5° at these longitudes — accepted for v1.)
- **Hillshade lighting** — azimuth honored: `tests/test_relief.py::test_hillshade_comes_from_requested_azimuth`.
- **No invented terrain** — off-DEM crops refuse loudly (`OffDemError` → 422):
  `tests/test_render.py::test_rasterize_rejects_off_dem_crop`; `/readyz` proves DEM
  presence + 0-drift bounds per region.
- **Track↔terrain alignment across DPIs** — the proof is a faithful scale of the final,
  corridor-masked and calibrated: `test_proof_track_treatment_is_a_faithful_scale_of_final`
  (14.75 correct vs 17.34 px-regression, threshold 16.0).
- **Zoom cap** — never render finer than the data: `tests/test_spec.py` +
  `test_too_tight_crop_rejected_at_proof_422`.
- **Journey semantics** — same-day pause-split segments neither widen the route nor pin
  mid-route termini: `tests/test_track_style.py`.

## 3. Print-correctness checklist

- **Embedded 300 DPI** — PNG + PDF: `test_final_png_embeds_srgb_and_dpi`,
  `test_async_final_pdf_via_job_queue` (MediaBox 648×864 pt for 9×12).
- **sRGB ICC profile** in the PNG final (labs/viewers read color as intended).
- **PDF encoder** at quality 95, 4:4:4 (no chroma fringing on the gold line).
- **Title block + stats caption** (`~scale · days · miles`, deterministic from the spec)
  and the **keyline frame** at 0.25 in inset — treat the keyline as the trim-safe zone.
- **Open:** bleed/trim spec (confirm with the actual print lab; typically +0.125 in
  bleed), physical-proof color check, and a decision on the full margin-frame layout
  (map inset in a paper border) — that variant changes crop-aspect semantics through the
  whole wizard, so it is deliberately NOT in v1.1.

## 4. Continuity (V1-12)

`regions/<id>/sources.json` records the source datasets/licenses, exact fetch bbox, and
sha256 of every built asset (written by `region_prep.py` on each build). The DEMs stay
gitignored; **archival of `dem.tif` to owned storage is still open** — upload the two
DEMs and verify against the manifest hashes. A rebuild whose hashes drift = upstream
3DEP/NHD changed, and the golden references must be re-validated by eye.
