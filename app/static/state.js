// state.js — the single source of truth for the wizard plus localStorage prefs.
// Every module imports `state`; only app.js mutates `state.step`.
export const state = {
  step: 'tracks',
  steps: ['region', 'tracks', 'frame', 'proof'],
  session: null,
  region: null,
  regionName: '',
  regions: [],            // /api/regions metadata (id,name,bounds,overview_size,native_resolution_m,overview)
  ovSize: null,           // [w, h] overview pixels of the active region
  scale: 1,               // canvas px per overview px
  tracks: [],             // polylines in overview px
  hotspots: [],           // [{px:[ovx,ovy], weight, label, icon, photo}]
  crop: null,             // [x0,y0,x1,y1] in CANVAS px (Frame step)
  starterCrop: null,      // [x0,y0,x1,y1] in OVERVIEW px (from /api/upload)
  printW: 18,
  printH: 24,
  hasSpec: false,         // a proof has been stamped this session
  proofStale: false,      // an edit since the last proof (marker/crop change)
  files: [],              // uploaded filenames (accumulating)
  title: '',              // poster title ('' -> region name; '-' -> no title block)
  contours: false,        // elevation contour lines
  compass: true,          // compass rose above the title block
  finalFormat: 'png',     // final deliverable: 'png' | 'pdf'
  lastFinal: null,        // { url, fmt } of the last completed final (re-download)
};

const LS_KEY = 'trailprint';   // { region, printSize, theme }

export function loadPrefs() {
  try { return JSON.parse(localStorage.getItem(LS_KEY)) || {}; } catch { return {}; }
}
export function savePref(k, v) {
  const p = loadPrefs(); p[k] = v;
  try { localStorage.setItem(LS_KEY, JSON.stringify(p)); } catch { /* private mode */ }
}

// The metadata for the currently-bound region (null before a region is chosen).
export function activeRegion() {
  return state.regions.find((r) => r.id === state.region) || null;
}

// Ground metres per overview pixel for the active region. The overview is built
// (near-)isotropic, so one scale serves both axes; the zoom-cap check uses it to
// translate a pixel crop width into ground metres.
export function metresPerPx() {
  const r = activeRegion();
  if (!r || !r.overview_size) return null;
  const [minx, , maxx] = r.bounds;
  return (maxx - minx) / r.overview_size[0];
}

// The current crop expressed in OVERVIEW px (ordered), or null. Shared by the
// canvas (proof request) and markers (out-of-frame cue) so both agree on geometry.
export function cropOverviewPx() {
  if (!state.crop || !state.scale) return null;
  const s = state.scale;
  const [a, b, c, d] = state.crop;
  return [Math.min(a, c) / s, Math.min(b, d) / s, Math.max(a, c) / s, Math.max(b, d) / s];
}
