# TrailPrint scope — the chronicle, not the poster

TrailPrint began as "a poster maker and a digital visualization of track files."
Measured against that goal, three later features look like scope creep: time-lapse
films, photos pinned to markers, and living editions. This document restates the goal
so that those three features are not passengers but the product — and resolves each
objection against them with a concrete design commitment that leaves the app
*stronger* than if the feature had never existed.

## The goal, restated

**TrailPrint is a self-archiving chronicle of a life outdoors.** One composition spec
is the score; a print, a wallpaper, and a film are performances of it. Every file the
app emits carries everything needed to reproduce it, continue it, and hand it to the
future. There is no account, no database, no cloud: **the artifact is the archive.**
The poster on your wall is the save file.

A poster maker produces snapshots. A chronicle produces *editions* — and needs three
things a snapshot doesn't: a time axis you can watch (film), the memories attached to
the places (photos), and a way to grow next year without losing this year (editions).

## Three pillars

Each pillar is one of the three contested features, generalized from an invariant the
engine already enforces.

### 1. One score, many performances *(time-lapse)*

Invariant 1 — "one spec, painted at many sizes" — generalizes: the composition is
decided once in ground coordinates, then performed at any size (print), any pixel
density (wallpaper), and along its own **time axis** (film). The spec already carries
time (`track_days`); a still poster is simply the film's final frame flattened.

### 2. The file is the whole record *(photos)*

"The file is the artwork" generalizes to "the file is the record": not just the
picture, but the geometry, the source hashes, the pacing — and the memories pinned to
it. A GPX track records where you went; the photo records what you saw there. A
chronicle needs both, and it needs them *inside the file*.

### 3. The record is alive *(living editions)*

A chronicle grows. `/api/continue` is the product's defining verb: last year's PNG
plus this year's GPX renders the next edition, lineage carried in the file itself.
This is the sharpest differentiator TrailPrint has — no other track-print tool can
promise "your artifact can never be orphaned."

## Each objection, inverted

### Objection 1 — "Time-lapse is a third product category"

*The claim:* an animated APNG is neither a poster nor a static visualization; it drags
in pacing validation, an `animation` manifest block that must be honored forever, and
render seams that exist only to cut frames.

*Resolved:* under pillar 1 a film is not a new category — it is the same spec with the
time axis performed instead of flattened. The engine already proves this is not
rhetoric: **the film's final frame is byte-identical to `/api/final`**, asserted
directly in `test_timelapse.py`. The "forever contract" cost is already amortized by
the same fixture discipline as every other deliverable: `manifest_animation_v1.json`
is frozen alongside `manifest_v1.json`, the `animation` block is purely additive, and
`MANIFEST_VERSION` stays 1 — every pre-film manifest is byte-for-byte unchanged. The
render seams (`_paint_base` / `_paint_journey` / `_paint_overlays`) are the natural
layering of the paint pipeline, and they price a film at ~one full render plus N cheap
route passes.

*Why it strengthens the app:* the film is the public, watchable proof of the engine's
determinism. No other tool produces an animation whose last frame is byte-identical to
your archival print, re-renderable from the file alone. The feature that looked like
scope creep is the demo of the invariants.

### Objection 2 — "Photos break the app's own promise and are its only security hole"

*The claim:* photos live in a TTL-swept uploads directory and ride the spec as server
file paths, so (a) a reprint of an older poster silently loses them — the one place
"same spec → same image" is soft — and (b) manifests carrying paths force
`provenance.sanitize_photos`, the app's entire path-traversal defense.

*Resolved — the engineering commitment:* **embed photo bytes in the manifest.** Photos
are already capped on upload (`PHOTO_MAX_BYTES`, `PHOTO_MAX_PIXELS`) and rendered no
larger than `photo_box_in` (1.5 in), so the embedded form is a render-resolution
derivative — a JPEG whose long edge covers the largest dpi the file will ever be
performed at (300 dpi → ~450 px, tens of KB), carried per-hotspot in the manifest.
Then:

- **Reprint becomes faithful forever.** No uploads-dir dependency, no TTL loss. The
  one soft spot in "the file is the artwork" becomes hard.
- **The security surface shrinks below today's.** Manifests stop carrying server
  paths at all, so `sanitize_photos` — the realpath/prefix dance and the whole class
  of path-traversal risk — is *deleted*, not defended. Untrusted photo input reduces
  to "decode capped bytes with Pillow," the exact posture `/api/photo` already applies
  to fresh uploads. One code path, and it's the already-hardened one.
- **Migration is honest.** Old path-based manifests still open (`spec_from_json` is
  forward-compatible); `/api/continue` re-embeds a photo if its upload still exists
  and reports it dropped if not — never silently.

*Why it strengthens the app:* solving this is what makes pillar 2 true rather than
aspirational. The poster that carries its own photographs is a strictly better
artifact than one that references a server directory — and the app gets *less*
attackable in the process.

### Objection 3 — "Living editions are a workflow bolt-on and a second untrusted surface"

*The claim:* `/api/continue` turns a poster maker into multi-year journaling, doubles
the endpoints that rebuild trusted state from arbitrary PNGs, and carries the largest
test file in the repo (440 lines).

*Resolved:* under the restated goal, editions are not adjacent to the product — they
*are* the product's tense. The untrusted-surface concern is answered by unification,
not removal: `/api/reprint`, `/api/reprint/inspect`, and `/api/continue` already share
one posture (capped read → `_manifest_or_422` → `bound_geometry` → full `validate`).
The commitment is to promote that shared posture into **a single hardened decode
function in `provenance`** — one parser, one guard chain, tested once — so there is
exactly one door through which an untrusted manifest enters, no matter how many verbs
consume it. With photos embedded (objection 2), path sanitization drops out of that
chain entirely, so the unified door is *simpler* than any of today's three.

*Why it strengthens the app:* the 440-line test file inverts from cost to moat. It is
the executable form of the promise "any TrailPrint PNG from any year opens forever"
(`manifest_edition_v1.json` freezes it), and that promise — not the shaded relief — is
why someone chooses this app over a print-my-map website. The upload dedup reframes
the same way: it is what makes the yearly ritual safe. Drop last year's poster and the
whole year's GPX folder in one gesture; nothing double-counts, nothing thickens the
worn-width pass.

## Engineering commitments (ordered)

1. **Embed photos in the manifest. — DONE.** A pinned photo now travels inside the
   file as a render-resolution JPEG `data:` URI (`provenance.build_final_spec`), carried
   at every manifest-emitting path (final, async final, reprint, continue, time-lapse,
   the wallpaper bundle) so no deliverable silently loses it. `render._draw_photos`
   reads bytes-or-path through `provenance.load_photo`; the old path sanitizer is gone,
   replaced by `drop_unembedded_photos` (a manifest can no longer carry a server path,
   so there is nothing to traverse) plus a decompression-bomb guard on decode. Because
   the same embedded spec feeds the render and the manifest, the final and its reprint
   are now byte-identical *including the photo*, and a reprint no longer touches the
   uploads dir — the "reprint loses photos" soft spot is closed and the security surface
   shrank. Frozen forever by `tests/fixtures/manifest_photo_v1.json`. (`/api/photo`
   keeps its upload caps; embedding happens at manifest build.)
2. **One door for untrusted manifests.** A single `provenance` decode function —
   capped read, manifest parse, geometry bound, validate — consumed by reprint,
   inspect, and continue.
3. **Say the goal where people read it.** The README opens with the chronicle framing
   and the three pillars, so the next "should we remove X?" conversation starts from
   the right measuring stick.

## Still out of scope

A scope that includes everything is not a scope. The chronicle framing draws the line
just as sharply as "poster maker" did — on the other side of it remain:

- **Social anything** — sharing feeds, comments, public galleries. The share copy
  (manifest stripped) is the entire social feature.
- **Cloud sync and accounts** — the file being the archive is the point; a server-side
  archive would compete with it.
- **Fitness metrics** — pace, heart rate, splits. The chronicle records *where* and
  *when*, not *how fast*.
- **Route planning / live tracking** — TrailPrint looks backward, by design.
- **Track editing** — sources are hashed into provenance; the app renders what
  happened, it does not revise it.
