# TrailPrint — Output-Fitness Red-Team (wallpapers · print files · social items)

**Date:** 2026-07-17 · **Scope:** the three deliverable surfaces at `main` (1d460dc) —
poster print files (PNG/PDF @300 dpi), device wallpapers (native px @ device ppi), and
social share artifacts (WebP/MP4 film twins, share-copy PNGs). Output fitness only;
security/scale were covered by the 2026-07-01 and 2026-07-02 assessments.
**Method:** direct code audit of every output path (spec → render → encode → endpoint
→ UI), a survey pass over the wizard/scripts/test suite, and an independent
adversarial verification pass — every finding below carries file:line evidence; **24
findings → 23 confirmed or nuanced, 1 part-refuted (recorded in §7).** Device claims
were checked against Apple's published panel specs; encoder claims against the pinned
stack (Pillow 12.3.0, imageio-ffmpeg 0.6.0). This document records the verdict; **the
companion PR fixes the additive, contract-safe subset (§3)** and this file marks what
remains.

## 1. Verdict

The engine's output plumbing is genuinely engineered, not accidental: exact native
pixels via `pixel_size(final_dpi())`, pHYs + sRGB on stills, even-dim padding +
BT.709 convert-and-tag + faststart on the MP4 twin, manifest-less share twins **by
construction**, honest 422s at every gate, and the orphan drill proving the reprint
promise end to end. The gaps cluster in three bands:

1. **The targets, not the pixels.** The renderer hits any target perfectly — but the
   *set of targets* decayed: the wallpaper table predates every current Pro-tier
   iPhone (16 Pro/17-gen panels 1206×2622 / 1320×2868 match nothing), there was no
   custom-device escape hatch despite the spec validating any glass in (72, 600) ppi,
   and nothing in the product could emit a 9:16/4:5/1:1 frame — the film twins built
   "for posting" pillarboxed on exactly the platforms they exist for.
2. **Honesty at the edges of the promise.** A flattened APNG showed the bare-terrain
   leader (an *empty* poster) on the surfaces the twins were invented for; the
   embed_spec privacy meaning lived only in a hover tooltip; the PDF silently drops
   the manifest; bundle crop re-fits were unreported; the client hardcoded 300 dpi.
3. **Claimed but unpinned.** SKIPPED.txt, the BT.709 tags, wallpaper/WebP ICC, and
   the promised wallpaper goldens had zero test coverage — engineered claims with no
   tripwire.

One structural fact underlies everything: **the manifest names the plate but not the
engine version** (`provenance.ENGINE` is a name; only `manifest_version` rides the
file — the README's "engine/schema version" overstates). Additive defaults are
therefore the *only* mechanism keeping old files reprintable, and that discipline
binds **encoders exactly as it binds the painter** — proven load-bearing by the APNG
fix below, which must ride the manifest's `animation` block to keep old films
byte-identical (`tests/test_timelapse.py::test_reprint_of_a_film_reproduces_it_byte_identically`).

## 2. What held up under fire

Credit where the red-team found none to take: wallpaper finals are the device's
exact native pixels with the glass's ppi in pHYs (`test_wallpaper_api.py:74-75`);
`_match_wallpaper_preset` keys on px+ppi so renames can't break continues; the bundle
dedupes ids, probes off-DEM pre-enqueue, and zips ZIP_STORED (PNGs precompressed);
`_mp4_stream` pads odd dims by replication (never crops a composed sheet), converts
*and* tags BT.709, fronts the moov atom, and is byte-deterministic; WebP/MP4 twins
have **no manifest parameter to pass** — the privacy posture is structural; the
120 MP ceiling, screen-ppi bounds, and zoom cap gate every crafted input; and the
proof/final/reprint chain held byte-identity everywhere we attacked it.

## 3. Fixed in the companion PR (all additive; old manifests re-stamp byte-identically)

**Wallpapers — the table caught up, and stopped being a cage.** Current-gen panels
added (`iphone_pro` 1206×2622, `iphone_pro_max` 1320×2868, `desktop_5k` 5120×2880 @218)
with display names that say which models they fit; and a **custom device escape
hatch** — `wallpaper_preset="custom"` + `custom_px_w/custom_px_h/custom_ppi` on
`/api/proof` (`wallpaper.custom_preset`, bounds-checked, then the existing validate
gates do the real work). A continued custom wallpaper now restores as the *same*
custom device instead of silently falling back to a print (`main.continue_poster`
prefills `custom_device`). The bundle stays table-only (arcnames name table ids) with
an honest 422. UI: a "Custom…" option reveals three inputs; the synthesized preset
feeds the same zoom-floor math as a table device.

**Social — the share frames the twins were built for.** New `device_class="social"`
presets ride the whole existing wallpaper machinery unchanged: `ig_reel` 1080×1920
(exact 9:16 — the Reels/Stories/Shorts frame the 0.46-aspect phone panels only
approximated), `ig_portrait` 1080×1350, `ig_square` 1080×1080, at a deliberate
effective ppi (`SOCIAL_PPI = 160`: 2.6 pt track ≈ 5.8 px — the one knob a platform
canvas has no physical truth for; flagged for by-eye tuning). They ship **clean**
(a caption belongs to the post; a titled social card is a product call, §4). Films
target them through the existing `wallpaper_preset` field — 9:16 films are now one
form value away.

**The chrome band's missing twin.** New spec field `bottom_clear_frac` (default 0,
validated ≤ `TOP_CLEAR_MAX`, omitted from the manifest at 0 — the additive pattern)
keeps auto geography labels out of the phone home-indicator / lock-screen-controls
zone and the Reel caption zone (`render._draw_labels` keepout mirror; phone presets
0.10, `ig_reel` 0.20). Pre-feature posters reprint byte-identically.

**Flatten-safe films.** `encode_apng(default_image=True)` writes the **complete
poster** as the APNG's default image: animated viewers play the same frames;
flattening surfaces — the exact failure the twins exist for — now show the finished
poster instead of the bare-terrain leader. The flag rides the manifest's `animation`
block and is read back strictly (`is True`) on reprint, so **a pre-feature film
re-encodes byte-identically** — the encoder is under the same forever-contract as
the painter. MP4 `crf` 23→18 (4:2:0 is compatibility-mandatory; a lower crf is the
one lever left for the gold-hairline-on-paper worst case the PDF branch already
pins `subsampling=0` for).

**Honesty seams.** The save-file note now states the privacy benefit in the visible
copy ("your exact route coordinates stay out of the file"), not only the tooltip,
and tells PDF users the PDF is not a save file (`app.js updateSaveFileNote`). The
bundle response reports per-device **`crop_growth`** (re-fit area / proofed area)
and the UI names growth ≥1.15× instead of hiding it. `/api/upload` and
`/api/continue` serve **`final_dpi`**, and `state.js finalWidthPx()` uses it — the
client's zoom-floor math no longer assumes a resolution the server didn't state.

**Test-gap closures** (`tests/test_output_fitness.py` + expanded
`test_timelapse.py`): the bundle worker's SKIPPED.txt + survivors path and the
all-fail RuntimeError; the pre-enqueue `skipped`/`fitted` response; the MP4 `colr`
box read back as the BT.709 `nclx` 1/1/1 triplet; sRGB ICC asserted on wallpaper
finals and the WebP twin; the bottom band mirror of the clock-band test; the strict
`default_image` gate (crafted values degrade to legacy); custom-device round-trip
incl. continue-restore. The native-pixel suite iterates `PRESETS`, so every new
preset is covered by construction.

## 4. Confirmed, deliberately a product call (needs Dom)

- **Titled social cards.** Social presets ship clean; the cartouche on a 1080 px
  canvas is a design question (and `Preset.spec_fields()` deliberately stays the
  single furniture-policy site — generalize it only when the titled variant is real).
- **Metric units.** The cartouche speaks miles only (`render.NICE_MILES`, `"MI"`)
  while the elevation profile labels metres (`render.py:1852-1855`) — a mixed-units
  sheet even for US buyers. A `units` spec field is additive and cheap; the call is
  whether the cartouche grows a knob or a locale rule.
- **The embed default.** `embed_spec=True` everywhere is the product's soul ("the
  file is the whole record") and a privacy footgun only at the share boundary. The
  visible copy now says both truths; flipping the default would trade the archive
  promise for the privacy default. Recorded, not recommended.
- **Engine-version stamp.** Adding `engine_version` to the manifest would let a 2035
  reader *detect* painter drift, at the cost of a new forever-key. Until then the
  additive-defaults discipline is the whole contract — this doc's fixes obey it and
  future painter/encoder changes must too.
- **SOCIAL_PPI tuning.** 160 is a reasoned default (5.8 px track at feed size), not
  a validated one — needs the by-eye pass the wallpaper goldens also wait on.

## 5. Known-deferred, now due (the recorded backlogs already said so)

- **Bleed/trim** — `docs/superpowers/quality/2026-07-02-v1-quality-bar.md:52-53`
  ("typically +0.125 in bleed; confirm with the actual print lab") and V1-10. The
  elegant path is real terrain in the bleed zone (grow `spec.crop`; the DEM window
  already reads 6% past it) — but **all furniture is sheet-edge-anchored**
  (`KEYLINE_INSET_IN`, `TITLE_INSET_IN`, the profile strip, both clear bands), so
  bleed needs trim-box-relative furniture: an L, gated on a print-lab conversation.
  — **code shipped** as `spec.bleed_in` behind a `sheet_geometry` seam (real terrain
  in the bleed band, trim-box-relative furniture, trim-only proof / full-bleed final,
  off-DEM refusal extended to the band): see the 2026-07-17 plan Tranche B. The
  *offered value + format/marks/color* are still **open on the lab** — the
  questionnaire (`docs/superpowers/quality/2026-07-17-print-lab-questionnaire.md`) is
  the blocker, not more coding. `bleed_in` 0 reprints byte-identically.
- **Custom pixel dimensions** — was on the wallpaper plan's out-of-scope list
  (`2026-07-05-wallpaper-output.md:229-231`); **shipped in §3**.
- **iOS parallax overscan** — same list (line 233); still deferred (exact-pixel
  edges crop slightly under perspective zoom).
- **Wallpaper goldens** — promised by the plan's Phase 4 (lines 211-212), absent
  from `docs/superpowers/quality/golden/`; needs real-DEM renders + Dom's eye.
- **Profile-strip physical inset / `MARGIN_FRAC` decouple** — the strip's layout
  inset reuses the DEM-read margin constant (`render.py:1827-1828`), proportional
  where every other furniture is physical inches, and it shares the bottom-left
  corner with the cartouche stack under a different scaling law (overpaint risk at
  `furniture_scale` ≳ 1.3). A painter change → needs its own additive spec gate
  (there is no engine version to hide behind); bundle it with the next profile
  revision. — **shipped** as `profile_rev` 2 (physical inset, cartouche/compass
  stack clearance via the shared `_profile_rect` geometry, feet labels): see
  `docs/superpowers/plans/2026-07-17-profile-rev2-and-bleed.md` Tranche A. Rev 1
  reproduces the shipped strip verbatim, so every pre-feature poster reprints
  byte-identically; the `furniture_scale` ≳ 1.3 overpaint is now a geometry-sweep
  tripwire (`tests/test_profile_rev.py`).

## 6. Test-coverage delta (after the companion PR)

Now pinned: SKIPPED.txt + all-fail; `skipped`/`fitted` response truth; BT.709 tags;
ICC on wallpaper finals + WebP twin; bottom band; default-image poster-equality,
frame accounting (`n_frames == frames + 1`), and the strict legacy gate; custom
device 422s + round-trip; `final_dpi` served. Still open: wallpaper goldens (real
DEMs), cross-host font identity (Georgia→DejaVu makes reprint byte-identity
same-host only — `render._font`; the manifest names the plate, not the typeface),
any frontend test at all (the `final_dpi` plumb removes the worst drift trap, but
nothing executes `app.js`), and the 120 MP ceiling message naming a supported size
in inches (it names "120 MP"; all four offered UI sizes clear it — API-only edge).

## 7. Nuances & refuted details (recorded so they don't recur)

- **REFUTED:** "the elevation-profile strip can sit under the lock-screen clock" —
  it is pinned bottom-left (`render.py:1827-1830`); the real exposure was the
  *bottom* chrome zone, which had no keep-out at all → became `bottom_clear_frac`.
- **Corrected:** "the 422 doesn't name the ceiling" — it names **120 MP**
  (`spec.py:255-258`); what it doesn't name is a size in inches.
- **Corrected:** one verification pass under-counted the UI size menu (two sizes);
  direct read shows four (`index.html:110-113`). None approaches the ceiling.
- **Nuance:** Instagram-format assets *did* exist — but only as CLI marketing
  mockups (`scripts/render_mockups.py`, 1080×1080/1080×1350 through the same
  `_mp4_stream`), which is evidence the seam was proven, not that the product had
  the target.
- **Nuance:** the 16:9 desktop presets already served landscape platforms; the gap
  was specifically vertical (9:16) and feed (4:5/1:1) frames.

**Bottom line:** the renderer was always able to hit any frame at any density — the
red-team's work was pointing it at the frames people actually hang, unlock, and
post, and wiring tripwires to the claims that had none. Everything shipped here is
additive; every old file reprints byte-for-byte, films included.
