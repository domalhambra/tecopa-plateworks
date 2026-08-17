# Deploying the landing page

`tecopa.plateworks.org` (Netlify site `tecopa-plateworks`,
`1902a58d-74a9-4def-8b4e-d93793f81ac4`, Cloudflare zone `plateworks.org`).

**The site is deployed manually, not from git, and that is deliberate.** The
page's imagery is the asset farm under `assets/`, which is gitignored — the
renders are generated, and a synthetic-DEM preview is not real terrain. A
git-connected build would therefore serve a page with seven broken images.
The deploy assembles a root from the repo *plus* a fresh render.

The published page is the repo's `landing.html` with four mechanical
transforms, no hand-editing:

1. `../assets/` → `/assets/` — the page becomes the site root, so the
   relative walk-up no longer resolves.
2. Print-resolution PNGs → web derivatives. The farm's poster and editions are
   ~50 MB each at 6200px, correct for print and unusable on a web page.
   Downscaled and re-encoded they come to a few MB. Every pixel is still the
   engine's own render, resized only — `film.webp` is the farm's own share
   twin, not a re-encode. The one exception to downscaling is `detail.jpg`,
   the 1:1 print-pixels crop: its entire point is unscaled resolution, so it
   ships at the farm's own crop size.
3. `film.png` (APNG) → `film.webp`, which the farm already renders.
4. Per-plate coins: every `data-plate` card's `mockup_plate.glb` is copied
   into the root when the farm has rendered it; a card whose GLB is missing
   has its `<model-viewer>` stripped (with a warning) rather than published
   as a broken fetch. To ship all five coins, render the farm's `model` tier
   for all five regions — which needs each region's real DEM for the poster
   it restages.

## The terrain guard

The footer promises every image on the page is the engine's own render. A
*synthetic* DEM — the 240x300 stand-in `tests/conftest.py` hydrates for any
plate missing its real 3DEP terrain — renders perfectly cleanly: right
hillshade, right palette, right place labels, right route ink. Nothing in the
picture betrays that the landforms are invented, so a container that could not
pull 700 MB of DEM would deploy happily and publish country that does not
exist.

So the farm stamps the DEM it actually opened into `assets/index.json`:

```json
"terrain": {"synthetic": false, "sha256": "20cec75c…", "bytes": 192087365}
```

**Stamped at render time, never re-derived at deploy time.** Reading
`regions/<id>/dem.tif` here would answer the wrong question — a machine can
render from a stand-in and obtain the real DEM afterwards, at which point the
file on disk reports "real" while the posters on disk are still synthetic. That
is the lassen_ca orphan bug seen from the other side.

`build_deploy.py` fails closed on **every region it publishes anything for** —
`--region`'s derivatives *and* each plate card whose coin it copies, since the
coins are marketing images too. Two refusals:

- **`synthetic: true`** → exit 1. The plate must be rebuilt from real 3DEP
  terrain and the farm re-run. Override: `--allow-synthetic`.
- **no `terrain` record** → exit 1. What the assets were rendered from is
  unrecorded. Note a restage-only run (`--only detail/model/mockups/coin`)
  opens no DEM and so stamps nothing — it deliberately preserves any prior
  record rather than clobbering it, but it cannot create one. Override:
  `--allow-unverified-terrain`.

Each override prints a loud stderr warning naming exactly what is being
published unverified. Each opens only its own door: `--allow-unverified-terrain`
will not wave through a *known*-synthetic plate.

Every plate built before 2026-08-16 predates the stamp, so the first deploy
after this guard landed refuses until the farm is re-rendered. That refusal is
the guard working — re-render rather than reaching for the override.

## Steps

```bash
cd "<repo>"
./.venv/bin/python scripts/render_asset_farm.py --regions lassen_ca   # real DEM; see CLAUDE.md
python3 marketing/build_deploy.py                                     # writes the staged root
export NETLIFY_AUTH_TOKEN=$(cat ~/.config/netlify/token)
netlify deploy --prod --dir=<staged root> --site=1902a58d-74a9-4def-8b4e-d93793f81ac4
```

Verify: `curl -sI https://tecopa.plateworks.org` → `HTTP/2 200`, and every
`/assets/...` reference in the deployed `index.html` returns 200.

## Gotchas paid for

- **`--regions lassen_ca` needs the real DEM.** `regions/lassen_ca/dem.tif` is
  gitignored and goes orphan on a pull; see CLAUDE.md's "Known local failures".
  A synthetic plate renders a poster that is wrong to show a customer — which
  the terrain guard above now refuses rather than trusts you to remember.
- **Netlify's cert is slow and its API lies about it.** `POST /sites/<id>/ssl`
  returns `200` with a `null` body and creates nothing observable for minutes.
  Poll the site's `ssl` field; it flipped `False` → `True` about 90 seconds
  after the request that appeared to do nothing. Do not re-request in a loop.
- **Grey-cloud the Cloudflare record until the cert issues**, then proxy. With
  the proxy on, Netlify's HTTP challenge sees Cloudflare's IP and stalls.
- The `og:image` is `mockup_plate_1080x1080.jpg` from the farm. It must be
  copied into the staged root — nothing in `landing.html` references it, so a
  build that only follows `src` attributes will miss it.
- **The region-request form is Netlify Forms.** Detection happens at deploy
  time from the static HTML (`data-netlify` + the hidden `form-name` input) —
  it works with a manual `netlify deploy`, no build step needed, but check
  the Forms tab after the first deploy of a changed form: a renamed form is a
  NEW form and notifications must be re-pointed at it. Submissions are the
  region-demand signal (and the commission lead list); enable email
  notifications in the Netlify site settings or they sit unread.
- **Form detection is OFF by default on this site, and a correct deploy still
  detects nothing.** Netlify ships newer sites with
  `processing_settings.ignore_html_forms: true` (this site was created
  2026-07-28). The deploy succeeds, the HTML is right, and the Forms tab stays
  empty with no error anywhere. Turn it on, then **deploy again** — detection
  only runs at deploy time, so flipping the setting does not retroactively scan
  the published HTML:
  ```
  curl -X PATCH -H "Authorization: Bearer $NETLIFY_AUTH_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"processing_settings":{"html":{"pretty_urls":true},"ignore_html_forms":false}}' \
    https://api.netlify.com/api/v1/sites/1902a58d-74a9-4def-8b4e-d93793f81ac4
  ```
  Verify with `GET /sites/<id>/forms` (not the UI — it caches). Once detected,
  the live HTML loses its `data-netlify` attribute: that is Netlify rewriting
  the form, not a regression. Notifications are hooks:
  `POST /api/v1/hooks` with `{site_id, form_id, type:"email",
  event:"submission_created", data:{email}}`; list them with
  `GET /api/v1/hooks?site_id=<id>` (the `/sites/<id>/hooks` path returns HTML).
- **A billing block reads as an auth failure.** `netlify deploy` reports a bare
  `JSONHTTPError: Forbidden`, even with `--debug`, when the real cause is
  account credit exhaustion. `netlify status` succeeds and both
  `GET /sites/<id>` and `GET /sites/<id>/deploys` return 200 — only the POST is
  refused, which looks exactly like a token-scope problem. Get the real message
  by calling the API yourself:
  ```
  curl -X POST -H "Authorization: Bearer $NETLIFY_AUTH_TOKEN" \
    -H "Content-Type: application/json" -d '{"files":{}}' \
    https://api.netlify.com/api/v1/sites/<site-id>/deploys
  ```
  → `403 "Account credit usage exceeded - new deploys are blocked until credits
  are added"`. The block is account-wide, so every Netlify property fails at
  once; if two sites break together, suspect billing before config. Fixing it
  means adding credits — an operator action, not a technical one.
- **The social coin videos** (`coin.webp` / `coin.mp4`, the farm's `coin`
  tier) are for posting, not for the page — the page's coins are the live
  GLBs. Don't add them to the deploy root; they'd be dead weight.
