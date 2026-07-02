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

> **Progress (rolling):** PR #4 landed P0-a, P0-b, the `/readyz` half of P0-c, and most of P0-e. PR #5 landed **P0-d** and the **V1-8 + V1-11 halves of P0-f** (lifecycle + logging). A third PR completed **P0-c**: real 3DEP DEMs + real NHD hydro rebuilt for **both** regions (lassen 183 MB, susanville 257 MB — susanville previously 500'd on every render); `region.json` now derives from the DEM's own transform (`/readyz` reports **0.0 m** bounds drift — the old lassen bounds overhung real data by ~1–2 km/edge); the real-elevation control-point registration test runs and passes; full suite **112 passed / 2 skipped** against real terrain; look-validation renders sent to Dom. What's **still open**: Dom's look sign-off + the golden-reference quality bar, `V1-12` source-archival (needs an owned object store; DEMs also remain gitignored/undistributed — the distribution channel is P1), and the **V1-10 finished-poster/print-correctness** half of P0-f.

- [x] **P0-a · Stand up CI + a committed synthetic test region + pin deps.** *Done:* GitHub Actions (`.github/workflows/ci.yml`) runs `pytest -q` on push/PR; `tests/conftest.py` hydrates a tiny synthetic DEM per region (build-if-missing, bounds == region.json, tagged `synthetic=1`) so the endpoint/render/**registration** suites run instead of skipping; `test_hydro`/`test_region_prep` `importorskip` the geopandas/py3dep stack; `requirements-lock.txt` (exact-version pins) + `requirements-{dev,regionprep}.txt` split + `.python-version`. *Note: pins are exact-version (pip freeze), not yet `--generate-hashes`/`uv lock` — a hashed lock is the remaining nicety. Roadmap: V1-4, V1-9.*
- [x] **P0-b · Fix the fabricated-terrain bug (the #1 v1 correctness defect).** *Done:* `render.rasterize` raises a humanized `OffDemError` (→ 422) when the trimmed crop's NaN fraction exceeds `MAX_OFFDEM_NAN_FRAC` (1%); `relief._fill_nan` now fills stray holes from the **nearest finite neighbour** (scipy `distance_transform_edt`), not the crop mean. *Deferred to P0-c/readyz: deriving region.json bounds FROM the DEM at build time — the drift is now surfaced by `/readyz` rather than auto-corrected. Roadmap: V1-1.*
- [x] **P0-c · Real DEMs for both regions + a `/readyz` bounds/DEM-present check.** *Done:* `/readyz` endpoint + `Region.readiness()` (present DEM, bounds + CRS match, 503 with per-region report otherwise). Real 3DEP DEMs + NHD hydro rebuilt for **both** regions via `region_prep.py`; regenerated `region.json`/`overview.png`/`hydro.json` committed, so bounds now derive from the DEM's transform (drift = 0.0 m). The registration control-point test runs against the real DEM and passes; 18×24 @ 300 dpi final stress-checked on the real COG. *Note:* the DEM files themselves stay gitignored/undistributed — rebuild with `region_prep.py` (~4 min/region) or wait for the P1 distribution channel; CI still uses the synthetic-DEM harness. *Look sign-off from Dom pending (renders sent). Roadmap: V1-2.*
- [~] **P0-d · Real-export spike.** *Done:* `tests/test_real_exports.py` — a corpus of **representative** OnX/Gaia/Strava/Avenza/Google exports encoding the real quirks (multi-track/segment, `<wpt>`/`<Point>` waypoints mixed with tracks, Strava trackpoint extensions, KML-in-folders, KMZ, `gx:Track` with paused/repeated fixes, 4k-point tracks, mixed dated/undated), validated end-to-end ingest → hotspots → framing (starter_crop clears the zoom cap). No density/hotspot/framing regression surfaced. *Still open:* swap in **actual** exported files (gold standard) under `tests/fixtures/exports/` when on hand. *Roadmap: V1-5, Open-Q4.*
- [~] **P0-e · Batch the cheap fixes.** *Done:* `MemoryStore` `create`/`get`/`update` now `deepcopy` (value semantics matching SqliteStore — V1-3); `gx:Track` paired `(lon,lat,when)` parse dropping a bad coord as a unit (V1-7); upload-hardening (V1-6) — hardened lxml parser (`resolve_entities=False`, `huge_tree=False`, DOCTYPE rejected), KMZ entry/decompressed-size caps, output-pixel + non-positive-size guards in `spec.validate()`, `Image.MAX_IMAGE_PIXELS` + photo byte/pixel caps. *Still open:* `V1-12` archive the shipped regions' raw source DEM/water to your own store (continuity).*
- [~] **P0-f · Hygiene + finish.** *Done (V1-8 lifecycle):* the sync final now routes through the blob seam (no more `final_*.png` in `region.dir`); TTL/eviction for blobs, the job registry, and `uploads/` photo dirs (`TRAILPRINT_TTL_SECONDS`, default 24h; `LocalBlobs.delete`/`sweep`). *Done (V1-11 observability):* `app/logconfig.py` (text default, JSON opt-in) — `traceback.print_exc()` replaced by `logger.exception`; job-lifecycle + upload/proof/final render logs with timings. *Done (V1-10 styling — the "hybrid" Dom approved):* legibility-first track cartography (2.6 pt near-solid gold on a narrow **paper halo**; casing blur/edge feather converted from raw px to **points**, fixing the proof≠final halo softness); **frequency→width** ("lived in": segments traveled on 2+ distinct days widen ×1.6, like a desire path); **journey terminus pins**; 10% terrain **paper-lift** (figure-ground); markers 0.24″ / labels 13 pt / photos 1.5″; sheet-scaled PROOF watermark; **PDF export** (`format=pdf` on `/api/final` + `/api/final/submit`). *Still open (V1-10 print-correctness):* title block/legend/margin treatment, sRGB/gamut sanity, bleed/trim — iterate with Dom against the quality bar. *Roadmap: V1-8, V1-11, V1-10.*

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
3. **Unit-economics gate** (belongs ahead of P2, not P3): tie a per-render cost to a price floor. **Measured (2026-07-02, real lassen COG):** the flagship 18×24 @ 300 dpi final is **68.5 s and ~4.8 GB peak RSS** (5400×7200 px; single-threaded; COG re-read uncached) — much heavier than the earlier ~18 s/hundreds-of-MB estimate that was taken at 9×12. Per-worker RAM sizing and DEM caching are non-optional before any fleet math.
4. **Which global DEM/water sources — and are their licenses OK for commercial sale?** Determines required on-poster attribution.

---

## How to run / verify (so the next session starts fast)
```bash
cd /home/user/badwatertrails
python3 -m venv .venv && ./.venv/bin/pip install -r requirements-lock.txt   # pinned core + test stack (what CI installs)
./.venv/bin/python -m pytest -q                                             # conftest hydrates synthetic DEMs; region-prep tests importorskip
./.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8011     # then drive with Playwright/Chromium at /opt/pw-browsers
```
- **Renders now run on a fresh clone / in CI:** `tests/conftest.py` hydrates a tiny *synthetic* DEM per region (gitignored, tagged `synthetic=1`) so the endpoint/render/registration suites run without the real 3DEP data. `/readyz` reports each region's DEM-present + bounds/CRS match.
- **The by-eye look still needs a REAL DEM** (P0-c, open): rebuild with `python region_prep.py --id lassen_ca --name "Lassen County, California" --bbox -121.06 40.16 -120.34 40.85 --epsg 32610` (needs `pip install -r requirements-regionprep.txt`, network, ~4 min, ~190 MB) — this also regenerates `region.json`/`overview.png`/`hydro.json`, so `git checkout` them afterward if you only want the DEM. The real-elevation registration test (`test_control_point_elevation`) only runs against a real DEM.

## Stale-fact corrections (vs the older HANDOFF.md)
- **Two** regions ship (`lassen_ca`, `susanville_reno`), not one — but neither has a distributed *real* DEM (P0-c); CI/tests use synthetic DEMs.
- Test suite is now **93 passed / 3 skipped** (17 test files) with the DEM-gated integration suites running via the synthetic-DEM harness; the old "24 skip without a DEM" no longer holds.
- The async render path **is** now wired into the UI (the wizard's Accept uses submit+poll).
