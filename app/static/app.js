// app.js — the studio bootstrap + router. One window, no steps: a top output-target
// switcher (Poster / Wallpaper / Film / Social), the project sidebar on the left, the
// always-present appearance sidebar on the right, and a center stage that adapts to
// the target (Map|Preview workspace, film player, social gallery). Every target's
// behaviour lives in its own module; this file decides what the stage shows and keeps
// the shell in sync with the store.
import { state, savePref, loadPrefs, markProofPaths, subscribe } from './store.js';
import * as api from './api.js';
import * as controls from './controls.js';
import * as inspector from './inspector.js';
import * as proof from './proof.js';
import * as jobs from './jobs.js';
import * as compose from './compose.js';
import * as library from './library.js';
import * as create from './create.js';
import * as social from './social.js';
import * as films from './films.js';
import * as exportsCenter from './exports.js';
import * as presets from './presets.js';
import * as sunDial from './sunDial.js';
import * as guided from './guided.js';
import * as viewer from './viewer.js';
import * as statusbar from './statusbar.js';
import { initPalette, open as openPalette } from './palette.js';
import { $, toast, wireSegmented, updateSaveFileNote, withTransition } from './ui.js';

const TARGETS = ['poster', 'wallpaper', 'film', 'social'];

// ---- router: target (what you're making) x view (map or preview) -----------------
export function setTarget(name) {
  if (!TARGETS.includes(name)) return;
  if (name === 'wallpaper' && !state.wpPresets.length) { toast('No wallpaper presets available (server offline at load?)', 'info'); return; }
  withTransition(() => {
    state.target = name;
    // poster/wallpaper drive the composition's output kind; film/social present it
    if (name === 'poster') compose.setOutput('print');
    else if (name === 'wallpaper') compose.setOutput('wallpaper');
    for (const b of document.querySelectorAll('.target-item')) {
      b.setAttribute('aria-current', b.dataset.target === name ? 'true' : 'false');
    }
    // left sidebar: page setup for poster/wallpaper, film setup for films
    $('pagePanel').hidden = !(name === 'poster' || name === 'wallpaper');
    $('filmPanel').hidden = name !== 'film';
    // right sidebar: film pacing + social panel appear with their targets
    $('filmPacingHost').hidden = name !== 'film';
    $('panel-social').hidden = name !== 'social';
    // the poster action foot only makes sense when composing the sheet
    $('inspectorFoot').hidden = !(name === 'poster' || name === 'wallpaper');
    if (name === 'film') films.buildFilms();
    else if (name === 'social') social.buildSocial();
    refreshStage();
  });
  refreshShell();
}

// Which center surface is showing. Map|Preview applies to the poster/wallpaper
// workspace; film and social bring their own stages; no tracks = the start surface.
export function setView(v) {
  state.view = v === 'map' ? 'map' : 'preview';
  refreshStage();
}

function currentSurfaceId() {
  if (!state.tracks.length) return 'surface-home';
  if (state.target === 'film') return 'surface-film';
  if (state.target === 'social') return 'surface-social';
  return state.view === 'map' ? 'surface-map' : 'surface-proof';
}

let lastSurface = null;
function refreshStage() {
  const id = currentSurfaceId();
  for (const s of document.querySelectorAll('.surface')) s.hidden = s.id !== id;
  const sv = $('stageView');
  sv.hidden = !(state.tracks.length && (state.target === 'poster' || state.target === 'wallpaper'));
  $('viewMapBtn').classList.toggle('on', state.view === 'map');
  $('viewPreviewBtn').classList.toggle('on', state.view !== 'map');
  if (id !== lastSurface) {
    lastSurface = id;
    // entering the map re-seeds the frame + feasibility (and kicks the canvas layout)
    if (id === 'surface-map') compose.enterCompose();
    if (id === 'surface-proof') proof.refreshProofUI();
  }
}

// Palette / deep-link helper: land on the target that owns a control, then focus it.
export function jumpToControl(c) {
  if (c.section === 'films') { if (state.target !== 'film') setTarget('film'); }
  else if (state.target === 'film' || state.target === 'social') {
    setTarget(state.output === 'wallpaper' ? 'wallpaper' : 'poster');
  }
  setTimeout(() => {
    const el = $(`c_${c.id}`);
    if (!el) return;
    const group = el.closest('details'); if (group) group.open = true;
    el.scrollIntoView({ block: 'center' });
    el.focus();
  }, 60);
}

// ---- shell sync ------------------------------------------------------------------
function refreshShell() {
  $('regionName').textContent = state.regionName || '';
  const rk = $('regionKind');
  rk.hidden = !state.regionKind; rk.textContent = state.regionKind || '';
  const eb = $('editionBadge');
  eb.hidden = state.edition < 2; eb.textContent = state.edition >= 2 ? `Edition ${state.edition}` : '';
  $('yearSpan').textContent = state.yearSpan || '';
  $('startOver').hidden = !(state.session || state.files.length);
  $('themeToggle').hidden = false;
  $('noTracksHint').hidden = state.tracks.length > 0 || state.hintDismissed;
  $('targetBar').querySelector('[data-target="wallpaper"]').hidden = !state.wpPresets.length;
  updateSaveFileNote();
  compose.updateLightAvailability();
  $('formatField').hidden = state.output === 'wallpaper';
  if (state.target === 'film') films.refreshGate();
  proof.refreshProofUI();
  statusbar.refreshProof();
  refreshStage();
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
    region: null, regionName: '', regionKind: '',
  });
  state.regions = regions; state.wpPresets = wpPresets;
  $('markerList').innerHTML = ''; $('markersBox').hidden = true; $('fileList').innerHTML = '';
  $('dropzone').hidden = false; $('map').hidden = true; $('addFiles').hidden = true;
  $('continuePoster').hidden = false; $('mapMode').hidden = true;
  $('posterImg').removeAttribute('src'); $('posterCard').hidden = true; $('proofEmpty').hidden = false;
  viewer.reset();
  $('titleInput').value = ''; $('provenanceCard').hidden = true;
  inspector.reflectAll(); compose.reflectStatic();
  statusbar.closeDrawer();
  setTarget('poster');
  setView('map');
  refreshShell();
  toast('Cleared — drop your GPX to start a new map.', 'info');
}

// ---- appearance sidebar (built once, always visible) ------------------------------
function buildPanels() {
  presets.renderInto($('stylePresets'), { onApply: () => { inspector.reflectAll(); compose.reflectStatic(); proof.refreshProofUI(); } });
  inspector.buildSectionPanel('style', $('styleHost'));
  inspector.buildSectionPanel('layers', $('layersHost'));

  // Light: the registry controls, then the sun dial in its own group
  const lightHost = $('lightHost');
  inspector.buildSectionPanel('light', lightHost);
  const dialGroup = document.createElement('details'); dialGroup.className = 'insp-group'; dialGroup.open = true;
  dialGroup.innerHTML = '<summary class="insp-head"><span class="insp-title">Sun position</span></summary><div id="sunDialHost"></div>';
  lightHost.appendChild(dialGroup);
  sunDial.mount($('sunDialHost'));

  // Film pacing rides the right sidebar when the Film target is active; the film
  // target/format/render controls live in the left sidebar (films.js).
  inspector.buildSectionPanel('films', $('filmPacingHost'), { panels: ['Pacing'] });

  attachStaticHelp();
}

// The static page-setup rows get the same ? affordance as registry rows, reusing the
// registry's own sentences where an entry exists.
function attachStaticHelp() {
  const H = (id, help) => { const el = $(id); if (el && help) inspector.attachHelp(el, help); };
  H('sizeField', controls.control('size').help);
  H('orientField', controls.control('orientation').help);
  H('bleedField', controls.control('bleed').help);
  H('titleField', controls.control('title').help);
  H('wpPresetField', "Pick the exact screen this wallpaper is for — it renders at that device's native pixels.");
  H('customDeviceField', "A device the list doesn't carry: its exact pixel size and physical pixels-per-inch.");
  H('formatField', controls.control('finalFormat').help);
  const rt = document.querySelector('.reprint-toggle');
  if (rt) { rt.removeAttribute('title'); inspector.attachHelp(rt, controls.control('embedSpec').help); }
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
  // GPX-first: no pre-pick, no region gallery. The region is an OUTCOME — the server
  // auto-detects the covering plate from the dropped tracks (or the creation flow builds
  // one). We still keep the full list so activeRegion()/metresPerPx() resolve a match.
  refreshShell();
}

// ---- foot export controls + shell wiring -----------------------------------------
function wireShell() {
  applyTheme(currentScheme());
  $('themeToggle').onclick = toggleTheme;
  $('paletteBtn').onclick = openPalette;
  $('startOver').onclick = startOver;
  $('reframeBtn').onclick = () => setView('map');

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

  // target switcher + stage view toggle + hint dismissal
  for (const b of document.querySelectorAll('.target-item')) b.onclick = () => setTarget(b.dataset.target);
  $('viewMapBtn').onclick = () => setView('map');
  $('viewPreviewBtn').onclick = () => setView('preview');
  $('noTracksHintClose').onclick = () => { state.hintDismissed = true; $('noTracksHint').hidden = true; };
  $('shortcutsClose').onclick = () => $('shortcutsDialog').close();

  // keyboard: Cmd/Ctrl+K palette; ? shortcuts; 1..4 targets; M/P map or preview
  document.addEventListener('keydown', (e) => {
    if ((e.metaKey || e.ctrlKey) && (e.key === 'k' || e.key === 'K')) { e.preventDefault(); openPalette(); return; }
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    const el = document.activeElement;
    if (el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.tagName === 'SELECT' || el.isContentEditable)) return;
    if ($('paletteDialog').open) return;
    if (e.key === '?') { e.preventDefault(); const d = $('shortcutsDialog'); if (!d.open) d.showModal(); return; }
    if (e.key === 'm' || e.key === 'M') { e.preventDefault(); setView('map'); return; }
    if (e.key === 'p' || e.key === 'P') { e.preventDefault(); setView('preview'); return; }
    const b = [...document.querySelectorAll('.target-item')].find((x) => x.dataset.key === e.key);
    if (b && !b.hidden) { e.preventDefault(); setTarget(b.dataset.target); }
  });

  // drag-anywhere: PNG -> reopen a poster; GPX/KML/KMZ -> upload. Surface drop zones
  // handle their own drops (and stopPropagation), so this is the catch-all elsewhere.
  document.addEventListener('dragover', (e) => { if (e.dataTransfer && e.dataTransfer.types.includes('Files')) e.preventDefault(); });
  document.addEventListener('drop', (e) => {
    // The creation modal is open: surface dropzones are inert under showModal(), but a drop
    // onto the dialog itself still bubbles here. Ignore it so nothing uploads behind the modal.
    if ($('buildDialog').open) return;
    const f = e.dataTransfer && e.dataTransfer.files[0];
    if (!f) return;
    e.preventDefault();
    if (/\.png$/i.test(f.name)) library.openPoster(f);
    else if (/\.(gpx|kml|kmz)$/i.test(f.name)) compose.doUpload([f]);
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
  statusbar.initStatusbar({ onReproof: () => proof.renderProof() });
  proof.initProof({
    onProofed: () => { setView('preview'); refreshShell(); },
    onSnapshotApplied: () => {},
    onUiRefresh: () => statusbar.refreshProof(),
  });
  compose.initCompose({
    onLoaded: () => {
      // an upload always lands in the sheet workspace — leave film/social presentation
      if (state.target === 'film' || state.target === 'social') {
        setTarget(state.output === 'wallpaper' ? 'wallpaper' : 'poster');
      }
      setView('map'); refreshShell();
    },
    refresh: refreshShell,
  });
  library.initLibrary({ goCompose: () => setView('map'), trackReprint: (job) => jobs.track(job, { kind: 'reprint', label: 'Film reprint', runningMsg: 'Reprinting film…' }) });
  // GPX-first region creation: on build done, re-upload the kept tracks (they now match the
  // fresh plate) and re-sync the shell so the "Built" chip and cleared session take effect.
  create.initCreate({ reupload: (files) => compose.doUpload(files), refresh: refreshShell });
  exportsCenter.initExports();
  films.initFilms();
  social.setNav({ goExports: () => statusbar.openDrawer() });
  initPalette({
    setTarget,
    setView,
    jumpToControl,
    actions: [
      { label: 'Render proof', run: () => proof.renderProof() },
      { label: 'Accept & render final', run: () => proof.acceptFinal() },
      { label: 'Proof + final (express)', run: () => proof.expressFinal() },
      { label: 'Open Exports', run: () => statusbar.openDrawer() },
      { label: 'Start over', run: startOver },
      { label: 'Toggle Day / Night theme', run: toggleTheme },
      { label: 'Keyboard shortcuts', run: () => $('shortcutsDialog').showModal() },
      { label: 'Show welcome guide', run: () => guided.open() },
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
  // land on the target matching the restored output pref (compose.restorePagePrefs)
  setTarget(state.output === 'wallpaper' && state.wpPresets.length ? 'wallpaper' : 'poster');
  await loadRegions(pendingRegions);
  guided.maybeStart();               // first-run welcome (once per browser)
})();
