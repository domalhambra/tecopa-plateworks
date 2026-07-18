// jobs.js — one job store and one poll loop over /api/jobs, shared by every async
// render (final, wallpaper bundle, time-lapse, social kit, in-app mockups). Absorbs the
// old app.js pollJob so the retry policy (600 ms cadence, 20-miss give-up, vanished-job
// 404) can never drift between flows, and every submit shows up in the Exports center.
import * as api from './api.js';

const jobs = [];              // newest first: the live + finished job records this session
let seq = 0;
const subs = new Set();

export function subscribe(fn) { subs.add(fn); return () => subs.delete(fn); }
function notify() { for (const fn of subs) { try { fn(jobs); } catch { /* isolate */ } } }
export function list() { return jobs; }

const sleep = (ms) => new Promise((res) => setTimeout(res, ms));

// Track a submitted job to a terminal state. Registers it in the store (the Exports
// center renders `list()` and re-renders on every notify), narrates via the optional
// onState callback, and resolves to the result URL on done or null on failure. `group`
// ties several jobs into one named kit so Exports can box them together.
export async function track(jid, { kind = 'render', label = 'Render',
                                   runningMsg = 'Rendering…', group = null,
                                   onState = null } = {}) {
  const entry = {
    id: ++seq, jid, kind, label, group,
    state: 'queued', result: null, filename: null, error: null, runningMsg,
  };
  jobs.unshift(entry);
  notify();
  onState && onState('queued');
  let misses = 0;
  for (;;) {
    await sleep(600);
    let s;
    try {
      s = await api.jobStatus(jid);
      misses = 0;
    } catch (e) {
      if (e.status === 404) {                 // vanished: server restarted / record evicted
        entry.state = 'error'; entry.error = 'Render lost (server restarted?) — try again.';
        notify(); onState && onState('error'); return null;
      }
      if (++misses >= 20) {
        entry.state = 'error'; entry.error = 'Lost contact with the server — try again.';
        notify(); onState && onState('error'); return null;
      }
      continue;
    }
    if (s.state !== entry.state) { entry.state = s.state; notify(); onState && onState(s.state); }
    if (s.state === 'error') { entry.error = s.error || 'render error'; notify(); return null; }
    if (s.state === 'done') { entry.result = s.result; notify(); return s.result; }
  }
}

// Record that a job's result was downloaded (and under what filename) — the Exports
// center offers a re-download from the same record without re-rendering.
export function markDownloaded(jid, filename) {
  const e = jobs.find((j) => j.jid === jid);
  if (e) { e.filename = filename; notify(); }
}
