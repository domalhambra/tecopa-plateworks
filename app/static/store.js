// store.js — the single source of truth for the studio, plus localStorage prefs.
//
// This is state.js grown up. The `state` object keeps its exact original shape (so
// canvas.js and markers.js, which import specific fields and derived helpers, keep
// working untouched through the state.js re-export shim). What's new is the mutation
// discipline: every user edit flows through setField(), which is the ONE place the
// stale-proof guard lives. The old code scattered ~20 hand-written
// `if (state.hasSpec) state.proofStale = true` lines across app.js; forgetting one on
// a new control silently shipped a stale spec to the final render. Now a control just
// declares `affectsProof` in controls.js and the choke-point can never forget.
export const state = {
  // single-window router (replaces the old section rail): which output target the
  // studio is presenting (poster | wallpaper | film | social) and, for the sheet
  // targets, whether the center stage shows the map workspace or the proof preview.
  target: 'poster',
  view: 'map',            // 'map' | 'preview' (poster/wallpaper targets only)
  hintDismissed: false,   // the "controls apply once tracks land" sidebar hint
  guided: false,
  session: null,
  region: null,
  regionName: '',
  regionKind: '',         // reveal chip beside the region name: '' | 'Matched' (an existing
                          // plate covered the tracks) | 'Built' (created this session)
  regions: [],            // /api/regions metadata (id,name,bounds,overview_size,native_resolution_m,overview)
  ovSize: null,           // [w, h] overview pixels of the active region
  scale: 1,               // canvas px per overview px
  tracks: [],             // polylines in overview px
  trackDays: [],          // per-track day index (from /api/upload|continue); year-span source
  hotspots: [],           // [{px:[ovx,ovy], weight, label, icon, photo}]
  crop: null,             // [x0,y0,x1,y1] in CANVAS px (Frame step)
  starterCrop: null,      // [x0,y0,x1,y1] in OVERVIEW px (from /api/upload)
  printW: 18,
  printH: 24,
  orientation: 'auto',    // 'auto' (tracks decide) | 'landscape' | 'portrait'
  output: 'print',        // 'print' | 'wallpaper' (a screen is a sheet with a known ppi)
  wpPresets: [],          // /api/wallpapers/presets metadata (id,name,px,ppi,device_class,*_clear_frac)
  wpPreset: '',           // active device preset id (wallpaper mode); 'custom' = bespoke
  customDevice: null,     // { px:[w,h], ppi } when wpPreset === 'custom' (the escape hatch)
  finalDpi: 300,          // print final resolution, served by /api/upload|continue --
                          // the server's truth, never assumed (mirrors spec.FINAL_DPI)
  bundlePicks: [],        // preset ids ticked in the bundle / social kit card
  tlFrames: 40,           // time-lapse frame count
  tlStepMs: 220,          // per-frame hold while journeys ink (server default)
  tlHoldMs: 2500,         // final-frame hold before the film loops
  tlLeaderMs: 700,        // opening hold on the empty terrain
  tlTarget: '',           // '' = accepted sheet; else a wallpaper/social preset id
  tlFormat: 'apng',       // film container: 'apng' (archival) | 'webp' | 'mp4' (share)
  hasSpec: false,         // a proof has been stamped this session
  proofStale: false,      // an edit since the last proof (marker/crop/style change)
  files: [],              // uploaded filenames (accumulating)
  edition: 1,             // living editions: 1 = a fresh poster; >=2 = continued
  yearSpan: '',           // human year span echoed by continue ("2021–2024")
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
    profileRev: null,     // strip layout rev; null = omit -> server default (2, corrected
                          // strip). A continued poster sets this to its own stored rev.
    bleedIn: 0,           // print-shop bleed (inches); 0 = none. Print-only; a continued
                          // poster restores its own value.
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
  autoProof: true,        // live-proofing: re-proof on settle after a picture edit
};

const LS_KEY = 'tecopa';       // { region, printSize, orient, theme, finalFormat, autoProof, stylePresets }
const LS_KEY_OLD = 'trailprint';   // the pre-"Tecopa Plateworks" key; migrated once on read

export function loadPrefs() {
  try {
    const cur = localStorage.getItem(LS_KEY);
    if (cur) return JSON.parse(cur) || {};
    // one-time migration from the pre-rebrand key so a returning operator keeps their
    // theme / region / print size / saved presets. Copy across, then read the new key
    // from here on; the old key lingers harmlessly. MUST stay in sync with the pre-paint
    // fallback in index.html/help.html, or a partial rename orphans saved prefs.
    const old = localStorage.getItem(LS_KEY_OLD);
    if (old) { localStorage.setItem(LS_KEY, old); return JSON.parse(old) || {}; }
    return {};
  } catch { return {}; }
}
export function savePref(k, v) {
  const p = loadPrefs(); p[k] = v;
  try { localStorage.setItem(LS_KEY, JSON.stringify(p)); } catch { /* private mode */ }
}

// --- mutation choke-point + pub/sub -------------------------------------------------
// controls.js registers which dotted paths are picture decisions; setField consults
// that set so the stale-proof rule is declared once, per control, and never forgotten.
const proofAffectingPaths = new Set();
export function markProofPaths(paths) { for (const p of paths) proofAffectingPaths.add(p); }

const subscribers = new Set();
// subscribe(fn) -> unsubscribe. fn is called with (path, value) after every setField
// and with (null) after applySnapshot, so panels/inspectors can re-reflect state.
export function subscribe(fn) { subscribers.add(fn); return () => subscribers.delete(fn); }
function notify(path, value) { for (const fn of subscribers) { try { fn(path, value); } catch { /* isolate */ } } }

function readPath(path) {
  const dot = path.indexOf('.');
  return dot < 0 ? state[path] : state[path.slice(0, dot)]?.[path.slice(dot + 1)];
}
function writePath(path, value) {
  const dot = path.indexOf('.');
  if (dot < 0) state[path] = value;
  else state[path.slice(0, dot)][path.slice(dot + 1)] = value;
}

// The single mutation entry point for user edits. Writes the value, stales the proof
// when the path is a picture decision and a spec is already stamped, and notifies
// subscribers. `opts.proof` forces the stale decision (used by bulk applySnapshot so a
// preset/variant swap always re-proofs); `opts.silent` skips notification (batching).
export function setField(path, value, opts = {}) {
  writePath(path, value);
  const affects = opts.proof ?? proofAffectingPaths.has(path);
  if (affects && state.hasSpec) state.proofStale = true;
  if (!opts.silent) notify(path, value);
  return value;
}

// A snapshot of every picture decision (the paths a preset/variant/history entry can
// carry). Used by presets, A/B variants, and the proof-history filmstrip. Deliberately
// excludes geometry (crop/print size) and session identity — a look is portable, a
// frame is not.
const SNAPSHOT_PATHS = [
  'title', 'contours', 'compass', 'biome', 'labels',
  'style.width', 'style.halo', 'style.color', 'style.marker', 'style.ring',
  'style.photoStyle', 'style.furniture', 'style.terrain', 'style.shadow', 'style.oblique',
  'style.lightMode', 'style.sunHour', 'style.golden', 'style.profile', 'style.profileHeight',
  'style.trackColorBy', 'style.labelPlace', 'style.trackWeave',
];
export function snapshotPaths() { return SNAPSHOT_PATHS.slice(); }

export function snapshot(paths = SNAPSHOT_PATHS) {
  const snap = {};
  for (const p of paths) snap[p] = readPath(p);
  return snap;
}

// Apply a bulk set of picture decisions (a preset or a restored variant). Every field
// goes through the write path with proof:true so the accept gate always forces a fresh
// re-proof of the chosen look — a stale variant can never reach /api/final (the server
// holds exactly one stamped spec).
export function applySnapshot(snap) {
  for (const [p, v] of Object.entries(snap)) {
    if (v === undefined) continue;
    writePath(p, v);
  }
  if (state.hasSpec) state.proofStale = true;
  notify(null, null);
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

// The active wallpaper preset's metadata (null when none / print mode). A custom
// device synthesizes the same shape from state.customDevice, so every consumer
// (applyPrintSize, finalWidthPx, sizeLabel) treats it exactly like a table preset --
// null until all three fields are filled, which keeps the proof gate honest.
export function activePreset() {
  if (state.wpPreset === 'custom') {
    const c = state.customDevice;
    return c && c.px && c.px[0] > 0 && c.px[1] > 0 && c.ppi > 0
      ? { id: 'custom', name: `Custom ${c.px[0]}×${c.px[1]}`, px: c.px, ppi: c.ppi,
          device_class: 'custom', top_clear_frac: 0, bottom_clear_frac: 0 }
      : null;
  }
  return state.wpPresets.find((p) => p.id === state.wpPreset) || null;
}

// The FINAL's output width in pixels -- what the zoom-cap floor is judged against.
// Prints render at the server-served final dpi; a wallpaper renders the device's
// exact native pixels. Every client-side floor check keys on this, so neither mode
// assumes a resolution the server didn't state (the old hardcoded 300 could drift).
export function finalWidthPx() {
  if (state.output === 'wallpaper') {
    const p = activePreset();
    if (p) return p.px[0];
  }
  return Math.round(state.printW * state.finalDpi);
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

// Total ground distance of all loaded tracks, in metres (isotropic overview px).
// Feeds the Social caption helper's "N miles across M journeys" line.
export function totalTrackMetres() {
  const mpp = metresPerPx();
  if (!mpp) return 0;
  let m = 0;
  for (const t of state.tracks) {
    for (let i = 1; i < t.length; i++) {
      m += Math.hypot(t[i][0] - t[i - 1][0], t[i][1] - t[i - 1][1]) * mpp;
    }
  }
  return m;
}
