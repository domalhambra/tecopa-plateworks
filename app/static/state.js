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
  orientation: 'auto',    // 'auto' (tracks decide) | 'landscape' | 'portrait'
  output: 'print',        // 'print' | 'wallpaper' (a screen is a sheet with a known ppi)
  wpPresets: [],          // /api/wallpapers/presets metadata (id,name,px,ppi,device_class)
  wpPreset: '',           // active device preset id (wallpaper mode)
  bundlePicks: [],        // preset ids ticked in the post-proof bundle card
  tlFrames: 40,           // time-lapse frame count
  tlTarget: '',           // '' = accepted sheet; else a wallpaper preset id
  tlFormat: 'apng',       // film container: 'apng' (archival) | 'webp' | 'mp4' (share)
  hasSpec: false,         // a proof has been stamped this session
  proofStale: false,      // an edit since the last proof (marker/crop change)
  files: [],              // uploaded filenames (accumulating)
  edition: 1,             // living editions: 1 = a fresh poster; >=2 = continued
  title: '',              // poster title ('' -> region name; '-' -> no title block)
  contours: false,        // elevation contour lines
  compass: true,          // compass rose above the title block
  biome: false,           // NLCD land-cover tint (forests green, desert sage-tan)
  labels: false,          // named geography (GNIS terrain + water names)
  style: {                // the Style panel's knobs (server defaults mirrored here)
    width: 2.6, halo: 0.7, color: '', marker: 0.24, ring: 0.09, photoStyle: 'mat',
    furniture: 1.0,       // multiplier on the automatic sheet-size furniture scale
    terrain: 1.0,         // multiplier on the scale-keyed terrain-depth pass
    shadow: 0.5,          // cast-shadow + sky-occlusion strength ("Blender relief")
    oblique: 0.0,         // High relief: plan-oblique stand-up terrain; 0 = flat sheet
    // Journey Light (v1.9): the poster lit by the hike's own sun.
    lightMode: 'archival', // 'archival' (region light) | 'journey' (the journey's sun)
    sunHour: null,        // time-of-day scrubber (local solar hour); null = summit light
    sunAzimuth: null, sunAltitude: null,  // explicit resolved sun (continue-restore path)
    golden: 0.7,          // warm/cool golden-hour grade amount (journey mode)
    profile: false,       // DEM-sampled elevation-profile furniture
    profileHeight: 0.9,
    trackColorBy: 'none', // 'none' | 'elevation' | 'grade' -- DEM-derived track ramp
    // Smart cartography (v1.10): new posters default to the enhanced look; old posters
    // reprint unchanged because the spec/manifest omit these at their pre-feature default.
    labelPlace: 'smart',  // 'anchor' (single centered position) | 'smart' (ring + route obstacle + leaders)
    trackWeave: true,     // chronological over/under weave where journeys cross (newest on top)
  },
  journeyLight: null,     // upload/continue meta: { available, date, sun } or null
  lightMotion: 'none',    // film: 'none' | 'auto' | 'diurnal' | 'seasonal'
  finalFormat: 'png',     // final deliverable: 'png' | 'pdf'
  embedSpec: true,        // embed the reprint manifest in the PNG (off = a share copy)
  lastFinal: null,        // { url, fmt } of the last completed final (re-download)
};

const LS_KEY = 'trailprint';   // { region, printSize, orient, theme, finalFormat }

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

// The active wallpaper preset's metadata (null when none / print mode).
export function activePreset() {
  return state.wpPresets.find((p) => p.id === state.wpPreset) || null;
}

// The FINAL's output width in pixels -- what the zoom-cap floor is judged against.
// Prints render at 300 dpi; a wallpaper renders the device's exact native pixels.
// Every client-side floor check keys on this, so wallpaper mode never inherits the
// print path's hardcoded 300.
export function finalWidthPx() {
  if (state.output === 'wallpaper') {
    const p = activePreset();
    if (p) return p.px[0];
  }
  return Math.round(state.printW * 300);
}

// True when the loaded tracks read wider than tall (overview px are isotropic, so
// the pixel bbox aspect IS the ground aspect). Drives 'auto' orientation: a wide
// journey lies down, a tall one stands up. False with no tracks (portrait default).
export function trackAspectIsWide() {
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  for (const t of state.tracks) for (const [x, y] of t) {
    if (x < x0) x0 = x; if (x > x1) x1 = x;
    if (y < y0) y0 = y; if (y > y1) y1 = y;
  }
  return x1 > x0 && (x1 - x0) > (y1 - y0);
}

// The current crop expressed in OVERVIEW px (ordered), or null. Shared by the
// canvas (proof request) and markers (out-of-frame cue) so both agree on geometry.
export function cropOverviewPx() {
  if (!state.crop || !state.scale) return null;
  const s = state.scale;
  const [a, b, c, d] = state.crop;
  return [Math.min(a, c) / s, Math.min(b, d) / s, Math.max(a, c) / s, Math.max(b, d) / s];
}
