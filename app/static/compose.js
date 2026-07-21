// compose.js — the Compose section: the map workspace (frame + place markers), the page
// setup controls (output / size / bleed / device / orientation / title), and the upload
// and continue-a-poster flows. This is the old app.js "tracks + frame" engine, preserved
// in its load-bearing details (auto-orientation before the starter crop, the reframe →
// refit → feasibility chain, the loud upload boundaries, the continue-restore prefill)
// and adapted to the studio: no linear stepper, a map-mode toggle instead of steps, and
// all reflection driven by the store.
import { state, savePref, loadPrefs, activePreset, trackAspectIsWide } from './store.js';
import * as api from './api.js';
import * as canvas from './canvas.js';
import * as markers from './markers.js';
import * as proof from './proof.js';
import * as inspector from './inspector.js';
import * as create from './create.js';
import { $, wireSegmented, toast, announce } from './ui.js';

let hooks = {};                 // { onLoaded(kind), refresh() } provided by app.js
let segOutput = null, segOrient = null;

export function initCompose(h = {}) {
  hooks = h;
  canvas.init($('map'), {
    onCropChange: () => { stalePicture(); markers.refreshOutOfFrame(); proof.scheduleAutoProof(); proof.refreshProofUI(); },
    onMarkerMoved: () => { stalePicture(); markers.refreshOutOfFrame(); proof.scheduleAutoProof(); proof.refreshProofUI(); announce('Marker moved'); },
    onDragTip: () => showHint('Tip: drag a gold dot to reposition that place'),
    onRenderProof: () => proof.renderProof(),
    announce,
  });

  // dropzone + file input + drag-drop onto the map
  const dz = $('dropzone'), fi = $('fileInput');
  dz.onclick = () => fi.click();
  $('addFiles').onclick = () => fi.click();
  fi.onchange = (e) => { doUpload(e.target.files); e.target.value = ''; };
  const pi = $('posterInput');
  pi.onchange = (e) => { continueFromPoster(e.target.files[0]); e.target.value = ''; };
  $('continuePoster').onclick = () => pi.click();
  const mapPane = $('mapPane');
  mapPane.addEventListener('dragover', (e) => { e.preventDefault(); dz.classList.add('over'); });
  mapPane.addEventListener('dragleave', () => dz.classList.remove('over'));
  mapPane.addEventListener('drop', (e) => { e.preventDefault(); e.stopPropagation(); dz.classList.remove('over'); doUpload(e.dataTransfer.files); });

  // map mode: drag the frame, or drag a marker dot
  $('mapModeTracks').onclick = () => setMapMode('tracks');
  $('mapModeFrame').onclick = () => setMapMode('frame');
  $('resetFrame').onclick = () => { canvas.resetFrame(); markers.refreshOutOfFrame(); updateFrameFeasibility(); };

  // page setup controls
  segOutput = wireSegmented($('outputField').querySelector('.segmented'), (v) => {
    state.output = v; savePref('output', v); applyOutputVisibility(); reframe(); hooks.refresh && hooks.refresh();
  });
  segOrient = wireSegmented($('orientField').querySelector('.segmented'), (v) => {
    state.orientation = v; savePref('orient', v); reframe();
  });
  $('size').onchange = (e) => { savePref('printSize', e.target.value); reframe(); };
  $('bleed').oninput = (e) => {
    state.style.bleedIn = parseFloat(e.target.value) || 0;
    $('bleedVal').textContent = state.style.bleedIn ? `${state.style.bleedIn.toFixed(3).replace(/0+$/, '').replace(/\.$/, '')} in` : 'None';
    stalePicture(); proof.scheduleAutoProof(); proof.refreshProofUI();
  };
  $('wpPreset').onchange = (e) => { state.wpPreset = e.target.value; savePref('wpPreset', e.target.value); applyOutputVisibility(); reframe(); };
  const readCustom = () => {
    const w = Math.round(Number($('customPxW').value) || 0);
    const h = Math.round(Number($('customPxH').value) || 0);
    const ppi = Number($('customPpi').value) || 0;
    state.customDevice = w > 0 && h > 0 && ppi > 0 ? { px: [w, h], ppi } : null;
    if (state.wpPreset === 'custom') reframe();
  };
  for (const id of ['customPxW', 'customPxH', 'customPpi']) $(id).oninput = readCustom;
  $('titleInput').oninput = (e) => { state.title = e.target.value; stalePicture(); proof.scheduleAutoProof(); proof.refreshProofUI(); };

  restorePagePrefs();
}

function stalePicture() { if (state.hasSpec) state.proofStale = true; }

// The top-bar target switcher drives the composition's output kind through here, so
// the segmented face, prefs, field visibility, and the reframe chain stay one code path.
export function setOutput(v) {
  if (state.output === v) return;
  state.output = v; savePref('output', v);
  segOutput && segOutput.reflect(v);
  applyOutputVisibility();
  reframe();
  hooks.refresh && hooks.refresh();
}
function showHint(text) { const h = $('hint'); if (!h) return; h.textContent = text; h.hidden = !text; }

function setMapMode(m) {
  canvas.setMode(m);
  $('mapModeTracks').classList.toggle('on', m === 'tracks');
  $('mapModeFrame').classList.toggle('on', m === 'frame');
  if (m === 'frame') { markers.refreshOutOfFrame(); updateFrameFeasibility(); showHint('Drag to draw a frame · arrow keys nudge it · Reset to recenter'); }
  else showHint('Drag a gold dot to reposition a place');
}

// Called by app.js when the Compose section becomes active: seed the frame + feasibility.
export function enterCompose() {
  if (!state.tracks.length) return;
  $('mapMode').hidden = false;
  applyPrintSize(); applyOutputVisibility();
  setMapMode('frame');
  updateFrameFeasibility();
}

// ---- page geometry (ported verbatim from app.js) ----------------------------------
export function applyPrintSize() {
  if (state.output === 'wallpaper') {
    const p = activePreset();
    if (p) { state.printW = p.px[0] / p.ppi; state.printH = p.px[1] / p.ppi; }
    return;
  }
  const [a, b] = $('size').value.split(',').map(Number);
  const landscape = state.orientation === 'auto' ? trackAspectIsWide() : state.orientation === 'landscape';
  state.printW = landscape ? Math.max(a, b) : Math.min(a, b);
  state.printH = landscape ? Math.min(a, b) : Math.max(a, b);
}

export function applyOutputVisibility() {
  const wp = state.output === 'wallpaper';
  $('sizeField').hidden = wp;
  $('bleedField').hidden = wp;
  $('wpPresetField').hidden = !wp;
  $('customDeviceField').hidden = !(wp && state.wpPreset === 'custom');
  $('orientField').hidden = wp;
  $('titleField').hidden = wp;
}

function reframe() {
  applyPrintSize();
  canvas.refitForSize(); markers.refreshOutOfFrame(); updateFrameFeasibility();
  stalePicture(); proof.scheduleAutoProof(); proof.refreshProofUI();
}

export function updateFrameFeasibility() {
  const infeasible = canvas.sizeInfeasibleForRegion();
  proof.refreshProofUI();
  if (infeasible) toast(`This region is too small for ${proof.sizeLabel()} — pick a smaller size.`, 'error');
}

function ensurePrintSize(w, h) {
  if (!w || !h) return;
  const mn = Math.min(w, h), mx = Math.max(w, h);
  const fmt = (n) => (Number.isInteger(n) ? String(n) : String(Math.round(n * 100) / 100));
  const val = `${fmt(mn)},${fmt(mx)}`;
  const sel = $('size');
  if (![...sel.options].some((o) => o.value === val)) {
    const o = document.createElement('option');
    o.value = val; o.textContent = `${fmt(mn)} × ${fmt(mx)} in`;
    sel.appendChild(o);
  }
  sel.value = val;
  state.orientation = w > h ? 'landscape' : 'portrait';
  segOrient && segOrient.reflect(state.orientation);
}

function restorePagePrefs() {
  const prefs = loadPrefs();
  if (prefs.printSize && [...$('size').options].some((o) => o.value === prefs.printSize)) $('size').value = prefs.printSize;
  if (['auto', 'landscape', 'portrait'].includes(prefs.orient)) state.orientation = prefs.orient;
  if (!state.wpPresets.length) { $('outputField').hidden = true; }
  else if (prefs.output === 'wallpaper' || prefs.output === 'print') state.output = prefs.output;
  segOutput && segOutput.reflect(state.output);
  segOrient && segOrient.reflect(state.orientation);
  applyPrintSize(); applyOutputVisibility();
}

// ---- region selection -------------------------------------------------------------
export function selectRegion(id) {
  state.region = id;
  const meta = state.regions.find((r) => r.id === id);
  state.regionName = meta ? meta.name : '';
  $('regionName').textContent = state.regionName;
  for (const el of document.querySelectorAll('.region-card')) el.classList.toggle('sel', el.dataset.id === id);
}

// ---- upload ----------------------------------------------------------------------
export async function doUpload(fileList) {
  const arr = Array.from(fileList || []);
  if (!arr.length) return;
  toast(`Uploading ${arr.length} file(s)…`, 'working');
  try {
    const j = await api.upload(arr, { sessionId: state.session, regionId: state.region });
    state.session = j.session;
    if (j.region !== state.region) selectRegion(j.region);
    state.regionName = j.name; $('regionName').textContent = j.name || '';
    // Reveal chip: an existing plate covered these tracks -> "Matched". Don't clobber a
    // "Built" set by the creation flow's re-upload (or on further adds this session) — a
    // plate built this session stays "Built" until Start Over resets the chip.
    if (state.regionKind !== 'Built') state.regionKind = 'Matched';
    state.ovSize = j.overview_size; state.tracks = j.tracks; state.hotspots = j.hotspots;
    state.trackDays = j.track_days || [];
    state.starterCrop = j.starter_crop; state.crop = null;
    state.hasSpec = false; state.proofStale = true;
    if (j.final_dpi) state.finalDpi = j.final_dpi;
    savePref('region', j.region);
    const skipped = j.skipped_duplicates || [];
    const skippedSet = new Set(skipped);
    arr.forEach((f) => { if (!skippedSet.has(f.name)) state.files.push(f.name); });
    renderFiles();
    state.journeyLight = j.journey_light || null;
    canvas.setOverview(j.overview, j.overview_size);
    $('dropzone').hidden = true; $('continuePoster').hidden = true;
    $('map').hidden = false; $('addFiles').hidden = false;
    markers.render($('markerList'), (msg) => toast(msg, 'info'));
    hooks.onLoaded && hooks.onLoaded('upload');
    enterCompose();
    const boundary = [];
    if (j.dropped_points) boundary.push(`${j.dropped_points} point${j.dropped_points === 1 ? '' : 's'} outside the plate's map projection — dropped`);
    if (j.journeys_outside_plate) boundary.push(`${j.journeys_outside_plate} of ${j.tracks.length} journeys extend beyond the plate and won't fully appear`);
    if (j.recovered) {
      const note = boundary.length ? ` (${boundary.join('; ')})` : '';
      showHint(`These tracks are in ${j.name} — switched to that region`);
      toast(`Switched to ${j.name} — the dropped tracks belong to that region.${note}`, 'info');
      announce(`Switched region to ${j.name}`);
    } else {
      showHint('Your tracks are on the map — gold dots mark places you returned to most');
      const dupTracks = j.skipped_duplicate_tracks || 0;
      const parts = [];
      if (skipped.length) parts.push(`${skipped.length} file(s) already added`);
      if (dupTracks) parts.push(`${dupTracks} track(s) already on the poster`);
      const notes = [];
      if (parts.length) notes.push(`${parts.join(', ')} — skipped`);
      notes.push(...boundary);
      const dupNote = notes.length ? ` (${notes.join('; ')})` : '';
      toast(`${state.tracks.length} track(s) across ${state.files.length} file(s)${dupNote} — frame it, then render a proof.`, 'ok');
    }
  } catch (e) {
    // GPX-first: "no built plate covers these tracks" is the COMMON case, not an error.
    // Hand the kept File[] to the creation flow, which offers to build a plate for them.
    // ApiError still carries .status and .message, so the old wizard's check ports as-is.
    if (e.status === 422 && /any available region/.test(e.message || '')) {
      create.enterCreationFlow(arr);
    } else {
      toast('Upload failed: ' + e.message, 'error');
    }
  }
}

function renderFiles() {
  const el = $('fileList');
  el.innerHTML = '';
  for (const n of state.files) { const li = document.createElement('li'); li.textContent = n; el.appendChild(li); }
}

// ---- continue a poster (living editions) -----------------------------------------
export async function continueFromPoster(file) {
  if (!file) return;
  toast('Opening poster…', 'working');
  try {
    const j = await api.continuePoster(file);
    state.session = j.session;
    selectRegion(j.region);
    state.regionName = j.name; $('regionName').textContent = j.name || '';
    state.regionKind = 'Matched';   // a continued poster reopens an existing plate
    state.ovSize = j.overview_size; state.tracks = j.tracks; state.hotspots = j.hotspots;
    state.trackDays = j.track_days || [];
    state.starterCrop = j.starter_crop; state.crop = null;
    state.hasSpec = false; state.proofStale = true;
    if (j.final_dpi) state.finalDpi = j.final_dpi;
    state.edition = j.edition || 2;
    state.yearSpan = j.year_span || '';
    state.files = (j.files || []).slice();
    applyPrefill(j.prefill);
    renderFiles();
    state.journeyLight = j.journey_light || null;
    canvas.setOverview(j.overview, j.overview_size);
    $('dropzone').hidden = true; $('continuePoster').hidden = true;
    $('map').hidden = false; $('addFiles').hidden = false;
    markers.render($('markerList'), (msg) => toast(msg, 'info'));
    hooks.onLoaded && hooks.onLoaded('continue');
    enterCompose();
    const echo = [`Edition ${state.edition}`, j.name, j.year_span].filter(Boolean).join(' · ');
    showHint(`${echo} — ready to add this year. Drop this year's GPX, then reframe and render.`);
    toast(`${echo} — ${state.tracks.length} track(s) restored, ready to add this year.`, 'ok');
    announce(`Continuing poster as edition ${state.edition}`);
  } catch (e) { toast('Could not open that poster: ' + e.message, 'error'); }
}

// Restore a continued poster's recipe into state, then reflect it everywhere at once.
function applyPrefill(p) {
  if (!p) return;
  state.title = p.title || '';
  state.contours = !!p.contours;
  state.compass = p.compass !== false;
  state.biome = !!p.biome;
  state.labels = !!p.labels;
  const s = p.style || {};
  Object.assign(state.style, {
    width: s.width ?? state.style.width, halo: s.halo ?? state.style.halo, color: s.color || '',
    marker: s.marker ?? state.style.marker, ring: s.ring ?? state.style.ring,
    photoStyle: s.photoStyle || 'mat', furniture: s.furniture ?? state.style.furniture,
    terrain: s.terrain ?? state.style.terrain, shadow: s.shadow ?? state.style.shadow, oblique: s.oblique ?? 0,
    lightMode: s.lightMode || 'archival', sunAzimuth: s.sunAzimuth ?? null, sunAltitude: s.sunAltitude ?? null,
    sunHour: null, golden: s.golden ?? 0.7, profile: !!s.profile, profileHeight: s.profileHeight ?? 0.9,
    profileRev: s.profileRev ?? 1, bleedIn: s.bleed ?? 0, trackColorBy: s.trackColorBy || 'none',
    labelPlace: s.labelPlace || 'anchor', trackWeave: !!s.trackWeave,
  });
  $('titleInput').value = state.title;
  $('bleed').value = String(state.style.bleedIn || 0);
  $('bleedVal').textContent = state.style.bleedIn ? `${state.style.bleedIn} in` : 'None';
  // output kind + sheet
  if (p.output === 'wallpaper' && p.wallpaper_preset && state.wpPresets.length) {
    state.output = 'wallpaper'; $('wpPreset').value = p.wallpaper_preset; state.wpPreset = p.wallpaper_preset;
    if (p.wallpaper_preset === 'custom' && p.custom_device) {
      state.customDevice = { px: p.custom_device.px.slice(), ppi: p.custom_device.ppi };
      $('customPxW').value = state.customDevice.px[0];
      $('customPxH').value = state.customDevice.px[1];
      $('customPpi').value = state.customDevice.ppi;
    }
  } else {
    state.output = 'print';
    ensurePrintSize(p.print_w_in, p.print_h_in);
  }
  segOutput && segOutput.reflect(state.output);
  applyOutputVisibility();
  inspector.reflectAll();   // Style/Layers/Light panels re-reflect the restored recipe
}

// Re-sync the static page controls (title, bleed, output, orientation, size, device)
// from the store — called on a bulk state change (preset apply, continue-restore) that
// the registry-driven inspector can't reach.
export function reflectStatic() {
  const t = $('titleInput'); if (t) t.value = state.title || '';
  const bl = $('bleed'); if (bl) bl.value = String(state.style.bleedIn || 0);
  const bv = $('bleedVal'); if (bv) bv.textContent = state.style.bleedIn ? `${state.style.bleedIn} in` : 'None';
  segOutput && segOutput.reflect(state.output);
  segOrient && segOrient.reflect(state.orientation);
  applyOutputVisibility();
}

// Journey Light availability for the Light panel: enable the toggle when a track is
// timestamped (or a continued poster restored an explicit sun); else disable with a note.
export function updateLightAvailability() {
  const chk = $('c_lightMode');
  if (!chk) return;
  const meta = state.journeyLight;
  const restorable = state.style.sunAzimuth != null;
  const available = !!(meta && meta.available) || restorable;
  chk.disabled = !available;
  if (!available && state.style.lightMode === 'journey') {
    state.style.lightMode = 'archival'; chk.checked = false;
  }
}
