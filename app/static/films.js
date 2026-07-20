// films.js — the Films section: the accepted composition as a time-lapse, the
// day-ordered journeys inking themselves onto the terrain to the finished poster. Full
// pacing (frames, per-frame hold, final hold, opening hold — the API always accepted
// these; the old UI exposed only frame count), the container choice (APNG archival vs
// WebP/MP4 share twins), and Journey Light motion (the sun travels with the hike). Uses
// the generic registry controls for pacing/format/motion and adds the target picker,
// the submit, and the preview.
import { state } from './store.js';
import * as api from './api.js';
import * as jobs from './jobs.js';
import * as inspector from './inspector.js';
import * as proof from './proof.js';
import { subscribe } from './store.js';
import { $, toast, saveBlob } from './ui.js';

let tlInFlight = false;
let tlUrl = null;
let built = false;

export function buildFilms() {
  const panel = $('panel-films');
  if (!state.hasSpec) {
    panel.innerHTML = '<section class="insp-group"><p class="lede insp-empty">Render and accept a proof first — a film is your accepted poster, animated. Frame it in Compose, then come back.</p></section>';
    built = false;
    return;
  }
  panel.innerHTML = '';
  const controls = document.createElement('div');
  panel.appendChild(controls);
  inspector.buildSectionPanel('films', controls);   // pacing + format + light motion

  const g = document.createElement('section');
  g.className = 'insp-group';
  g.innerHTML =
    `<div class="insp-head"><span class="insp-title">Target &amp; render</span></div>` +
    `<div class="field" id="tlTargetField" hidden><label for="tlTarget">Target</label>` +
    `<div class="select-wrap"><select id="tlTarget"></select></div></div>` +
    `<p class="insp-note" id="tlLightNote" hidden>A Journey Light film (the sun travels with the hike) is a share copy — WebP or MP4.</p>` +
    `<div class="tl-preview"><img id="tlPreview" alt="" hidden></div>` +
    `<button id="tlBtn" class="primary" type="button">Render time-lapse</button>`;
  panel.appendChild(g);

  populateTarget();
  $('tlBtn').onclick = renderTimelapse;
  reflectLightNote();
  built = true;
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
subscribe((path) => { if (built && (path === null || path === 'lightMotion' || path === 'tlFormat')) reflectLightNote(); });

async function renderTimelapse() {
  if (tlInFlight) return;
  if (!proof.hasFreshProof()) { toast('Re-proof first — the film renders the accepted composition.', 'error'); return; }
  tlInFlight = true; $('tlBtn').disabled = true;
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
      const img = $('tlPreview');
      if (img) {
        if (fmt === 'mp4') { img.hidden = true; img.removeAttribute('src'); }   // <img> can't play video
        else { img.src = tlUrl; img.hidden = false; }
      }
      saveBlob(blob, filename);
      toast(`Time-lapse ready — ${sub.frames} frames, downloaded.`, 'ok');
    }
  } catch (e) {
    // the server's honest 422 (e.g. APNG + moving sun, or no timestamps) reads well as-is
    toast('Time-lapse failed: ' + e.message, 'error');
  }
  tlInFlight = false; const b = $('tlBtn'); if (b) b.disabled = false;
}
