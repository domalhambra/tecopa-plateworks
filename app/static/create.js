// create.js — the GPX-first "no plate covers these tracks" creation flow.
//
// When an upload lands outside every built plate (the COMMON case in real use, not an
// error), the server 422s and this module takes over: a modal dialog that plans a new
// terrain plate from the dropped tracks, shows an honest cost card, builds the plate as a
// background job with streamed progress, then re-uploads the kept tracks so they land on
// the fresh plate. The backend contract (/api/regions/plan|build) is fixed and shipped;
// this is purely the UI over it.
//
// The logic is ported from the pre-Studio wizard (enterCreationFlow / startBuild /
// showBuildError), re-homed in a <dialog> so it works from any section and dodges the
// map-pane layout entirely. The lessons from that wizard's nine confirmed bugs are wired
// in here: the client region cache is refreshed before the re-upload (so the Frame-step
// guards resolve the new plate), the stale matched-region STATE is cleared (refreshShell
// reads state, not the DOM), and the dialog's Cancel/Esc is an always-available exit.
//
// State is a small machine so the flow survives adversarial input (rapid re-drops, a
// Cancel mid-submit, a plan that fails). `phase` is the single source of truth; `#buildGo`
// is bound ONCE and reads `currentPlan`, so there are no stale-closure builds.
import { state } from './store.js';
import * as api from './api.js';
import { $, toast, announce } from './ui.js';

let hooks = {};            // { reupload(files) -> Promise, refresh() } supplied by app.js
let pollTimer = null;
let keptFiles = [];        // the File[] the failed upload kept, re-uploaded on build done
let currentPlan = null;    // the resolved, BUILDABLE plan for this flow (null otherwise)
let flowGen = 0;           // bumped on each new flow AND on dialog close; a stale async
                           // continuation (plan/build/poll) whose captured gen no longer
                           // matches bails, so a rapid re-drop or a close can't cross wires
let phase = 'idle';        // 'idle' | 'planning' | 'ready' | 'building'

export function initCreate(h = {}) {
  hooks = h;
  // Bind the primary action ONCE. It acts on `currentPlan`, so a re-plan can never leave a
  // stale closure wired to a previous plan, and a click with no ready plan is a safe no-op.
  $('buildGo').onclick = onBuildClick;
  $('buildCancel').onclick = () => $('buildDialog').close();
  // Cancel button and Esc both fire the dialog's native 'close'. Cancel any in-flight flow;
  // if a build was actually running, say so — it finishes server-side and the plate appears
  // on the next region refresh (in-memory job, single-operator v1).
  $('buildDialog').addEventListener('close', onDialogClose);
}

function onDialogClose() {
  const wasBuilding = phase === 'building';
  flowGen++;                 // invalidate any in-flight plan/build continuation
  stopPolling();
  phase = 'idle';
  currentPlan = null;
  if (wasBuilding) {
    toast('Build continues in the background — it’ll appear in your plates when done.', 'info');
  }
}

function onBuildClick() {
  if (phase !== 'ready' || !currentPlan) return;   // only actionable once a buildable plan resolved
  startBuild(currentPlan);
}

// Entry: the upload 422'd with "no available region". A fresh drop SUPERSEDES any in-flight
// flow — stop the old poll and take the new files (a build already submitted keeps running
// server-side; we simply stop tracking it). Then clear the stale matched-region label and plan.
export async function enterCreationFlow(files) {
  const gen = ++flowGen;     // this flow supersedes any earlier one; its stale awaits bail
  stopPolling();
  keptFiles = Array.from(files || []);
  currentPlan = null;
  phase = 'planning';
  // This card is about a NEW region: clear the previously matched region so the toolbar
  // label doesn't lie. Clear the STATE (refreshShell reads state.regionName), not the DOM.
  state.region = null; state.regionName = ''; state.regionKind = '';
  hooks.refresh && hooks.refresh();
  toast('', 'info');   // drop the lingering "Uploading…" working-toast; the modal speaks now

  resetDialog();
  $('buildLede').textContent = 'Planning a terrain plate for these tracks…';
  const dlg = $('buildDialog');
  if (!dlg.open) dlg.showModal();

  let p;
  try { p = await api.planRegion(keptFiles); }
  catch (e) { if (gen === flowGen) showPlanError('Planning failed: ' + e.message); return; }
  if (gen !== flowGen) return;   // superseded by a newer drop, or the dialog was closed

  $('buildName').value = p.name_prefill || '';

  if (!p.us_covered) {
    $('buildLede').textContent =
      'These tracks are outside USGS 3DEP coverage — terrain data is US-only, '
      + 'so a plate can’t be built for them here.';
    phase = 'idle'; hideBuildAction();
    return;
  }
  if (!p.prep_ready) {
    $('buildLede').textContent = 'The region-build toolchain isn’t set up yet. In the project folder run:';
    $('buildEstimate').textContent =
      'python3 -m venv .venv-prep && source .venv-prep/bin/activate\n'
      + 'pip install -r requirements-regionprep.txt';
    $('buildEstimate').hidden = false;
    phase = 'idle'; hideBuildAction();
    return;
  }
  if (p.over_budget) {
    // The build endpoint rejects an over-budget grid server-side; say so up front rather
    // than let the Build button 422. Corridor-scale terrain stays a deliberate CLI run.
    $('buildLede').textContent =
      'This area is too large to build from the app (corridor-scale terrain). '
      + 'Build it deliberately from the terminal with region_prep.py.';
    $('buildEstimate').textContent = estimateLine(p);
    $('buildEstimate').hidden = false;
    phase = 'idle'; hideBuildAction();
    return;
  }

  // Buildable: arm the flow. currentPlan + phase gate the (already-bound) Build button.
  currentPlan = p;
  phase = 'ready';
  $('buildLede').textContent = 'Tecopa Printworks can build the terrain for these tracks from USGS data.';
  $('buildEstimate').textContent = estimateLine(p);
  $('buildEstimate').hidden = false;
  $('buildNameField').hidden = false;
  $('buildGo').hidden = false; $('buildGo').disabled = false;
}

function estimateLine(p) {
  return `Terrain: ${p.resolution_m} m grid (${p.grid[0]}×${p.grid[1]}), `
    + `~${Math.round(p.est_dem_mb)} MB download in ${p.n_slices} slice(s).`;
}

async function startBuild(p) {
  const gen = flowGen;       // this build belongs to the current flow; a close/re-drop bumps it
  const name = $('buildName').value.trim() || p.name_prefill || p.id;
  // Enter 'building' BEFORE the submit await, so a Cancel/Esc during the POST is treated as
  // a build-in-progress close (background toast) and the resumed continuation bails.
  phase = 'building';
  $('buildGo').disabled = true;
  $('buildError').hidden = true;
  $('buildProgress').hidden = false; $('buildProgress').textContent = 'Starting…';
  let jid;
  try {
    ({ job: jid } = await api.buildRegion({ id: p.id, name, bbox: p.bbox, epsg: p.epsg }));
  } catch (e) { if (gen === flowGen) { phase = 'ready'; showBuildError(e.message); } return; }
  if (gen !== flowGen) return;   // closed during the submit await — build runs server-side, stop here
  announce('Building the terrain plate');
  stopPolling();
  pollTimer = setInterval(async () => {
    let st;
    try { st = await api.buildStatus(jid); } catch { return; }   // transient poll miss
    if (st.state === 'running' || st.state === 'queued') {
      if (st.progress) $('buildProgress').textContent = st.progress;
      return;
    }
    stopPolling();
    if (gen !== flowGen) return;   // dialog dismissed / superseded mid-build — don't hijack the UI
    if (st.state === 'error') { phase = 'ready'; showBuildError(st.error || 'Build failed'); return; }

    // Done. Refresh the client region cache BEFORE re-uploading so activeRegion() /
    // metresPerPx() resolve the new plate — the Frame-step refit / zoom-floor / feasibility
    // guards all key on its bounds and would silently no-op for exactly the new region.
    try { state.regions = await api.getRegions(); } catch { /* keep the stale list */ }
    state.regionKind = 'Built';   // the chip reads "Built" (vs "Matched") after a fresh build
    phase = 'idle';               // so the close() below doesn't fire the background toast
    const files = keptFiles; keptFiles = []; currentPlan = null;
    $('buildDialog').close();
    toast(st.result && st.result.labels_note
      ? `Region built (${st.result.labels_note}) — loading your tracks…`
      : 'Region built — loading your tracks…', 'ok');
    hooks.reupload && await hooks.reupload(files);   // now matches the new plate; chip = Built
  }, 1000);
}

// A build that was SUBMITTED then failed: retryable, so re-show the Build button (currentPlan
// is still valid and phase is back to 'ready').
function showBuildError(msg) {
  $('buildError').textContent = msg;
  $('buildError').hidden = false;
  $('buildProgress').hidden = true;
  $('buildGo').hidden = false; $('buildGo').disabled = false;
}

// Planning itself failed: there is no plan to build, so keep the Build button hidden. Cancel
// remains as the always-available exit.
function showPlanError(msg) {
  phase = 'idle'; currentPlan = null;
  $('buildError').textContent = msg;
  $('buildError').hidden = false;
  $('buildProgress').hidden = true;
  hideBuildAction();
}

// The honest non-build states (US-only / no venv-prep / over budget): no Build button and
// no name field, but Cancel stays as the exit. The old wizard's card dead-ended here —
// both non-build states hid the only button and Start Over was still hidden.
function hideBuildAction() {
  $('buildNameField').hidden = true;
  $('buildGo').hidden = true;
}

// Fresh card: hide the Build button until a BUILDABLE plan resolves (so there is never a
// clickable button bound to no plan or a stale one), and clear the name so a prior flow's
// prefill can't ride into a new region.
function resetDialog() {
  $('buildEstimate').textContent = ''; $('buildEstimate').hidden = true;
  $('buildProgress').textContent = ''; $('buildProgress').hidden = true;
  $('buildError').textContent = ''; $('buildError').hidden = true;
  $('buildNameField').hidden = true;
  $('buildName').value = '';
  $('buildGo').hidden = true; $('buildGo').disabled = false;
}

function stopPolling() { if (pollTimer) { clearInterval(pollTimer); pollTimer = null; } }
