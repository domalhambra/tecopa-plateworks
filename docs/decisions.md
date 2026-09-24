# Decisions

Durable choices that constrain later work, dated, with the reason and where
the decision is carried. Never delete a row. When a decision is reversed,
mark the old row superseded and add the new one under its own date.

The six engine invariants are restated in `../CLAUDE.md`.
`superpowers/handoffs/HANDOFF.md` names Dom's original build plan as their source. That
plan lives outside this repo. Rows below cite a commit in this repo, a spec or plan under
`superpowers/`, an assessment, or a handoff. "Design record" means the
`Decisions` or `Decision record` section of the named spec.

## 2026-06-29 (v1 architecture)

| Decision | Why | Source |
|---|---|---|
| The engine splits at one seam. `compose` decides the picture once in ground coordinates and emits a `CompositionSpec`. `rasterize` paints that spec at any resolution. The proof and the final are the same spec at two pixel sizes. | Invariant 1. Never compute the picture twice. | `superpowers/specs/2026-06-29-trailprint-v1-architecture-design.md`; commits c5f7336, 5b03e55 |
| Every visual value is physical (points, inches, ground metres) and converts to pixels at paint time. | Invariant 2. A pixel-sized element looks bold in the proof and vanishes in the final. The bug shipped more than once. | commit 13c8cc7; `app/spec.py` |
| Same spec plus seed gives an identical image. Grain and jitter are seeded on the spec. | Invariant 3. The proof predicts the print. | commit c36b38b; `app/relief.py` |
| One projection throughout. DEM, overview, tracks, crop and hydro live in the region CRS in metres. Tracks arrive in lon/lat and are reprojected at ingest. | Invariant 4. | commit fa0bd43; `app/ingest.py` |
| `app/geo.py` is the only source of coordinate conversions. Prove the coordinate chain before tuning aesthetics. | Invariant 5. Registration is correctness. | commits 68365af, e4cd440 |
| The zoom cap is judged at the final dpi, at proof time. A large print of a small plate gets a 422. | Invariant 6. Never request finer ground detail than the data holds. | commit ee7a51f; `CompositionSpec.validate` in `app/spec.py` |
| Region data (the DEM, `hydro.json`, labels) is read from the region folder by `render`. The spec holds only the picture decisions. | The spec must stay a small, portable recipe. | the v1 spec; `superpowers/handoffs/HANDOFF.md` |
| v1 stays local and single-user: no database, no queue, no hosting. | Product decision 1 of the v1 spec. | the v1 spec, Goal |
| Hydrography is vector, baked to `hydro.json` by `region_prep.py`, and drawn in physical units at paint time. | It scales correctly across dpi. | commits 33dcf6d, 4921466 |
| KML and KMZ import share one `_make_track` helper behind a format sniff. | One ingest path for every format. | commits ac59c72, 410dea2 |
| `dem.tif` is the one gitignored plate asset. Every other file under `regions/<id>/` is committed. | The DEM is large and regenerable. Everything else is small. | `.gitignore`, the single rule `regions/*/dem.tif` |

The committed set grew after this date: `sources.json` and `labels.json` arrived
2026-07-02, `landcover.tif` on 2026-07-03, `playa.json` on 2026-08-13. Today a built
plate holds `region.json`, `overview.png`, `hydro.json`, `sources.json`, `labels.json`,
`landcover.tif` and `playa.json` in git, and `dem.tif` on the machine only.

## 2026-06-30 and 2026-07-01 (multi-region, markers, server foundation)

| Decision | Why | Source |
|---|---|---|
| A region registry discovers every `regions/<id>` folder. The app is pinned to no region. | Multi-region was v1.2 of the build plan. | commit 69d4167; `app/regions.py` |
| Marker icons are vector shapes, never emoji. | Determinism across hosts. | commit 1275a96 |
| Sessions, blobs and the render queue sit behind small interfaces: `MemoryStore` or `SqliteStore` (`TECOPA_STORE=sqlite`, then `TRAILPRINT_STORE`, renamed 2026-07-20 in commit 5083073), `LocalBlobs`, `ThreadJobQueue`. | A real server can replace each one later without a teardown. | commit c5602bd; `app/store.py`, `app/blobs.py`, `app/jobs.py` |
| The studio is vanilla ES modules with no build step and no JS test runner. | Kept simple on purpose. Front-end checks are text tests and a browser drive. | `superpowers/specs/2026-06-30-trailprint-studio-wizard-design.md`; commit 549c7b7; `tests/test_static_registry.py` |

## 2026-07-01 and 2026-07-02 (hardening, the manifest)

| Decision | Why | Source |
|---|---|---|
| `tests/conftest.py` hydrates a tiny synthetic DEM, tagged `synthetic=1`, for any plate that lacks one. The DEM-gated suites run on a fresh clone and in CI. | The red team found 29 percent of the suite silently not running. | commit 2607a2a |
| A fabricated-terrain guard and `/readyz` report whether every plate has a DEM whose bounds match its `region.json`. | Never render invented ground as real. | commit 2607a2a |
| Plate bounds are derived from the real 3DEP DEM, not typed. | The DEM is the truth. | commit 9eccde0 |
| A quality bar with committed golden references under `superpowers/quality/golden/`. Formal acceptance on a printed proof is still open. | The red team said definition-of-done was missing. | `superpowers/quality/2026-07-02-v1-quality-bar.md`; commit e77bfb3 |
| Every final PNG embeds its manifest in one zTXt chunk with the keyword `trailprint`. The keyword is frozen forever. | Renaming it orphans every poster ever printed. | commit ef396ba; `MANIFEST_KEY` in `app/provenance.py`; `MANIFEST.md` |
| Named geography comes from USGS GNIS, baked offline to `labels.json` by `scripts/build_labels.py`. | Real place names, public-domain source. | commit ef396ba |
| Cast shadows and sky occlusion are implemented natively in `app/relief.py`, ray-marched and seeded. | The Blender look without a path tracer. | commit 3a6558e |
| An adversarial review pass after each substantial component. | It caught about 15 real bugs in one session, including a 90-degree rotated hillshade. | `superpowers/handoffs/HANDOFF.md`; commits a2a09f4, 5ca5ee4 |

## 2026-07-03 to 2026-07-11 (v1.2 and v1.3 features)

| Decision | Why | Source |
|---|---|---|
| `plan_build` sizes a region build before any fetch. | A corridor-scale bbox once tried to allocate 15.8 GB. | commit ac72087; `region_prep.py` |
| Biome tint reads NLCD land cover from `landcover.tif`. | v1.2 of the build plan. | commit b062b4f |
| A wallpaper is a print whose sheet size is the device pixels divided by its ppi. The final dpi is the device ppi. PNG only. | Every engine invariant carries over unchanged. | `superpowers/plans/2026-07-05-wallpaper-output.md`; commit 2a4d3a8; `app/wallpaper.py` |
| Living editions. `POST /api/continue` renders the next edition from last year's PNG plus new tracks, with lineage in the file. | The record is alive. Pillar 3 of `scope.md`. | commit 1571987; `superpowers/plans/2026-07-08-living-editions.md` |
| The time-lapse film is the same spec performed along its time axis. Its last frame is pixel-equal to `render.rasterize` at the same dpi. | Pillar 1 of `scope.md`. Asserted in `tests/test_timelapse.py`. | commit f1c10a8; `superpowers/plans/2026-07-08-timelapse.md` |
| The goal is restated as a self-archiving chronicle. Pinned photos travel inside the manifest as data URIs, and the path sanitizer is deleted. | A manifest can no longer carry a server path, so there is nothing to traverse. | commit df50a5d; `scope.md`, commitment 1 |
| One door for untrusted manifests: `provenance.spec_from_manifest`. Every file-consuming verb funnels through it. | The guard chain is audited once. | commit 6a652c8; `scope.md`, commitment 2 |
| Every marketing image is rendered by the engine. Every claim has a test behind it. | Marketing honesty. | commit 9580cd4; `marketing.md` |
| Uploads deduplicate at track level. | The yearly ritual drops last year's poster and the whole GPX folder in one gesture. | commit 369ba0d |

## 2026-07-12 and 2026-07-13 (strategy, license, name)

| Decision | Why | Source |
|---|---|---|
| Code is AGPL-3.0-or-later. Region plates and the manifest schema are CC0-1.0. The name and branding are covered by neither. | The only license that keeps the reprint promise true, reads well to the audience, and blocks a proprietary hosted fork. `or-later` for the day no copyright holder is left. | `superpowers/plans/2026-07-12-strategy-and-license.md`, Decision 2; commit d14445c; `LICENSE` |
| Keep relicensing power: the first outside contribution needs a DCO sign-off or a CLA. | Sole authorship is what makes dual licensing possible. | the same plan, Decision 2 |
| The product trunk is a published local engine. Revenue is prints, editions, plate commissions and a packaged app. Plates are free forever. The hosted-proprietary v2 is retired. | A paywalled plate would tax the product's own archival claim. | the same plan, Decision 1 |
| Every plate input is U.S. federal public-domain data, so plates may be sold. A non-USGS source is a hard gate and must be cleared before it enters a plate. | Losing the all-public-domain posture should be a decision, never an accident. | the same plan, Decision 3 |
| The name is Tecopa Plateworks, always the full compound. "TrailPrint" was a no-go and "Hillshade Press" was declined. | A senior common-law user and a same-niche product own the old name. A Minnesota flexographic-plate maker owns the bare word "Plateworks". | commits 589b410, eb934cb; `superpowers/plans/2026-07-12-marketing-language-branding.md` |
| The manifest names its plate: a `region_pack` block records every asset the render read, by sha256. | Hashes identify a plate. URLs rot. | commit bb785f2; `MANIFEST.md` |
| Plates are artifacts: `scripts/pack_region.py` packs a deterministic zip and `.venv/bin/python -m app.plates install` verifies every hash. | A plate is not a laptop's state. | commit cc80d9f; `app/plates.py` |
| Share twins (WebP, MP4, mockups, the GLB) carry no manifest. | They are share-class, not the record. | commits a744f41, 4d0f8a5; `../marketing/README.md` |
| The data credit rides the spec (`credit_text`). | Attribution becomes law the day a non-federal source enters. | commit f52cb45 |
| Six single-topic plans were consolidated into two documents. | Four of six bundled cheap fixes with unpriced infrastructure. | commit d14445c |
| Imported design scaffolding was pruned before the repo went public. | Nothing private in a public history. | commits 681bd59, 9ed7fc6 |

## 2026-07-14 to 2026-07-18 (looks, output fitness, the launcher)

| Decision | Why | Source |
|---|---|---|
| High relief is a plan-oblique shear on the spec (`oblique`). | A knob, not a second renderer. | commit fd72706 |
| Journey Light stores the resolved sun on the spec, never the GPX timestamps. | Reprint and continue reproduce the light without the source file. | commit 10ebb80; `app/solar.py` |
| Smart label placement and the chronological track weave are opt-in spec fields whose defaults are the old behavior. | Every existing poster reprints untouched. | commit 1d460dc |
| Bleed and trim geometry is parameterized. The final config values wait on a print lab. | The lab's spec is an external contract and lives as data. | `superpowers/quality/2026-07-17-print-lab-questionnaire.md`; commit 8593c0c |
| The macOS launcher binds port 8848 on localhost, signs ad hoc, bakes the repo path at build time, and runs the engine from this repo's `.venv`. | Personal-use build. A `git pull` updates it with no rebuild. | `superpowers/specs/2026-07-18-macos-launcher-app-design.md`, design record; `scripts/macos/build_app.sh` |
| The bundle id is `guide.badwater.tecopa` and is name-neutral. | A rebrand must not make macOS see a new app. | `scripts/macos/Info.plist.template`; `../CLAUDE.md`, invariant 9 |

## 2026-07-19 to 2026-07-21 (GPX-first, the studio, the rename, CI)

| Decision | Why | Source |
|---|---|---|
| Tracks are dropped first. The region is an outcome: matched when a built plate covers them, built in-app behind a cost card when none does. | Fresh client tracks rarely land on a built plate. | `superpowers/specs/2026-07-19-gpx-first-region-creation-design.md`, Decisions 1 and 2; commits 5083073, d24a009 |
| In-app builds spawn `region_prep.py` as a subprocess in `.venv-prep` on a dedicated single-slot queue. The heavy fetch stack never enters the app venv. | In-process imports and a sidecar daemon were rejected. | the same spec, Decision 4; `app/regionbuild.py` |
| The single-window studio replaced the step wizard. A target switcher, two sidebars, and a progressive proof (instant draft, background refine). | The proof was too low-res to judge a poster. | commit 4e3a22f; `../SESSION_LOG.md` |
| `ENGINE` is `tecopa-plateworks`, stamped and never read back. `LEGACY_ENGINES` lists the two former values and nothing gates on any of them. | Old files must open. Readers must accept every historical value. | commit 4e3a22f; `app/provenance.py`; `MANIFEST.md` |
| `ENGINE_URL` names the repo's real name, never a redirect. | GitHub frees a renamed repo's old name for reuse. | commit e499359 |
| Env vars, `localStorage` keys, the bundle id and the download prefix are name-neutral (`TECOPA_*`, `tecopa`). | A rebrand orphans no saved preference. | `../CLAUDE.md`, invariant 9; `scripts/macos/Info.plist.template`; `app/provenance.py` |
| The suite runs under `pytest-xdist`. Heavy render tests carry a `slow` marker assigned centrally in `tests/conftest.py`. PRs run `-m "not slow"`. Every push to `main` runs everything. | The serial suite took about 33 minutes. | commit d62e673; `pytest.ini`; `.github/workflows/ci.yml`; `../SESSION_LOG.md`, 2026-07-21 |
| Each xdist worker gets its own `TECOPA_BLOBS` and `TECOPA_UPLOADS`. Synthetic DEMs are written atomically. | One worker's sweep must not evict another's result. | commit d62e673; `tests/conftest.py` |
| The nightly CI schedule was dropped. | The full suite already runs on every merge. | `../SESSION_LOG.md`, 2026-07-21 |
| Session logs go to the Notion Session Log database, with the convention inlined in the guide. `../SESSION_LOG.md` is the offline fallback. | A cloud container clones only this repo. | commits 1f6335a, bc01386 |

## 2026-07-25 and 2026-07-26 (the relief seam, the caches)

| Decision | Why | Source |
|---|---|---|
| New terrain techniques register at a stage (`color`, `light`, `finish`, `grade`) through `relief.register_relief_pass` instead of editing `shaded_relief`. A pass is a strict no-op at its pre-feature default. | Every shipped poster's terrain comes out of that one function. | commit 2b3f6a8; `relief-passes.md` |
| Wide blurs go through `relief._blur`, which decimates onto a fixed ground resolution. | dpi-stable and a fraction of the exact filter's cost. | `relief-passes.md` |
| The proof loop caches the painted terrain in a byte-budgeted LRU. The key is derived by masking known-inert fields, never by listing relevant ones. | A field added later lands in the key by default. The worst case is a miss, not a stale poster. | commit fb634b2; `superpowers/plans/2026-07-26-base-layer-cache.md`; `app/basecache.py` |
| The cache cut point sits just before place names are drawn. The cache stores RGBA. The default budget is 512 MB. | Labels stop being terrain inputs. Curved names over lakes read destination alpha. 256 MB evicted the draft and refine pair every step. | commit 1a4ea88 |
| Route ink is cached one layer up with the same masking construction. | Most knobs do not touch the route. | commit 5a0094e (2026-07-26); `superpowers/plans/2026-07-27-route-ink-cache.md`, filed the next day |

## 2026-07-27 (fonts, the forever-contract)

| Decision | Why | Source |
|---|---|---|
| The ink composite is restricted to its support. | Two full-sheet alpha blends over a raster that is non-zero on about 1 percent of pixels. | commits b473cd0, c9bbcf8; `superpowers/plans/2026-07-27-support-restricted-composite.md` |
| A drift test constructs its drift. It never inherits it from the host's plate. | Two tests were coupled to the local plate being wrong. | commits c81ca51, 5c22096 |
| No licensed font enters this public repo. `.gitignore` blocks `*.otf`, `*.ttf`, `*.woff` and `*.woff2`. | MB Type licence paragraph 7. History is permanent. | commit 39ad08c |
| Type is set by role (`body`, `point`, `area`, `water`, `title`). The operator binds faces per role with `TECOPA_FONT_<ROLE>`. Bindings ride in no manifest. | A licensed face stays operator-side. A redistributable default ships. | commits fca299a to f1678af; `superpowers/plans/2026-07-27-per-role-font-seam.md`; `TYPE_ROLES` in `app/render.py` |
| A curved label reads its direction from its glyphs, not its spine. | Range names rendered upside down. | commit 0b6b217 |
| **The forever-contract is retired.** The engine no longer promises byte-identical reprints across builds. `engine_version` rides every manifest and records drift. | The contract served an imagined stranger in 2035 and forced a revision question onto an ordinary bug fix. | `superpowers/specs/2026-07-27-retire-the-forever-contract-design.md`; commit ee63eb6 |
| Superseded by the row above: the additive-defaults rule, where a new field was omitted at its default so old manifests re-stamped byte-identically. `spec_to_json` now emits every field. Read-tolerance in `spec_from_json` is the promise that remains. | Only one of the two was expensive. | the same spec, section 2 |
| Superseded: `profile_rev` and `relief_rev` gates. Each collapsed to its rev-2 behavior. | The version stamp makes the gate unnecessary. | the same spec, section 1 |
| Superseded: a `region_pack` mismatch refuses with 422. It now warns and proceeds on `allow_plate_mismatch=true`. | USGS re-flying 3DEP must not block a customer's reorder. | the same spec, section 4 |
| Superseded: the resurrection note (`trailprint-note` tEXt chunk). No longer written. Files already printed keep theirs. | It baked a promise into every file sold. | the same spec, section 5 |
| Superseded: `MANIFEST.md` as a public CC0 specification. It is now an internal format doc. The CC0 dedication on published versions stands and cannot be revoked. | A decision to stop maintaining it, not a withdrawal. | the same spec, section 5; `MANIFEST.md` status note |
| Superseded: the orphan drill, the `serial` pytest tier, and the rev test suites. Deleted. The seven `tests/fixtures/manifest_*_v1.json` files stay as read-tolerance inputs. | They proved the retired scenario. | the same spec, section 5; commit ee63eb6 |
| Determinism within one build is unchanged and load-bearing. | It is what makes the proof predict the print. | the same spec, The line |
| A deleted test deletes its marketing claim. | The claims register rule, applied to itself. | commit ee63eb6 |
| The ink budget's documented ceiling is about 66 long journeys, not 90. The budget itself is unchanged. | Measured on a real onX track. Synthetic straight lines under-inked. | commit 103f5b2 |

## 2026-07-28 (the landing page goes live)

| Decision | Why | Source |
|---|---|---|
| The landing page is deployed by hand from a staged root built by `../marketing/build_deploy.py`, never from a git-connected build. | The imagery is the gitignored asset farm. A git build serves broken images. | commit b66b754; `../marketing/DEPLOY.md` |
| Plausible page analytics on the landing page, with its own property id. | The page carried no analytics. There is no CSP to allowlist. | commit 1f6b4c3 |

## 2026-08-10 to 2026-08-14 (Blender, looks, water, concurrency)

| Decision | Why | Source |
|---|---|---|
| Blender is not the engine. The hero plate is an operator-only CLI, non-deterministic by nature, whose output carries the source manifest unchanged. | No `bpy` wheel for Python 3.14. Cycles promises no bit-exactness. The engine already performs the load-bearing physics deterministically. | `superpowers/assessments/2026-08-10-blender-render-viability.md`; commit 60fdc09; `scripts/hero_plate.py` |
| Soft light and atmospheric haze ship as spec knobs through the relief seam. The server default is 0 for both. The studio starts a new poster at 35 and 15 percent. | Every poster printed before they existed reprints untouched. | commit 60fdc09; `app/looks.py`; `superpowers/plans/2026-08-10-softlight-haze-heroplate-plan.md` |
| Lake depth is synthesized from distance to shore. Tapered rivers are always on. Dry lakes come from a `playa.json` sidecar, and NHD ftype 361 stays out of `WATER_FTYPES`. | Filled as water, playas put 874 square km of fictional lake on one plate. | commit d6f6771; `region_prep.py`; `scripts/bake_playa.py` |
| The playa stipple is a paper screen sized in points, not a ground texture. | The sheet reads at one density at any crop scale. | commit c408c99 |
| The four heavy relief passes run concurrently on threads. Results merge in submission order. `TECOPA_RELIEF_WORKERS=1` restores the serial order, which the test pins. | 5.1 seconds of a final was serialized work with no dependency. The sheet stays bit-identical. | commit f305a77; `tests/test_relief.py` |
| On customer surfaces the order is craft first, the growing artifact second, the file-as-record last. | Architecture stories do not sell posters. | commit 703568d; `marketing.md`, Hierarchy correction |
| Two doors, never blurred: the concierge press and the free studio. Every order arriving by email is the CRM. | A landing page cannot close a sale for a service performed on someone's computer. | `marketing.md`, The funnel |
| CI also runs on `claude/**` pushes. | Cloud sessions push there, so CI fired only once a human opened the PR. | commit 20f1cca |
| Root-level tuning images were dropped from tracking and no ignore rule was added, per Dom. | The handoff had claimed a rule that never matched. | commit 20f1cca |

## 2026-08-15 and 2026-08-16 (real-network demo tracks)

| Decision | Why | Source |
|---|---|---|
| Demo journeys route over OSM via Overpass. The network lives in a gitignored cache and never enters a plate. | Plates are CC0. OSM is ODbL. | `superpowers/specs/2026-08-15-real-network-demo-tracks-design.md`, Decisions; commits fbbf2db, 2182c0b |
| The demo story is a year of six to eight separate outings across the plate. | One base-camp trip is why ink pooled centrally. | the same spec |
| The forced worn-trailhead mechanism is retired. | Instrumentation showed it unreachable on two plates and all but unreachable on the third: 0 of 96 trips on `lassen_ca`, 0 of 96 on `elko_bonneville`, 2 of 96 on `tushar_beaver_ut`. Structural, not a tuning miss. | commit 6f45ec6 |
| Trip length is a plate-scaled target, not a floor. | Corridor plates need different spans. | commit bdae6ef; `TRIP_SPAN_FRAC` in `scripts/track_network.py` |
| The delete-after-ship promise was removed from the page rather than adopted. | No retention practice exists to honor it. | commit 7a0336d |

## 2026-08-16 and 2026-08-17 (the Collector, the terrain guard)

| Decision | Why | Source |
|---|---|---|
| The Home-Ground Collector profile is canon for every customer-facing surface. The physical poster leads. Privacy reassurance is struck from customer copy. | Nobody ordering a poster believes the print shop is a privacy risk. | `superpowers/specs/2026-08-16-target-customer-profile-design.md`, Decisions; commit 9d881d3 |
| The register is enforced by `tests/test_marketing_page.py`: banned builder vocabulary, pinned customer anchors. | A wording change alone can turn the tests red, on purpose. | commit cb4d7f9 |
| The price tension is recorded, not resolved: the profile says $80 for an 18 by 24, the page says $149. | Pricing is Dom's separate decision. | the same spec, Decisions |
| The farm stamps the DEM it opened into `assets/index.json` as a `terrain` record. The deploy refuses any region that is synthetic or unrecorded. The record is stamped at render time, never re-derived at deploy time. | A synthetic DEM renders cleanly. A machine can render from a stand-in and get the real DEM afterwards. | commits e0ae019, 2b34d26; `../marketing/DEPLOY.md`, The terrain guard |
| The 1:1 detail crop is chosen by scanning for route ink, with a fallback to centre. | The real-network tracks made the centre the emptiest part of every poster. No test could see it. | commit 615f21d; `superpowers/handoffs/2026-08-16-collector-register-and-terrain-guard.md` |
| `sources.json` drift on a rebuilt DEM is a record, never re-stamped. `scripts/verify_regions.py` is a script, not a test. A `--repair-dem` mode was dropped on review. | The mismatch is the only evidence the plate was swapped. A no-drift test would be red on every fresh clone. | commit f518be8 |
| A farm run that lost a region exits non-zero. Wallpapers may not roam off the DEM. | Silent partial output is worse than a failure. | commits 6bf0160, d7b7905 |

## 2026-09-01 to 2026-09-03 (the geometry gate, privacy)

| Decision | Why | Source |
|---|---|---|
| Every render verb refuses a plate whose DEM geometry drifts from its `region.json` with a 503 that names the drift. No override. An engine gate, not a git hook. No readiness cache. | The pull orphan painted a misregistered poster three times since July. | `superpowers/plans/2026-09-01-dem-geometry-gate.md`; commits 4709cf3, ba9e644, 99ad6f1; `_ready_or_503` in `app/main.py` |
| The farm refuses an orphaned DEM as well. `--synthetic-dem` stands in for a missing DEM only. | It cannot paper over a wrong one. | commit 8b5c131 |
| `.venv` is built from the CI recipe: the lock, then `pandas geopandas`, then `requirements-share.txt`. The region-prep stack never enters `.venv`. | Installing `py3dep` and `pynhd` pulled numpy, scipy and rasterio past their pins for six weeks. | commit 58d8899; `changing-things.md`, Set up a machine |
| A privacy page serves at `/privacy/`, copied verbatim into the staged root. Its claims are pinned to the landing HTML by test. | Change the landing page and the privacy page goes red until its copy follows. | commit 58905c4; `../marketing/privacy.html`; `tests/test_marketing_page.py` |
| FastAPI's auto-docs (`/docs`, `/redoc`, `/openapi.json`) are switched off, pinned by a test. | The default pages fetch Swagger UI and ReDoc from jsDelivr, which breaks the privacy page's promise. A thread asks whether to keep or revert this. | commit a3d4ba9; `tests/test_main.py` |
| The folder on disk is `Tecopa Plateworks/`, renamed from `Badwater Trails/`. | The folder matches the brand. | commit d5a6d89 |
| The privacy promise is stated in the customer's terms: no analytics, no tracking, one outbound request for public map data. | A customer never sees the studio, plates, USGS or MRLC. | commit a9dec6c |

## 2026-09-08

| Decision | Why | Source |
|---|---|---|
| This repo follows the documentation standard: the guide becomes a router under 2,000 tokens, task docs live in `docs/`, and the check runs with the suite. Existing handoffs, assessments and quality docs stay where they are and are indexed as history. | The 27 KB guide loaded whole on every session. | `00_Resources/documentation-standard.md`; this rollout |
| `scripts/docs_check.py` is vendored byte for byte from Badwater OS and run by `tests/test_docs.py`. No CI change was needed. | `pytest.ini` sets `testpaths = tests`, so both tiers collect the test. `tests/conftest.py` does not classify it as slow, so a pull request runs it too. | `tests/test_docs.py`; `pytest.ini`; `.github/workflows/ci.yml` |
| The check is given exactly five `known_absent` entries, in place of the default: `cache/`, `blobs/`, `assets/`, `.venv/`, and `docs/superpowers/assessments/2026-09-02-metal-render-viability.md`. The default excuse for `../SESSION_LOG.md` is deliberately not carried over. | The four folders are gitignored runtime output. A fresh clone lacks them, and the docs name all four, plus `assets/index.json` under one of them. The assessment is written but deliberately uncommitted, so a fresh clone must still pass. This repo's `../SESSION_LOG.md` is tracked, so excusing it would only hide a real deletion later. | `.gitignore`; `tests/test_docs.py` |
| The manifest's forward-tolerance rule leaves the guide. `docs/MANIFEST.md` keeps the binding half: a reader MUST treat `trailprint`, `tecopa-printworks` and `tecopa-plateworks` as this engine. | It is a schema rule, not a routing rule, and the manifest is the document that owns it. The router points at the manifest. The guide's second half, that a reader must not reject an unrecognized fourth value, is not restated: `MANIFEST.md` never carried it, and its Schema evolution section covers unknown keys rather than an unknown engine value. | `docs/MANIFEST.md`, the `engine` field and Schema evolution |
| The guide's dated known-local-failure counts leave the router. | A dated measurement goes stale fastest in the one file every session loads. The failing set is a section of `docs/changing-things.md` instead. | `docs/changing-things.md`, Run the tests |
| The full `sources.json` drift table, with digests and byte deltas, is not restated in the new docs. | Another dated measurement. Commit f518be8 and the 2026-08-17 row hold it. "Repair an orphaned DEM" names the four rebuilt plates and points at both. | commit f518be8; `docs/changing-things.md`, Repair an orphaned DEM |
| The guide's naming history, versioned-drift essay, venv forensics, launcher paragraph, region gotchas and repo map move into `docs/decisions.md`, `docs/architecture.md` and `docs/changing-things.md`. | The router carries only what every session needs. Nothing was dropped except the dated measurements named in the two rows above: the known-local-failure counts and the `sources.json` drift digests. The move was verified by grep before the guide was trimmed. | this rollout |
| The plate release ritual leaves `README.md`. `scripts/pack_region.py <id> --resync` stays, inside "Repair an orphaned DEM". | The ritual was never run and no plates folder has ever existed. `--resync` is the designed packing path and is still needed. | commit f518be8; `superpowers/handoffs/2026-07-12-implementation-handoff.md` |
| The orphan drill and the `serial` pytest tier are not documented. | Both were deleted on 2026-07-27 with the forever-contract. No procedure remains to carry. | `superpowers/specs/2026-07-27-retire-the-forever-contract-design.md` |
| The README's import smoke line is replaced by the fast test tier. | The fast tier proves the same imports and more. | `README.md`, Prove a change |
| The launcher's first-launch permission narrative is compressed to the rule that matters: keep the bundle id `guide.badwater.tecopa`. | A changed bundle id reads to macOS as a new app, which re-prompts for Documents access. The prompt wording is OS behavior, not a procedure. | `docs/changing-things.md`, Rebuild the macOS launcher |

## 2026-09-23 (price, demo journeys)

| Decision | Why | Source |
|---|---|---|
| The Print is $80 at 18×24, digital Poster included. The Edition N+1 reprint drops from $99 to $55. Print and reprint prices superseded 2026-09-24. | Dom's call against the customer profile's $80 sense. The reprint must stay below a first print, and $55 keeps the old two-thirds ratio. | `marketing/landing.html` pricing band |
| A demo destination unreachable from its trailhead is replaced by the next candidate in selection order. A plate that loses none keeps its exact trips. | A disconnected OSM pocket shipped tushar_beaver_ut with seven journeys. The selector's order is prefix-stable, so the retry cannot move an approved poster. | commit 27f0b58 |
| A corridor plate (short side 150 km or more) composes 5 journeys at 10–20% of the short side, capped at 60 km. | Dom's taste call: at corridor scale the demo tells a drive. Only elko_bonneville qualifies. | commit 27f0b58; `CORRIDOR_*` in `scripts/track_network.py` |

## 2026-09-24 (print sizes)

| Decision | Why | Source |
|---|---|---|
| The Print comes in two sizes: $90 at 18×24 and $80 at 13×19. This supersedes the 2026-09-23 $80 at 18×24. Superseded later the same day by $89 and $79. | Dom's call. The 13×19 keeps the profile's $80 entry price. | Dom, 2026-09-24; `marketing/landing.html` pricing band still shows the old price |
| The Poster, the digital final, drops from $79 to $39. | Dom's call. At $79 it sat $1 below the 13×19 Print, which includes it. | Dom, 2026-09-24; `marketing/landing.html` pricing band still shows $79 |
| The Edition N+1 digital edition drops from $49 to $25. | Dom's call. At $49 it cost more than the $39 Poster, and the reprint must stay below a first year. $25 keeps the two-thirds ratio. | Dom, 2026-09-24; `marketing/landing.html` pricing band still shows $49 |
| The Print is $89 at 18×24 and $79 at 13×19. | Dom's call, replacing the $90 and $80 set earlier the same day. | Dom, 2026-09-24; `marketing/landing.html` pricing band still shows $80 at 18×24 |
| The plate commission is retired as a product. The $299 tier comes off the landing page. | Dom: "it's not really a thing." `marketing.md` and the landing page's coverage copy still name it. | Dom, 2026-09-24 |
| The Edition N+1 reprint is $69 at 18×24 and $59 at 13×19. | Dom's call. Each reprint stays below its size's first print. | Dom, 2026-09-24; `marketing/landing.html` pricing band still shows $55 |

## Rejected and deferred

| Date | Item | Why | Source |
|---|---|---|---|
| 2026-06-29 | Server seams in v1: a database, a queue, hosting. | v1 finishes features locally. The seams were built behind interfaces on 2026-06-30 and promotion to a real server is still deferred. | the v1 spec; `superpowers/handoffs/HANDOFF.md`, what's next |
| 2026-07-12 | The hosted-proprietary multi-tenant v2. | Retired as strategy. A public AGPL engine forecloses selling access to the renderer. | `superpowers/plans/2026-07-12-strategy-and-license.md`, Decision 1 |
| 2026-07-12 | The neighbor-plate cross-sell feature. | Cut outright, not deferred. | commit d14445c |
| 2026-07-12 | "Hillshade Press" as the name. | Dom declined it and steered to Tecopa. | `superpowers/plans/2026-07-12-strategy-and-license.md`, Decision 2; `superpowers/plans/2026-07-12-marketing-language-branding.md` |
| 2026-07-12 | Publishing plate packs as release assets and committing a plates index. | Never run. No plates folder has ever existed, no plate has ever been packed. `README.md` named the ritual until the 2026-09-08 rollout removed it. | `superpowers/handoffs/2026-07-12-implementation-handoff.md`, What remains; commit f518be8 |
| 2026-07-17 | Final bleed and trim values. | Await a print lab's answers. | `superpowers/quality/2026-07-17-print-lab-questionnaire.md` |
| 2026-07-18 | Notarization of the launcher. Runtime discovery of the repo path. | Ad-hoc signing for a personal build. An alert on a moved repo beats a heuristic. | `superpowers/specs/2026-07-18-macos-launcher-app-design.md`, design record |
| 2026-07-19 | An auto-proof preview, a sample-tracks demo, a no-match graticule map. In-process `region_prep` imports. A sidecar daemon. | Cut from GPX-first. The subprocess in `.venv-prep` won. | `superpowers/specs/2026-07-19-gpx-first-region-creation-design.md`, Decisions |
| 2026-07-27 | Recording the bound faces in the manifest. | Deferred until the font seam landed. Not decided since. | `superpowers/specs/2026-07-27-retire-the-forever-contract-design.md`, Not decided here |
| 2026-07-27 | Threading the ink support through a cache hit. | Measured, declined. | `superpowers/plans/2026-07-27-support-restricted-composite.md` |
| 2026-08-10 | Blender as the engine. `bpy` in process. | No 3.14 wheel, no determinism contract, the film target dies. | `superpowers/assessments/2026-08-10-blender-render-viability.md` |
| 2026-08-14 | A gitignore rule for root-level tuning images. | Per Dom. | commit 20f1cca |
| 2026-08-16 | The print price: $80 by the profile, $149 on the page. | Dom's call. Decided 2026-09-23: see that section. | `superpowers/specs/2026-08-16-target-customer-profile-design.md` |
| 2026-08-17 | A `--repair-dem` mode that re-stamps `sources.json`. | It makes the drift gate unable to ever fire. | commit f518be8 |
| 2026-09-01 | A git hook for the geometry gate. An override flag. A readiness cache. | The engine is the gate. A misregistered DEM has no honest render. | `superpowers/plans/2026-09-01-dem-geometry-gate.md` |
| 2026-09-02 | Metal as a render path. | Not now: no determinism contract on the GPU, a bounded gain, no CI parity. Assessment committed in `d49fb82`. Dom accepted the verdict on 2026-09-23 and declined the optional CPU lookup table. | `superpowers/assessments/2026-09-02-metal-render-viability.md` |
| 2026-09-02 | Keeping or reverting the auto-docs switch-off. | Kept off. Dom closed the thread on 2026-09-23. | commit a3d4ba9 |
| 2026-09-08 | A project charter (PROJECT_CHARTER.md) and a DESIGN.md. | Deferred to Dom. Charters are hand-written, never generated. | this rollout |
