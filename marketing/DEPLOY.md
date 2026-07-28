# Deploying the landing page

`tecopa.plateworks.org` (Netlify site `tecopa-plateworks`,
`1902a58d-74a9-4def-8b4e-d93793f81ac4`, Cloudflare zone `plateworks.org`).

**The site is deployed manually, not from git, and that is deliberate.** The
page's imagery is the asset farm under `assets/`, which is gitignored — the
renders are generated, and a synthetic-DEM preview is not real terrain. A
git-connected build would therefore serve a page with seven broken images.
The deploy assembles a root from the repo *plus* a fresh render.

The published page is the repo's `landing.html` with three mechanical
transforms, no hand-editing:

1. `../assets/` → `/assets/` — the page becomes the site root, so the
   relative walk-up no longer resolves.
2. Print-resolution PNGs → web derivatives. The farm's poster and editions are
   ~50 MB each at 6200px, correct for print and unusable on a web page: the
   seven referenced files total **218 MB**. Downscaled and re-encoded they come
   to **5.3 MB**. Every pixel is still the engine's own render, resized only —
   `film.webp` is the farm's own share twin, not a re-encode.
3. `film.png` (APNG) → `film.webp`, which the farm already renders.

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
  A synthetic plate renders a poster that is wrong to show a customer.
- **Netlify's cert is slow and its API lies about it.** `POST /sites/<id>/ssl`
  returns `200` with a `null` body and creates nothing observable for minutes.
  Poll the site's `ssl` field; it flipped `False` → `True` about 90 seconds
  after the request that appeared to do nothing. Do not re-request in a loop.
- **Grey-cloud the Cloudflare record until the cert issues**, then proxy. With
  the proxy on, Netlify's HTTP challenge sees Cloudflare's IP and stalls.
- The `og:image` is `mockup_plate_1080x1080.jpg` from the farm. It must be
  copied into the staged root — nothing in `landing.html` references it, so a
  build that only follows `src` attributes will miss it.
