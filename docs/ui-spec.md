# TrailPrint — UI Spec (for Claude Design)

A one-page map of the current web UI: every surface, its states, the data it shows,
the actions, and the API behind it. Paste this (with the screenshots) into Claude
Design so its output drops cleanly back onto this codebase.

## Product in one line

A **local** app that imports GPX/KML/KMZ tracks and renders a **shaded-relief poster**
of where you've been within one curated region. The whole point is a beautiful,
print-ready artifact — the UI should feel like a small, premium **poster studio**, not
a dashboard.

## Visual language (match this)

- **Relief**: earthy hypsometric terrain — sage/tan basins → brown ridges → near-white
  peaks, with soft hillshade and paper grain. (See the poster screenshots.)
- **Track**: a pronounced **desert-gold** line (`rgb(214,158,58)`) with a thin dark-umber
  casing. This is the hero color.
- **Markers**: gold discs with dark vector icons (peak/camp/water/flag/camera/star),
  cream **label plates** (`rgb(243,237,223)`), and optional pinned photo thumbnails.
- **Water**: muted slate-blue lakes (`rgb(104,128,134)`), thin rivers.
- **Current chrome palette** (style.css): ink `#2b2a28`, paper `#efeae0`, gold accent
  `#c7a955`, dark header `#1a1a1c`, Georgia serif. Treat these as a starting point —
  Claude Design should elevate them, but stay in the warm/earthy/gold family.

## The flow (one screen, progressive)

`pick region → drop tracks → (name/icon/photo markers) → drag a crop → proof → accept → download`

It is currently a single page (`app/static/index.html`) with a controls strip, a large
aim canvas, and a side column. A guided left-to-right **stepper** is a fair thing to
explore in Wireframe if we want more hand-holding.

## Surfaces & states

### 1. Region picker
- **Shows**: a gallery of region cards (overview thumbnail + name). Only appears when
  more than one region exists; a single-region install skips it and just labels the
  header. The selected card is highlighted (gold border).
- **Actions**: click a card to choose the region (or skip — the backend auto-detects
  from the dropped track). After upload, the bound region is reflected back.
- **Data/API**: `GET /api/regions` → `[{id, name, overview, overview_size, bounds, lonlat_bbox}]`.

### 2. Upload / drop zone
- **Shows**: a dashed drop target ("Drop GPX / KML / KMZ — files accumulate") + a running
  file list.
- **States**: idle · drag-over (highlight) · uploading · error ("No usable tracks").
- **Actions**: drag-drop or click-to-browse; multiple files accumulate into one session.
- **Data/API**: `POST /api/upload` (multipart `files[]`, optional `region_id`, optional
  `session_id`) → `{session, region, name, overview, overview_size, tracks[], hotspots[]}`.

### 3. Aim canvas
- **Shows**: the region overview image, the uploaded **tracks** drawn over it, **hotspot**
  dots, and a **crop rectangle** the user drags.
- **Key constraint**: the crop is **locked to the selected print aspect ratio** (drag sets
  width; height is derived). The crop also can't be too tight — see zoom cap below.
- **Actions**: mouse-drag to draw/resize the crop box.

### 4. Marker editor (rich markers)
- **Shows**: one row per hotspot — a color dot, a **label** text field, an **icon**
  dropdown (`dot/peak/camp/water/flag/camera/star`), and a **photo** button (📷, lights up
  gold when a photo is attached).
- **States**: empty (hidden until tracks load) · edited ("re-render the proof to see them").
- **Actions**: edit label, pick icon, attach photo. Any edit invalidates the stamped
  proof (you must re-proof before the final reflects it).
- **Data/API**: `POST /api/markers` (`session_id`, `markers` JSON `[{i,label,icon}]`);
  `POST /api/photo` (`session_id`, `i`, `file`).

### 5. Print size + actions
- **Shows**: a print-size `<select>` (18×24, 24×36, 12×16, 9×12), and three buttons —
  **Render proof**, **Accept & render final**, **Clear**.
- **States**: buttons disable until their precondition is met (proof needs a crop; accept
  needs a successful proof).

### 6. Proof pane
- **Shows**: the rendered **proof** image (96 dpi, watermarked "PROOF").
- **States**: empty · rendering · ready · rejected (see zoom cap).
- **Data/API**: `POST /api/proof` (`session_id`, `x0,y0,x1,y1`, `print_w`, `print_h`) →
  PNG. The crop is stamped into a spec; the final renders from that exact spec.

### 7. Final render (async)
- **Shows**: progress while a background worker paints the 300 dpi poster, then a download.
- **Flow/API**: `POST /api/final/submit` → `{job}`; poll `GET /api/jobs/{id}`
  (`queued|running|done|error`); when `done`, download from `GET /api/jobs/{id}/result`.
- A synchronous `POST /api/final` also exists for simple callers.

## Error/edge states the design must handle

- **Zoom too tight (422)**: a crop finer than the data resolution (10 m/px at 300 dpi) is
  rejected at proof time. Needs a clear inline message ("zoomed in too far — widen the crop
  or pick a smaller print").
- **Re-proof required (400)**: after changing tracks or markers, the final is blocked until
  a fresh proof is approved.
- **Unknown/expired session (404)**, **no usable tracks (400)**, **unknown region (404)**.
- **One bad file in a batch** is skipped silently; the good ones still load.

## Implementation notes for the round-trip

- Current frontend is **vanilla JS** (`app/static/app.js`, ~200 lines) over plain `fetch`.
  No build step.
- If Claude Design outputs **React + Tailwind** (likely): we're open to adopting it. The
  backend is pure JSON endpoints, so a framework swap touches only `app/static/` (and the
  StaticFiles mount, or a dev proxy). See the migration note the team will attach.
- Things Claude Design **cannot** reproduce and should treat as behavior-only: the canvas
  crop interaction, the live relief render, and the proof/final job polling. Design the
  *appearance*; the wiring stays in code.

## Framework migration note (if Claude Design leans React/Tailwind)

Claude Design commonly emits **React + Tailwind** (often shadcn/ui). We're open to adopting
it. Recommended target if so:

- **React + Vite + Tailwind** SPA living in `frontend/` (or replacing `app/static/`), talking
  to the unchanged FastAPI JSON endpoints. In dev, Vite proxies `/api` to uvicorn; in prod,
  FastAPI serves the built bundle via the existing `StaticFiles` mount.
- The current logic ports directly: `useRef` for the aim canvas, `useState` for
  session/crop/markers/region, plain `fetch` for the endpoints, and the job-poll loop as a
  small `useEffect`/async helper. The backend is untouched — a framework swap only touches the
  frontend.
- This is a contained migration; do it **after** the design is finalized, not before.

If Claude Design instead outputs plain HTML/CSS, no migration is needed — we port the visual
design (layout, palette, type, spacing, components) straight into the existing
`index.html`/`style.css`. Either way, the API contracts above are the stable foundation.
