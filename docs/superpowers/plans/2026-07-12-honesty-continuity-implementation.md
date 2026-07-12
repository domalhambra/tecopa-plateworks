# TrailPrint — Honesty & Continuity (implementation plan)

_2026-07-12 · Status: **proposed** (decisions it builds on are recorded in
`2026-07-12-strategy-and-license.md`). Supersedes the six 2026-07-12 blind-spot plans —
all findings retained, consolidated after red-team review: the cheap fixes and the heavy
machinery now sit in one dependency-ordered plan, and one growth feature (neighbor-plate
cross-sell / email capture) is cut, not deferred._

---

## Context — what this plan fixes

Five confirmed findings, one plan:

1. **The promise fails off this machine.** `/api/reprint` 422s wherever the region isn't
   built (`app/main.py:927` `_manifest_region_or_422`); DEMs (190–704 MB) are gitignored
   with no distribution channel; raw sources aren't archived (red-team **V1-12**, still
   open); until this PR there was no `LICENSE`, so nobody else could legally run the
   engine. "Your file reprints itself" was true for one laptop.
2. **The file doesn't name its terrain.** `build_manifest` (`app/provenance.py:89`)
   records the spec, GPX hashes, and engine version — but no hash of the plate it was
   painted on. USGS re-flies 3DEP; a rebuilt plate reprints an old poster *differently*,
   silently. The determinism suite can't see it: it only asserts same-bytes-in →
   same-bytes-out.
3. **The boundary is silent.** Out-of-projection points are dropped to `(inf, inf)`
   without a word (`app/ingest.py:26-29`, verified against current code), and an
   out-of-plate journey surfaces only as a terse 422 — while the hero copy says
   "everywhere you've been."
4. **The film can't travel.** The APNG (deliberate — it carries the manifest) flattens to
   a static first frame — bare terrain, no trails — on the social channels
   `docs/marketing.md` names as the growth loop.
5. **Nobody is taught that the PNG is the save file.** The `zTXt` manifest doesn't survive
   printing; the wall poster is the one artifact that *can't* be continued. The Living
   Editions ritual — the product's defining verb — is guarded by "hopefully it's still in
   Downloads."

## The one design idea

**The file names everything it needs, and everything it names is public.** The manifest
gains a verifiable plate identity; plates become published, hash-addressed artifacts; the
engine becomes runnable-by-right (AGPL); every boundary the engine already enforces gets
narrated instead of swallowed. This is invariant 5 — *registration is correctness; never
paint invented terrain* — extended across time: never reprint against the wrong terrain,
never lose a point silently, never let the archive depend on a private machine.

---

## Phase 0 — Paperwork (S)

- **`LICENSE`** — AGPL-3.0-or-later, canonical text (lands with this PR). README gains a
  short License section (code AGPL / plates + schema CC0 / name reserved).
- **`docs/MANIFEST.md`** — the manifest schema written down as prose + the frozen fixtures
  (`tests/fixtures/manifest_*_v1.json` are the normative examples), with an explicit
  CC0-1.0 dedication. This is the deepest layer of the promise: anyone may implement a
  reader/renderer without touching AGPL code.
- **Name check** — trademark/collision search on "TrailPrint" before anything public
  carries it (strategy doc, Decision 2).

## Phase 1 — The file becomes verifiable; the boundary becomes loud (M)

All v1-local; no distribution infrastructure required; lands before Phase 2 because the
manifest must know how to *name* packs before packs ship.

**`region_pack` manifest block.**
- `build_manifest` gains an additive block, populated from the region's `sources.json`
  (which already computes every asset's sha256 at build time — this is re-surfacing, not
  new machinery):
  `"region_pack": {"pack_version": "<short-hash>", "assets": {"dem.tif": "<sha256>", …}}`
  where `pack_version` is a deterministic digest of the sorted asset hashes.
- **No URLs in the machine block** — hashes are eternal, URLs rot. Human-readable pointers
  live in the `tEXt` note (Phase 2).
- Additive-manifest discipline, fourth instance of the proven pattern (`edition`,
  `lineage`, `animation`): omitted-when-absent, `MANIFEST_VERSION` stays 1, every existing
  frozen fixture byte-for-byte unchanged. New frozen fixture:
  `tests/fixtures/manifest_region_pack_v1.json`.

**Plate verification on reprint/continue.**
- `_manifest_region_or_422` grows a three-way branch, all through the existing one-door
  posture (`spec_from_manifest` untouched — verification is a region-availability concern,
  which correctly lives at the call site per `docs/scope.md`):
  - *match* → render;
  - *mismatch* → honest 422 naming both packs: "this poster was painted on the Lassen
    plate `a1b2c3`; this server has `d4e5f6` — install the original plate to reprint
    exactly";
  - *region absent* → today's 422, now naming the pack id the file wants.
  - *manifest predates the block* → render, with a "plate unverifiable (pre-pack poster)"
    note in the response — soft, never a hard fail (same forward-compat stance as
    `.get(..., [])` drift tolerance).
- `/api/reprint/inspect` reports `plate: verified | mismatch | unverifiable |
  region_missing`.

**Loud boundaries.**
- `ingest.py`: count the non-finite drops instead of swallowing them; upload response
  gains `dropped_points` (per file) and `journeys_outside_plate` (computed against the
  *true* DEM bounds the off-DEM guard already derives — reuse, not new geometry).
- Wizard surfaces the sentence: "3 of your 14 journeys extend beyond the Lassen plate and
  won't appear on this poster." Named and counted, never silent. This is the product face
  of a data-integrity fix the 2026-07-01 red-team already demanded.

**Tests (TDD, per repo convention).** Frozen fixture; old fixtures byte-identical;
mismatch → 422 (fixture with one tweaked hash); pre-pack manifest still reprints;
determinism restated as *pack-relative*: same spec + same pack → identical bytes;
dropped-points counts surface end-to-end.

## Phase 2 — Plates become artifacts; the file gets its resurrection note (M/L)

- **`scripts/pack_region.py`** — builds `<id>-<pack_version>.trailplate.zip`: the region
  dir's committed assets + `dem.tif` + `sources.json` + a `PLATE.txt` (CC0 dedication +
  USGS credits + the rebuild recipe already recorded in `sources.json`). Deterministic
  (sorted entries, fixed metadata) so the zip itself is hash-stable. Writes/updates
  `plates/index.json`: `{id, pack_version, bytes, sha256}` per plate.
- **Installer** — `python -m app.plates install <id> [--from <url|path>]`: stdlib
  download, sha256-verify **every asset against the index before placing anything** under
  `regions/`, refuse on mismatch. `/readyz` already validates presence/bounds afterward.
  (In-app download UI is packaging polish, later; the CLI is the v1 door.)
- **Hosting: GitHub Releases** — the zero-new-infra answer. Packs (≤704 MB) fit the 2 GB
  release-asset limit; `plates/index.json` is committed to the repo so the hashes are in
  history even if assets move. An object-store mirror can come later without changing the
  format.
- **Raw-source archival (closes V1-12)** — every built pack is itself the archive of the
  baked assets; additionally keep one copy of each pack + the exact `region_prep`
  inputs-record (bbox, datasets, dates — already in `sources.json`) in operator-controlled
  storage (S3/B2 + one offline copy). If USGS revises or rate-limits, the plates survive.
- **The `tEXt` resurrection note** — `provenance.embed` adds a plain-text chunk beside the
  `zTXt` manifest: what this file is, *the PNG is the save file*, the engine is AGPL at
  `<repo>`, the plate id + pack_version, the data is US public domain, and where plates
  live / how to rebuild one. **Must be a pure function of the manifest** (no timestamps,
  no environment) — finals are byte-compared in the determinism suite and reprints must
  keep producing identical bytes. Share copies (`embed_spec=false`) carry neither chunk.

**Tests.** Pack build determinism (same region dir → same zip hash); installer refuses a
tampered asset; end-to-end: pack the synthetic test region → install into an empty
regions dir → reprint a golden → byte-identical. That last one is the seed of the Phase 3
drill, running in CI from day one.

## Phase 3 — Publication: the promise goes live (M)

- **Pre-publication sweep** — no user GPX/photos in history (gitignore has always covered
  them — verify), no secrets, `docs/` uploads checked for anything private.
- **Publish the repo** under the Phase-0 LICENSE; cut plate packs for all four regions as
  release assets; commit `plates/index.json`.
- **README: "Reprint forever, honestly"** — the promise restated as mechanism: file →
  `region_pack` hashes → published plates → AGPL engine → CC0 schema. The FAQ answer
  *"What if you disappear?"* becomes checkably true.
- **The orphan drill — the acceptance test for the whole plan.** On a fresh machine with
  nothing but one PNG and an internet connection: clone the repo, `pip install -r
  requirements-lock.txt`, read the poster's plate id via `/api/reprint/inspect`, install
  that plate, `/api/reprint` → **byte-identical PNG**. Documented as a release ritual and
  automated in CI against the synthetic region (Phase 2's test). This drill *is* the
  product claim; if it ever fails, the release doesn't ship.

## Phase 4 — The film learns to travel (S/M)

The archival film stays APNG-with-manifest (last frame byte-identical to `/api/final` —
untouched). It gains share twins, exactly parallel to the poster's `embed_spec=false`
share copy — lossy, manifest-less, for posting not archiving:

- **WebP first** — Pillow-native (`save_all=True, format="WEBP"`, per-frame durations,
  loop): no new dependency, plays on most modern surfaces. The default share format.
- **MP4 included** — via `imageio-ffmpeg` as an **optional extra** (`requirements-
  share.txt`), for the platforms that only speak video (Instagram/TikTok upload paths).
  Gated on availability with an honest 422 — the exact posture PDF already has. The
  bundled ffmpeg binary is why it's an extra and not in the core lock: the app's "native
  wheels, no system deps" property is worth protecting.
- Film submit gains a `format` field mirroring the print PNG/PDF picker:
  `apng` (default, archival) | `webp` | `mp4` (share twins — manifest omitted by
  construction, not toggled). `scripts/render_asset_farm.py` emits the share formats for
  the social columns.

**Tests.** Share twins carry no manifest chunk; frame count + durations match the APNG;
APNG suite unchanged; MP4 path 422s cleanly when the extra isn't installed.

## Phase 5 — Words & furniture: the copy stops over-claiming (S)

- **Own the plate.** Hero copy: "your Lassen years, as one poster" — not "everywhere
  you've been." The FAQ's honest answer ("we refuse to print terrain we don't have real
  elevation data for") gets set up by the hero instead of buried. CTA tells the truth
  per the strategy doc: "Order a print" now, "Get the app" when a packaged build exists.
- **The save-file moment.** At download, one sentence: "This PNG is your save file — it
  holds your whole poster and reprints forever. Keep it; next year it becomes Edition 2."
  Filename self-documents: `trailprint_<region>_edition-<n>_<years>.png` (pure function
  of spec/manifest data). "Download again" relabeled "Save another copy." The continue
  flow echoes what it read: "Edition 1 · Lassen · 2026 — ready to add this year."
- **Attribution renders from `sources.json`** — a small credit line in the cartouche
  ("Terrain USGS 3DEP · Water USGS NHD · Land cover NLCD · Names GNIS"), data-driven so
  a future non-PD plate automatically carries its *required* credit instead of relying
  on memory. Courtesy today, load-bearing later.
- **Font posture.** Never bundle `Georgia.ttf`; pick a redistributable SIL-OFL serif as
  the packaged-build default (`TRAILPRINT_FONT` remains the licensed-upgrade seam).

## Sequencing & effort

**0 → 1 → 2 → 3**, with **4 and 5 parallel any time after 1.** Phase 1 before 2: the
manifest must name packs before packs exist to verify. Phase 2 before 3: publishing the
promise without plates ready would re-create the original gap in public. Total: Phase 0
(S) · 1 (M) · 2 (M/L) · 3 (M) · 4 (S/M) · 5 (S).

## Invariants — protected and extended

- **Additive manifest, forever.** `MANIFEST_VERSION` stays 1; every frozen fixture
  byte-identical; `region_pack` and the `tEXt` note are omitted-when-absent.
- **Determinism becomes pack-relative and total.** Same spec + same plate → identical
  bytes, *including* the `tEXt` note (pure function of the manifest — no timestamps).
- **Honest refusal over silent wrongness.** Plate mismatch → 422, never a silent redraw;
  dropped points → counted and shown, never `(inf, inf)` into the void. Invariant 5,
  extended across time.
- **Share copies carry nothing.** `embed_spec=false` posters, WebP/MP4 films: no
  manifest, no note — the privacy posture is unchanged.
- **The core lock stays lean.** WebP is Pillow; ffmpeg is an optional extra; the plate
  installer is stdlib.
- **One door for untrusted manifests** (`spec_from_manifest`) is untouched — plate
  verification is server-capability checking at the call site, exactly where
  `docs/scope.md` says it belongs.

## Cut and out of scope

- **Cut (not deferred):** neighbor-plate cross-sell + region-request email capture on the
  boundary message — a growth feature wearing honesty's coat; revisit only post-launch
  with real users.
- **Out of scope:** the print storefront build (waits on the strategy doc's one open
  choice); global/on-demand coverage (its own rock); cloud accounts/sync of any kind
  (`docs/scope.md` line-in-the-sand); auto "re-master to a newer plate" (detection ships
  here; migration is a later verb); in-app plate-download UI (packaging polish).
