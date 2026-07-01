# Badwater HD — Design System

The visual and editorial system behind **Badwater HD: An Atlas of Human Design** (`hd.badwater.group`), the encyclopedia layer of **Badwater Guidance** — Dom Alhambra's body of work on philosophy, systems thinking, and Human Design.

Badwater is what you find when you take a step closer to dry country: more life than you expected, you just have to slow down and see the beauty. The atlas applies that instinct to Human Design — a cross-referenced reference for gates, channels, centers, circuits, lines, and crosses, written so someone can look a concept up the way they'd look up a word in a dictionary. The brand is warm, earthen, and quiet. Dark-by-default like the desert at night; cream like sun-bleached paper by day.

This design system lets a design agent build on-brand interfaces, slides, and prototypes for Badwater — production code or throwaway mocks.

## Sources

Built by reading the real product. Explore these to go deeper:

- **GitHub — `domalhambra/badwater-astro`** (private): the Astro + SQLite encyclopedia. The token system (`src/styles/tokens.css`), global base (`src/styles/base.css`), entity-page and index-card styles, and the Svelte component layer were lifted directly from here. Worth browsing further to match new surfaces.
- Related repos in the same hand: `domalhambra/badwater-garden` (public PKM garden), `domalhambra/badwater` (the Badwater blog, Ghost), `domalhambra/badwater-hd-reference` (the prior Hugo encyclopedia).
- Live: the encyclopedia at `hd.badwater.group`; the blog at `www.badwater.guide`; coaching as **Badwater Guidance**.

Token values, the palette, type families, spacing, and the nine Human Design center colors in this system are reproduced verbatim from `badwater-astro`. Fonts (Fraunces + Lora) are Google Fonts — no substitution.

---

## Content fundamentals

How Badwater writes. The register is the product as much as the palette is.

**Voice is first person, singular, and personal.** Dom writes as himself — a wildland firefighter who got into Human Design and built the reference he wished existed. "I'm a lead wildland firefighter on the Diamond Mountain Interagency Hotshot Crew." "What HD gave me, that nothing else had, was a way to tell what energy was actually mine." When the reader is addressed it's direct second person: "Begin where the friction is." "Spend effort on a body signal, not a plan."

**Claim-first, mechanism-as-readout, no hedging.** State the thing, then explain how it works. The encyclopedia register avoids the "many practitioners believe…" throat-clearing of most HD writing. A gate *does* something; say what.

**No em dashes.** This is a hard house rule from the engine's voice spec. Use commas, periods, parenthetical clauses, or restructure. Both `—` and `–` as parenthetical separators are out. (This README follows the rule.)

**Casing.** Sentence case for headings and body. Eyebrows and section labels are UPPERCASE with `0.08em` tracking — the signature label treatment. Human Design proper nouns keep their canonical capitals: Type, Strategy, Authority, Profile, Definition, Manifestor, Generator, Projector, Reflector, Not-Self, the names of the nine Centers.

**Tone.** Calm, exact, unhurried. Desert and systems metaphors recur ("read what nature is doing," "the spring at the center of dry country," "a wiring diagram, not a verdict"). Knowledge-management framing recurs too: taking a complex system and making it navigable. Never breathless, never mystical-for-its-own-sake, never salesy. The 80/20 of Strategy and Authority should land for someone who just got their chart.

**Emoji: never.** None appear anywhere in the product. Do not introduce them.

**Mechanical specifics.** Gate and channel references are terse and mono-set: "Gate 25", "10–57", "51–25" (en-dash between channel gates, but *not* as a parenthetical dash). Dates are ISO (`2026-06`). Keynotes are single italic words or short phrases ("Innocence"). Cross-references are everywhere — the atlas is a graph, and the prose assumes the reader can follow a thread.

**Example copy, on-brand:**

> *Start with the Not-Self.* The conditioning story is the way into the system. Begin where the friction is.

> Wait for the invitation. A Projector who informs instead of waiting spends energy on a door that was never going to open.

---

## Visual foundations

**Palette — warm earth / desert.** The system is built on near-black and cream, with a single saturated through-accent (terracotta) and one secondary (antique gold). Everything else is warm neutral. Dark is the default scheme; light is cream paper.

- *Dark (default):* background `#161618` (near-black, faintly warm), elevated surfaces `#1A1A1C`, text `#D5D8E0` body / `#EBE6D9` contrast. Terracotta accent `#B56B4A`, gold `#D4B464`.
- *Light:* background `#F0EFEC` (warm cream), white cards `#FFFFFF`, layered gray `#E6E4DF`, ink `#2B2A28`. Terracotta deepens to `#A85638`, gold to antique `#8A6310` for contrast on cream.
- The accent has a family: `accent` (UI), `accent-hover`, `accent-strong` (solid fills behind white, AA 5.4:1), `accent-text` (AA small text). Always reach for the contrast-correct one rather than tinting by hand.

**The nine Human Design center colors** are a domain palette of their own (`tokens/centers.css`), anchored to the **Jovian Archive standard** color families and rendered in southwestern-desert shades: **Yellow** (Head sun-gold, G antique-ochre), **Green** (Ajna sage), **Brown** (Throat sienna, Spleen clay, Root dark-earth), **Red** (Heart brick, Sacral canyon-rust), and **Mauve** (Solar Plexus desert-dusk — the one center that is both an awareness center and a motor, so it carries its own hue rather than a fourth flat brown). A trained HD eye reads the canonical grouping, while each center keeps a distinct shade so the bodygraph stays navigable. They are tuned to read on either background and are the source for the four Wheel-quarter accents. Use them for center glyphs, gate-by-center grouping, and the system-map graph — never as decorative brand color.

**The six pillar accents** (`tokens/colors.css`, `--pillar-accent-*`) extend the same palette into the site's information architecture. Each top-level section owns one intentional hue, threaded through every place that pillar surfaces — its axis pill, its homepage pathway card, its hub top-rule and movement numbers, and its footer group — so a reader learns a section by its color: **The Design** terracotta (the brand-core identity pillar), **The BodyGraph** antique gold (the energy map), **The Wheel** dusk mauve (the celestial zodiac and crosses), **The Not-Self** canyon rust (friction and conditioning, the wound), **Energy & Effort** chaparral green (the body), **Reference** slate (the quiet utility drawer). The set is a balanced spread around the warm desert wheel plus one neutral, each color chosen to resonate with its pillar's meaning rather than assigned arbitrarily. New hubs should adopt their pillar's accent the way the Energy & Effort hub does, never invent a new one.

**Typography.** Two serifs, no sans. **Fraunces** (optical-size serif, weights 500–800) for all headings and hero display — it carries the bookish, slightly literary character. **Lora** (warm serif, 400–600, with italics) for body and UI text. A system monospace stack for code, gate/channel chips, and metadata tags. Sizes are deliberately small and reading-tuned: a 24px h1, 32px hero display, 16px body at `1.5`, long-form prose at `1.65` capped to a `68ch` measure. Headings sit tight at `1.25`.

**Spacing & radius.** A compact rem scale (`--spacing-1` 2px … `--spacing-10` 40px). Radii are gentle and few: 6px (`--radius-1`, inputs/buttons/code), 12px (`--radius-2`, cards), and full-round `999px` for chips and identity badges. Nothing is heavily rounded; the brand reads as calm and bookish, never bubbly.

**Backgrounds & texture.** Flat, solid surfaces. No photographic backgrounds, no repeating patterns, no noise. The one gradient in the product is a barely-there `rgba(212,175,106,0.05)` gold wash on the returning-visitor hero — effectively a tint, not a gradient statement. Avoid bluish-purple gradients entirely; they are off-brand.

**Borders, cards & elevation.** Borders are low-contrast and warm: `rgba(235,230,217,0.10)` hairlines, `0.18` for stronger rules. Cards are an elevated surface + 1px border + 12px radius + a soft shadow (`0 2px 8px rgba(0,0,0,0.30)` dark, much lighter on cream). The signature card move is a **2px accent top-rule** above an uppercase eyebrow label — and, on the homepage pathway cards, a **3px accent left-border** keyed to the pillar's hue. Left-border accents recur throughout (callouts, bespoke sections, blockquotes) as the way to break reading flow without drawing a box.

**Eyebrows everywhere.** The uppercase, tracked, accent-colored micro-label is the system's most recognizable device. It sits above titles, marks sections, and labels callouts. When in doubt, an eyebrow + a serif title is the Badwater header.

**Animation & states.** Restrained. Transitions are `0.15s ease` on `color`, `background`, and `border-color` — never transform-heavy, never bouncy. No infinite decorative loops. A single rotating `▸` marker on disclosures is about as animated as it gets. Reduced-motion is honored. **Hover** = border picks up the terracotta accent and/or text shifts to `accent-hover`; on solid buttons, nothing dramatic. **Press** = no shrink or bounce; rely on the natural active state. **Focus** = a 2px solid terracotta outline at 2px offset, always visible.

**Imagery vibe.** Warm and earthen if present, but the product is overwhelmingly typographic. The brand mark is the only illustration: concentric rings read from above, a spring at the center of dry country. There is no icon zoo and no stock photography.

**Layout rules.** Three container widths anchor everything: `440px` narrow (forms), `800px` default (reading), `1100px` wide (hubs, the homepage). Reading columns cap at `68ch`. The entity page is a two-column grid — prose plus an `18rem` structural gutter for margin notes that float right. A sticky top nav (`surface-elevated`, hairline bottom border) and a generous browse-everything footer bracket each page. Transparency and blur are essentially unused; the system favors solid, legible surfaces over glass.

---

## Iconography

**Badwater is near-iconless by design, and that is the strongest brand statement here.** The product carries no icon font, no icon sprite, and no Lucide/Heroicons/Feather set. Do not introduce one. When a glyph is genuinely needed, the system uses a single typographic character set in the existing fonts:

- `▸` — disclosure / deep-dive marker (rotates 90° when open).
- `·` — the separator between identity facets (Type · Profile · Authority · Definition).
- `+` — the "add your chart" affordance.
- `↩` — citation backlink in the references list.
- `▾` / chevrons — only where a native control implies them.

**Color as icon.** The nine center colors and five aura-type colors do the work icons would do elsewhere: a filled dot is a defined center, a hollow ring is an open one; a tinted capsule names a type. Reach for a `CenterBadge` or `TypeBadge` before reaching for any pictogram.

**The brand mark** (`assets/badwater-mark.svg`, also `public/favicon.svg`) is the only SVG illustration: four concentric rounded rings. Tint it via `currentColor` — terracotta, gold, or contrast. It is a favicon and a quiet masthead device, not a UI icon.

**Emoji: never**, in product or in generated artifacts.

If a build truly needs functional UI icons (a search magnifier, a close ×), prefer a Unicode glyph or a minimal inline stroke icon at the weight of the surrounding text. Flag any icon set you add, because adding one is a departure from the brand.

---

## What's in this system

**Tokens** (`styles.css` → imports):

- `tokens/colors.css` — dark-default + light/system scopes; text, surface, border, terracotta accent family, antique gold, semantic, aura-type, and pillar-accent tokens.
- `tokens/centers.css` — the nine HD center colors + four Wheel-quarter accents.
- `tokens/typography.css` — Fraunces/Lora/mono families, the reading-tuned size scale, weights, semantic aliases.
- `tokens/spacing.css` — spacing scale, radii, container widths, card chrome.
- `tokens/fonts.css` — Fraunces + Lora from Google Fonts.
- `tokens/base.css` — global element styling (body, headings, links, `.eyebrow`).

**Components** (`components/`), under `window.BadwaterHDDesignSystem_cd9780`:

- `core/` — **Button** (primary/secondary/gold/ghost), **Chip** (mono cross-ref pill), **Badge** (identity/status pill), **Eyebrow** (signature label), **Card** (entity index card).
- `feedback/` — **Callout** (context / note / bespoke asides), **DeepDive** (disclosure).
- `hd/` — **CenterBadge** (nine centers, defined/open), **TypeBadge** (five aura types, with Strategy).

**UI kit** (`ui_kits/badwater-hd/`): a click-through recreation of the encyclopedia — home hero, axis-pill navigation, an entity (gate) page with prose + margin notes, and the chart-loaded state. See its `README.md`.

**Foundations** (`guidelines/`): specimen cards for the Design System tab — type, colors, spacing, brand mark.

**Assets** (`assets/`): the Badwater mark (SVG), favicon, and the social card wordmark.

**`SKILL.md`**: makes this directory usable as a downloadable Agent Skill.

---

## Working with this system

- **Mocks, slides, prototypes:** copy assets out, link `styles.css`, and build static HTML. Use the tokens for every color and measurement; use the components for buttons, chips, badges, cards, and callouts.
- **Production:** read the token files and component sources; they mirror `badwater-astro` closely enough to port.
- **Always:** dark scheme by default, two serifs, terracotta as the one bright note, eyebrows over titles, left-border accents to break flow, no em dashes, no emoji, no new icon set. When unsure, make it quieter.
