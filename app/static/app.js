// app.js — the studio bootstrap + router. Shrunk from the old 1000-line wizard to the
// orchestrator: it loads regions/presets, builds the inspector panels once, wires the
// shell (rail, foot export controls, theme, palette, keyboard, drag-anywhere), and drives
// the section router. Every section's behaviour lives in its own module; this file only
// decides which surface + panel is showing and keeps the shell in sync with the store.
import { state, savePref, loadPrefs, markProofPaths, subscribe } from './store.js';
import * as api from './api.js';
import * as controls from './controls.js';
import * as inspector from './inspector.js';
import * as proof from './proof.js';
import * as jobs from './jobs.js';
import * as compose from './compose.js';
import * as library from './library.js';
import * as social from './social.js';
import * as films from './films.js';
import * as exportsCenter from './exports.js';
import * as presets from './presets.js';
import * as sunDial from './sunDial.js';
import { initPalette, open as openPalette } from './palette.js';
import { $, toast, wireSegmented, updateSaveFileNote, withTransition } from './ui.js';

const SURFACE = { library: 'surface-home', compose: 'surface-map', style: 'surface-proof',
  layers: 'surface-proof', light: 'surface-proof', social: 'surface-social',
  films: 'surface-proof', exports: 'surface-queue' };
const PANEL = { library: 'panel-library', compose: 'panel-compose', style: 'panel-style',
  layers: 'panel-layers', light: 'panel-light', social: 'panel-social',
  films: 'panel-films', exports: 'panel-exports' };
const TITLE = { library: 'Library', compose: 'Compose', style: 'Style', layers: 'Layers',
  light: 'Light', social: 'Social', films: 'Films', exports: 'Exports' };
const FOOT = new Set(['compose', 'style', 'layers', 'light']);
const PROOF_SECTIONS = new Set(['style', 'layers', 'light']);

// A section is reachable once its inputs exist: options need tracks; social/films need a
// stamped proof. Library/Compose/Exports are always open.
function ready(section) {
  if (['library', 'compose', 'exports'].includes(section)) return true;
  if (['style', 'layers', 'light'].includes(section)) return state.tracks.length > 0;
  if (['social', 'films'].includes(section)) return state.hasSpec;
  return true;
}

// ---- router ----------------------------------------------------------------------
function setSection(name) {
  if (!ready(name)) { toast(hintFor(name), 'info'); return; }
  withTransition(() => {
    state.section = name;
    for (const s of document.querySelectorAll('.surface')) s.hidden = s.id !== SURFACE[name];
    for (const p of document.querySelectorAll('.panel')) p.hidden = p.id !== PANEL[name];
    for (const b of document.querySelectorAll('.rail-item')) b.setAttribute('aria-current', b.dataset.section === name ? 'true' : 'false');
    $('inspectorTitle').textContent = TITLE[name];
    $('inspectorFoot').hidden = !FOOT.has(name);
    $('reframeBtn').hidden = !(state.hasSpec && PROOF_SECTIONS.has(name));
    $('formatField').hidden = state.output === 'wallpaper';

    if (name === 'compose') compose.enterCompose();
    else if (name === 'social') social.buildSocial();
    else if (name === 'films') films.buildFilms();
    else if (name === 'library') library.buildRegionGallery();
    if (PROOF_SECTIONS.has(name)) proof.refreshProofUI();

    focusHeading(name);
  });
  refreshRail();
}

function hintFor(name) {
  if (['style', 'layers', 'light'].includes(name)) return 'Drop your tracks in Compose first.';
  return 'Render and accept a proof to unlock this.';
}

function focusHeading(name) {
  const id = { library: 'h-home', exports: 'h-queue', social: 'h-social' }[name];
  const el = id && $(id); if (el) el.focus();
}

function refreshRail() {
  for (const b of document.querySelectorAll('.rail-item')) b.disabled = !ready(b.dataset.section);
}

// ---- shell sync ------------------------------------------------------------------
function refreshShell() {
  $('regionName').textContent = state.regionName || '';
  const eb = $('editionBadge');
  eb.hidden = state.edition < 2; eb.textContent = state.edition >= 2 ? `Edition ${state.edition}` : '';
  $('yearSpan').textContent = state.yearSpan || '';
  $('startOver').hidden = !(state.session || state.files.length);
  $('themeToggle').hidden = false;
  updateSaveFileNote();
  compose.updateLightAvailability();
  $('formatField').hidden = state.output === 'wallpaper';
  refreshRail();
  proof.refreshProofUI();
}

// ---- theme -----------------------------------------------------------------------
const currentScheme = () => document.documentElement.getAttribute('data-color-scheme') === 'light' ? 'light' : 'dark';
function applyTheme(scheme) {
  document.documentElement.setAttribute('data-color-scheme', scheme);
  const btn = $('themeToggle');
  (btn.querySelector('.tb-txt') || btn).textContent = scheme === 'light' ? 'Night' : 'Day';
  btn.setAttribute('aria-label', scheme === 'light' ? 'Switch to night theme' : 'Switch to day theme');
}
function toggleTheme() { const next = currentScheme() === 'light' ? 'dark' : 'light'; applyTheme(next); savePref('theme', next); }

// ---- start over ------------------------------------------------------------------
function startOver() {
  const hasWork = state.session || state.files.length;
  if (hasWork && !confirm('Start over? This clears the loaded tracks and framing (uploaded photos are kept until the session ends).')) return;
  const { regions, wpPresets } = state;
  Object.assign(state, {
    session: null, ovSize: null, scale: 1, tracks: [], trackDays: [], hotspots: [],
    crop: null, starterCrop: null, hasSpec: false, proofStale: false, files: [],
    edition: 1, yearSpan: '', title: '', lastFinal: null, journeyLight: null,
  });
  state.regions = regions; state.wpPresets = wpPresets;
  $('markerList').innerHTML = ''; $('markersBox').hidden = true; $('fileList').innerHTML = '';
  $('dropzone').hidden = false; $('map').hidden = true; $('addFiles').hidden = true;
  $('continuePoster').hidden = false; $('mapMode').hidden = true;
  $('posterImg').removeAttribute('src'); $('posterCard').hidden = true; $('proofEmpty').hidden = false;
  $('titleInput').value = ''; $('provenanceCard').hidden = true;
  inspector.reflectAll(); compose.reflectStatic();
  refreshShell();
  setSection('library');
  toast('Cleared — pick a region and drop files to start a new map.', 'info');
}

// ---- inspector panels (built once) -----------------------------------------------
function buildPanels() {
  // Style: presets bar + the registry controls
  const ps = $('panel-style');
  const pg = document.createElement('section'); pg.className = 'insp-group';
  pg.innerHTML = '<div class="insp-head"><span class="insp-title">Presets</span></div><div id="stylePresets"></div>';
  const sc = document.createElement('div');
  ps.append(pg, sc);
  inspector.buildSectionPanel('style', sc);
  presets.renderInto($('stylePresets'), { onApply: () => { inspector.reflectAll(); compose.reflectStatic(); proof.refreshProofUI(); } });

  inspector.buildSectionPanel('layers', $('panel-layers'));

  // Light: the registry controls, then the sun dial
  const pl = $('panel-light');
  const ctl = document.createElement('div');
  const dialGroup = document.createElement('section'); dialGroup.className = 'insp-group';
  dialGroup.innerHTML = '<div class="insp-head"><span class="insp-title">Sun position</span></div><div id="sunDialHost"></div>';
  pl.append(ctl, dialGroup);
  inspector.buildSectionPanel('light', ctl);
  sunDial.mount($('sunDialHost'));
}

// ---- wallpaper presets (server truth; decides whether wallpaper mode exists) ------
async function loadWallpaperPresets() {
  try {
    state.wpPresets = await Promise.race([
      api.getWallpaperPresets(),
      new Promise((_, rej) => setTimeout(() => rej(new Error('timeout')), 4000)),
    ]);
  } catch { state.wpPresets = []; }
  const sel = $('wpPreset'); sel.innerHTML = '';
  const groups = [['desktop', 'Desktop'], ['laptop', 'Laptop'], ['phone', 'Phone'], ['tablet', 'Tablet'], ['social', 'Social share']];
  for (const [cls, label] of groups) {
    const items = state.wpPresets.filter((p) => p.device_class === cls);
    if (!items.length) continue;
    const og = document.createElement('optgroup'); og.label = label;
    for (const p of items) { const o = document.createElement('option'); o.value = p.id; o.textContent = `${p.name} — ${p.px[0]}×${p.px[1]}`; og.appendChild(o); }
    sel.appendChild(og);
  }
  const oc = document.createElement('option'); oc.value = 'custom'; oc.textContent = 'Custom…'; sel.appendChild(oc);
  const pref = loadPrefs().wpPreset;
  if (pref && state.wpPresets.some((p) => p.id === pref)) sel.value = pref;
  state.wpPreset = sel.value || (state.wpPresets[0] ? state.wpPresets[0].id : '');
}

async function loadRegions(pending) {
  let list = [];
  try { list = await pending; } catch { /* leave empty; drop-to-detect still works */ }
  state.regions = list;
  const prefs = loadPrefs();
  if (list.length === 1) compose.selectRegion(list[0].id);
  else if (prefs.region && list.some((r) => r.id === prefs.region)) compose.selectRegion(prefs.region);
  library.buildRegionGallery();
  refreshShell();
  setSection('library');
}

// ---- foot export controls + shell wiring -----------------------------------------
function wireShell() {
  applyTheme(currentScheme());
  $('themeToggle').onclick = toggleTheme;
  $('paletteBtn').onclick = openPalette;
  $('startOver').onclick = startOver;
  $('reframeBtn').onclick = () => setSection('compose');

  // final format + reprintable toggle (foot)
  wireSegmented($('formatField').querySelector('.segmented'), (v) => {
    state.finalFormat = v; savePref('finalFormat', v); updateSaveFileNote();
  });
  const fmtPref = loadPrefs().finalFormat;
  if (fmtPref === 'pdf' || fmtPref === 'png') { state.finalFormat = fmtPref; }
  wireSegmentedReflect('formatField', state.finalFormat);
  $('embedSpecChk').checked = state.embedSpec;
  $('embedSpecChk').onchange = (e) => { state.embedSpec = e.target.checked; updateSaveFileNote(); };
  if (loadPrefs().autoProof === false) state.autoProof = false;

  // rail
  for (const b of document.querySelectorAll('.rail-item')) b.onclick = () => setSection(b.dataset.section);

  // keyboard: Cmd/Ctrl+K palette; 1..8 sections
  document.addEventListener('keydown', (e) => {
    if ((e.metaKey || e.ctrlKey) && (e.key === 'k' || e.key === 'K')) { e.preventDefault(); openPalette(); return; }
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    const el = document.activeElement;
    if (el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.tagName === 'SELECT' || el.isContentEditable)) return;
    if ($('paletteDialog').open) return;
    const b = [...document.querySelectorAll('.rail-item')].find((x) => x.dataset.key === e.key);
    if (b) { e.preventDefault(); setSection(b.dataset.section); }
  });

  // drag-anywhere: PNG -> reopen a poster; GPX/KML/KMZ -> upload. Surface drop zones
  // handle their own drops (and stopPropagation), so this is the catch-all elsewhere.
  document.addEventListener('dragover', (e) => { if (e.dataTransfer && e.dataTransfer.types.includes('Files')) e.preventDefault(); });
  document.addEventListener('drop', (e) => {
    const f = e.dataTransfer && e.dataTransfer.files[0];
    if (!f) return;
    e.preventDefault();
    if (/\.png$/i.test(f.name)) { setSection('library'); library.openPoster(f); }
    else if (/\.(gpx|kml|kmz)$/i.test(f.name)) { setSection('compose'); compose.doUpload([f]); }
  });
}

// keep a hidden <select> + segmented face reflecting a programmatic value without firing
function wireSegmentedReflect(fieldId, value) {
  const seg = $(fieldId).querySelector('.segmented');
  for (const btn of seg.querySelectorAll('button')) {
    const on = btn.dataset.val === String(value);
    btn.classList.toggle('on', on); btn.setAttribute('aria-checked', on ? 'true' : 'false'); btn.tabIndex = on ? 0 : -1;
  }
  const sel = seg.dataset.for ? $(seg.dataset.for) : null; if (sel) sel.value = value;
}

// ---- bootstrap -------------------------------------------------------------------
function initAll() {
  markProofPaths(controls.proofAffectingPaths());   // the stale-proof rule, declared once
  buildPanels();
  wireShell();
  proof.initProof({ onProofed: () => { if (state.section === 'compose') setSection('style'); refreshShell(); }, onSnapshotApplied: () => {} });
  compose.initCompose({ onLoaded: () => { setSection('compose'); refreshShell(); }, refresh: refreshShell });
  library.initLibrary({ goCompose: () => setSection('compose'), trackReprint: (job) => jobs.track(job, { kind: 'reprint', label: 'Film reprint', runningMsg: 'Reprinting film…' }) });
  exportsCenter.initExports();
  social.setNav({ goExports: () => setSection('exports') });
  initPalette({
    setSection,
    actions: [
      { label: 'Render proof', run: () => proof.renderProof() },
      { label: 'Accept & render final', run: () => proof.acceptFinal() },
      { label: 'Proof + final (express)', run: () => proof.expressFinal() },
      { label: 'Open Social studio', run: () => setSection('social') },
      { label: 'Open Films', run: () => setSection('films') },
      { label: 'Start over', run: startOver },
      { label: 'Toggle Day / Night theme', run: toggleTheme },
    ],
  });

  // one global reflector: a bulk state change (preset / continue / snapshot restore)
  // re-reflects every surface and, if it staled the proof, schedules a live re-proof.
  subscribe((path) => {
    if (path !== null) return;
    inspector.reflectAll(); compose.reflectStatic(); updateSaveFileNote(); proof.refreshProofUI();
    if (state.proofStale) proof.scheduleAutoProof();
  });
}

// Both fetches start immediately, in parallel. wire() must run after the presets resolve
// (it decides whether wallpaper mode exists and restores its pref) and before the regions
// are PROCESSED -- but the regions REQUEST must not wait behind the presets fetch.
(async () => {
  const pendingRegions = api.getRegions();
  await loadWallpaperPresets();
  initAll();
  await loadRegions(pendingRegions);
})();
