// app.js — bootstrap + step state machine. Owns transitions and the stepper; wires
// the panes to canvas.js / markers.js / api.js. Single nav paradigm: one named
// primary button drives each step forward; the stepper only clicks BACK to a
// completed step.
import { state, loadPrefs, savePref, activeRegion, trackAspectIsWide, activePreset } from './state.js';
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
    if (step === 'frame') { applyPrintSize(); applyOutputVisibility(); }
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
  if (step === 'proof') {
    // wallpapers are PNG-only (the server refuses PDF); the bundle card offers the
    // accepted composition re-rendered for every screen the client picks.
    $('formatField').hidden = state.output === 'wallpaper';
    renderBundleCard();
    renderTimelapseCard();
  }
  buildStepper();
  focusHeading(step);
}

function focusHeading(step) {
  const id = { region: 'h-region', tracks: 'h-workspace', frame: 'h-workspace', proof: 'h-proof' }[step];
  const el = $(id); if (el) el.focus();
}

function showHint(text) { const h = $('hint'); if (!h) return; h.textContent = text; h.hidden = !text; }

// Reflect the hidden <select> values onto their segmented-control faces WITHOUT firing
// a 'change' event — used after a programmatic value set (e.g. a continued poster's
// restored output/orientation) so we don't trigger the onchange side-effects
// (savePref clobbering the user's defaults, a premature reframe before the canvas is up).
function syncSegmentedFaces() {
  for (const seg of document.querySelectorAll('.segmented[data-for]')) {
    const sel = $(seg.dataset.for);
    if (!sel) continue;
    for (const b of seg.querySelectorAll('button')) {
      const on = b.dataset.val === sel.value;
      b.classList.toggle('on', on);
      b.setAttribute('aria-checked', on ? 'true' : 'false');
      b.tabIndex = on ? 0 : -1;
    }
  }
}

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

async function loadRegions(pending) {
  let list = [];
  try { list = await pending; } catch { /* leave empty; drop-to-detect still works */ }
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

// The device-preset table comes from the server (single source of truth); the picker
// groups it by device class. Runs BEFORE wire() so the output pref is restored only
// once presets exist; with no presets (fetch failed/empty) the whole Output control
// is hidden and the app stays a plain print wizard -- wallpaper mode is never
// offered in a state where every proof would 422 on an empty preset id.
async function loadWallpaperPresets() {
  try {
    state.wpPresets = await Promise.race([
      api.getWallpaperPresets(),
      new Promise((_, rej) => setTimeout(() => rej(new Error('timeout')), 4000)),
    ]);
  } catch { state.wpPresets = []; }
  const sel = $('wpPreset'); sel.innerHTML = '';
  const groups = [['desktop', 'Desktop'], ['laptop', 'Laptop'],
                  ['phone', 'Phone'], ['tablet', 'Tablet']];
  for (const [cls, label] of groups) {
    const items = state.wpPresets.filter((p) => p.device_class === cls);
    if (!items.length) continue;
    const og = document.createElement('optgroup'); og.label = label;
    for (const p of items) {
      const o = document.createElement('option');
      o.value = p.id; o.textContent = `${p.name} — ${p.px[0]}×${p.px[1]}`;
      og.appendChild(o);
    }
    sel.appendChild(og);
  }
  const pref = loadPrefs().wpPreset;
  if (pref && state.wpPresets.some((p) => p.id === pref)) sel.value = pref;
  state.wpPreset = sel.value || (state.wpPresets[0] ? state.wpPresets[0].id : '');
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
    // living editions: a file already on the poster (same bytes) is skipped server-side,
    // so don't list it as newly added either.
    const skipped = j.skipped_duplicates || [];
    const skippedSet = new Set(skipped);
    arr.forEach((f) => { if (!skippedSet.has(f.name)) state.files.push(f.name); });
    renderFiles();
    canvas.setOverview(j.overview, j.overview_size);
    $('dropzone').hidden = true; $('continuePoster').hidden = true;
    $('map').hidden = false; $('addFiles').hidden = false;
    $('startOver').hidden = false;               // reset is reachable from any step now
    markers.render($('markerList'), (msg) => setStatus(msg));
    $('toFrame').disabled = state.tracks.length === 0;
    // re-enter Tracks through the normal transition so step/canvas-mode/panes stay in
    // sync even when files were dropped while on the Frame step (adding tracks is a
    // Tracks-step action; it invalidated the crop, so returning to Tracks is correct).
    go('tracks');
    // loud boundaries: name what the plate can't hold instead of dropping it silently —
    // on BOTH branches below (a recovered upload can still drop out-of-projection
    // points or hold journeys that spill past the recovered plate's edge).
    const boundary = [];
    if (j.dropped_points) boundary.push(`${j.dropped_points} point${j.dropped_points === 1 ? '' : 's'} outside the plate's map projection — dropped`);
    if (j.journeys_outside_plate) boundary.push(`${j.journeys_outside_plate} of ${j.tracks.length} journeys extend beyond the plate and won't fully appear`);
    if (j.recovered) {                                 // dropped tracks belonged elsewhere
      const boundaryNote = boundary.length ? ` (${boundary.join('; ')})` : '';
      showHint(`These tracks are in ${j.name} — switched to that region`);
      setStatus(`Switched to ${j.name} — the dropped tracks belong to that region.${boundaryNote}`);
      announce(`Switched region to ${j.name}`);
    } else {
      showHint('Your tracks are on the map — gold dots mark places you returned to most');
      // two dedup passes can skip work: whole files already on the poster (same bytes),
      // and individual tracks already present (e.g. a re-exported folder that overlaps).
      const dupTracks = j.skipped_duplicate_tracks || 0;
      const parts = [];
      if (skipped.length) parts.push(`${skipped.length} file(s) already added`);
      if (dupTracks) parts.push(`${dupTracks} track(s) already on the poster`);
      const notes = [];
      if (parts.length) notes.push(`${parts.join(', ')} — skipped`);
      notes.push(...boundary);
      const dupNote = notes.length ? ` (${notes.join('; ')})` : '';
      setStatus(`${state.tracks.length} track(s) across ${state.files.length} file(s)${dupNote} — name places or continue`);
    }
  } catch (e) { setStatus('Upload failed: ' + e.message); }
}

function renderFiles() { $('fileList').innerHTML = state.files.map((n) => `<li>${escapeHtml(n)}</li>`).join(''); }

// --- living editions: continue a poster ---
function updateEditionBadge() {
  const b = $('editionBadge');
  if (!b) return;
  const show = state.edition >= 2;
  b.textContent = show ? `Edition ${state.edition}` : '';
  b.hidden = !show;
}

// Reflect a continued poster's saved recipe into the Frame-step controls, so the
// restored composition renders exactly as it was composed until the operator edits it.
function applyPrefill(p) {
  if (!p) return;
  state.title = p.title || '';
  $('titleInput').value = state.title;
  state.contours = !!p.contours; $('contoursChk').checked = state.contours;
  state.compass = p.compass !== false; $('compassChk').checked = state.compass;
  state.biome = !!p.biome; $('biomeChk').checked = state.biome;
  state.labels = !!p.labels; $('labelsChk').checked = state.labels;
  const s = p.style || {};
  Object.assign(state.style, {
    width: s.width, halo: s.halo, color: s.color || '', marker: s.marker, ring: s.ring,
    photoStyle: s.photoStyle, furniture: s.furniture, terrain: s.terrain, shadow: s.shadow,
  });
  const setSlider = (sid, vid, val, fmt) => {
    const el = $(sid); if (el != null && val != null) { el.value = val; $(vid).textContent = fmt(val); }
  };
  setSlider('sWidth', 'vWidth', s.width, (v) => `${v} pt`);
  setSlider('sHalo', 'vHalo', s.halo, (v) => Number(v).toFixed(2));
  setSlider('sShadow', 'vShadow', s.shadow, (v) => Number(v).toFixed(1));
  setSlider('sTerrain', 'vTerrain', s.terrain, (v) => `${Number(v).toFixed(1)}×`);
  setSlider('sMarker', 'vMarker', s.marker, (v) => `${v} in`);
  setSlider('sRing', 'vRing', s.ring, (v) => Number(v).toFixed(2));
  setSlider('sFurniture', 'vFurniture', s.furniture, (v) => `${Number(v).toFixed(2)}×`);
  if ($('sPhotoStyle')) $('sPhotoStyle').value = s.photoStyle || 'mat';
  for (const el of document.querySelectorAll('.swatch')) {
    el.classList.toggle('sel', (el.dataset.hex || '').toLowerCase() === (s.color || '').toLowerCase());
  }
  // output kind + sheet: a continued wallpaper re-enters wallpaper mode on its matched
  // device; otherwise a print, with the exact restored sheet added as a size option.
  if (p.output === 'wallpaper' && p.wallpaper_preset && state.wpPresets.length) {
    state.output = 'wallpaper'; $('output').value = 'wallpaper';
    state.wpPreset = p.wallpaper_preset; $('wpPreset').value = p.wallpaper_preset;
  } else {
    state.output = 'print'; $('output').value = 'print';
    ensurePrintSize(p.print_w_in, p.print_h_in);
  }
  applyOutputVisibility();
  syncSegmentedFaces();   // update the faces directly; no 'change' side-effects
}

// Ensure the print-size <select> can express the continued poster's exact dimensions,
// then select them (and set orientation so applyPrintSize reproduces w×h verbatim).
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
  $('orient').value = state.orientation;
}

async function continueFromPoster(file) {
  if (!file) return;
  setStatus('Opening poster…');
  try {
    const j = await api.continuePoster(file);
    state.session = j.session;
    selectRegion(j.region);
    state.regionName = j.name; $('regionName').textContent = j.name || '';
    state.ovSize = j.overview_size; state.tracks = j.tracks; state.hotspots = j.hotspots;
    state.starterCrop = j.starter_crop; state.crop = null;
    state.hasSpec = false; state.proofStale = true;
    state.edition = j.edition || 2;
    state.files = (j.files || []).slice();
    applyPrefill(j.prefill);
    renderFiles(); updateEditionBadge();
    canvas.setOverview(j.overview, j.overview_size);
    $('dropzone').hidden = true; $('continuePoster').hidden = true;
    $('map').hidden = false; $('addFiles').hidden = false; $('startOver').hidden = false;
    markers.render($('markerList'), (msg) => setStatus(msg));
    $('toFrame').disabled = state.tracks.length === 0;
    if (!state.steps.includes('tracks')) state.steps = ['tracks', 'frame', 'proof'];
    go('tracks');
    showHint(`Edition ${state.edition}: last year's poster is restored — drop this year's GPX to add it, then reframe and render.`);
    setStatus(`Continuing as edition ${state.edition} — ${state.tracks.length} track(s) restored. Add this year's files, or continue to reframe.`);
    announce(`Continuing poster as edition ${state.edition}`);
  } catch (e) {
    setStatus('Could not open that poster: ' + e.message);
  }
}

// --- a11y live-region announcements ---
function announce(msg) { const el = $('a11yStatus'); if (el) el.textContent = msg || ''; }

// Print dims = the chosen sheet (the size select stores portrait-first) turned by
// the orientation control. 'auto' lets the tracks decide: a wide journey lies down,
// a tall one stands up. In wallpaper mode the DEVICE is the sheet: px / ppi (a screen
// is a sheet with a known ppi), and its pixels fix the orientation. Called on Frame
// entry and whenever output/size/preset/orientation change.
function applyPrintSize() {
  if (state.output === 'wallpaper') {
    const p = activePreset();
    if (p) { state.printW = p.px[0] / p.ppi; state.printH = p.px[1] / p.ppi; }
    return;
  }
  const [a, b] = $('size').value.split(',').map(Number);
  const landscape = state.orientation === 'auto'
    ? trackAspectIsWide() : state.orientation === 'landscape';
  state.printW = landscape ? Math.max(a, b) : Math.min(a, b);
  state.printH = landscape ? Math.min(a, b) : Math.max(a, b);
}

// Frame-step controls that only make sense for one output kind: wallpaper swaps the
// size select for the device picker and drops orientation (the device decides),
// the title field and the compass (wallpapers render clean, enforced server-side).
function applyOutputVisibility() {
  const wp = state.output === 'wallpaper';
  $('sizeField').hidden = wp;
  $('wpPresetField').hidden = !wp;
  $('orientField').hidden = wp;
  $('titleField').hidden = wp;
  $('compassRow').hidden = wp;
}

// the human name of the current sheet, for feasibility / zoom-cap messages
function sizeLabel() {
  if (state.output === 'wallpaper') {
    const p = activePreset(); return p ? p.name : 'this device';
  }
  return `${state.printW}×${state.printH}`;
}

// disable proof when the region physically can't hold the selected output size, with
// an honest "pick a smaller size" message (vs. the "draw wider" case for a tight box).
function updateFrameFeasibility() {
  const infeasible = canvas.sizeInfeasibleForRegion();
  $('renderProof').disabled = infeasible;
  $('expressBtn').disabled = infeasible;
  setStatus(infeasible
    ? `This region is too small for ${sizeLabel()} — pick a smaller size.` : '',
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
                                   labels: state.labels, style: state.style,
                                   output: state.output, wpPreset: state.wpPreset });
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
        msg = `This region is too small for ${sizeLabel()} — pick a smaller size.`;
      } else if (!msg || /m\/px/.test(msg)) {
        msg = `This crop is too tight to render sharp for ${sizeLabel()} — draw wider or pick a larger size.`;
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

// Poll a render job to a terminal state, narrating into `statusTarget`. ONE loop
// shared by the final and the bundle, so the retry policy (the 600 ms cadence, the
// 20-miss give-up, the vanished-job 404) can never drift between the two flows.
// Resolves to the result URL on done, or null after reporting the failure.
async function pollJob(jid, statusTarget, runningMsg) {
  let misses = 0;
  for (;;) {
    await sleep(600);
    let s;
    try {
      s = await api.jobStatus(jid);
      misses = 0;
    } catch (e) {
      // a vanished job (404: server restarted, record evicted) can never finish
      if (e.status === 404) { setStatus('Render lost (server restarted?) — try again.', statusTarget); return null; }
      if (++misses >= 20) { setStatus('Lost contact with the server — try again.', statusTarget); return null; }
      continue;
    }
    if (s.state === 'queued') { setStatus('Queued…', statusTarget); continue; }
    if (s.state === 'running') { setStatus(runningMsg, statusTarget); continue; }
    if (s.state === 'error') { setStatus('Render failed: ' + (s.error || 'render error'), statusTarget); return null; }
    if (s.state === 'done') return s.result;
  }
}

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
  // a wallpaper final is always PNG (native device pixels; the server refuses PDF)
  const fmt = state.output === 'wallpaper' ? 'png' : state.finalFormat;
  try {
    const { job } = await api.submitFinal(state.session, fmt, state.embedSpec);
    const result = await pollJob(job, 'proofStatus', 'Rendering the full-resolution final…');
    if (result) {
      await downloadFinal(result, fmt);
      state.lastFinal = { url: result, fmt };            // re-download without re-rendering
      $('downloadAgain').hidden = false;
      setStatus(`Final ${fmt.toUpperCase()} downloaded.`, 'proofStatus');
    }
  } catch (e) { setStatus('Final failed: ' + e.message, 'proofStatus'); }
  $('accept').disabled = false;
}

// --- wallpaper bundle (post-proof): the accepted composition, re-rendered for every
// screen the client ticks, downloaded as one zip. The server re-fits the crop per
// device aspect; a device the region can't satisfy comes back in `skipped`.
let bundleInFlight = false;

function renderBundleCard() {
  const card = $('bundleCard');
  if (!state.wpPresets.length || !state.hasSpec) { card.hidden = true; return; }
  card.hidden = false;
  const host = $('bundleList');
  host.innerHTML = '';
  for (const p of state.wpPresets) {
    const lab = document.createElement('label'); lab.className = 'bundle-item';
    const cb = document.createElement('input'); cb.type = 'checkbox'; cb.value = p.id;
    cb.checked = state.bundlePicks.includes(p.id);
    cb.onchange = () => {
      state.bundlePicks = [...host.querySelectorAll('input:checked')].map((i) => i.value);
      $('bundleBtn').disabled = bundleInFlight || !state.bundlePicks.length;
    };
    const span = document.createElement('span');
    span.textContent = `${p.name} · ${p.px[0]}×${p.px[1]}`;
    lab.append(cb, span); host.appendChild(lab);
  }
  $('bundleBtn').disabled = bundleInFlight || !state.bundlePicks.length;
}

async function downloadBundle() {
  if (bundleInFlight || !state.bundlePicks.length) return;
  bundleInFlight = true; $('bundleBtn').disabled = true;
  setStatus('Queuing wallpaper renders…', 'bundleStatus');
  try {
    const sub = await api.submitWallpapers(state.session, state.bundlePicks, state.embedSpec);
    const skipped = (sub.skipped || []).map((s) => s.preset);
    const result = await pollJob(sub.job, 'bundleStatus',
      `Rendering ${sub.count} wallpaper(s) at native pixels…`);
    if (result) {
      await downloadFinal(result, 'zip');
      setStatus('Bundle downloaded.'
        + (skipped.length ? ` Skipped (region too small): ${skipped.join(', ')}.` : ''),
        'bundleStatus');
    }
  } catch (e) { setStatus('Bundle failed: ' + e.message, 'bundleStatus'); }
  bundleInFlight = false;
  $('bundleBtn').disabled = !state.bundlePicks.length;
}

// --- time-lapse (post-proof): the accepted composition as a film, the day-ordered
// journeys accumulating to the complete poster. The APNG autoplays in the preview.
let tlInFlight = false;
let tlUrl = null;

function renderTimelapseCard() {
  const card = $('timelapseCard');
  if (!card) return;
  if (!state.hasSpec) { card.hidden = true; return; }
  card.hidden = false;
  const sel = $('tlTarget');
  // target picker (only when device presets are available): the accepted sheet, or a
  // wallpaper preset to film at that device's exact native pixels.
  if (sel && !sel.dataset.filled && state.wpPresets.length) {
    const o0 = document.createElement('option');
    o0.value = ''; o0.textContent = 'Accepted sheet';
    sel.appendChild(o0);
    for (const p of state.wpPresets) {
      const o = document.createElement('option');
      o.value = p.id; o.textContent = `${p.name} — ${p.px[0]}×${p.px[1]}`;
      sel.appendChild(o);
    }
    sel.dataset.filled = '1';
  }
  $('tlTargetField').hidden = !state.wpPresets.length;
  $('tlBtn').disabled = tlInFlight;
}

async function renderTimelapse() {
  if (tlInFlight) return;
  tlInFlight = true; $('tlBtn').disabled = true;
  setStatus('Queuing time-lapse…', 'tlStatus');
  try {
    const fmt = state.tlFormat;
    const sub = await api.submitTimelapse(state.session, {
      maxFrames: state.tlFrames, wpPreset: state.tlTarget, embedSpec: state.embedSpec,
      format: fmt });
    const result = await pollJob(sub.job, 'tlStatus', `Painting ${sub.frames} frames…`);
    if (result) {
      const blob = await api.fetchBlob(result);
      if (tlUrl) URL.revokeObjectURL(tlUrl);
      tlUrl = URL.createObjectURL(blob);
      const img = $('tlPreview');
      if (fmt === 'mp4') {                 // an <img> can't play video — download only
        img.hidden = true; img.removeAttribute('src');
      } else {
        img.src = tlUrl; img.hidden = false;               // APNG/WebP autoplay
      }
      const ext = fmt === 'apng' ? 'png' : fmt;            // the apng IS a PNG
      const a = document.createElement('a');
      a.href = tlUrl; a.download = `trailprint-timelapse.${ext}`; a.click();
      setStatus(`Time-lapse ready — ${sub.frames} frames, downloaded.`, 'tlStatus');
    }
  } catch (e) { setStatus('Time-lapse failed: ' + e.message, 'tlStatus'); }
  tlInFlight = false; $('tlBtn').disabled = false;
}

// --- start over ---
function startOver() {
  const hasWork = state.session || state.files.length;
  if (hasWork && !confirm('Start over? This clears the loaded tracks and framing (uploaded photos are kept until the session ends).')) return;
  const regions = state.regions, steps = state.steps;
  Object.assign(state, {
    session: null, ovSize: null, scale: 1, tracks: [], hotspots: [],
    crop: null, starterCrop: null, hasSpec: false, proofStale: false, files: [],
    edition: 1, title: '', lastFinal: null,
  });
  state.regions = regions; state.steps = steps;
  renderFiles(); $('markerList').innerHTML = ''; $('markersBox').hidden = true;
  $('dropzone').hidden = false; $('continuePoster').hidden = false;
  $('map').hidden = true; $('addFiles').hidden = true;
  $('posterImg').removeAttribute('src'); $('toFrame').disabled = true;
  $('titleInput').value = ''; $('downloadAgain').hidden = true; updateEditionBadge();
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
  // living editions: "Continue a poster" opens a PNG whose embedded recipe restores
  // the whole composition. Two entry points (region step + dropzone) share one input.
  const pi = $('posterInput');
  pi.onchange = (e) => { continueFromPoster(e.target.files[0]); e.target.value = ''; };
  $('continuePoster').onclick = () => pi.click();
  $('continuePosterRegion').onclick = () => pi.click();
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
  $('labelsChk').onchange = (e) => {
    state.labels = e.target.checked;
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

  $('bundleBtn').onclick = downloadBundle;
  $('tlBtn').onclick = renderTimelapse;
  $('tlFrames').oninput = (e) => {
    state.tlFrames = Number(e.target.value); $('tlFramesVal').textContent = e.target.value;
  };
  $('tlTarget').onchange = (e) => { state.tlTarget = e.target.value; };
  $('tlFormat').onchange = (e) => { state.tlFormat = e.target.value; };

  const prefs = loadPrefs();
  if (prefs.printSize && /^\d+,\d+$/.test(prefs.printSize) &&
      [...$('size').options].some((o) => o.value === prefs.printSize)) {
    $('size').value = prefs.printSize;
  }
  if (['auto', 'landscape', 'portrait'].includes(prefs.orient)) {
    state.orientation = prefs.orient; $('orient').value = prefs.orient;
  }
  if (!state.wpPresets.length) {
    // no preset table -> no wallpaper mode at all (and ignore a stale wallpaper pref)
    $('outputField').hidden = true;
  } else if (prefs.output === 'wallpaper' || prefs.output === 'print') {
    state.output = prefs.output; $('output').value = prefs.output;
  }
  applyPrintSize();
  applyOutputVisibility();
  const reframeForSheet = () => {
    applyPrintSize();
    canvas.refitForSize(); markers.refreshOutOfFrame(); updateFrameFeasibility();
    if (state.hasSpec) state.proofStale = true;    // the sheet prints; re-proof it
  };
  $('size').onchange = (e) => { savePref('printSize', e.target.value); reframeForSheet(); };
  $('orient').onchange = (e) => {
    state.orientation = e.target.value; savePref('orient', e.target.value);
    reframeForSheet();
  };
  $('output').onchange = (e) => {
    state.output = e.target.value; savePref('output', e.target.value);
    applyOutputVisibility();
    reframeForSheet();
  };
  $('wpPreset').onchange = (e) => {
    state.wpPreset = e.target.value; savePref('wpPreset', e.target.value);
    reframeForSheet();
  };

  // segmented faces reflect the (pref-seeded) hidden selects -- wire last so their
  // initial .on state matches the values set from prefs above.
  wireSegmented();
}

// Both fetches start immediately, in parallel. wire() must run after the presets
// resolve (it decides whether wallpaper mode exists and restores its pref from the
// table) and before the regions are PROCESSED (go() drives the canvas wire() set
// up) -- but the regions REQUEST must not wait behind the presets fetch, or a slow
// presets endpoint blanks the region picker for seconds.
(async () => {
  const pendingRegions = api.getRegions();
  await loadWallpaperPresets();
  wire();
  loadRegions(pendingRegions);
})();
