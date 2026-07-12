# TrailPrint — Shareable Film Export (design + implementation plan)

_2026-07-12 · Status: **proposed** (not yet built). Small feature, outsized leverage:
it unblocks the marketing plan's primary growth loop. Companion: `2026-07-08-timelapse.md`
(the APNG engine this extends)._

---

## Context — the film can't play where the marketing needs it

The time-lapse ships as an **APNG** — deliberately, because an APNG *is* a PNG and can
therefore carry the provenance manifest (`app/timelapse.py:15`, `encode_apng`), keeping the
film inside "the file is the artwork." MP4/WebP export was explicitly deferred as out of
scope (`2026-07-08-timelapse.md`: *"Animated WebP / MP4 exports … later"*).

The marketing plan was written **after** that deferral and makes the film the centerpiece
of the growth strategy:

- `docs/marketing.md`, Phase 2 (the trail launch): *"Asset: the film, posted natively —
  'my year, drawing itself.'"* on r/ultrarunning, r/trailrunning, r/Strava, Instagram.
- *"every customer film shared on social is a looping ad."* — the entire viral loop.
- The landing hero is a *"looping time-lapse film (it's an APNG — it is a web asset)."*

The landing-page hero is fine — a browser renders APNG. **The share loop is broken:** the
platforms the plan names for growth do **not** accept APNG. Reddit and Instagram, iMessage,
most native mobile share sheets either reject APNG or flatten it to a **static first frame**
— which, for a time-lapse, is *bare terrain with no trails yet*. The single most-shared
asset in the marketing plan degrades to an empty map on the exact channels meant to spread
it.

## The one design idea: the film has an archival form and a social form, exactly like the poster

The poster already has this shape: the **archival** PNG carries the manifest; the **share
copy** (`embed_spec=false`) strips it for public posting. The film should mirror it:

- **Archival film = APNG + manifest** (today's `encode_apng`). Unchanged. Self-describing,
  reprintable, the last frame byte-identical to `/api/final`. This stays the canonical form.
- **Social film = MP4 (H.264) / WebP**, manifest-stripped, lossy, universally playable. It
  is the film's `embed_spec=false` twin: a share artifact that intentionally carries no
  provenance because it's for posting, not archiving. No invariant is weakened — the lossy
  social copy makes **no** determinism or reprint claim, by design, the same way the
  stripped share PNG doesn't.

This framing keeps the deferral's original reasoning intact (the *archival* film is still
APNG-because-manifest) while giving the marketing plan the file it actually needs.

## Concrete work

- **Encode path.** `timelapse.render_frames` already yields the frame list; add
  `encode_mp4(frames, step_ms, …)` beside `encode_apng`. Pillow can't write MP4 — add a
  bundled encoder (`imageio-ffmpeg` ships a static ffmpeg wheel, no system dep; matches the
  "native wheels, no Homebrew" ethos of `README.md`). WebP animation *is* Pillow-native
  (`save_all=True, format="WEBP"`) — cheap to add as the lighter-weight option.
- **Where it hooks.** A `format` field on the film submit (mirroring the print PNG/PDF
  picker): `apng` (default, archival) / `mp4` / `webp`. The MP4/WebP branches always behave
  as share copies — manifest omitted, not merely toggled off.
- **Size targets.** The APNG ceiling is ~40 MB (phone) today; H.264 will land the same film
  at a fraction of that, which *also* fixes the practical problem that a 40 MB APNG is
  awkward to share even where it's accepted.
- **Landing page.** Keep the APNG hero (browsers handle it), but the "download/share your
  film" affordance and every social asset in the Phase-0 asset farm
  (`scripts/render_asset_farm.py`) should emit MP4 as the shareable default.

## Invariants / risks

- **The archival film is untouched.** APNG + manifest + last-frame-identity all hold; the
  master invariant test (`test_timelapse.py`) is unaffected.
- **The social film makes no forever-claim** — it's explicitly the lossy, manifest-less
  twin. Document this the way the share-copy PNG is documented, so nobody later "fixes" the
  MP4 by trying to embed a manifest into a container that can't carry one faithfully.
- **New dependency** (`imageio-ffmpeg`) is a runtime cost; pin it in the lock file and gate
  MP4 behind its availability with an honest error, the way PDF is gated today.

## Out of scope

Audio/music, a scrubber UI, per-point (intra-day) animation, live-wallpaper packaging — all
still deferred per `2026-07-08-timelapse.md`. This plan adds *only* the shareable container
for the film that already exists.
