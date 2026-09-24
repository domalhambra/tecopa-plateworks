# Documentation index

Every document in this folder, and when to read it. `tests/test_docs.py` runs
`scripts/docs_check.py` with the suite: it fails when a file under `docs/` is missing
from this list, when a quoted path in `../CLAUDE.md`, `../README.md`, `../AGENTS.md`,
this file, or any top-level doc here does not exist, when the guide passes 2,000
tokens, or when it stops routing to a task doc.

## Working documents

| Document | Read when |
|---|---|
| `architecture.md` | You are new here, or you need to know which file owns a behavior and which test covers it. The shape, the module map, runtime behavior, environment variables, delivery, the harness, cross-repo dependencies. |
| `changing-things.md` | You are about to change something. One section per task: set up a machine, run the tests, repair an orphaned DEM, build a plate, a relief technique, a spec knob, the manifest, fonts, the studio front end, the farm and the landing-page deploy, landing copy, the launcher, a hero plate, a decision or spec. |
| `decisions.md` | Something looks like a past decision and you want the reason before you touch it. Dated, newest last, with superseded rows kept and a Rejected and deferred table at the end. |

## Reference

Undated documents that still govern something. Each is path-checked.

| Document | Read when |
|---|---|
| `MANIFEST.md` | Changing what a poster file carries. Schema v1 of the embedded manifest: top-level keys, the spec, sources, editions and lineage, animation, the region pack, schema evolution, privacy. Internal format documentation since 2026-07-27, no longer a maintained public CC0 specification. |
| `relief-passes.md` | Adding a terrain technique. The seam: spec field, `relief_extra`, `register_relief_pass`, the stages, the four rules a pass keeps, and how to verify it. Its body predates the forever-contract retirement. The two corrections in the blockquote at the end of "The three moving parts" govern where they disagree. |
| `scope.md` | Deciding whether a feature belongs. The chronicle goal, the three pillars (time-lapse, photos, living editions), each objection inverted, the engineering commitments, and what stays out of scope. |
| `marketing.md` | Writing anything a customer reads, after the Collector profile spec. The message ladder, the feature translation table, what is sold and what is free, audiences, the landing page blueprint, channels, the 2026-08-13 hierarchy and funnel corrections. |

## Specifications

| Document | Read when |
|---|---|
| `superpowers/specs/2026-06-29-trailprint-v1-architecture-design.md` | You need the v1 design: local, single-user, no database or queue. KML and KMZ import, multi-file upload, baked hydrography, the first sized region. |
| `superpowers/specs/2026-06-30-trailprint-studio-wizard-design.md` | You want the four-step wizard the studio replaced on 2026-07-21. History of the front end's first shape. |
| `superpowers/specs/2026-07-18-macos-launcher-app-design.md` | Changing the launcher. The Swift app on port 8848, ad-hoc signing, the alert on a moved repo, and the design record of what was declined. |
| `superpowers/specs/2026-07-19-gpx-first-region-creation-design.md` | Changing how tracks find or build a plate. Drop first, match a built plate, or build one through the `region_prep.py` subprocess in `.venv-prep`. Its Decisions section lists what was cut. |
| `superpowers/specs/2026-07-27-retire-the-forever-contract-design.md` | Touching `engine_version`, `spec_from_json`, or any promise about reprints across builds. Cross-build drift is recorded, not prevented. Its "Not decided here" list is still open. |
| `superpowers/specs/2026-08-15-real-network-demo-tracks-design.md` | Changing the farm's demo journeys. Seeded routes over the cached OSM network, anchored at real destinations. `scripts/` only. |
| `superpowers/specs/2026-08-16-target-customer-profile-design.md` | Editing any customer-facing sentence. Canon for the Home-Ground Collector: his four doubts, the seven register rules, the say-instead table. Gated by `tests/test_marketing_page.py`. |
| `superpowers/specs/2026-09-08-documentation-layout-design.md` | Changing how this repo is documented. The tier, what moved where, and what was deferred to Dom. |
| `superpowers/specs/2026-09-24-order-pipeline-design.md` | Working on customer orders: the order folder, plate per order, nestled framing, the paper table, photo placement, the print TIFF, the customer package. |

## Plans

History, not to-do lists. A plan carries the task-by-task record of a build and the
notes on what changed against the spec while it ran.

| Document | Read when |
|---|---|
| `superpowers/plans/2026-06-29-trailprint-v1-architecture.md` | You want the build record of the v1 spec above. |
| `superpowers/plans/2026-06-30-trailprint-studio-wizard.md` | You want the build record of the wizard, since replaced by the studio. |
| `superpowers/plans/2026-07-05-wallpaper-output.md` | Changing device or social presets. Design plus build record for `app/wallpaper.py`, and the defaults Dom chose. |
| `superpowers/plans/2026-07-08-living-editions.md` | Changing editions or lineage in the manifest. Design plus build record. |
| `superpowers/plans/2026-07-08-timelapse.md` | Changing the film. The master invariant: the last frame is pixel-equal to `/api/final`. |
| `superpowers/plans/2026-07-12-honesty-continuity-implementation.md` | You want the consolidated 2026-07-12 build plan: the cheap fixes and the heavy machinery behind the manifest, the plates, and the register of claims. |
| `superpowers/plans/2026-07-12-marketing-language-branding.md` | Writing marketing. The playbook and the claims register that whitelists what the page may say. |
| `superpowers/plans/2026-07-12-strategy-and-license.md` | You need the decision record for AGPL, CC0 plates, the concierge model, and the retired hosted v2. |
| `superpowers/plans/2026-07-17-profile-rev2-and-bleed.md` | Changing bleed or trim. The code is parameterized. The final values wait on the print lab. |
| `superpowers/plans/2026-07-18-macos-launcher-app.md` | Changing `scripts/macos/`. The build record of the launcher. |
| `superpowers/plans/2026-07-20-gpx-first-region-creation.md` | You want the build record of the GPX-first endpoints and the cost-card gate. |
| `superpowers/plans/2026-07-26-base-layer-cache.md` | Changing what the terrain cache may reuse. Phase 1 and Phase 2 of `app/basecache.py`. The cut point moved before labels in commit `1a4ea88`. |
| `superpowers/plans/2026-07-27-per-role-font-seam.md` | Changing `TYPE_ROLES` or a font binding. The build record of the per-role seam. |
| `superpowers/plans/2026-07-27-route-ink-cache.md` | Changing `ink_cache_key`. The second cache, one layer above terrain. |
| `superpowers/plans/2026-07-27-support-restricted-composite.md` | You wonder why the ink composite is not threaded through a cache hit. Measured and declined. |
| `superpowers/plans/2026-08-10-softlight-haze-heroplate-plan.md` | Changing `app/looks.py` or `scripts/hero_plate.py`. The seam's first two passes and the Blender CLI. |
| `superpowers/plans/2026-08-15-real-network-demo-tracks.md` | Changing `scripts/track_network.py` or `scripts/fetch_track_network.py`. The build record of the demo-track spec. |
| `superpowers/plans/2026-08-16-collector-register-copy-rework.md` | Editing landing copy. The final copy verbatim, plus the four dated in-place amendments it makes to `marketing.md`. |
| `superpowers/plans/2026-09-01-dem-geometry-gate.md` | Changing `_ready_or_503` or readiness. Why there is no override, no hook, and no cache. |
| `superpowers/plans/2026-09-24-order-plate-per-order.md` | Changing how an order's plate is planned or built. Build plan for sub-project 1 of the order pipeline. |

## Handoffs

Machine state and the traps a session hit. The current one is
`superpowers/handoffs/2026-09-23-open-threads.md`. `HANDOFF.md`
is not a pointer to the newest: it is the original 2026-06-30 architecture handoff,
with a banner that points at the 2026-07-03 one.

| Document | Read when |
|---|---|
| `superpowers/handoffs/HANDOFF.md` | You want the long-lived architecture notes from 2026-06-30: the invariants, the first file map, the environment gotchas. Its "current state" is superseded. |
| `superpowers/handoffs/2026-07-01-prioritized-next-steps.md` | You want the action plan that followed the first red-team. The reasoning is in the assessment. |
| `superpowers/handoffs/2026-07-03-session-handoff.md` | You want the state after the v1.2 and v1.3 run: style controls, biome tint, the Elko corridor plate, the build planner, terrain depth. |
| `superpowers/handoffs/2026-07-12-implementation-handoff.md` | You want the state after the honesty and continuity work, and its "What remains" list. Records that plate packing never ran. |
| `superpowers/handoffs/2026-07-20-gpx-first-ui-report.md` | You want the brief for re-porting the GPX-first UI onto the studio, and the Tecopa rename. |
| `superpowers/handoffs/2026-07-27-fonts-shipped-forever-contract-retirement.md` | You want the state after the type roles shipped and the retirement was decided. |
| `superpowers/handoffs/2026-08-16-collector-register-and-terrain-guard.md` | Picking the repo up cold. The Collector register, the terrain guard that blocks a deploy, the detail-crop regression, the copy traps, open threads, known-good state. |
| `superpowers/handoffs/2026-09-23-open-threads.md` | Working the open threads. All ten Tecopa threads open on 2026-09-23, ordered around the customer path: the price, the demo tracks, the plate re-render, then the rest. Each has its state checked that day. |

## Assessments

Red-team passes and viability studies. Each is a dated record.

| Document | Read when |
|---|---|
| `superpowers/assessments/2026-07-01-trailprint-redteam-and-roadmap.md` | You want the eight-lens red-team of v1 and the roadmap it produced. |
| `superpowers/assessments/2026-07-02-v1.1-redteam.md` | You want the five-lens pass over v1.1 after the first hardening. |
| `superpowers/assessments/2026-07-17-output-fitness-redteam.md` | Changing print files, wallpapers, or share twins. The pass that found the profile and bleed work. |
| `superpowers/assessments/2026-08-10-blender-render-viability.md` | You wonder why Blender is a CLI and not the engine. No 3.14 wheel, no determinism contract. |
| `superpowers/assessments/2026-08-10-studio-redteam.md` | Changing the upload, preview, or customize flow. The adversarial pass over the studio. |
| `superpowers/assessments/2026-09-02-metal-render-viability.md` | You wonder about a GPU render path. Not now. Uncommitted, pending Dom's review: the file exists on the Mac and is not in git. |

## Quality

| Document | Read when |
|---|---|
| `superpowers/quality/2026-07-02-v1-quality-bar.md` | Judging a poster. The definition-of-done checklist, with the items the code enforces marked. |
| `superpowers/quality/2026-07-17-print-lab-questionnaire.md` | Talking to a print lab. The questions whose answers become the bleed and trim config. |

`superpowers/quality/golden/` holds two reference renders, not Markdown.
`trails for claude design/` holds no Markdown.

## Runbooks outside this folder

| Document | Read when |
|---|---|
| `../marketing/DEPLOY.md` | Deploying the landing page. The manual deploy, the four transforms, the terrain guard, the steps, and the Netlify gotchas. |
| `../marketing/README.md` | Working on the landing page itself, after `marketing.md`. What `landing.html` holds, what `scripts/render_asset_farm.py` produces for it, and the three tiers of the social-preview suite. |

## Canon that lives outside this repo

In the Plateworks OS workspace, at `../../00-09 System/00 Resources/` from this repo on Dom's Mac;
quoted here as `00_Resources/` by convention.

| Document | Governs |
|---|---|
| `00_Resources/documentation-standard.md` | The shape of this folder. |
| `00_Resources/typography-standards.md` | The MB Type slate the font seam was built to ship. The faces never enter this repo. |
| `00_Resources/voice-principles.md` | Tone and sentence mechanics under every customer-facing sentence. The Collector profile spec layers on top. |
