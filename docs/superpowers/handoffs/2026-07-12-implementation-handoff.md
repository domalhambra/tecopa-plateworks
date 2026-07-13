# TrailPrint — Session Handoff (2026-07-12)

_Branch `claude/app-blind-spots-rifpre` (ahead of `main`@`9580cd4`) · plan:
[`../plans/2026-07-12-honesty-continuity-implementation.md`](../plans/2026-07-12-honesty-continuity-implementation.md) ·
decisions: [`../plans/2026-07-12-strategy-and-license.md`](../plans/2026-07-12-strategy-and-license.md)_

Read this first to continue in a fresh session. This session executed Phases 0–2, 4,
and 5 of the honesty & continuity plan — turning "your file reprints itself" from a
one-laptop slogan into tested mechanism. **Phase 3 (Publication) has NOT run**: no
pre-publication sweep, no published repo, no real plate packs, no `plates/index.json`
commit — see "What remains" item 1 before anything goes public.
For the longer-lived architecture notes see
[`HANDOFF.md`](HANDOFF.md) and [`2026-07-03-session-handoff.md`](2026-07-03-session-handoff.md).

---

## What shipped this session (P0–P2, P4–P5; P3 remains)

**Phase 0 — Paperwork** (`d14445c`)
- `LICENSE` — AGPL-3.0-or-later, canonical text; README License section (code AGPL /
  plates + schema CC0-1.0 / name reserved).
- The six blind-spot plans consolidated into two:
  `plans/2026-07-12-strategy-and-license.md` (decisions) +
  `plans/2026-07-12-honesty-continuity-implementation.md` (build).

**Phase 1 — The manifest names its plate; the boundary gets loud** (`bb785f2`)
- `app/provenance.py` — `region_pack_block(region_dir, labels, biome)`: plate identity
  hashed from asset **bytes on disk** (never the sidecar), spec-relative (labels.json
  only when the spec draws labels; landcover.tif only when biome is on; overview.png
  never). `build_manifest` gains the additive `region_pack` block — `MANIFEST_VERSION`
  stays 1, every frozen fixture byte-identical; new frozen fixture
  `tests/fixtures/manifest_region_pack_v1.json` pins the mismatch path.
- `app/main.py` — `_manifest_region_or_422` verifies the plate on reprint AND continue:
  mismatch → honest 422 naming both plate ids; pre-pack files stay printable.
  `/api/reprint/inspect` reports `plate: verified|mismatch|unverifiable|region_missing`.
- `app/ingest.py` — non-finite reprojection drops counted, not swallowed; `/api/upload`
  returns `dropped_points` + `journeys_outside_plate`; the wizard says the sentence.
- `docs/MANIFEST.md` — the v1 schema as prose, CC0-1.0 dedicated.
- `scripts/build_labels.py` + `region_prep.py` — `labels.json` now recorded in
  `sources.json` (hash + GNIS entry); all four regions' records synced.

**Phase 2 — Plates become artifacts; the orphan drill** (`cc80d9f`)
- `scripts/pack_region.py` — deterministic `<id>-<sha256[:12]>.trailplate.zip`
  (ZIP_STORED, sorted entries, 1980 timestamps: pack twice → byte-identical), drift
  gate against `sources.json`, `PLATE.txt` (credits + CC0 + rebuild recipe), tracked
  `plates/index.json` (zips gitignored — they're release assets).
- `app/plates.py` (stdlib-only) — `python -m app.plates install <path|url>`: namelist
  allowlist before extraction, zip sha256 vs self-name, per-asset re-hash both
  directions, atomic swap; `verify <poster.png>` checks a file against the installed
  plate. `provenance.resurrection_note` — the `tEXt` chunk beside the manifest, a pure
  function of the manifest (reprint byte-identity holds, note included).
- `tests/test_orphan_drill.py` — the acceptance test of the whole plan: pack → install
  into an **empty** regions root → `/api/reprint` → bytes fully equal. Runs in CI.

**Phase 4 — The film learns to travel** (`a744f41`)
- `app/timelapse.py` — WebP share twin (Pillow-native) + MP4 via `imageio-ffmpeg` as an
  optional extra (`requirements-share.txt`), honest 422 when absent. Share twins carry
  no manifest/note by construction; APNG stays the archival film.

**Phase 5 — Words & furniture** (uncommitted in the working tree, two tasks)
- *Task A (teammate):* `spec.credit_text` (appended last, defaults `""`, bounded in
  `validate()` — printable ASCII, `CREDIT_MAX_CHARS=200`); derived at proof time from
  `sources.json` by `main.credit_line`; painted as a third cartouche row; `year_span`
  relocated to `app/spec.py`; self-documenting download names
  (`trailprint_<region>[_edition-<n>][_<years>]<kind>.<fmt>`) carried on the blob key
  and Content-Disposition; wizard reads the server's filename.
  Tests: `tests/test_credit_and_names.py` (19).
- *Task B (this handoff's author):* landing copy stops over-claiming (plate-honest hero,
  "Order a print" mailto CTA, mechanism-not-promise FAQ, hash-addressed plates lede);
  wizard save-file moment (proof-pane sentence, "Save another copy" relabel);
  `/api/continue` response gains additive `year_span` and the wizard echoes
  "Edition n · region · years — ready to add this year."; README "Reprint forever,
  honestly" section + Layout entries + release ritual + font posture; this handoff.

## Invariants — extended this session, PROTECT THESE

(Full list in `HANDOFF.md`; new or sharpened here:)

- **Plate identity is spec-relative.** `region_pack` hashes only the assets the spec
  actually painted with — a GNIS rebake must never refuse reprints of posters that
  never drew labels. Don't "simplify" it to hash-everything.
- **Pack determinism is content-addressing.** ZIP_STORED, sorted names, fixed 1980
  timestamps — deflate output varies across zlib builds, so a deflated pack would hash
  differently per machine. The DEM COG is internally compressed anyway.
- **The `tEXt` resurrection note is a pure function of the manifest.** No timestamps,
  no environment — reprint byte-identity is asserted note-included by the drill.
- **Additive manifest, forever.** `MANIFEST_VERSION` 1; `region_pack`, `credit_text`,
  `year_span` (continue response) all omitted-or-default when absent; every frozen
  fixture byte-identical.
- **Untrusted-manifest posture.** New spec fields are attacker-controlled via
  `/api/reprint` — `credit_text` is bounded in `spec.validate()`; pack_versions are
  hex-gated before comparison or echo; region ids are `_ID_RE`-gated before path joins.

## What remains — for Dom, not for code

1. **Publish + release** (plan Phase 3, the ritual is in the README): FIRST the
   pre-publication sweep the plan requires — no user GPX/photos in history, no secrets,
   `docs/` uploads checked for anything private (not yet done; no sweep report exists) —
   then, on a machine with the real DEMs, `scripts/pack_region.py` all four regions,
   publish the zips as GitHub release assets, commit `plates/index.json`, run the orphan
   drill, and only then make the repo public under the merged LICENSE.
2. **Monetization flavor** — concierge-only vs. thin print storefront (strategy doc's
   one open choice; gates nothing). The landing CTA is concierge (mailto) until decided.
3. **Trademark / collision search on "TrailPrint"** before anything public carries the
   name (strategy doc, Decision 2); rename now rather than after posters carry it.
4. **Cut plan Phase 3's remaining nicety when publishing:** one operator-controlled
   offline copy of each pack + `region_prep` inputs-record (raw-source archival, V1-12).

## Gotchas paid this session (don't rediscover)

- **`labels.json` rides `sources.json` now.** `build_labels.py` records the baked hash
  idempotently; a region whose labels were rebuilt without re-running it will trip the
  packer's drift gate — that's the gate working, not a bug.
- **`--resync` semantics (pack_region).** It writes TRUE disk hashes into the zip's
  *copy* of `sources.json` only — the source region dir is never mutated. Default is
  refuse-on-drift naming each drifted asset; the orphan drill uses `--resync` because
  the CI region carries a synthetic DEM.
- **Deflate is not deterministic across zlib builds.** Compressed zip members would
  make identical content hash differently machine-to-machine. Content-addressed
  identity must be a pure function of content → ZIP_STORED, forever (the DEM COG is
  internally compressed already, so the packs stay a sane size).
- **A title-less poster continues as `"-"`, not `""`** (an empty title re-resolves to
  the region name in `_build_spec` and would regrow a title block on edition 2).
- **MP4 color:** untagged yuv420p gets BT.601-converted by swscale while players assume
  BT.709 — the encoder tags + converts explicitly or every film hue-shifts against its
  own poster.

## Conventions to keep

TDD with targeted runs (never the full suite mid-session); picture decisions ride the
SPEC, stamped at `/api/proof`; physical units for everything visual; additive manifest
(`MANIFEST_VERSION` 1, frozen fixtures untouched); honest-422 voice; new spec fields
bounded in `spec.validate()`; no model identifiers in committed artifacts.
