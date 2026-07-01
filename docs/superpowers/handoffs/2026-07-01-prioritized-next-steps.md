# TrailPrint — Prioritized Handoff (Next Steps)

_Last updated: 2026-07-01 · after the guided-wizard merge (PR #2) and the red-team assessment (PR #3)._

**Read this to know what to work on next, in priority order.** It is the action plan; the *reasoning* behind every item lives in the red-team deliverable.

## Reference documents (read in this order)
1. **The roadmap / rationale (primary reference):** [`docs/superpowers/assessments/2026-07-01-trailprint-redteam-and-roadmap.md`](../assessments/2026-07-01-trailprint-redteam-and-roadmap.md) — the full red-team (8 verified lenses, 54 findings), the truly-ready-v1 and hosted-v2 end-state definitions, the phased P0–P3 roadmap, and the open questions. **Every item below cites its section/finding there.**
2. **Architecture & invariants + how-to-run:** `docs/superpowers/handoffs/HANDOFF.md` (still the best architecture/gotchas reference — but its "what's next" list is superseded by *this* doc, and note the stale-fact corrections below).
3. **Design specs / plans:** `docs/superpowers/specs/` and `docs/superpowers/plans/`.

## Current state (one paragraph)
The guided **TrailPrint Studio wizard** shipped and merged (PR #2): 4-step flow (Region → Tracks & Places → Frame → Proof), `POST /api/markers/move`, tested `starter_crop`, cross-region auto-recovery, express proof→final, keyboard/ARIA canvas, Night/Day theme. It is a **local, single-operator concierge tool**. A full adversarial red-team (PR #3) then assessed it against two targets — **truly-ready v1** (polished local tool) and **v2** (fully hosted, multi-tenant, any-user, paid). Verdict: **the architecture (compose→rasterize seam + the `store`/`blobs`/`jobs`/`serialize` swap-points) is the asset; v1 is under-hardened and v2 barely exists.**

---

## P0 — v1 hardening (do these next, in this order)

The goal: the local tool produces **client-quality posters back-to-back with no silent errors.** Sequence matters — CI lands first so the correctness surgery is guarded.

- [ ] **P0-a · Stand up CI + a committed synthetic test region + pin deps.** GitHub Actions runs `pytest -q` on push/PR; commit a tiny synthetic-DEM region so the endpoint/render/**registration** suites (24/82 currently skip behind the gitignored-DEM gate) actually run; `importorskip` the geopandas tests; add `uv lock`/`pip-compile` (hashed) + `.python-version`. *Roadmap: V1-4, V1-9. Why first: it's the safety net for everything below and determinism is a precondition for the golden-image baseline.*
- [ ] **P0-b · Fix the fabricated-terrain bug (the #1 v1 correctness defect).** Derive `region.json` bounds/size from the DEM's own transform (single source of truth); count in-bounds against **true** DEM bounds; raise a humanized 422 when the trimmed crop's NaN fraction exceeds a small threshold. Stop `_fill_nan` silently substituting crop-mean terrain inside the frame. *Evidence: `app/relief.py:28` (`_fill_nan`→`np.nanmean`), `app/render.py:52`, bounds-overhang. Roadmap: V1-1.*
- [ ] **P0-c · Real DEMs for both regions + a `/readyz` bounds/DEM-present check.** Build/restore `regions/susanville_reno/dem.tif` (missing → 500s today), replace lassen's throwaway synthetic DEM with real 3DEP, re-verify the by-eye look. *Roadmap: V1-2. (A real lassen DEM was rebuilt in-session but is gitignored/undistributed — see P1.)*
- [ ] **P0-d · Real-export spike (run in parallel with P0-b/c, early).** Add real OnX/Gaia/Strava/Avenza fixtures (multi-segment, waypoints, KMZ, big point counts); validate ingest + hotspots + framing end-to-end. **This can invalidate density/hotspot tuning and framing — surface that before polishing the correctness fixes.** *Roadmap: V1-5, Open-Q4.*
- [ ] **P0-e · Batch the cheap fixes.** `MemoryStore.get()/create()` deepcopy (`store.py:25,32` shallow aliasing); upload-hardening (hardened lxml — billion-laughs DoS is the real threat, not XXE; KMZ size/entry caps; print-size + output-pixel ceiling in `spec.validate()`; `Image.MAX_IMAGE_PIXELS` + photo cap); `gx:Track` paired-tuple parse (`ingest.py`); archive the shipped regions' raw source DEM/water to your own store (continuity). *Roadmap: V1-3, V1-6, V1-7, V1-12.*
- [ ] **P0-f · Hygiene + finish.** Route all finals through the blob seam (stop writing `final_*.png` into `region.dir`) + TTL/eviction for jobs/blobs/uploads; structured logging + job-lifecycle logs; a real title/legend/margin + print-correct output (embedded DPI, gamut/bleed). *Roadmap: V1-8, V1-11, V1-10.*

**Before declaring P0 done, agree a quality bar with Dom** (this doesn't exist yet): a golden reference of 3–5 accepted posters (real DEM + real tracks), a render-geometry checklist (north-up, hillshade azimuth/z-factor, track↔terrain pixel alignment), and a print-correctness checklist. *Roadmap §2 acceptance criteria.*

**P0 exit:** both regions render on real DEMs; no fabricated-terrain path; CI green with integration + registration tests running; validated on real exports against the agreed bar; a concierge day doesn't leak.

---

## P1 — promote the seams to real backends (deployable single-tenant; **not** public)
Container/CI-image + `/healthz`+`/readyz` + structured logging + a config module (absolute paths, CORS/host/port); a **DEM distribution channel** (object store the deploy pulls/caches); **Postgres `SessionStore`** (Alembic + versioned schema + atomic update) and **S3/GCS `Blobs`** (+ delete + presigned URLs); offload sync renders off the event loop (`run_in_threadpool`) as an interim. **Do not** expose a public *unauthenticated* hosted instance. *Roadmap §5 P1.*

## P2 — v2 build (in dependency order)
1. **Auth + multi-tenancy** — the hinge; blocks everything paid/multi-user. Includes a v1→v2 data-ownership backfill.
2. **Durable render infra** — broker + worker fleet + persisted jobs + concurrency caps.
3. **Global geo pipeline** — global DEM/water + attribution, tiled store + spatial index + cache, extent-based projection (reconsider UTM; prefer per-track LAEA) with loud out-of-CRS errors, `native_resolution_m` from source; **keep offline catalog-build separate from any request-time provisioning.**
4. **Payments + fulfillment** — pricing/quote, Stripe, orders, paid gate on the unwatermarked final (needs watermark-robustness first), color-managed export; physical adds lab API + address + SKU + tracking + email.
5. **Self-serve UX** — coverage onboarding (no raw 422), touch-action fix for canvas drag, humanized errors, real-scale size/price/material preview.

## P3 — scale / compliance / polish
Data-privacy lifecycle (delete/export/retention — pull earlier for EU/CA), ToS/support, golden-image visual regression + load + frontend tests, autoscaling/CDN/cost controls, i18n/units. *Roadmap §5 P3.*

---

## Decisions that gate the v2 build (resolve before P2 planning)
1. **Digital-only or physical prints?** Forks the entire fulfillment rock.
2. **On-demand any-location vs a curated expanding catalog?** The catalog is likely right — on-demand means a ~4-min/190 MB build the user waits through, at per-build cost.
3. **Unit-economics gate** (belongs ahead of P2, not P3): profile peak per-render RAM (~18 s, hundreds of MB, re-reads a ~190 MB COG uncached) and tie a per-render cost to a price floor.
4. **Which global DEM/water sources — and are their licenses OK for commercial sale?** Determines required on-poster attribution.

---

## How to run / verify (so the next session starts fast)
```bash
cd /home/user/badwatertrails
python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt   # + pandas geopandas playwright for full suite
./.venv/bin/python -m pytest tests/ -q --ignore=tests/test_hydro.py --ignore=tests/test_region_prep.py   # region-prep modules need py3dep/geopandas
./.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8011   # then drive with Playwright/Chromium at /opt/pw-browsers
```
- **Rendering needs a DEM.** `regions/*/dem.tif` is gitignored and **not distributed** (P1 fixes this). To verify renders locally, rebuild with `python region_prep.py --id lassen_ca --name "Lassen County, California" --bbox -121.06 40.16 -120.34 40.85 --epsg 32610` (needs `py3dep`+`pynhd`, network, ~4 min, ~190 MB) — this also regenerates `region.json`/`overview.png`/`hydro.json`, so `git checkout` them afterward if you only want the DEM. The register/render pytest suites SKIP without a DEM.

## Stale-fact corrections (vs the older HANDOFF.md)
- **Two** regions ship (`lassen_ca`, `susanville_reno`), not one — but `susanville_reno` has no distributed DEM (P0-c).
- Test counts in the old handoff are outdated; there are now 16 test files (~76–82 tests; 24 skip without a DEM).
- The async render path **is** now wired into the UI (the wizard's Accept uses submit+poll).
