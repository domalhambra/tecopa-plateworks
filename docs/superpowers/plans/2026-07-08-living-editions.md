# TrailPrint — Living Editions (design + implementation plan)

_2026-07-08 · Status: **proposed** (not yet built). Companion plan:
`2026-07-08-timelapse.md` — build Editions first; the two compound but do not
depend on each other._

---

## Context — why this feature

The provenance manifest already makes every final **stateless-reprintable**: the full
`CompositionSpec` (tracks included) and the source-GPX hashes ride the PNG in one
`zTXt` chunk, and `POST /api/reprint` re-renders the file with no session and no DB.
Today that provenance is used defensively — to reproduce the *same* picture.

Living Editions uses it generatively: **the poster is the save file.** Upload last
year's poster plus this year's GPX and get **Edition N+1** — same region, same frame
and style, the new journeys woven in, hotspots recomputed, and one quiet cartouche
line of lineage ("EDITION 3 · 2024–2026"). Each edition's manifest chains to its
parent's hash, so any poster in the series proves its ancestry from the file alone.

Product intent: convert a one-time purchase into a ritual. Every December the client
feeds the year's tracks into the poster and reprints. No competitor can copy this
cheaply — it requires the provenance architecture to already exist.

## The one design idea: continue is upload with a poster as the seed

There is no new render path and no new spec semantics. `POST /api/continue` turns a
poster back into a **live session** — tracks, hotspots, sources, style, title, crop,
all resurrected from the embedded manifest — and then the *existing* flow does
everything else:

- `/api/upload` with that session id accumulates the new GPX (the accumulate +
  `_carry_annotations` path already exists and already preserves operator work).
- `/api/proof` re-stamps; `/api/final` renders Edition N+1 with the lineage embedded.

Everything falls out of code that already ships:

- Tracks ride the spec (`spec.tracks` + `spec.track_days`), so a session can be
  rebuilt from the file alone — the same property `reprint` relies on.
- `_carry_annotations` (main.py) already transfers labels/icons across a hotspot
  recompute; continuing a poster is exactly that case.
- The untrusted-manifest posture exists (`_read_capped`, `_manifest_or_422`,
  `sanitize_photos`, `spec.validate` re-gate) — continue reuses it verbatim.
- Invariant 1 holds: the edition is still one spec stamped after one clean proof.

## Product shape (v1)

- **"Continue a poster" on the landing page**, next to the region picker: drop a
  TrailPrint PNG, land in the wizard with the journey, markers, style panel, title,
  and frame pre-filled exactly as the poster was composed. Add GPX, re-frame if the
  new tracks outgrow the old crop, proof, final.
- **The edition line**: editions ≥ 2 render one extra cartouche stats line —
  `EDITION N · 2024–2026 · 41 TRACKS` (year span from `track_days`; falls back to
  `EDITION N` when no track carries a date). Edition 1 posters are byte-identical to
  today's output.
- **Lineage in the manifest**: each edition's manifest carries the sha256 of the
  parent PNG file and the full ancestor chain. `POST /api/reprint/inspect` reports it.
- **Exact-duplicate GPX is skipped**: re-uploading a file whose sha256 already
  appears in the session's sources is a no-op — re-adding last year's GPX must not
  double-count journeys and thicken the worn-width pass.
- Photos referenced by the old poster's hotspots survive **only if the files still
  exist** in the uploads dir (the TTL usually evicts them within a day). A missing
  photo drops silently from the resurrected hotspot; label and icon always survive.

## Design by module

### `app/spec.py`

One new field (defaults → `serialize.py`'s known-fields filter gives free
forward/backward compat for old sessions and embedded manifests):

- `edition: int = 1` — a picture decision (the cartouche draws it), so it lives on
  the spec. `validate()` refuses a non-int or anything outside 1–999 (honest 422,
  same pattern as the style bounds).

### `app/provenance.py`

- `build_manifest(spec, sources, lineage=None)` — additive optional key. When
  `spec.edition >= 2` the manifest gains:
  - `"edition": N`
  - `"lineage": [{"sha256": ..., "edition": ...}, ...]` — ancestors oldest-first;
    the continue endpoint hashes the uploaded parent file and appends one entry.
    Capped at 100 entries (a century of yearly editions) — beyond that, drop the
    oldest; never refuse.
  Both keys are **omitted for edition 1**, so every existing manifest byte —
  including the frozen `manifest_v1.json` / `manifest_wallpaper_v1.json` fixtures —
  is untouched. `MANIFEST_VERSION` stays 1: the change is additive and
  `spec_from_json` already tolerates unknown/missing fields in both directions.
- `bound_geometry(spec)` — NEW shared guard (see Security below): caps on track
  count, total points, and hotspot count for a spec rebuilt from an untrusted
  manifest. Called by **both** `/api/continue` and `/api/reprint` (reprint gets
  retroactively hardened for free — today a crafted manifest with a huge tracks
  array reaches the coverage loops unchecked).

### `app/serialize.py` + `app/session.py`

- Session dict gains `edition: int` and `lineage: list`; `dump_session` /
  `load_session` carry them with the usual `.get(...)` drift tolerance (pre-feature
  rows load as edition 1, empty lineage).

### `app/main.py`

- **`POST /api/continue`** (multipart: `file` = the poster PNG):
  1. `_read_capped` (reuse `REPRINT_MAX_BYTES`) → `_manifest_or_422` →
     `manifest_to_spec` (malformed → 422, same as reprint).
  2. Region check: `spec.region_id` must be built here, else the reprint-style 422.
  3. `sanitize_photos` + drop photo paths whose file no longer exists;
     `bound_geometry`; `spec.validate(spec.final_dpi())`.
  4. Rebuild `Track` objects from `spec.tracks`/`spec.track_days`
     (`track_id=f"edition-{i}"` — density keys on day-or-index, so ids only need
     uniqueness). Normalize `track_days` length to match tracks (pad None / 422 on
     gross mismatch).
  5. Create the session: tracks, hotspots (annotations intact), `sources` from the
     manifest, `edition = (manifest edition or 1) + 1`, `lineage = manifest lineage
     + [{"sha256": sha256(uploaded bytes), "edition": manifest edition or 1}]`.
  6. Respond with the `/api/upload` shape (session, region, overview, tracks px,
     hotspots px, `starter_crop` = the **old crop** projected to overview px) plus
     what the wizard needs to pre-fill: `style` (every Style-panel knob off the
     spec), `title`, `print_size_in`, `output_kind`/`wallpaper` hints, `edition`,
     and `lineage`.
- **`/api/upload` dedup**: before accumulating, skip any payload whose sha256 is
  already in the session's `sources` (log it; report `skipped_duplicates` in the
  response so the UI can say "already on this poster"). Applies to all sessions,
  not just continued ones.
- **`_build_spec`**: pass `edition` from the session onto the spec (default 1).
- **`_final_manifest`**: thread the session's `lineage` through to
  `build_manifest`. `_require_stamped` grows a fourth return (or returns the
  session dict) — mechanical.
- `/api/reprint`: unchanged behavior, plus the `bound_geometry` call. A reprint is
  a re-render, **not** a new edition — it must not touch edition/lineage (it
  re-embeds the manifest's own values verbatim, as it does today for sources).

### `app/render.py`

- `_stats_line` / `_draw_title_block`: when `spec.edition >= 2`, prepend
  `EDITION {N}` and the year span (min–max over `track_days`, skipping `None`;
  single year renders once) to the existing stats line, same tracked-caps
  typography, all sizes physical. Edition 1 renders byte-identically to today.

### `app/static/` (wizard)

- Landing: a "Continue a poster" drop target beside the region gallery (same visual
  pattern as the existing upload affordances). On drop → `POST /api/continue` →
  enter the wizard at the map step with tracks/markers/crop restored and the Style
  panel + title + print size pre-filled from the response.
- Upload step: surface `skipped_duplicates` ("2 files already on this poster").
- Proof/final: show the edition badge ("Edition 3") near the format controls.

## Security notes (the manifest is untrusted input)

Same posture as `/api/reprint`, plus the new hardening:

- Photo paths: `sanitize_photos` (path-traversal) + existence check — a crafted
  manifest must never read arbitrary server files, and a stale path must not 500 a
  later final.
- Geometry bombs: `bound_geometry` caps tracks ≤ 4096, total points ≤ 5,000,000,
  hotspots ≤ 64 → 422 beyond. Continue makes specs *persistent* (they become
  session state that re-renders on every proof), so bounding here matters more than
  on one-shot reprint — but both get the guard.
- `edition`/`lineage` from the manifest are re-validated (ints, bounded, list
  shape); a garbage lineage entry is dropped, never 500s.
- The uploaded parent is hashed as raw bytes — no image decode is needed beyond the
  existing text-chunk read (`provenance.extract` never decodes pixels).

## Decision points for Dom (defaults chosen — cheap to reverse before build)

1. **Continue re-opens the wizard** (chosen) vs. a one-shot "auto-edition" endpoint
   that renders without human review. Wizard chosen: new tracks often outgrow the
   old crop, and the proof-gate invariant ("stamp only after a clean proof") stays
   intact. A one-shot mode can be added later as a thin wrapper.
2. **Old crop as the starter frame** (chosen) vs. auto-refit to the union of old +
   new tracks. Keeping the frame preserves the edition's visual identity; the
   operator re-frames deliberately when needed.
3. **Edition line in the cartouche stats line** (chosen) vs. a separate corner
   mark. One line, zero new layout machinery.
4. **Full ancestor chain in the manifest** (chosen, capped at 100) vs. parent-only.
   The chain is what makes "prove its ancestry from the file alone" true.
5. **Duplicate-GPX skip is silent-but-reported** (chosen) vs. a 422. A client
   re-dropping their whole folder every year is the expected ritual; punish nothing.

## Implementation plan (TDD, in order)

**Phase 1 — spec + cartouche**
1. `spec.py`: `edition` field + validate bounds; tests — bounds 422, default 1,
   serialize round-trip, old manifests load as edition 1.
2. `render.py`: edition stats line; tests — edition 1 output byte-identical
   (existing goldens/suite untouched), edition ≥ 2 draws the line, year span
   correct with and without dated tracks.

**Phase 2 — provenance + session plumbing**
3. `provenance.py`: lineage in `build_manifest` (omitted at edition 1 — assert the
   frozen v1 fixtures still pass untouched), `bound_geometry`; tests — caps 422,
   lineage cap drops oldest, manifest byte-stability at edition 1.
4. `serialize.py`/`session.py`: edition + lineage fields with drift tolerance;
   tests — pre-feature session rows load.

**Phase 3 — API**
5. `/api/continue`; `/api/upload` sha256 dedup; `_build_spec`/`_final_manifest`
   threading; `bound_geometry` on reprint. Tests — the full ritual round-trip:
   upload `sample.gpx` → proof → final → continue(final PNG) → session matches
   (track count, style knobs, title, crop, annotations) → upload a second GPX →
   proof → final → manifest carries `edition: 2` + parent sha256; duplicate upload
   is skipped; hostile manifests (photo traversal, geometry bomb, garbage lineage,
   region not built) all 422/sanitize cleanly; a *wallpaper* PNG continues too
   (output_kind rides the spec; the wizard lands in wallpaper mode).
6. Freeze `tests/fixtures/manifest_edition_v1.json` — the forever-contract for the
   lineage keys, same discipline as the print and wallpaper fixtures.

**Phase 4 — wizard**
7. Landing drop target + pre-fill + edition badge + duplicate notice. Verify by
   driving the app (Playwright/Chromium, per repo convention).

Adversarial review (the `Workflow` tool pattern) after Phases 2 and 3, per repo
convention — the untrusted-manifest surface is exactly where it has caught real
bugs before.

## Verification

- `pytest -q` green; existing frozen fixtures byte-untouched (the strongest
  regression signal: edition 1 changes nothing).
- End-to-end drive: compose a poster from `sample.gpx`, download the final,
  continue it, add a second GPX, re-proof, re-final; `reprint/inspect` the edition-2
  file and confirm edition, lineage sha256 (== sha256 of the edition-1 file), and
  sources list = both GPX hashes. Reprint the edition-2 file → byte-identical.
- By-eye: the edition line on a real-terrain poster (cartouche rhythm, tracking).

## Out of scope (later)

- One-shot auto-edition endpoint (no wizard); a printed "family tree" of editions;
  diffing two posters ("what's new this year" highlighted in a second ink); embedding
  small photos into the manifest so they survive editions; edition-aware pricing.
