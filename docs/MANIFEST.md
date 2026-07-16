# The TrailPrint manifest — schema v1

The file is the artwork. Every TrailPrint final (PNG poster, wallpaper, APNG
time-lapse) carries its complete recipe in **one compressed zTXt chunk**, keyword
`trailprint`, whose payload is compact JSON with sorted keys (byte-stable for a given
manifest; no timestamp, no randomness). Any PNG library can read it — no TrailPrint
code required:

    python -c "from PIL import Image; import sys; print(Image.open(sys.argv[1]).text['trailprint'])" poster.png

The manifest is a **forever-contract**: a poster printed today must still reprint,
byte-identically, after any future engine upgrade. Everything below is normative;
the frozen fixtures in `tests/fixtures/manifest_*.json` are the reference examples
and never change.

Beside the manifest rides one **plain tEXt chunk**, keyword `trailprint-note` — a
human-readable resurrection note (ASCII, uncompressed, so `strings poster.png` finds
it): what the file is, that the PNG is the save file, where the engine lives and its
license, the plate id + `pack_version` it was painted on, and how to reproduce it.
It is a pure function of the manifest (byte-stable, reprint-identical) and is
informative, not normative — readers must parse the zTXt manifest, never the note.
Share copies (`embed_spec=false`) carry neither chunk.

## Top-level keys

| key                | always? | meaning |
|--------------------|---------|---------|
| `manifest_version` | yes     | `1`, forever (see "The additive contract") |
| `engine`           | yes     | `"trailprint"` — names the producing engine |
| `region_id`        | yes     | the terrain plate id, e.g. `"lassen_ca"` (duplicates `spec.region_id` for cheap inspection) |
| `spec`             | yes     | the full CompositionSpec — the entire picture recipe (below) |
| `sources`          | yes     | GPX provenance records (below); may be `[]` |
| `edition`          | conditional | integer >= 2; present only from the second living edition on |
| `lineage`          | conditional | ancestor chain; present exactly when `edition` is |
| `animation`        | conditional | time-lapse pacing + render dpi; APNG finals only |
| `region_pack`      | conditional | the plate's hash identity (below) |

Baseline example: `tests/fixtures/manifest_v1.json` (print) and
`manifest_wallpaper_v1.json` (`spec.output_kind = "wallpaper"`).

## `spec` — the CompositionSpec

Every visual decision lives here, in physical units, so the same spec renders the
same pixels. Fields (defaults may be omitted by future writers; readers fill them):

- `region_id` — terrain plate id (string)
- `crs` — projected CRS of all coordinates, e.g. `"EPSG:32610"`
- `crop` — `[min_x, min_y, max_x, max_y]` in CRS meters; maps to the full sheet
- `print_w_in`, `print_h_in` — sheet size in inches (a wallpaper derives these from device px / ppi)
- `native_resolution_m` — the plate's data floor in meters/pixel (the zoom cap is judged against it)
- `tracks` — list of (N, 2) coordinate arrays in CRS meters
- `track_days` — journey identity parallel to `tracks`, or `null` (each track its own journey)
- `hotspots` — list of `{"x", "y", "weight"}` dicts, optionally `"label"`, `"icon"`, `"photo"` (embedded JPEG data URI — see Privacy)
- `seed` — deterministic-noise seed (integer)
- `track_width_pt` — route stroke width, points
- `track_max_darken` — route ink ceiling, 0-1 (grain shows through)
- `marker_diameter_in` — POI marker diameter, inches
- `grain_cell_in`, `grain_strength` — paper-grain cell size (inches) and amplitude (0-1)
- `title_pt`, `title_text` — cartouche title size (points) and text
- `label_pt` — marker label size, points
- `photo_box_in` — pinned-photo thumbnail long edge, inches
- `contours`, `compass`, `biome`, `labels` — furniture toggles (elevation contours, compass rose, land-cover tint, named geography)
- `track_rgb` — route ink as three 0-255 integers
- `track_halo` — paper-halo strength around the route, 0-0.9
- `marker_ring` — POI ring width as a fraction of diameter, 0-0.25
- `photo_frame_style` — `"mat" | "keyline" | "borderless" | "polaroid"`
- `furniture_scale` — multiplier on the automatic furniture scale, 0.6-1.6
- `terrain_depth` — multiplier on the terrain-depth pass, 0-1.5
- `shadow_strength` — cast-shadow / sky-occlusion strength, 0-1
- `oblique` — High relief: plan-oblique shear strength, 0-1 (terrain and everything on it displaces up-sheet by elevation, with occlusion; 1 = max stand-up, 12% of sheet height); default `0.0` = the classic top-down sheet, and the key is omitted at the default (writers must not emit `0.0` — a pre-oblique manifest re-stamps byte-identically)
- `light_mode` — Journey Light: `"archival"` (the region's curated NW light, default) or `"journey"` (the poster lit by the hike's own sun); the four light keys below are omitted at the archival default (a pre-Journey-Light manifest re-stamps byte-identically)
- `sun_azimuth_deg` — resolved journey-sun azimuth, 0-360 (clockwise from north); present only in journey mode. This is the RESOLVED sun (derived from the GPX timestamps at proof time); the timestamps themselves never enter the manifest
- `sun_altitude_deg` — resolved journey-sun altitude above the horizon, 8-80 (the 8° floor bounds the cast shadows); journey mode only
- `golden_strength` — the warm/cool golden-hour grade amount, 0-1 (default 0.7); journey mode only
- `profile` — draw the DEM-sampled elevation-profile furniture (default `false`, omitted at the default); `profile_height_in` (0-2.5) rides with it when present
- `track_color_by` — colour the route by a DEM-derived ramp: `"none"` (the flat swatch, default and omitted), `"elevation"`, or `"grade"`
- `label_place` — named-geography placement: `"anchor"` (the single centered position that drops a name on any collision, default and omitted) or `"smart"` (a ranked ring of offset positions, the route as a placement obstacle, and leader lines from a displaced name); omitted at `"anchor"` so a pre-feature manifest re-stamps byte-identically
- `track_weave` — chronological over/under weave where journeys cross: `false` (one summed cased route, default and omitted) or `true` (journeys composited oldest→newest as separate cased strands, newest on top); a no-op with fewer than two journeys; omitted at `false`
- `output_kind` — `"print"` (finals at 300 dpi) or `"wallpaper"` (finals at `screen_ppi`)
- `screen_ppi` — device pixels per inch; meaningful for wallpapers only
- `keyline` — the thin sheet frame (wallpapers go clean)
- `top_clear_frac` — keep auto-placed labels out of the top fraction of the sheet (lock-screen clock), 0-0.35
- `edition` — the edition number the cartouche draws, 1-999 (default 1)
- `credit_text` — the cartouche's data-credit row (e.g. `"Terrain USGS 3DEP - Names USGS GNIS"`); printable ASCII, at most 200 characters; default `""` = no credit row, and the key is omitted at the default (writers must not emit `""` — a pre-credit manifest re-stamps byte-identically)

## `sources` — GPX provenance

One record per ingested GPX file:
`{"filename": "trip.gpx", "sha256": "<hex sha256 of the file bytes>", "bytes": <length>}`.
These name the raw inputs; they are not needed to reprint (the tracks ride in `spec`).

## `edition` + `lineage` — living editions

From the second edition on, the manifest carries `edition` (int, matches
`spec.edition`) and `lineage`: a list of `{"sha256", "edition"}` ancestor records,
oldest first, capped at the newest 100 (past the cap the oldest drop; the file never
refuses to embed). A first edition carries neither key. Normative example:
`tests/fixtures/manifest_edition_v1.json`. An embedded hotspot photo travels the same
way across editions — see `manifest_photo_v1.json`.

## `animation` — time-lapse pacing

An APNG time-lapse carries
`{"max_frames", "step_ms", "hold_ms", "leader_ms", "dpi"}` — the frame budget, the
per-frame / final-hold / leader durations in milliseconds, and the dpi the film was
rendered at — so the film re-renders from the file alone. Absent on stills.
Normative example: `tests/fixtures/manifest_animation_v1.json`.

## `region_pack` — the plate's identity

A final rendered against a hash-manifested terrain plate carries
`{"pack_version": "<12 hex>", "assets": {"<name>": "<sha256>", ...}}`. `assets` maps
each plate asset **the render actually read for these pixels** to the sha256 of its
bytes on disk at render time. `overview.png` never appears (it only feeds the
browser's aim canvas), `labels.json` appears only when `spec.labels` is true, and
`landcover.tif` only when `spec.biome` is true — an asset the pixels never touched
is not part of their identity, so e.g. a GNIS labels re-bake (or an NLCD refresh)
never invalidates a poster that never drew it. `pack_version` is one short id
for the whole plate: the first 12 hex chars of sha256 over the sorted `name:sha256`
lines joined by `\n`. Worked example: for `assets` of exactly
`{"dem.tif": "000…0"}` (64 zeros) the joined input is the single line
`dem.tif:000…0` and the derivation yields `a15c11e69898`.

Note that `tests/fixtures/manifest_region_pack_v1.json` is the frozen **mismatch**
fixture, not a derivation example: its `pack_version` of `"000000000000"`
deliberately violates the formula above so it can never match a real plate — do not
unit-test a reader's derivation against it.

Semantics on reprint/continue:

- **match** — the server's plate hashes to the same `pack_version`: a faithful
  reprint; the pixels come from the same terrain.
- **mismatch** — USGS re-flies 3DEP, plates get rebuilt; a rebuilt plate would
  reprint an old poster *differently*, silently. The server refuses with an honest
  422 naming both plate ids instead. Honest refusal over silent wrongness.
- **absent** — a pre-pack poster (or a hand-built plate with no `sources.json`):
  verification is skipped, the file prints, and a reprint truthfully re-stamps the
  block from the current server's plate.

Hashes, not URLs, identify a plate: URLs rot, mirrors move, but the bytes hash the
same everywhere. Any archive holding the named assets can reconstitute the plate.

## The additive contract

`manifest_version` stays `1`. Schema evolution is purely additive, and every added
key is **omitted when absent** — a pre-feature manifest is byte-for-byte unchanged
by new engine builds. Readers must therefore:

- tolerate unknown top-level and `spec` keys (ignore them), and
- tolerate missing optional keys (apply the documented defaults),

mirroring the engine's own two-way drift rule (`serialize.spec_from_json`): unknown
spec fields are dropped, missing ones take dataclass defaults. A reader written
against this document today reads every past and future v1 file.

## Privacy

The manifest carries the **exact track coordinates** and any pinned photos as
embedded JPEG data URIs — the file is the whole record, including where you were.
Share copies exported with `embed_spec=false` carry **no manifest at all**: no
coordinates, no photos, no provenance. Choose per file.

## License

This document and the TrailPrint manifest format it specifies are dedicated to the
public domain under **CC0-1.0** (see `docs/superpowers/plans/2026-07-12-strategy-and-license.md`).
Anyone may implement a manifest reader, inspector, or renderer — commercially or
otherwise, with or without attribution — without touching the AGPL-licensed engine.
Even if the engine rots, the file format is free to reimplement: the deepest layer
of the never-orphaned promise.
