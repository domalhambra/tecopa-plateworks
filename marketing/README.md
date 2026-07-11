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
film, three-edition lineage set), driving the render engine directly. See its module
docstring for flags. Every deliverable goes through the real final path, so it also serves
as an end-to-end smoke test of every output the product ships.
