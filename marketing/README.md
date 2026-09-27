# Marketing assets

The outward-facing companion to `docs/marketing.md` (the strategy): the renderer that
feeds the Tecopa pages.

## The landing page

The landing, order and privacy pages moved to Ghost on 2026-09-26: www.plateworks.org
`/tecopa/`, `/tecopa-build/` and `/tecopa-privacy-policy/`, built by the blog folder's
ghost-tecopa-pages script. The single-file `landing.html` and `privacy.html` that lived
here are at tag `landing-final-2026-09-26`. The farm below still feeds the pages,
through `scripts/export_relief.py`.

## `scripts/render_asset_farm.py`

Turns each curated region into the full deliverable spread (poster, wallpapers, time-lapse
film, three-edition lineage set, the social-preview suite below), driving the render engine
directly. See its module docstring for flags. The rendered deliverables — poster, wallpapers,
film, editions — go through the real final path, so a full run also serves as an end-to-end
smoke test of the engine's own outputs. The social-preview suite is share-class and exercises
none of that path: the mockups and the GLB restage an already-rendered final's pixels, and the
light-sweep re-renders but carries no manifest (see below).

## The social-preview suite (three tiers, one goal)

A composition that reads as a **physical, three-dimensional object** everywhere it's seen.
The artwork pixels in every asset are the engine's own final — these scripts only stage them.

| Tier | Asset | The job |
|---|---|---|
| 1 — Light-sweep (`lightsweep.mp4`, `scripts/render_lightsweep.py`) | the sun walks the azimuth circle; only the land relights | the "this map is 3D" wow — Reels/feed, plate drops |
| 2 — Object mockups (`mockup_*.jpg/.mp4`, `scripts/render_mockups.py`) | the embossed Plate and the matted Frame on a gallery wall; the MP4s ink the journeys while the object subtly yaws | the "physical product" shot — feed grid, Stories, per-order share kits (works on ANY final PNG, no region data) |
| 3 — Orbitable plate (`mockup_plate.glb`, `scripts/render_model.py`) | a real GLB (relief-displaced disc, poster texture) embedded on the landing page via the vendored `<model-viewer>` (`vendor/`) | the click-through payoff — "spin your plate" |

All three are share-class assets: deterministic, lossy where lossy, and never carrying a
manifest — exactly the film-twin posture.
