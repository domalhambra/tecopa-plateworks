// proof.js — proof orchestration for the studio: the single-flight + coalescing
// auto-proof, the stale-proof treatment, the session proof-history filmstrip, A/B
// variant compare, and the accept→final / express flows. This is the old app.js proof
// engine, preserved verbatim in its load-bearing details (the humanized 422, the
// stamp-only-on-success rule, the one-proof-at-a-time guard) and grown up for a studio
// where edits re-proof themselves.
import { state, activePreset, snapshot, applySnapshot } from './store.js';
import * as api from './api.js';
import * as canvas from './canvas.js';
import * as jobs from './jobs.js';
import { $, toast, announce, saveBlob } from './ui.js';

let hooks = {};
let proofInFlight = false;   // one proof at a time: /api/proof renders synchronously on
                             // the server, so two in flight block the event loop twice.
let coalesced = false;       // a settle fired while a proof was in flight -> run once more
let settleTimer = null;
const SETTLE_MS = 800;       // debounce: fire one proof after edits stop landing

let proofUrl = null;         // current proof object URL (revoked on replace: no leak)
const history = [];          // {url, snap, t} ring buffer, capped; each an old proof
const HISTORY_CAP = 8;
let variantB = null;         // {url, snap} — the pinned B side of an A/B compare
let abValue = 0;             // 0..100 scrub position (A on the left)

export function initProof(h = {}) {
  hooks = h;
  $('renderProof').onclick = () => renderProof();
  $('reproofBtn').onclick = () => renderProof();
  $('acceptBtn').onclick = acceptFinal;
  $('expressBtn').onclick = expressFinal;
  const dl = $('downloadAgain');
  if (dl) dl.onclick = () => {
    if (state.lastFinal) downloadFinal(state.lastFinal.url, state.lastFinal.fmt)
      .catch(() => toast('That final has expired — accept again to re-render.', 'error'));
  };
  const auto = $('autoProofChk');
  if (auto) {
    auto.checked = state.autoProof;
    auto.onchange = (e) => { state.autoProof = e.target.checked; savePrefAuto(e.target.checked); };
  }
  const pinB = $('abPinBtn');
  if (pinB) pinB.onclick = pinVariantB;
  const clearB = $('abClearBtn');
  if (clearB) clearB.onclick = clearVariantB;
  const scrub = $('abScrub');
  if (scrub) scrub.oninput = (e) => { abValue = Number(e.target.value); paintAB(); };
}

function savePrefAuto(v) {
  try {
    const p = JSON.parse(localStorage.getItem('trailprint') || '{}');
    p.autoProof = v; localStorage.setItem('trailprint', JSON.stringify(p));
  } catch { /* private mode */ }
}

// The live proof's object URL (or null) — the Social studio re-fits it into each format
// preview. hasFreshProof() is the gate for social/film output: a stamped, non-stale spec.
export function currentProofUrl() { return proofUrl; }
export function hasFreshProof() { return !!proofUrl && state.hasSpec && !state.proofStale; }

// The current crop in OVERVIEW px, or null (draw a frame first).
function cropForProof() {
  const c = state.crop; if (!c || !state.scale) return null;
  const s = state.scale;
  return [Math.min(c[0], c[2]) / s, Math.min(c[1], c[3]) / s,
          Math.max(c[0], c[2]) / s, Math.max(c[1], c[3]) / s];
}

// The human name of the current sheet, for feasibility / zoom-cap messages.
export function sizeLabel() {
  if (state.output === 'wallpaper') {
    const p = activePreset(); return p ? p.name : 'this device';
  }
  return `${state.printW}×${state.printH}`;
}

// Auto-proof: schedule one proof after edits settle. Single-flight + coalescing — a
// settle that lands mid-render sets `coalesced`, and exactly one follow-up runs when the
// in-flight proof finishes. Only meaningful once a proof exists and auto is on.
export function scheduleAutoProof() {
  if (!state.autoProof || !state.hasSpec || !state.proofStale) return;
  if (state.output === 'wallpaper' && state.wpPreset === 'custom' && !activePreset()) return;
  if (canvas.sizeInfeasibleForRegion()) return;
  if (settleTimer) clearTimeout(settleTimer);
  settleTimer = setTimeout(() => {
    settleTimer = null;
    if (proofInFlight) { coalesced = true; return; }
    renderProof({ auto: true });
  }, SETTLE_MS);
}

// Render a proof; on success stamps the server spec, shows it in the center, and (unless
// this was the very first proof) pushes the prior proof into the history filmstrip.
export async function renderProof({ auto = false } = {}) {
  if (proofInFlight) { if (auto) coalesced = true; return false; }
  if (state.output === 'wallpaper' && state.wpPreset === 'custom' && !activePreset()) {
    if (!auto) toast('Enter the custom device’s width, height and ppi first', 'error');
    return false;
  }
  if (canvas.sizeInfeasibleForRegion()) { hooks.onFeasibility && hooks.onFeasibility(); return false; }
  const ov = cropForProof();
  if (!ov) { if (!auto) toast('Draw a frame first', 'error'); return false; }
  proofInFlight = true;
  refreshProofUI();
  toast(auto ? 'Re-proofing…' : 'Rendering proof…', 'working');
  try {
    const blob = await api.proof(state.session, ov, state.printW, state.printH,
      { title: state.title, contours: state.contours, compass: state.compass,
        biome: state.biome, labels: state.labels, style: state.style,
        output: state.output, wpPreset: state.wpPreset, customDevice: state.customDevice });
    // push the outgoing proof into history before replacing it (skip the very first)
    if (proofUrl) pushHistory(proofUrl);
    proofUrl = URL.createObjectURL(blob);
    $('posterImg').src = proofUrl;
    state.hasSpec = true; state.proofStale = false;
    state.lastFinal = null;
    const da = $('downloadAgain'); if (da) da.hidden = true;
    hooks.onProofed && hooks.onProofed();
    refreshProofUI();
    toast('Proof ready — accept to render the full-resolution final', 'ok');
    return true;
  } catch (e) {
    handleProofError(e);
    return false;
  } finally {
    proofInFlight = false;
    refreshProofUI();
    // a settle landed mid-render: run exactly one more (coalescing many edits into one).
    if (coalesced) { coalesced = false; scheduleAutoProof(); }
  }
}

// The old renderProof's humanized 422: prefer the server's sentence; translate the terse
// zoom-cap numbers into operator language; the infeasible-size case is a smaller-size fix.
function handleProofError(e) {
  if (e.status === 422) {
    let msg = e.message && !/^HTTP /.test(e.message) ? e.message : '';
    if (canvas.sizeInfeasibleForRegion()) {
      msg = `This region is too small for ${sizeLabel()} — pick a smaller size.`;
    } else if (!msg || /m\/px/.test(msg)) {
      msg = `This crop is too tight to render sharp for ${sizeLabel()} — draw wider or pick a larger size.`;
    }
    toast(msg, 'error');
  } else {
    toast('Proof failed: ' + e.message, 'error');
  }
}

// Reflect the proof state into the center: the stale pill, the empty state, the buttons.
export function refreshProofUI() {
  const stale = $('proofStale');
  if (stale) stale.hidden = !(state.hasSpec && state.proofStale);
  const empty = $('proofEmpty');
  if (empty) empty.hidden = state.hasSpec;
  const card = $('posterCard');
  if (card) card.hidden = !state.hasSpec;
  const img = $('posterImg');
  if (img) img.classList.toggle('is-stale', state.hasSpec && state.proofStale);
  const accept = $('acceptBtn');
  if (accept) { accept.hidden = !state.hasSpec; accept.disabled = proofInFlight || !state.hasSpec || state.proofStale; }
  const rp = $('renderProof');
  if (rp) {
    const infeasible = canvas.sizeInfeasibleForRegion();
    rp.disabled = proofInFlight || infeasible;
    rp.textContent = state.hasSpec ? 'Re-proof' : 'Render proof';
  }
  const rb = $('reproofBtn'); if (rb) rb.disabled = proofInFlight;
  // express (proof + final in one) is a first-run shortcut; once a proof exists the
  // explicit Re-proof + Accept pair is clearer, so retire it.
  const eb = $('expressBtn'); if (eb) { eb.hidden = state.hasSpec; eb.disabled = proofInFlight || canvas.sizeInfeasibleForRegion(); }
  renderFilmstrip();
}

// --- proof history filmstrip -------------------------------------------------------
function pushHistory(url) {
  history.unshift({ url, snap: snapshot(), t: Date.now() });
  while (history.length > HISTORY_CAP) {
    const old = history.pop();
    if (old && old.url) URL.revokeObjectURL(old.url);   // no leak on eviction
  }
}

function renderFilmstrip() {
  const strip = $('proofFilmstrip');
  if (!strip) return;
  strip.hidden = history.length === 0;
  strip.innerHTML = '';
  history.forEach((h, i) => {
    const b = document.createElement('button');
    b.type = 'button'; b.className = 'strip-thumb';
    b.title = 'Restore this look (re-proofs)';
    const img = document.createElement('img'); img.src = h.url; img.alt = `Earlier proof ${i + 1}`;
    b.appendChild(img);
    b.onclick = () => restoreHistory(i);
    strip.appendChild(b);
  });
}

// Restoring a history entry applies its LOOK (a snapshot of picture decisions), which
// stales the proof and — via the accept gate — forces a fresh re-proof. The old blob is
// never reused for a final: the server holds exactly one stamped spec.
function restoreHistory(i) {
  const h = history[i];
  if (!h) return;
  applySnapshot(h.snap);
  toast('Restored an earlier look — re-proof to render it', 'info');
  hooks.onSnapshotApplied && hooks.onSnapshotApplied();
  scheduleAutoProof();
}

// --- A/B compare -------------------------------------------------------------------
// Pin the current proof as B; the live proof is A. The scrub reveals B over A via a
// clip. Switching to B for good is just applying B's snapshot (→ stale → re-proof).
async function pinVariantB() {
  if (!proofUrl) { toast('Render a proof first to pin it as B', 'error'); return; }
  if (variantB && variantB.url) URL.revokeObjectURL(variantB.url);
  // B owns an INDEPENDENT copy of the current pixels (re-fetch the live blob URL into a
  // fresh object URL) so evicting the shared proof from history can never free B's image.
  const blob = await api.fetchBlob(proofUrl);
  variantB = { url: URL.createObjectURL(blob), snap: snapshot() };
  const ab = $('abBar'); if (ab) ab.hidden = false;
  const bimg = $('posterImgB'); if (bimg) bimg.src = variantB.url;
  abValue = 50; const scrub = $('abScrub'); if (scrub) scrub.value = '50';
  paintAB();
  toast('Pinned B — scrub to compare, or restore B’s look to keep it', 'ok');
}

function clearVariantB() {
  variantB = null;
  const ab = $('abBar'); if (ab) ab.hidden = true;
  const bimg = $('posterImgB'); if (bimg) bimg.removeAttribute('src');
  paintAB();
}

function paintAB() {
  const bwrap = $('posterBWrap');
  if (!bwrap) return;
  if (!variantB) { bwrap.style.clipPath = 'inset(0 100% 0 0)'; return; }
  // reveal B from the left up to abValue%
  bwrap.style.clipPath = `inset(0 ${100 - abValue}% 0 0)`;
}

// Express: proof, then chain straight into the final on success (the Accept gate still
// stands as the explicit path).
export async function expressFinal() {
  const ok = await renderProof();
  if (ok) await acceptFinal();
}

async function downloadFinal(url, fmt) {
  const { blob, filename } = await api.fetchDownload(url, `trailprint.${fmt}`);
  saveBlob(blob, filename);
  return filename;
}

export async function acceptFinal() {
  if (!state.hasSpec || state.proofStale) {
    toast('Something changed since the last proof — re-proof first.', 'error');
    return;
  }
  const accept = $('acceptBtn'); if (accept) accept.disabled = true;
  const fmt = state.output === 'wallpaper' ? 'png' : state.finalFormat;   // wallpaper is PNG-only
  toast('Queuing final render…', 'working');
  try {
    const { job } = await api.submitFinal(state.session, fmt, state.embedSpec);
    const result = await jobs.track(job, {
      kind: 'final', label: `Final ${fmt.toUpperCase()}`,
      runningMsg: 'Rendering the full-resolution final…',
      onState: (s) => toast(s === 'running' ? 'Rendering the full-resolution final…'
        : s === 'queued' ? 'Queued…' : s === 'error' ? 'Final render failed.' : '', 'working'),
    });
    if (result) {
      const filename = await downloadFinal(result, fmt);
      jobs.markDownloaded(job, filename);
      state.lastFinal = { url: result, fmt };
      const da = $('downloadAgain'); if (da) da.hidden = false;
      toast(`Final ${fmt.toUpperCase()} downloaded.`, 'ok');
    }
  } catch (e) { toast('Final failed: ' + e.message, 'error'); }
  refreshProofUI();
}
