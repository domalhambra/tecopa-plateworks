# Studio red-team: upload → preview → customize (2026-08-10)

An adversarial pass over the single-window studio against one operator story: *drop
tracks easily, see a quick pretty preview of what landed, then customize the final
poster through simple, explained options — never a wall of unexplained sliders.*
Every front-end module (~5.6k lines across 22 ES modules + HTML/CSS) was read; every
finding below was verified in a real headless-Chromium drive against the live server
(synthetic plates, the `sample.gpx` fixture) before and after the fix.

**Overall verdict:** the architecture is sound and most of the story already holds —
drag-anywhere upload with accumulation, the progressive draft→sharp proof, the `?`
help affordance, presets-first appearance sidebar, the command palette. The failures
were all in the last inch: help sentences silently eaten by a JS footgun, palette
jumps that landed nowhere, a first proof that never rendered without a hunt for the
button, and a multi-file drop that quietly kept one file.

## Findings and dispositions

Severity: ● broke the operator story · ◐ friction · ○ polish.

1. ● **Five controls shipped with no explanation — the exact "unexplained slider"
   complaint — because of duplicate object keys.** In JS, a repeated key in one object
   literal silently keeps the *last* value. Three literals in `controls.js` carried
   their neighbours' `help:` lines (a paste drift): `marker` held oblique's sentence,
   `biome` held contours' and compass's, `tlFormat` held both film-hold sentences. Net:
   `oblique`, `contours`, `compass`, `tlHoldMs`, `tlLeaderMs` rendered with no `?` at
   all, while the welcome guide promised "every control explains itself behind its ?".
   **Fixed:** sentences restored to their owners; `tests/test_static_registry.py` now
   fails the build on any control with ≠1 help or any duplicated registry key (no JS
   runner needed — it checks the source as text).

2. ● **The first proof never rendered itself.** `scheduleAutoProof` gates on
   `state.hasSpec`, so "Live proof" only worked *after* the first manual render — the
   quick pretty preview required finding the button. Since the starter frame is
   already seeded at upload, there is nothing left to ask. **Fixed:**
   `proof.primeFirstProof()` fires after every successful upload/continue: a
   background proof with a new `stay` flag that warms the Preview *without* yanking
   the operator off the map (the old `onProofed` always stole the view). The upload
   toast now says the proof is rendering itself. Re-fires per batch because an upload
   resets `hasSpec` — new tracks deserve a fresh proof. Respects the Live-proof
   toggle; every existing guard (no crop, infeasible size, single-flight) applies.

3. ● **A multi-file drop outside a dropzone silently kept one file.** The
   drag-anywhere catch-all read `dataTransfer.files[0]` only; dropping three GPX on
   the proof stage uploaded one with no message. **Fixed:** the catch-all partitions
   the whole drop — a poster PNG wins a mixed drop (reopening is deliberate and
   single-file), otherwise every track file uploads. Verified with a synthetic
   two-file `DragEvent` on the top bar: all files accumulate.

4. ◐ **Palette jumps were dead-ends for a third of the registry.** `jumpToControl`
   resolved only `c_<id>` — but the seven page-setup/export controls are static
   `index.html` fields, and the sun dial used its own `dialAz`/`dialAlt` ids, so
   "jump to Print size / Orientation / Bleed / Title / Format / Sun azimuth…" all
   silently did nothing. **Fixed:** a static-target map + focus-the-live-face
   fallback; the dial's axis buttons now carry the canonical `c_sunAzimuth` /
   `c_sunAltitude`; the jump opens every enclosing `<details>`. Also the palette now
   filters out controls whose `visibleWhen` is currently false (no more offering "Sun
   azimuth" while archival light is on).

5. ◐ **`advanced` controls were unreachable, so nothing used the flag and every knob
   crowded the primary rows.** `buildSectionPanel` skipped them with a comment
   promising an "All options" drawer that does not exist. **Fixed:** advanced
   controls render into one collapsed **Fine-tuning** disclosure per section host —
   present, explained, deliberately second fiddle, and hidden entirely when all its
   rows are (`golden` under archival light). Demoted: `halo`, `ring`, `furniture`,
   `golden`. The primary rows are now: Route = color / width / color-by / weave,
   Terrain = depth / shadows / high-relief, Markers = size / photo frame, plus the
   cartography toggles and Journey Light. Nothing is removed and nothing is
   palette-only; the full instrument is one disclosure away.

6. ◐ **Duplicate `id="provenanceCard"`.** `index.html` declared it twice (project
   sidebar + home surface); `getElementById` resolves the first, so the home copy was
   dead markup — and a poster dropped on the home screen rendered its card in the
   sidebar with nothing pointing there. **Fixed:** one card (the sidebar, visible
   from every surface), dead markup removed, a toast + live-region announcement say
   where to look, and the registry test now fails on any duplicated id in
   `index.html`.

7. ○ **Help was click-only.** The inline-reveal pattern is right (touch, keyboard,
   stays put while adjusting) — but a mouse got nothing on hover. **Fixed:** the same
   sentence rides the `?` as a native `title`, and the toggle now carries
   `aria-controls`. The user-facing ask ("a tool tip for the customizations that
   stay") is satisfied by both paths.

8. ○ **The sidebar hint card nagged every reload** — `hintDismissed` lived only in
   memory. **Fixed:** persisted in prefs.

9. ○ **No favicon** — a 404 console error on every session. **Fixed:** inline SVG
   data-URI (a gold plate, cream ridge), no extra request.

## Deliberately left alone

- **The `?`-reveal help pattern** — better than hover tooltips for this audience;
  extended, not replaced.
- **`compose.js`'s size** (344 lines spanning upload + geometry + prefill): cohesive
  and load-bearing; splitting it buys nothing today.
- **`confirm()` in Start over** — native is fine for a destructive gate.
- **`comparison.png` / `tune.png` at the repo root** (~4.8 MB of old tuning
  artifacts): flagged for the operator; deleting them now doesn't shrink history, and
  they may still be wanted. Decide deliberately.
- **Wizard-era naming** (`api.js` header says "the wizard", `guided.js` mentions an
  eight-section rail): stale comments only; not worth churning files for.

## Verification

- `node --input-type=module --check` over every edited module (Node 22).
- `pytest tests/test_static_registry.py` — 4 new guards, all green (and the help
  guard fails on the pre-fix registry by construction).
- Full headless-Chromium drive (Playwright + the pre-installed browser) against a
  live server with synthetic plates: primed proof lands and stays on the map → sharp
  refine → all rendered rows carry `?` → Fine-tuning disclosures behave (style's
  visible+closed, light's hidden under archival) → palette jump opens the closed
  disclosure and focuses `c_halo` → "print size" jump focuses the static `size`
  select → "azimuth" matches nothing while archival → two-file synthetic drop on the
  top bar uploads both → zero console errors.
- Fast test tier (`pytest -n auto -m "not slow"`) green on this container.
