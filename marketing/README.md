# Marketing assets

The outward-facing companion to `docs/marketing.md` (the strategy) — the actual page and
the renderer that feeds it.

## `landing.html`

A single-file landing page built on the plan in `docs/marketing.md`: a gallery-wall
treatment (the product's own posters hung as framed prints on a dark topographic ground),
the message ladder, the three pillars, the "the poster is the save file" editions triptych,
the print/wallpaper/film formats, the region plates, a trust strip, and an FAQ. Palette and
type are pulled from the render engine itself — the route-ink gold, terrain olive, and the
Georgia cartouche face the posters actually use.

It references rendered imagery under `assets/` (relative `../assets/...`), so it comes alive
once you render the asset farm:

```
./.venv/bin/python scripts/render_asset_farm.py            # real 3DEP DEMs
./.venv/bin/python scripts/render_asset_farm.py --synthetic-dem   # local preview, no real DEM
python -m http.server            # then open http://localhost:8000/marketing/landing.html
```

Currently the page images the **Lassen** plate; render the other regions and swap in their
posters to feature them. `assets/` is gitignored (generated, and synthetic-DEM previews are
not real terrain), so the imagery is never committed — only the page and the renderer are.

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
