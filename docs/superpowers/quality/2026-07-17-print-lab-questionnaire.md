# Print-lab questionnaire — the conversation that pins the bleed/trim config

_2026-07-17 · Status: **awaiting a lab**. Companion to
`docs/superpowers/plans/2026-07-17-profile-rev2-and-bleed.md` (Tranche B). The code
ships fully parameterized; this document is the list of questions whose answers
become config values, plus where each answer lands. Industry practice is that you
never guess bleed — the lab's spec is an external contract, so it lives as data,
not constants._

## Questions for the lab

1. **Bleed amount.** How much bleed do you want on a full-bleed poster?
   *(US convention: 0.125 in; EU: 3 mm; large-format posters sometimes 0.25 in.)*
   → lands in the wizard's offered value (`index.html` bleed select) and the copy
   beside it. The spec ceiling is `BLEED_MAX_IN = 0.5`.
2. **Safe margin / trim tolerance.** What is your cut tolerance, and what minimum
   distance inside the trim line do you want for text and critical marks?
   *(Common: 0.125–0.25 in.)* → today the 0.25 in keyline doubles as the trim-safe
   zone by convention; the answer decides whether `KEYLINE_INSET_IN` needs to grow.
   Note for the conversation: a symmetric keyline frame is the single most
   cut-tolerance-sensitive element on the sheet — ask them directly whether 0.25 in
   is comfortable for their cutter.
3. **File format.** Flattened raster (PNG/TIFF) at exact bleed size, or PDF? If
   PDF: is a full-bleed page (page size = trim + 2×bleed, cut centered) acceptable,
   or do you require PDF/X with TrimBox/BleedBox set? Do you want crop marks, or
   marks-free exact-size files? *(Never both by default; marks live in a slug.)*
   → full-bleed page ships now; TrimBox/BleedBox = the deferred pikepdf follow-up.
4. **Color.** Do you accept sRGB RGB files (typical for digital/inkjet web labs),
   or do you require CMYK with your ICC profile (offset)? Do you offer a hard
   proof, and against what output intent do you proof?
   → the PNG already embeds sRGB; a CMYK ask is a new work item, flag it loudly.
5. **Resolution & limits.** Required dpi at final size (we deliver 300), and any
   maximum pixel-dimension or file-size limits?
   *(Our own output ceiling is 120 MP — no offered size approaches it.)*
6. **Physical proof.** Can we order one test sheet with corner targets before
   offering print files as a paid deliverable?
   → closes the still-open "physical-proof color check"
   (`docs/superpowers/quality/2026-07-02-v1-quality-bar.md` §3), and shows real
   trim wander against the keyline.

## Where the answers land

| Answer | Lands in |
|--------|----------|
| Bleed amount | wizard select value + copy (`app/static/index.html`) |
| Safe margin | `KEYLINE_INSET_IN` review + the collision sweep bounds in `tests/test_profile_rev.py` |
| Format / marks | keep full-bleed page, or schedule the pikepdf TrimBox/BleedBox follow-up |
| Color | no-op if sRGB; new work item if CMYK (flag before promising) |
| dpi / limits | should all be no-ops; verify against `FINAL_DPI` and `MAX_OUTPUT_PIXELS` |
| Physical proof | order it; record the result beside the quality bar's checklist |

## Answers (fill in)

- Lab: —
- Date: —
- Bleed: — · Safe margin: — · Format: — · Marks: — · Color: — · Limits: —
- Physical proof ordered / result: —
