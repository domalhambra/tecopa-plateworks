# The asset farm and the terrain guard

The Tecopa pages are Ghost pages on www.plateworks.org since 2026-09-26 (spec
`docs/superpowers/specs/2026-09-24-ghost-landing-page-design.md`), and
`tecopa.plateworks.org` is a Cloudflare 301 to www.plateworks.org/tecopa/. Their images
come from the asset farm under `assets/`, which is gitignored: the renders are
generated, and a synthetic-DEM preview is not real terrain. This file covers the farm's
honesty gate. The runbook is Add a region to the farm and publish its relief images, in
`../docs/changing-things.md`.

The Netlify landing that this file used to deploy retired the same day. Its page, its
privacy page and the staged-root builder are at tag `landing-final-2026-09-26`; the
Netlify site `tecopa-plateworks` still holds the last deploy as the rollback.

## The terrain guard

The pages promise every image on them is the engine's own render. A *synthetic*
DEM — the 240x300 stand-in `tests/conftest.py` hydrates for any plate missing its
real 3DEP terrain — renders perfectly cleanly: right hillshade, right palette, right
place labels, right route ink. Nothing in the picture betrays that the landforms are
invented, so a container that could not pull 700 MB of DEM would export happily and
publish country that does not exist.

So the farm stamps the DEM it actually opened into `assets/index.json`:

```json
"terrain": {"synthetic": false, "sha256": "20cec75c…", "bytes": 192087365}
```

**Stamped at render time, never re-derived at publish time.** Reading
`regions/<id>/dem.tif` would answer the wrong question — a machine can render from a
stand-in and obtain the real DEM afterwards, at which point the file on disk reports
"real" while the posters on disk are still synthetic. That is the lassen_ca orphan bug
seen from the other side.

`terrain_guard` in `build_deploy.py` fails closed on **every region it is given**.
`scripts/export_relief.py` gives it each region it is about to export, and exports
nothing for a region the guard refuses. Two refusals:

- **`synthetic: true`** → refused. The plate must be rebuilt from real 3DEP terrain and
  the farm re-run. Override: `allow_synthetic=True`.
- **no usable `terrain` record** → refused. What the assets were rendered from is
  unrecorded. A restage-only run (`--only detail/model/mockups/coin/relief`) opens no
  DEM and so stamps nothing — it deliberately preserves any prior record rather than
  clobbering it, but it cannot create one. A DEM that was opened and could not be read
  is stamped `"synthetic": null`, which lands here too and *replaces* any prior record
  rather than inheriting a stale claim. Override: `allow_unverified=True`.

Only `synthetic` is enforced, and only as a literal JSON `true`/`false` — any other
shape (`{}`, missing, `0`, `"false"`) is a hand-edited or corrupt record and refuses as
unverified rather than reading as real terrain. **`sha256` and `bytes` are recorded for
future audit and nothing checks them yet**, so do not read a published page as evidence
that its DEM digest was verified; it is evidence the DEM was real, not that it was a
*particular* DEM.

The overrides are arguments, and no command offers them: `export_relief.py` has no
override flag. Each prints a loud stderr warning naming exactly what is being published
unverified, and each opens only its own door: `allow_unverified` will not wave through a
*known*-synthetic plate. When the guard refuses, re-render rather than reach for one.

Tests: `tests/test_terrain_provenance.py` (the stamp, the merge, the guard) and
`tests/test_export_relief.py` (the exporter runs this guard, not a copy).

## Steps

```bash
cd "<repo>"
./.venv/bin/python scripts/render_asset_farm.py --regions lassen_ca   # real DEM; see ../docs/changing-things.md
./.venv/bin/python scripts/export_relief.py lassen_ca                  # the web images; the guard runs first
```

Then upload through the blog folder's ghost-tecopa-pages script, as the runbook says.

## Gotchas paid for

- **`--regions lassen_ca` needs the real DEM.** `regions/lassen_ca/dem.tif` is
  gitignored and goes orphan on a pull; see "Repair an orphaned DEM" in
  `../docs/changing-things.md`. A synthetic plate renders a poster that is wrong to
  show a customer — which the terrain guard refuses rather than trusts you to remember.
- **The social coin videos** (`coin.webp` / `coin.mp4`, the farm's `coin` tier) are for
  posting, not for the pages. The pages draw each coin in relief from
  `export_relief.py`'s surface and height images.

## Netlify lessons, kept for the other sites

Learned on the retired Tecopa landing; they still apply to the Netlify properties.

- **Netlify's cert is slow and its API lies about it.** `POST /sites/<id>/ssl` returns
  `200` with a `null` body and creates nothing observable for minutes. Poll the site's
  `ssl` field; it flipped `False` → `True` about 90 seconds after the request that
  appeared to do nothing. Do not re-request in a loop.
- **Grey-cloud the Cloudflare record until the cert issues**, then proxy. With the proxy
  on, Netlify's HTTP challenge sees Cloudflare's IP and stalls.
- **A billing block reads as an auth failure.** `netlify deploy` reports a bare
  `JSONHTTPError: Forbidden`, even with `--debug`, when the real cause is account credit
  exhaustion. `netlify status` succeeds and both `GET /sites/<id>` and
  `GET /sites/<id>/deploys` return 200 — only the POST is refused, which looks exactly
  like a token-scope problem. Get the real message by calling the API yourself:
  ```
  curl -X POST -H "Authorization: Bearer $NETLIFY_AUTH_TOKEN" \
    -H "Content-Type: application/json" -d '{"files":{}}' \
    https://api.netlify.com/api/v1/sites/<site-id>/deploys
  ```
  → `403 "Account credit usage exceeded - new deploys are blocked until credits are
  added"`. The block is account-wide, so every Netlify property fails at once; if two
  sites break together, suspect billing before config.
