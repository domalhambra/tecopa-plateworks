# TrailPrint — Red-Team Assessment & Roadmap: "Truly Ready v1" and "Fully Hosted v2"

**Date:** 2026-07-01
**Method:** Adversarial red-team workflow — 8 independent lenses (security, scalability, geo/data, correctness, product/UX, ops, testing, commercial), each finding independently verified against the code; a synthesis pass; a completeness critic; and hand-verification of the top-severity findings. 54 findings survived verification (11 critical, 21 high, 19 medium, 3 low; 43 CONFIRMED, 7 nuanced).
**Scope:** the codebase at `main` (post guided-wizard merge) plus the build/dev workflow.

> **Two target end states, assessed separately:**
> - **(A) Truly-Ready v1** — a polished, reliable *local* concierge tool. One operator (Dom) makes client-quality posters back-to-back. Correctness, quality, and robustness matter; **not** hosted or multi-user.
> - **(B) v2** — *fully hosted*, server-side map processing, used by *any user* (self-serve, multi-tenant, likely paid, broad coverage).

---

## 1. Verdict

TrailPrint today is a **strong architectural prototype, not yet shippable against either target.** The compose→rasterize seam, the six invariants, and the four swap-point interfaces (`store`/`blobs`/`jobs`/`serialize`) are genuinely well-designed — the hard conceptual work ("decide the picture once in ground coordinates, paint at any DPI") is done and defended by tests.

But **against Truly-Ready v1** the tool has correctness landmines that would burn a paying client, and **against v2** almost everything foundational is missing: no auth/tenancy, no payments, no fulfillment, no durable render infra, no networked store/object-store, no container/CI/observability — and, most fundamentally, **coverage is two hand-built US regions** on US-only data sources, so >99.99% of Earth returns a hard 422. **The bones are right; the flesh for v1 is under-hardened and the flesh for v2 barely exists.**

The three scariest confirmed facts (hand-verified):
1. **Silent fabricated terrain.** `region.json` bounds overhang the real DEM; off-DEM pixels are filled with the crop's *mean* elevation (`relief.py:28` `_fill_nan` → `np.nanmean`), so a crop past real data paints smooth invented terrain under real tracks — a *plausible* wrong poster with zero visible signal.
2. **A shipped region can't render.** `susanville_reno` has no `dem.tif` (DEMs are gitignored and undistributed); it appears in the picker and 500s on render from any clean clone.
3. **The multi-user pillars are absent.** No auth, no payments, no fulfillment — a user today extracts a free, unwatermarked, print-ready 300-dpi PNG.

---

## 2. "Truly Ready v1" End State

### Definition of "done"
One operator produces **client-quality 18×24 posters back-to-back, reliably, with no silent errors.** Concretely:
- **Correctness is guaranteed, not lucky** — every accepted poster is painted over *real* elevation across its whole frame; a crop lacking real DEM coverage yields a clear humanized error (like the zoom cap), never a plausible-but-wrong poster.
- **Both shipped regions render on real DEMs**, and the by-eye look has been re-validated on real 3DEP terrain (not the throwaway synthetic noise DEM the look was tuned against).
- **Real inputs work** — ingest/hotspot/framing validated against a corpus of real OnX/Gaia/Strava/Avenza exports (multi-segment, pauses, waypoints, KMZ, huge point counts).
- **Reproducible & safe to run repeatedly** — pinned deps + Python version (determinism holds); CI runs the *full* suite on every push; a long session doesn't leak memory/disk.
- **The deliverable is finishable** — a real title/legend/margin treatment, and print-correct output (embedded DPI, sane color) the print lab can use as-is.
- **Robust to operator mistakes** (cheap upload-hardening in place), not yet to adversaries.

**Explicitly NOT in v1:** auth, accounts, payments, fulfillment, hosting, multi-user, global coverage, Postgres/Redis/S3. Single operator, local, 18×24 locked.

### v1 acceptance criteria (a definition-of-done gate — *from the critic; this was missing*)
You cannot declare v1 "done" against an undefined quality bar. Before P0 exit, agree with Dom on:
- A **golden reference** of 3–5 accepted posters (real DEM + real tracks) that define "client quality," used as the visual-regression baseline (needs pinned deps first).
- A **render-geometry checklist**: north-up, hillshade azimuth/z-factor correct, tracks pixel-aligned to terrain at 300 dpi, scale/labels accurate — the georegistration control-point test (currently *skipped*) must run.
- A **print-correctness checklist**: embedded 300 DPI, RGB→print gamut sanity, bleed/trim/margin.

### Prioritized v1 gap checklist

| # | Gap | Why it matters | Effort |
|---|---|---|---|
| **V1-1** | **DEM-overhang / off-DEM guard.** Derive `region.json` bounds/size from the DEM's own transform (single source of truth); count in-bounds against *true* DEM bounds; raise a humanized 422 when the trimmed crop's NaN fraction exceeds a small threshold. Stop `_fill_nan` from silently substituting crop-mean terrain inside the frame. | **The #1 v1 correctness defect** — invented terrain under real tracks, invisible to the operator. `relief.py:28`, `render.py:52`, `geo.py`/`main.py` in-bounds check. | **M** |
| **V1-2** | **Build/restore `susanville_reno/dem.tif`; replace lassen's synthetic DEM with real 3DEP; re-verify the look.** Add a `/readyz`-style check that every discovered region has a present DEM whose bounds match `region.json`. | One of two regions 500s today; the tuned look was never validated on real terrain. | **M** |
| **V1-3** | **`MemoryStore.get()`/`create()` deepcopy.** Shallow `copy.copy` (`store.py:25,32`) shares `hotspots`; edits mutate stored state outside the lock and diverge from `SqliteStore`. | Store contract silently defeated. *(Low real-world stakes for a strictly-serial single operator — cheap to fix, but don't let it gate the v1 correctness milestone.)* | **S** |
| **V1-4** | **CI + de-skip integration tests — land FIRST.** GitHub Actions runs `pytest -q` on push/PR; commit a tiny synthetic-DEM test region so the endpoint/render/**registration** suites actually run (24/82 skip today); `importorskip` the geopandas tests. | A safety net nobody runs is no safety net; the highest-value 29% silently skip. **Sequence before the V1-1/2/3 correctness surgery so those fixes are guarded as written.** | **M** |
| **V1-5** | **Real-export corpus + look-on-real-terrain — run as an early SPIKE, not mid-pack.** Real OnX/Gaia/Strava/Avenza fixtures (multi-seg, waypoints, KMZ); validate ingest + hotspots + framing end-to-end. | Can *invalidate* density/hotspot tuning and framing — i.e. force rework of V1-1/V1-10. It's a cheap experiment that de-risks expensive work; do it before polishing the correctness fixes. | **M** |
| **V1-6** | **Cheap upload-hardening.** Hardened lxml parser (`resolve_entities=False`, `huge_tree=False`, reject DOCTYPE) — the real threat on modern lxml is **billion-laughs DoS**, not XXE file-read; KMZ decompressed-size + entry-count cap; print-size clamp + absolute output-pixel ceiling in `spec.validate()`; `Image.MAX_IMAGE_PIXELS` + photo size cap. | One malformed/oversized file OOM-kills the process mid-client-session. All small, all defensive. | **S** |
| **V1-7** | **`gx:Track` paired-tuple parse.** `<when>`/`<gx:coord>` are collected independently in `ingest.py`; a dropped coord shifts every later timestamp → wrong `day` → wrong hotspots. Iterate children in order, drop `(lon,lat,when)` as a unit. | Silent data-integrity error in the key that drives density's distinct-day weighting. | **S** |
| **V1-8** | **Lifecycle cleanup.** Route ALL finals through the blob seam (sync `/api/final` writes stray `final_*.png` into `region.dir` — 5 already stale); add TTL/eviction for the never-evicted job registry, blobs, and `uploads/` photos. | A back-to-back concierge day leaks memory and disk. | **M** |
| **V1-9** | **Pin deps + Python version** (`uv lock`/`pip-compile` with hashes, `.python-version`); verify the golden render is byte-stable. | Determinism depends on the exact numpy/rasterio/GDAL stack; **precondition for golden-image regression (V1-5, P3).** | **M** |
| **V1-10** | **Finished poster treatment + print-correctness.** Real title block/margin/legend (decide with Dom); embed DPI, check gamut/bleed/trim. | The deliverable is a poster; current output is a bare bottom-left caption in raw RGB. | **M/L** |
| **V1-11** | **Minimal observability.** Structured logging + job-lifecycle logs so a failed client render is diagnosable (today: `traceback.print_exc()` to vanishing stdout). | Operator currently has no trace to diagnose a bad render. | **S/M** |
| **V1-12** | **Archive the shipped regions' raw source DEM/water** (*from the critic*). The two regions' DEMs are gitignored and reproducible only via live USGS 3DEP/NHD; if those change/rate-limit, the shipped regions can't be rebuilt. Store the raw sources in your own object store. | Real v1 **continuity** risk, not just v2. | **S** |

**v1 sequencing (critic-corrected):** **V1-4 (CI + committed synthetic test region) first** → then correctness blockers V1-1, V1-2 (real DEMs) with V1-5/Open-Q4 as an early de-risking spike running in parallel → batch the cheap V1-3/V1-6/V1-7 → V1-9 pins → V1-8/V1-11 hygiene → V1-10 last mile.
**Exit criteria:** both regions render on real DEMs; no fabricated-terrain path; CI green with integration + registration tests running; validated on a real-export corpus against an agreed quality bar; a concierge day doesn't leak.

---

## 3. v2 Target Architecture (hosted, processes maps, any user, multi-tenant, paid)

Per layer: **target** and **delta from today.**

- **Auth & tenancy.** *Target:* users; magic-link/OAuth → cookie/JWT; `owner_id` on every session/job/blob/order; every endpoint authenticated; ownership checked on every read (no IDOR); per-user rate limits + render quotas. *Delta:* **from zero** — no auth on any route; `session_id`/`jid` are the only "access control"; finals leak via the public `/regions` static mount. **The single largest v2 build. XL.**
- **Session store.** *Target:* managed **Postgres** behind the existing `SessionStore` seam; stateless sessions (any worker serves any request); Alembic migrations + versioned schema (not one opaque JSON blob); atomic read-modify-write. *Delta:* default `MemoryStore` (per-process, lost on restart → random 404s behind a load balancer); `SqliteStore` non-atomic update drops concurrent edits; no Postgres impl. Seam clean; second impl to write. **L.**
- **Job / render infra.** *Target:* real broker + autoscaling worker fleet (Redis/SQS + Celery/RQ/Dramatiq); job records persisted in the DB (survive restarts, readable cross-node); renders off the web tier in `def` workers with per-worker RAM-sized concurrency caps, backpressure, retry, priority; spec crosses the boundary via `serialize.spec_to_json` (already built). *Delta:* `ThreadJobQueue` is in-process, unbounded thread-per-submit, non-durable (restart drops every job → client polls 404 forever); sync `/api/proof` and `/api/final` render **on the event loop**, freezing the worker. **XL.**
- **Blobs / CDN.** *Target:* S3/GCS behind `put/path/exists` (+ `delete`), presigned URLs via CDN (never streamed through the web tier), TTL/lifecycle. *Delta:* `LocalBlobs` on local disk (invisible across split nodes, lost on redeploy); no delete/GC/signed-URL/expiry; finals pollute `region.dir`. **M.**
- **Geo / DEM pipeline for coverage** *(the deepest, hardest area — see §4).* *Target:* global sources (Copernicus GLO-30 / SRTM; OSM water / HydroSHEDS) with recorded, rendered **attribution**; a global **tiled/COG** store windowed per request + a **spatial index** for coverage lookup + a **bbox-keyed cache**; **projection from extent** (per-track LAEA/oblique-azimuthal rather than patching UTM), explicit antimeridian/polar handling, and **loud errors** on out-of-CRS points (today they're silently dropped to `(inf,inf)`); `native_resolution_m` **derived from the source grid**, not hardcoded 10. *Delta:* coverage = 2 hand-built US regions; `region_prep.py` is an offline ~4-min ~190 MB-per-region CLI on US-only sources with a mac-specific SSL hack, not runtime-callable/importable/headless; one-projection-per-region UTM can't represent global extents; no global source, tiling, index, or attribution field. **XL (multiple).**
- **Payments / fulfillment.** *Target:* pricing/quote by size + option; Stripe checkout; `orders` table; **the unwatermarked final gated on a paid order** (watermarked proofs free — but see the watermark-robustness caveat in §6); if physical: address + print-lab/dropship API (Prodigi/Gelato) + SKU mapping + tracking + color-managed PDF/ICC with crop marks; transactional email (replacing browser polling). *Delta:* **from zero** — flow ends at a free unwatermarked PNG `a.click()`. **XL, and partly a product decision (digital vs physical).**
- **Ops / observability / delivery.** *Target:* pinned Dockerfile (system GDAL/PROJ + hashed wheels), `.dockerignore`, compose for local parity, CI that builds the image; `/healthz` + `/readyz`; structured JSON logging + request IDs + metrics + error reporter; single env-driven config module with **absolute** paths (today cwd-relative) + CORS/allowed-hosts; asset distribution via object store the workers pull/cache on cold start; DB + blob backups; GDPR/CCPA delete/export/retention. *Delta:* no Dockerfile/CI/compose/pyproject; no health routes; zero logging/metrics; config half-env/cwd-relative; DEMs undistributed; no backups/privacy lifecycle. **L–XL.** *(Note: reproducible GDAL/PROJ containerization that matches local render byte-for-byte routinely eats days — don't under-scope it.)*

---

## 4. The Big Rocks / Critical Path

1. **Global geo coverage + provisioning + projection generality (hardest).** Not a swap — a replacement of the whole coverage model: global DEM/water + licensing/attribution, a tiled global store + spatial index + cache, extent-based projection surviving polar/antimeridian/wide extents, and a decision to **pre-materialize tiles into your own store** rather than wire live third-party fetches into the request path. Every "any user" claim blocks here.
2. **Durable, split render infrastructure.** In-memory jobs + in-process store + local blobs + inline rendering all assume one immortal machine. Broker + worker fleet + persisted jobs + networked store + object store + concurrency caps must land **together** (half of it still loses work on restart).
3. **Payments + print fulfillment.** Real money + physical goods: Stripe, orders, a paid gate on the unwatermarked deliverable, and (if physical) a lab integration with color-managed export, address, SKU, shipping. Partly a **product decision**.
4. **Auth + multi-tenancy.** The precondition for *any* multi-user or paid feature; payments, privacy, and quotas all bind to it.
5. **Ops foundation** — containerize, CI, observe, distribute assets. Nothing hosted starts without it; also de-risks v1.
6. **Correctness + real-input trust** (the v1 rock that gates v2 credibility) — fabricated terrain, missing DEM, store aliasing, never-tested-on-real-exports. If posters can be silently wrong, no one can trust the output before scale amplifies it.

---

## 5. Prioritized Roadmap

### P0 — v1 hardening (make the local tool trustworthy)
1. **V1-4 CI + committed synthetic test region + V1-9 pins** *(first — the safety net for everything after).*
2. **V1-1 off-DEM guard + V1-2 real DEMs for both regions** (same root cause) with **V1-5/Open-Q4 real-exports-on-real-terrain as an early parallel spike.**
3. Batch **V1-3 deepcopy + V1-6 upload-hardening + V1-7 gx:Track + V1-12 archive sources.**
4. **V1-8 lifecycle cleanup + V1-11 logging.**
5. **V1-10 finished-poster + print-correctness** (last mile, iterate with Dom).
**Exit:** §2 acceptance criteria met.

### P1 — v1.x polish + v2 infra foundations (promote the seams; single-tenant, still not public)
- **Ops foundation:** Dockerfile + `.dockerignore` + compose + CI-builds-image; `/healthz`+`/readyz`; structured logging + error reporter; config module (absolute paths, CORS/host/port).
- **DEM distribution channel** (object store the deploy pulls/caches on cold start).
- **Postgres `SessionStore`** (Alembic + versioned schema + atomic update) and **S3/GCS `Blobs`** (+ delete + presigned URLs); stop writing finals into `region.dir`.
- **Offload sync renders** off the event loop (`run_in_threadpool`) as an interim before the broker.
> **Critic caveat:** do **not** stand up a *public, unauthenticated* hosted single-tenant state — it's a security liability (public finals leak, unbounded renders) for little payoff. Keep v1 local; if a hosted single-operator instance is wanted, gate it behind at least a shared secret. Auth should land *with* the public infra, not after a risky unauthed window.

### P2 — v2 build (the product surface), in dependency order
1. **Auth + multi-tenancy** *(the gate — blocks everything below)*. Includes a **v1→v2 data-ownership migration/backfill** story (existing sessions/finals/photos carry no owner) and versioned-schema migration of the opaque JSON rows.
2. **Durable render infra** (broker + workers + persisted jobs + concurrency caps). *Depends on P1 Postgres+S3.*
3. **Global geo pipeline** (global sources + attribution, tiled store + index + cache, extent-projection with loud errors, **offline catalog-build kept separate from request-time provisioning**, `native_resolution_m` from source). *Depends on durable jobs + object store.* **Decide first: on-demand any-AOI vs a curated expanding catalog** — the curated catalog is far cheaper and sidesteps the ~4-min/190 MB first-upload latency + per-build cost that on-demand imposes.
4. **Payments + fulfillment** (pricing/quote, Stripe, orders, paid gate, color-managed export; if physical: lab API + address + SKU + tracking; email). *Depends on auth.* **Watermark robustness** (proof resolution ceiling + non-removable mark) is a prerequisite of the free/paid gate.
5. **Self-serve UX** (coverage onboarding replacing raw 422; **touch-action fix for canvas drag**; typed/humanized errors + bounded poll; real-scale size/price/material preview). *Depends on geo + payments.*

### P3 — scale / compliance / polish
Data-privacy lifecycle (delete/TTL across store+blobs+uploads, delete-my-data + export, retention, privacy policy — **pull earlier if launching in EU/CA**); ToS/acceptable-use/refund/support; **golden-image visual regression** (depends on P1 pins) + load tests to size the fleet + upload-abuse suite + frontend tests (vitest/jsdom + Playwright); worker autoscaling, CDN, cost controls, cache warming; **i18n/units/non-Latin place names** for a global product.

**Critical path:** P0 correctness → P1 ops + durable backends → **P2 auth (the hinge)** → durable render infra → global geo → payments/fulfillment → self-serve UX → P3.

---

## 6. Top Risks & Open Questions (resolve before committing to the v2 build)

**Scariest (silently-wrong or premise-blocking):** fabricated terrain (accept-and-ship a *plausible* wrong poster); a shipped region that can't render; "everything hosted assumes one immortal machine"; coverage is two US counties; no auth/payments/fulfillment.

**A unit-economics go/no-go gate** *(from the critic — belongs ahead of P2, not in P3):* a 300-dpi final is ~18 s and hundreds of MB transient RAM, single-threaded, re-reading a ~190 MB COG with no cache. Profile peak per-render memory + add DEM caching, then tie a per-render cost to a price floor **before** fleet-sizing or pricing.

**Open questions, in the order they gate work:**
1. **Digital-only or physical prints?** Forks the entire fulfillment rock (lab, address, color-managed export, compliance). *Resolve before P2 planning.*
2. **Which global DEM/water sources — and are their licenses OK for commercial sale?** (Copernicus GLO-30 attribution; OSM water ODbL share-alike; SRTM/HydroSHEDS.) Determines the poster's required attribution and whether the current zero-attribution renderer is even legal at scale. *Blocks the geo design.*
3. **On-demand any-AOI vs a curated expanding catalog?** The single decision that most shapes P2 scope, latency, and cost. The catalog is likely right *because* of the ~4-min/190 MB build latency.
4. **Is the by-eye look actually good on real terrain and real exports?** The entire aesthetic was tuned on a synthetic noise DEM and a synthetic single-segment GPX. *Resolve in P0 (V1-2/V1-5) — it can invalidate downstream tuning.*
5. **What is "client quality," concretely?** No acceptance rubric or golden baseline exists; v1 "done" is undefined until it does.

**Bottom line:** the seams are the asset. Spend **P0** making the local tool *trustworthy* (correctness + CI + real inputs against an agreed quality bar); **P1** making the seams' backends *real and deployable*; then treat **auth as the gate** into a v2 whose genuinely hard, still-open questions are **global geo coverage + data licensing** and **the physical-vs-digital fulfillment fork** — resolve those two, plus the unit-economics gate, before committing to the v2 build.

---

### Appendix — Verified critical findings (hand-checked, with evidence)
- **Fabricated terrain:** `app/relief.py:28-34` (`_fill_nan` → `np.nanmean` crop-mean substitution) + `app/render.py:52` (`boundless=True, fill_value=np.nan`) + `region.json` bounds overhang the real DEM (observed as a 7-line bounds drift on rebuild).
- **Store aliasing:** `app/store.py:25,32` (`copy.copy` shallow; nested `hotspots` shared).
- **Missing/undistributed DEM:** `regions/susanville_reno/` has `region.json`+`overview.png`+`hydro.json` but no `dem.tif`; DEMs are gitignored with no distribution channel.
- Full 54-finding set (8 lenses, verdicts, evidence) retained in the red-team run artifact.
