// statusbar.js — the bottom status strip + the Exports slide-over drawer. The strip is
// the whole app's always-visible truth line: proof freshness on the left (visible even
// when the center stage shows the map, a film, or the social gallery), the newest
// active render job on the right, and the Jobs button opening the drawer that hosts
// the existing exports list (#jobList — exports.js renders into it unchanged).
import { state } from './store.js';
import * as jobs from './jobs.js';
import { $ } from './ui.js';

let hooks = {};

export function initStatusbar(h = {}) {
  hooks = h;
  jobs.subscribe(refreshJobs);
  $('jobsBtn').onclick = toggleDrawer;
  $('jobsClose').onclick = closeDrawer;
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !$('jobsDrawer').hidden) closeDrawer();
  });
  refreshJobs(jobs.list());
  refreshProof();
}

function refreshJobs(list) {
  const active = list.filter((j) => j.state === 'queued' || j.state === 'running');
  const sb = $('sbJob');
  if (active.length) {
    sb.hidden = false;
    $('sbJobLabel').textContent = active.length === 1
      ? `${active[0].label} — ${active[0].state === 'running' ? active[0].runningMsg : 'queued'}`
      : `${active.length} renders in flight`;
  } else {
    sb.hidden = true;
  }
  $('jobsBtn').textContent = list.length ? `Jobs (${list.length})` : 'Jobs';
}

// Called by app.js/proof.js whenever proof state may have changed (the strip has no
// subscription of its own — markers.js flips state.proofStale without a notify).
export function refreshProof() {
  const el = $('sbProof');
  if (!el) return;
  el.textContent = !state.session ? ''
    : !state.hasSpec ? 'No proof yet'
    : state.proofStale ? 'Changes not proofed'
    : 'Proof up to date';
  el.classList.toggle('is-stale', !!(state.hasSpec && state.proofStale));
}

export function openDrawer() { $('jobsDrawer').hidden = false; $('h-queue').focus(); }
export function closeDrawer() { $('jobsDrawer').hidden = true; }
function toggleDrawer() { $('jobsDrawer').hidden ? openDrawer() : closeDrawer(); }
