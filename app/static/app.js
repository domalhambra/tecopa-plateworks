// app.js — bootstrap + step state machine. Owns transitions and the stepper; wires
// the panes to canvas.js / markers.js / api.js. Single nav paradigm: one named
// primary button drives each step forward; the stepper only clicks BACK to a
// completed step.
import { state, loadPrefs, savePref, activeRegion } from './state.js';
import * as api from './api.js';
import * as canvas from './canvas.js';
import * as markers from './markers.js';

const $ = (id) => document.getElementById(id);
const escapeHtml = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
const STEP_LABELS = { region: 'Region', tracks: 'Tracks', frame: 'Frame', proof: 'Proof' };
const WORKSPACE_HEADING = { tracks: 'Add your tracks', frame: 'Frame the poster' };

function setStatus(msg, which = 'status') { const el = $(which); if (el) el.textContent = msg || ''; }
function stepIndex() { return state.steps.indexOf(state.step); }

// --- stepper ---
function buildStepper() {
  const nav = $('stepper'); nav.innerHTML = '';
  const ci = stepIndex();
  state.steps.forEach((s, idx) => {
    const row = document.createElement('button');
    row.type = 'button';
    row.className = 'step' + (s === state.step ? ' active' : '') +
                    (idx < ci ? ' done' : '') + (idx > ci ? ' upcoming' : '');
    if (s === state.step) row.setAttribute('aria-current', 'step');
    row.disabled = idx >= ci;                          // only completed steps go back
    row.innerHTML =
      `<span class="circle">${idx < ci ? '✓' : idx + 1}</span>` +
      `<span class="steptext"><span class="eyebrow">Step ${idx + 1}</span>` +
      `<span class="label">${STEP_LABELS[s]}</span></span>`;
    row.onclick = () => { if (idx < ci) go(s); };      // click-back only
    nav.appendChild(row);
  });
}

// --- transitions ---
function go(step) {
  state.step = step;
  const inWork = step === 'tracks' || step === 'frame';
  $('pane-region').hidden = step !== 'region';
  $('workspace').hidden = !inWork;
  $('pane-proof').hidden = step !== 'proof';

  if (inWork) {
    $('h-workspace').textContent = WORKSPACE_HEADING[step];
    $('filesBlock').hidden = step !== 'tracks';
    $('frameControls').hidden = step !== 'frame';
    $('toFrame').hidden = step !== 'tracks';
    $('renderProof').hidden = step !== 'frame';
    $('expressBtn').hidden = step !== 'frame';
    $('markersBox').hidden = !(state.hotspots.length);
    canvas.setMode(step);
    if (step === 'tracks') {
      setStatus(state.tracks.length
        ? `${state.tracks.length} track(s) — name places or continue` : '');
    } else {
      markers.refreshOutOfFrame();
      showHint('Drag to draw a frame · arrow keys nudge it · Reset to recenter');
      setStatus('', 'status');
      updateFrameFeasibility();
    }
  }
  buildStepper();
  focusHeading(step);
}

function focusHeading(step) {
  const id = { region: 'h-region', tracks: 'h-workspace', frame: 'h-workspace', proof: 'h-proof' }[step];
  const el = $(id); if (el) el.focus();
}

function showHint(text) { const h = $('hint'); if (!h) return; h.textContent = text; h.hidden = !text; }

// --- region step ---
function selectRegion(id) {
  state.region = id;
  const meta = state.regions.find((r) => r.id === id);
  state.regionName = meta ? meta.name : '';
  $('regionName').textContent = state.regionName;
  for (const el of document.querySelectorAll('.region-card')) el.classList.toggle('sel', el.dataset.id === id);
  $('toTracks').disabled = !id;
}

function buildRegionGallery() {
  const host = $('regionGallery'); host.innerHTML = '';
  for (const r of state.regions) {
    const b = document.createElement('button');
    b.type = 'button'; b.className = 'region-card'; b.dataset.id = r.id;
    b.innerHTML = `<img src="${r.overview}" alt=""><span>${r.name}</span>`;
    b.onclick = () => selectRegion(r.id);
    host.appendChild(b);
  }
}

async function loadRegions() {
  let list = [];
  try { list = await api.getRegions(); } catch { /* leave empty; drop-to-detect still works */ }
  state.regions = list;
  const prefs = loadPrefs();
  if (list.length <= 1) {                              // auto-skip the Region step
    state.steps = ['tracks', 'frame', 'proof'];
    if (list.length === 1) selectRegion(list[0].id);
    go('tracks');
  } else {
    state.steps = ['region', 'tracks', 'frame', 'proof'];
    buildRegionGallery();
    if (prefs.region && list.some((r) => r.id === prefs.region)) selectRegion(prefs.region);
    $('startOver').hidden = false;
    go('region');
  }
}

// --- upload / tracks step ---
async function doUpload(fileList) {
  const arr = Array.from(fileList || []);
  if (!arr.length) return;
  setStatus(`Uploading ${arr.length} file(s)…`);
  try {
    const j = await api.upload(arr, { sessionId: state.session, regionId: state.region });
    state.session = j.session;
    if (j.region !== state.region) selectRegion(j.region);   // reflect an auto-detected region
    state.regionName = j.name; $('regionName').textContent = j.name || '';
    state.ovSize = j.overview_size; state.tracks = j.tracks; state.hotspots = j.hotspots;
    state.starterCrop = j.starter_crop; state.crop = null;    // set on Frame entry
    state.hasSpec = false; state.proofStale = true;           // new tracks invalidate any spec
    savePref('region', j.region);
    arr.forEach((f) => state.files.push(f.name)); renderFiles();
    canvas.setOverview(j.overview, j.overview_size);
    $('dropzone').hidden = true; $('map').hidden = false; $('addFiles').hidden = false;
    markers.render($('markerList'), (msg) => setStatus(msg));
    $('toFrame').disabled = state.tracks.length === 0;
    // re-enter Tracks through the normal transition so step/canvas-mode/panes stay in
    // sync even when files were dropped while on the Frame step (adding tracks is a
    // Tracks-step action; it invalidated the crop, so returning to Tracks is correct).
    go('tracks');
    if (j.recovered) {                                 // dropped tracks belonged elsewhere
      showHint(`These tracks are in ${j.name} — switched to that region`);
      setStatus(`Switched to ${j.name} — the dropped tracks belong to that region.`);
      announce(`Switched region to ${j.name}`);
    } else {
      showHint('Your tracks are on the map — gold dots mark places you returned to most');
      setStatus(`${state.tracks.length} track(s) across ${state.files.length} file(s) — name places or continue`);
    }
  } catch (e) { setStatus('Upload failed: ' + e.message); }
}

function renderFiles() { $('fileList').innerHTML = state.files.map((n) => `<li>${escapeHtml(n)}</li>`).join(''); }

// --- a11y live-region announcements ---
function announce(msg) { const el = $('a11yStatus'); if (el) el.textContent = msg || ''; }

// disable proof when the region physically can't hold the selected print size, with
// an honest "pick a smaller size" message (vs. the "draw wider" case for a tight box).
function updateFrameFeasibility() {
  const infeasible = canvas.sizeInfeasibleForRegion();
  $('renderProof').disabled = infeasible;
  $('expressBtn').disabled = infeasible;
  setStatus(infeasible
    ? `This region is too small to print at ${state.printW}×${state.printH} — pick a smaller size.` : '',
    'status');
}

// --- proof step ---
async function renderProof() {
  // honor the infeasible-size guard from every entry point (button, Enter, express)
  if (canvas.sizeInfeasibleForRegion()) { updateFrameFeasibility(); return false; }
  const ov = cropForProof();
  if (!ov) { setStatus('Draw a frame first', 'status'); return false; }
  setStatus('Rendering proof…', 'status');
  try {
    const blob = await api.proof(state.session, ov, state.printW, state.printH);
    $('posterImg').src = URL.createObjectURL(blob);
    state.hasSpec = true; state.proofStale = false;
    go('proof');
    setStatus('Proof ready — accept to render the full-resolution final', 'proofStatus');
    return true;
  } catch (e) {
    if (e.status === 422) {
      const msg = canvas.sizeInfeasibleForRegion()
        ? `This region is too small to print at ${state.printW}×${state.printH} — pick a smaller size.`
        : `This crop is too tight to print sharp at ${state.printW}×${state.printH} — draw wider or pick a larger size.`;
      setStatus(msg, 'status');
    } else { setStatus('Proof failed: ' + e.message, 'status'); }
    return false;
  }
}

// Express: render a proof and, if it succeeds, chain straight into the final render.
// An extra shortcut -- the explicit Accept gate on the Proof step still stands.
async function expressFinal() {
  const okProof = await renderProof();
  if (okProof) await acceptFinal();
}

function cropForProof() {
  const c = state.crop; if (!c || !state.scale) return null;
  const s = state.scale;
  return [Math.min(c[0], c[2]) / s, Math.min(c[1], c[3]) / s,
          Math.max(c[0], c[2]) / s, Math.max(c[1], c[3]) / s];
}

const sleep = (ms) => new Promise((res) => setTimeout(res, ms));

async function acceptFinal() {
  if (!state.hasSpec || state.proofStale) {
    setStatus('Something changed since the last proof — re-render the proof first.', 'proofStatus');
    return;
  }
  $('accept').disabled = true;
  setStatus('Queuing final render…', 'proofStatus');
  try {
    const { job } = await api.submitFinal(state.session);
    for (;;) {
      await sleep(600);
      let s;
      try { s = await api.jobStatus(job); } catch { continue; }
      if (s.state === 'queued') { setStatus('Queued…', 'proofStatus'); continue; }
      if (s.state === 'running') { setStatus('Rendering final at 300 dpi…', 'proofStatus'); continue; }
      if (s.state === 'error') { setStatus('Final failed: ' + (s.error || 'render error'), 'proofStatus'); break; }
      if (s.state === 'done') {
        const blob = await api.fetchBlob(s.result);
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob); a.download = 'trailprint.png'; a.click();
        setStatus('Final downloaded.', 'proofStatus');
        break;
      }
    }
  } catch (e) { setStatus('Final failed: ' + e.message, 'proofStatus'); }
  $('accept').disabled = false;
}

// --- start over ---
function startOver() {
  const hasWork = state.session || state.files.length;
  if (hasWork && !confirm('Start over? This clears the loaded tracks and framing (uploaded photos are kept until the session ends).')) return;
  const regions = state.regions, steps = state.steps;
  Object.assign(state, {
    session: null, ovSize: null, scale: 1, tracks: [], hotspots: [],
    crop: null, starterCrop: null, hasSpec: false, proofStale: false, files: [],
  });
  state.regions = regions; state.steps = steps;
  renderFiles(); $('markerList').innerHTML = ''; $('markersBox').hidden = true;
  $('dropzone').hidden = false; $('map').hidden = true; $('addFiles').hidden = true;
  $('posterImg').removeAttribute('src'); $('toFrame').disabled = true;
  go(state.steps[0]);
  setStatus('Cleared — drop files to start a new map');
}

// --- theme (Night/Day) ---
// The pre-paint <head> script applies the saved scheme before first paint; here we
// reflect it in the toggle and persist changes. Restyles the UI only, never the poster.
function currentScheme() {
  return document.documentElement.getAttribute('data-color-scheme') === 'light' ? 'light' : 'dark';
}
function applyTheme(scheme) {
  document.documentElement.setAttribute('data-color-scheme', scheme);
  const btn = $('themeToggle');
  btn.textContent = scheme === 'light' ? 'Night' : 'Day';
  btn.setAttribute('aria-label', scheme === 'light' ? 'Switch to night theme' : 'Switch to day theme');
}
function initTheme() {
  const btn = $('themeToggle'); btn.hidden = false;
  applyTheme(currentScheme());
  btn.onclick = () => {
    const next = currentScheme() === 'light' ? 'dark' : 'light';
    applyTheme(next); savePref('theme', next);
  };
}

// --- wiring ---
function wire() {
  initTheme();
  canvas.init($('map'), {
    onCropChange: () => { if (state.hasSpec) state.proofStale = true; markers.refreshOutOfFrame(); },
    onMarkerMoved: () => { state.proofStale = true; markers.refreshOutOfFrame(); setStatus('Marker moved — re-render the proof to see it'); announce('Marker moved'); },
    onDragTip: () => showHint('Tip: drag a gold dot to reposition that place'),
    onRenderProof: () => renderProof(),                // Enter on the focused canvas
    announce,                                          // keyboard crop -> live region
  });

  const dz = $('dropzone'), fi = $('fileInput');
  dz.onclick = () => fi.click();
  $('addFiles').onclick = () => fi.click();
  fi.onchange = (e) => { doUpload(e.target.files); e.target.value = ''; };
  const mapPane = $('mapPane');
  mapPane.addEventListener('dragover', (e) => { e.preventDefault(); dz.classList.add('over'); });
  mapPane.addEventListener('dragleave', () => dz.classList.remove('over'));
  mapPane.addEventListener('drop', (e) => { e.preventDefault(); dz.classList.remove('over'); doUpload(e.dataTransfer.files); });

  $('toTracks').onclick = () => go('tracks');
  $('toFrame').onclick = () => go('frame');
  $('renderProof').onclick = renderProof;
  $('expressBtn').onclick = expressFinal;
  $('resetFrame').onclick = () => { canvas.resetFrame(); markers.refreshOutOfFrame(); updateFrameFeasibility(); };
  $('reframe').onclick = () => go('frame');
  $('accept').onclick = acceptFinal;
  $('startOver').onclick = startOver;

  const prefs = loadPrefs();
  if (prefs.printSize) {
    const [w, h] = prefs.printSize.split(',').map(Number);
    if (w && h) { state.printW = w; state.printH = h; $('size').value = prefs.printSize; }
  }
  $('size').onchange = (e) => {
    const [w, h] = e.target.value.split(',').map(Number);
    state.printW = w; state.printH = h; savePref('printSize', e.target.value);
    canvas.refitForSize(); markers.refreshOutOfFrame(); updateFrameFeasibility();
  };
}

wire();
loadRegions();
