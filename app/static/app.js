// app.js — bootstrap + step state machine. Owns transitions and the stepper; wires
// the panes to canvas.js / markers.js / api.js. Single nav paradigm: one named
// primary button drives each step forward; the stepper only clicks BACK to a
// completed step.
import { state, loadPrefs, savePref, activeRegion, trackAspectIsWide } from './state.js';
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
    $('stylePanel').hidden = step !== 'frame';
    $('toFrame').hidden = step !== 'tracks';
    $('renderProof').hidden = step !== 'frame';
    $('expressBtn').hidden = step !== 'frame';
    // stepping back from a still-valid proof must not force a ~5 s re-render:
    // offer the way forward when nothing changed since the last proof.
    $('backToProof').hidden = !(step === 'frame' && state.hasSpec && !state.proofStale);
    $('markersBox').hidden = !(state.hotspots.length);
    // 'auto' orientation reads the tracks now on board -- decide the print dims
    // BEFORE setMode seeds the starter crop, so the first frame has the right aspect
    if (step === 'frame') applyPrintSize();
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
    // built with DOM APIs, not interpolated HTML: region.json is our own data, but
    // a hostile/typo'd region name must render as text, never as markup (red-team).
    const b = document.createElement('button');
    b.type = 'button'; b.className = 'region-card'; b.dataset.id = r.id;
    const img = document.createElement('img'); img.src = r.overview; img.alt = '';
    const span = document.createElement('span'); span.textContent = r.name;
    b.append(img, span);
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
    $('startOver').hidden = false;               // reset is reachable from any step now
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

// Print dims = the chosen sheet (the size select stores portrait-first) turned by
// the orientation control. 'auto' lets the tracks decide: a wide journey lies down,
// a tall one stands up. Called on Frame entry and whenever size/orientation change.
function applyPrintSize() {
  const [a, b] = $('size').value.split(',').map(Number);
  const landscape = state.orientation === 'auto'
    ? trackAspectIsWide() : state.orientation === 'landscape';
  state.printW = landscape ? Math.max(a, b) : Math.min(a, b);
  state.printH = landscape ? Math.min(a, b) : Math.max(a, b);
}

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
// One proof at a time (red-team S3): the server renders /api/proof synchronously,
// so a double-click used to fire two concurrent multi-hundred-MB renders. The flag
// gates every entry point (button, Enter on the canvas, express).
let proofInFlight = false;
let proofUrl = null;   // last object URL, revoked on replace (red-team F2: leak)

async function renderProof() {
  if (proofInFlight) return false;
  // honor the infeasible-size guard from every entry point (button, Enter, express)
  if (canvas.sizeInfeasibleForRegion()) { updateFrameFeasibility(); return false; }
  const ov = cropForProof();
  if (!ov) { setStatus('Draw a frame first', 'status'); return false; }
  proofInFlight = true;
  $('renderProof').disabled = true; $('expressBtn').disabled = true;
  setStatus('Rendering proof…', 'status');
  try {
    const blob = await api.proof(state.session, ov, state.printW, state.printH,
                                 { title: state.title, contours: state.contours,
                                   compass: state.compass, biome: state.biome,
                                   style: state.style });
    if (proofUrl) URL.revokeObjectURL(proofUrl);
    proofUrl = URL.createObjectURL(blob);
    $('posterImg').src = proofUrl;
    state.hasSpec = true; state.proofStale = false;
    state.lastFinal = null; $('downloadAgain').hidden = true;   // new spec, old final void
    go('proof');
    setStatus('Proof ready — accept to render the full-resolution final', 'proofStatus');
    return true;
  } catch (e) {
    if (e.status === 422) {
      // Prefer the server's humanized sentence (off-DEM, aspect, in-bounds…);
      // translate only the terse zoom-cap numbers into operator language. The old
      // catch-all "draw wider" advice was the OPPOSITE fix for an off-DEM crop.
      let msg = e.message && !/^HTTP /.test(e.message) ? e.message : '';
      if (canvas.sizeInfeasibleForRegion()) {
        msg = `This region is too small to print at ${state.printW}×${state.printH} — pick a smaller size.`;
      } else if (!msg || /m\/px/.test(msg)) {
        msg = `This crop is too tight to print sharp at ${state.printW}×${state.printH} — draw wider or pick a larger size.`;
      }
      setStatus(msg, 'status');
    } else { setStatus('Proof failed: ' + e.message, 'status'); }
    return false;
  } finally {
    proofInFlight = false;
    // restore the buttons' real (feasibility) state WITHOUT updateFrameFeasibility,
    // whose status side-effect would wipe the humanized 422 set in the catch above.
    const infeasible = canvas.sizeInfeasibleForRegion();
    $('renderProof').disabled = infeasible;
    $('expressBtn').disabled = infeasible;
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

async function downloadFinal(url, fmt) {
  const blob = await api.fetchBlob(url);
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob); a.download = `trailprint.${fmt}`; a.click();
  // the click has queued the download; release the blob (a 300-dpi PNG is ~50 MB)
  setTimeout(() => URL.revokeObjectURL(a.href), 60000);
}

async function acceptFinal() {
  if (!state.hasSpec || state.proofStale) {
    setStatus('Something changed since the last proof — re-render the proof first.', 'proofStatus');
    return;
  }
  $('accept').disabled = true;
  setStatus('Queuing final render…', 'proofStatus');
  const fmt = state.finalFormat;
  try {
    const { job } = await api.submitFinal(state.session, fmt, state.embedSpec);
    let misses = 0;
    for (;;) {
      await sleep(600);
      let s;
      try {
        s = await api.jobStatus(job);
        misses = 0;
      } catch (e) {
        // a vanished job (404: server restarted, record evicted) can never finish --
        // the old `continue` polled it forever with the button locked.
        if (e.status === 404) { setStatus('Final lost (server restarted?) — accept again to re-render.', 'proofStatus'); break; }
        if (++misses >= 20) { setStatus('Lost contact with the server — accept again to retry.', 'proofStatus'); break; }
        continue;
      }
      if (s.state === 'queued') { setStatus('Queued…', 'proofStatus'); continue; }
      if (s.state === 'running') { setStatus('Rendering final at 300 dpi…', 'proofStatus'); continue; }
      if (s.state === 'error') { setStatus('Final failed: ' + (s.error || 'render error'), 'proofStatus'); break; }
      if (s.state === 'done') {
        await downloadFinal(s.result, fmt);
        state.lastFinal = { url: s.result, fmt };        // re-download without re-rendering
        $('downloadAgain').hidden = false;
        setStatus(`Final ${fmt.toUpperCase()} downloaded.`, 'proofStatus');
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
    title: '', lastFinal: null,
  });
  state.regions = regions; state.steps = steps;
  renderFiles(); $('markerList').innerHTML = ''; $('markersBox').hidden = true;
  $('dropzone').hidden = false; $('map').hidden = true; $('addFiles').hidden = true;
  $('posterImg').removeAttribute('src'); $('toFrame').disabled = true;
  $('titleInput').value = ''; $('downloadAgain').hidden = true;
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
  const txt = btn.querySelector('.tb-txt') || btn;
  txt.textContent = scheme === 'light' ? 'Night' : 'Day';
  btn.setAttribute('aria-label', scheme === 'light' ? 'Switch to night theme' : 'Switch to day theme');
}

// Segmented controls are a native-feeling face over a hidden <select>: clicking a
// segment sets the select's value and fires its 'change' event, so every existing
// select handler (orientation, final format) keeps working untouched. Keyboard
// follows the WAI-ARIA radio-group pattern (red-team S5): roving tabindex — one
// tab stop per group — and arrow keys move both the selection and the focus.
function wireSegmented() {
  for (const seg of document.querySelectorAll('.segmented[data-for]')) {
    const sel = $(seg.dataset.for);
    if (!sel) continue;
    const btns = [...seg.querySelectorAll('button')];
    const sync = () => {
      for (const b of btns) {
        const on = b.dataset.val === sel.value;
        b.classList.toggle('on', on);
        b.setAttribute('aria-checked', on ? 'true' : 'false');
        b.tabIndex = on ? 0 : -1;
      }
    };
    const set = (val, focus) => {
      if (sel.value !== val) {
        sel.value = val;
        sel.dispatchEvent(new Event('change', { bubbles: true }));
      }
      sync();
      if (focus) btns.find((b) => b.dataset.val === val)?.focus();
    };
    btns.forEach((b, i) => {
      b.onclick = () => set(b.dataset.val, false);
      b.onkeydown = (e) => {
        const step = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[e.key];
        if (!step) return;
        e.preventDefault();
        set(btns[(i + step + btns.length) % btns.length].dataset.val, true);
      };
    });
    sync();
  }
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
  $('backToProof').onclick = () => go('proof');
  $('accept').onclick = acceptFinal;
  $('startOver').onclick = startOver;
  $('downloadAgain').onclick = () => {
    if (state.lastFinal) downloadFinal(state.lastFinal.url, state.lastFinal.fmt)
      .catch(() => setStatus('That final has expired — accept again to re-render.', 'proofStatus'));
  };
  $('titleInput').oninput = (e) => {
    state.title = e.target.value;
    if (state.hasSpec) state.proofStale = true;      // the title prints; re-proof it
  };
  $('contoursChk').onchange = (e) => {
    state.contours = e.target.checked;
    if (state.hasSpec) state.proofStale = true;
  };
  $('compassChk').onchange = (e) => {
    state.compass = e.target.checked;
    if (state.hasSpec) state.proofStale = true;
  };
  $('biomeChk').onchange = (e) => {
    state.biome = e.target.checked;
    if (state.hasSpec) state.proofStale = true;
  };

  // Style panel: every knob is a picture decision -> stale the proof on change.
  const styleSliders = [
    ['sWidth', 'vWidth', 'width', (v) => `${v} pt`],
    ['sHalo', 'vHalo', 'halo', (v) => Number(v).toFixed(2)],
    ['sMarker', 'vMarker', 'marker', (v) => `${v} in`],
    ['sRing', 'vRing', 'ring', (v) => Number(v).toFixed(2)],
    ['sFurniture', 'vFurniture', 'furniture', (v) => `${Number(v).toFixed(2)}×`],
    ['sTerrain', 'vTerrain', 'terrain', (v) => `${Number(v).toFixed(1)}×`],
    ['sShadow', 'vShadow', 'shadow', (v) => Number(v).toFixed(1)],
  ];
  for (const [sid, vid, key, fmt] of styleSliders) {
    $(sid).oninput = (e) => {
      state.style[key] = Number(e.target.value);
      $(vid).textContent = fmt(e.target.value);
      if (state.hasSpec) state.proofStale = true;
    };
  }
  $('sPhotoStyle').onchange = (e) => {
    state.style.photoStyle = e.target.value;
    if (state.hasSpec) state.proofStale = true;
  };
  for (const sw of document.querySelectorAll('.swatch')) {
    sw.onclick = () => {
      for (const el of document.querySelectorAll('.swatch')) el.classList.remove('sel');
      sw.classList.add('sel');
      state.style.color = sw.dataset.hex;
      if (state.hasSpec) state.proofStale = true;
    };
  }
  $('finalFormat').onchange = (e) => {
    state.finalFormat = e.target.value; savePref('finalFormat', e.target.value);
  };
  $('embedSpecChk').onchange = (e) => {
    state.embedSpec = e.target.checked;
    // PDF can't carry the manifest anyway; the toggle only affects PNG.
  };
  const fmtPref = loadPrefs().finalFormat;
  if (fmtPref === 'pdf' || fmtPref === 'png') {
    state.finalFormat = fmtPref; $('finalFormat').value = fmtPref;
  }

  const prefs = loadPrefs();
  if (prefs.printSize && /^\d+,\d+$/.test(prefs.printSize) &&
      [...$('size').options].some((o) => o.value === prefs.printSize)) {
    $('size').value = prefs.printSize;
  }
  if (['auto', 'landscape', 'portrait'].includes(prefs.orient)) {
    state.orientation = prefs.orient; $('orient').value = prefs.orient;
  }
  applyPrintSize();
  $('size').onchange = (e) => {
    savePref('printSize', e.target.value);
    applyPrintSize();
    canvas.refitForSize(); markers.refreshOutOfFrame(); updateFrameFeasibility();
  };
  $('orient').onchange = (e) => {
    state.orientation = e.target.value; savePref('orient', e.target.value);
    applyPrintSize();
    canvas.refitForSize(); markers.refreshOutOfFrame(); updateFrameFeasibility();
  };

  // segmented faces reflect the (pref-seeded) hidden selects -- wire last so their
  // initial .on state matches the values set from prefs above.
  wireSegmented();
}

wire();
loadRegions();
