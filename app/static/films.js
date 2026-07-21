// films.js — the Film target: the accepted composition as a time-lapse, the
// day-ordered journeys inking themselves onto the terrain to the finished poster.
// Split for the single-window studio: the film SETUP (target sheet, container format,
// light motion, the render action) lives in the LEFT project sidebar (#filmPanel);
// PACING rides the right appearance sidebar (built by app.js from the registry); the
// CENTER stage (#filmStage) is the player. Nothing is gated — the render action simply
// explains what it needs until a fresh proof exists.
import { state, subscribe } from './store.js';
import * as api from './api.js';
import * as jobs from './jobs.js';
import * as inspector from './inspector.js';
import * as proof from './proof.js';
import { $, toast, saveBlob } from './ui.js';

let tlInFlight = false;
let tlUrl = null;
let tlIsVideo = false;

// Build the left-sidebar setup panel ONCE at boot (registry controls must not be
// re-registered on every target switch). Target options populate after presets load.
export function initFilms() {
  const host = $('filmPanel');
  const fmtHost = document.createElement('div');
  inspector.buildSectionPanel('films', fmtHost, { panels: ['Output'] });   // tlFormat + lightMotion

  const g = document.createElement('section');
  g.className = 'insp-group';
  g.innerHTML =
    `<div class="insp-head"><span class="insp-title">Film</span></div>` +
    `<div class="field" id="tlTargetField" hidden><label for="tlTarget">Target</label>` +
    `<div class="select-wrap"><select id="tlTarget"></select></div></div>` +
    `<p class="insp-note" id="tlLightNote" hidden>A Journey Light film (the sun travels with the hike) is a share copy — WebP or MP4.</p>` +
    `<p class="insp-note" id="tlGateNote" hidden>A film animates your proofed poster — render a proof first.</p>` +
    `<button id="tlBtn" class="primary" type="button">Render film</button>`;
  host.append(g, fmtHost);

  populateTarget();
  inspector.attachHelp($('tlTargetField'), 'Render the film at the accepted sheet, or re-target any device preset.');
  $('tlBtn').onclick = renderTimelapse;
  reflectLightNote();
  refreshGate();
}

// Called when the Film target activates (and on shell refreshes while active).
export function buildFilms() {
  populateTarget();
  reflectLightNote();
  refreshGate();
  renderStage();
}

// The no-gate rule: everything visible, the ACTION carries the reason when it can't run.
export function refreshGate() {
  const btn = $('tlBtn'); if (!btn) return;
  const ok = proof.hasFreshProof();
  btn.disabled = tlInFlight || !ok;
  const note = $('tlGateNote'); if (note) note.hidden = ok;
}

function renderStage() {
  const stage = $('filmStage'); if (!stage) return;
  let head = stage.querySelector('.home-head');
  if (!head) {
    stage.innerHTML =
      `<div class="home-head"><h1 id="h-film" tabindex="-1">Film</h1>` +
      `<p class="lede">Your journeys ink themselves onto the terrain, day by day, to the finished poster. ` +
      `Pick pacing on the right and the container on the left, then render.</p></div>` +
      `<div class="tl-stage"><img id="tlPreview" alt="Time-lapse preview" hidden>` +
      `<video id="tlVideo" controls loop playsinline hidden></video>` +
      `<p class="lede" id="tlEmpty">No film yet — it appears here when the render lands.</p></div>`;
  }
  reflectPlayer();
}

function reflectPlayer() {
  const img = $('tlPreview'), vid = $('tlVideo'), empty = $('tlEmpty');
  if (!img || !vid) return;
  img.hidden = !(tlUrl && !tlIsVideo);
  vid.hidden = !(tlUrl && tlIsVideo);
  if (empty) empty.hidden = !!tlUrl;
  if (tlUrl && tlIsVideo && vid.src !== tlUrl) vid.src = tlUrl;
  if (tlUrl && !tlIsVideo && img.src !== tlUrl) img.src = tlUrl;
}

function populateTarget() {
  const sel = $('tlTarget');
  if (!sel) return;
  sel.innerHTML = '';
  const o0 = document.createElement('option'); o0.value = ''; o0.textContent = 'Accepted sheet'; sel.appendChild(o0);
  for (const p of state.wpPresets) {
    const o = document.createElement('option'); o.value = p.id; o.textContent = `${p.name} — ${p.px[0]}×${p.px[1]}`;
    sel.appendChild(o);
  }
  $('tlTargetField').hidden = !state.wpPresets.length;
  sel.value = state.tlTarget || '';
  sel.onchange = (e) => { state.tlTarget = e.target.value; };
}

function reflectLightNote() {
  const note = $('tlLightNote');
  if (note) note.hidden = state.lightMotion === 'none';
}

// keep the light-motion note honest as the registry select changes it
subscribe((path) => { if (path === null || path === 'lightMotion' || path === 'tlFormat') reflectLightNote(); });

export async function renderTimelapse() {
  if (tlInFlight) return;
  if (!proof.hasFreshProof()) { toast('Re-proof first — the film renders the accepted composition.', 'error'); return; }
  tlInFlight = true; refreshGate();
  const fmt = state.tlFormat;
  toast('Queuing time-lapse…', 'working');
  try {
    const sub = await api.submitTimelapse(state.session, {
      maxFrames: state.tlFrames, stepMs: state.tlStepMs, holdMs: state.tlHoldMs, leaderMs: state.tlLeaderMs,
      wpPreset: state.tlTarget, embedSpec: state.embedSpec, format: fmt, lightMotion: state.lightMotion || 'none',
    });
    const result = await jobs.track(sub.job, {
      kind: 'film', label: `Time-lapse ${fmt.toUpperCase()} · ${sub.frames} frames`,
      runningMsg: `Painting ${sub.frames} frames…`,
      onState: (s) => toast(s === 'running' ? `Painting ${sub.frames} frames…` : s === 'queued' ? 'Queued…' : '', 'working'),
    });
    if (result) {
      const ext = fmt === 'apng' ? 'png' : fmt;
      const { blob, filename } = await api.fetchDownload(result, `tecopa-timelapse.${ext}`);
      jobs.markDownloaded(sub.job, filename);
      if (tlUrl) URL.revokeObjectURL(tlUrl);
      tlUrl = URL.createObjectURL(blob);
      tlIsVideo = fmt === 'mp4';
      renderStage();
      saveBlob(blob, filename);
      toast(`Time-lapse ready — ${sub.frames} frames, downloaded.`, 'ok');
    }
  } catch (e) {
    // the server's honest 422 (e.g. APNG + moving sun, or no timestamps) reads well as-is
    toast('Time-lapse failed: ' + e.message, 'error');
  }
  tlInFlight = false; refreshGate();
}
