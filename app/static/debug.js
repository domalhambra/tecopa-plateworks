// debug.js — the studio's report to its own engine, for the `tecopa` tool. Each 2
// seconds it posts the studio's small state, and each error the page had, to
// /api/debug/studio, so a fault in the browser can be read from outside. The route
// exists only when the engine runs with TECOPA_DEBUG=1. Without it the first post is
// refused, and the hook stops for the page load: one refused post is the only trace.
// A post that gets no answer (the engine restarts) is silent, and the hook waits.
//
// Three rules hold in every line below.
// 1. The hook can never break the studio. Each entry point swallows its own failure.
//    It shows no toast, writes nothing to the browser log, and stores nothing.
// 2. A report never holds journey data. The state is the eight scalars in snapshot()
//    and nothing else from the store. The engine keeps only those eight keys too.
// 3. The one request goes to the hook's own origin, by path.
import { state } from './store.js';

const TICK_MS = 2000;
const MAX_WAITING = 20;         // errors that wait for the next post; the oldest is dropped
const MAX_MESSAGE = 2000;       // the engine cuts at the same three lengths
const MAX_STACK = 8000;
const MAX_SOURCE = 300;
const MAX_STATE_TEXT = 200;
// The engine refuses a post over 64 KB, and a refused post stops the hook. A UTF-16
// unit is 3 bytes at most in UTF-8, so 20,000 JSON characters of errors are at most
// 60 KB. One error alone can pass that (JSON writes a control character as 6), so
// tick() also measures the bytes and sends no errors in a post that is too large.
const MAX_POST_CHARS = 20000;
const MAX_POST_BYTES = 60000;
const RESEND_MS = 30000;        // the state goes again after this, changed or not
const SEND_LIMIT_MS = 10000;    // a request with no answer ends after this
const TOAST_REPEAT_MS = 5000;   // the same toast text inside this time is one report
const ALPHABET = 'abcdefghijklmnopqrstuvwxyz0123456789';

let tab = '';                   // a random id for this page load, kept nowhere
let started = false;
let stopped = false;
let busy = false;               // one request in flight at a time
let timer = null;
let observer = null;
let toastEl = null;
let lastSent = null;            // the JSON text of the last state sent
let lastSentAt = 0;
let waitUntil = 0;              // no post before this time, after one that got no answer
let lastToast = '';
let lastToastAt = 0;
const waiting = [];             // oldest first

function quiet(fn) { try { fn(); } catch { /* rule 1: never break the studio */ } }

// Any value as text of a limited length. String() can throw for a strange value.
function cut(value, limit) {
  try { return String(value).slice(0, limit); } catch { return ''; }
}

function makeTab() {
  let id = '';
  try {
    for (const b of crypto.getRandomValues(new Uint8Array(16))) id += ALPHABET[b % 36];
  } catch {
    id = '';
    for (let i = 0; i < 16; i++) id += ALPHABET[Math.floor(Math.random() * 36)];
  }
  return id;
}

// Only a scalar leaves the page. If a store field becomes an object one day, the
// report holds null and not the object.
function scalar(v) {
  if (typeof v === 'string') return v.slice(0, MAX_STATE_TEXT);
  if (typeof v === 'boolean') return v;
  if (typeof v === 'number' && Number.isFinite(v)) return v;
  return null;
}

// The whole state report. tests/test_static_registry.py reads this function as text
// and compares its keys with STATE_KEYS in app/debug.py: change them together.
function snapshot() {
  return {
    session: scalar(state.session),
    target: scalar(state.target),
    view: scalar(state.view),
    region: scalar(state.region),
    output: scalar(state.output),
    edition: scalar(state.edition),
    has_spec: scalar(state.hasSpec),
    proof_stale: scalar(state.proofStale),
  };
}

// The message and the stack of a thrown value, which is not always an Error.
function describe(thrown, fallback) {
  const isError = !!thrown && typeof thrown === 'object' && typeof thrown.message === 'string';
  return {
    message: cut(isError ? thrown.message : (fallback || thrown), MAX_MESSAGE),
    stack: isError && typeof thrown.stack === 'string' ? cut(thrown.stack, MAX_STACK) : null,
  };
}

function push(error) {
  if (stopped) return;
  waiting.push(error);
  while (waiting.length > MAX_WAITING) waiting.shift();
}

// The hook's own failures never arrive here: each is swallowed where it happens.
function onError(e) {
  quiet(() => {
    const { message, stack } = describe(e.error, e.message);
    push({
      kind: 'error', message,
      source: e.filename ? cut(e.filename, MAX_SOURCE) : null,
      line: Number.isInteger(e.lineno) ? e.lineno : null,
      stack,
    });
  });
}

function onRejection(e) {
  quiet(() => {
    const { message, stack } = describe(e.reason);
    push({ kind: 'rejection', message, stack });
  });
}

// "The last API error" is the error toast: the studio keeps no last error, each caller
// shows a toast. One toast() call sets three properties, so this can run more than one
// time for one toast: the same text inside TOAST_REPEAT_MS is reported one time. The
// observer sees the toast as it is after the task, so an error toast that another
// toast replaces in the same task is not reported.
function onToast() {
  quiet(() => {
    if (!toastEl || toastEl.hidden || toastEl.dataset.kind !== 'error') return;
    const message = cut(toastEl.textContent || '', MAX_MESSAGE);
    if (!message) return;
    const now = Date.now();
    if (message === lastToast && now - lastToastAt < TOAST_REPEAT_MS) return;
    lastToast = message;
    lastToastAt = now;
    push({ kind: 'toast', message });
  });
}

// The errors for one post, oldest first: as many as stay under the size limit, and
// always one. The others wait for the next tick.
function takeErrors() {
  const errors = [];
  let chars = 0;
  while (waiting.length) {
    const cost = JSON.stringify(waiting[0]).length;
    if (errors.length && chars + cost > MAX_POST_CHARS) break;
    chars += cost;
    errors.push(waiting.shift());
  }
  return errors;
}

// The store notifies only for some changes, so the hook compares and does not
// subscribe: it builds the state each tick and posts only when the text changed or
// errors wait. The first tick always posts, so the tab shows soon after load. The
// state also goes again each RESEND_MS: a restart empties the engine's buffer, and
// an idle tab must show there again.
function tick() {
  quiet(() => {
    const now = Date.now();
    if (stopped || busy || now < waitUntil) return;
    const current = snapshot();
    const text = JSON.stringify(current);
    const due = text !== lastSent || now - lastSentAt >= RESEND_MS;
    if (!due && !waiting.length) return;
    const report = { tab };
    if (due) report.state = current;
    const errors = takeErrors();
    if (errors.length) report.errors = errors;
    let body = JSON.stringify(report);
    if (new TextEncoder().encode(body).length > MAX_POST_BYTES) {
      delete report.errors;     // a 413 would stop the hook: the errors go, the state stays
      body = JSON.stringify(report);
    }
    lastSent = text;
    lastSentAt = now;
    busy = true;
    send(body);
  });
}

function limit() {
  try { return AbortSignal.timeout(SEND_LIMIT_MS); } catch { return undefined; }
}

// The stop rule: a reply that is not 2xx stops the hook for the page load. That is
// the gate-off case (the route does not exist) on the first post, and the hook then
// never sends again to an engine that refused it. A reload starts it again.
// A request with no answer is different: the engine is stopped or restarts. That is
// silent. The hook waits RESEND_MS and then sends the state again.
async function send(body) {
  try {
    const reply = await fetch('/api/debug/studio', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },   // the engine refuses any other type
      body,
      signal: limit(),
    });
    if (!reply.ok) stop();
  } catch {
    lastSent = null;
    waitUntil = Date.now() + RESEND_MS;
  } finally {
    busy = false;
  }
}

function stop() {
  stopped = true;
  quiet(() => clearInterval(timer));
  quiet(() => { if (observer) observer.disconnect(); });
  quiet(() => window.removeEventListener('error', onError));
  quiet(() => window.removeEventListener('unhandledrejection', onRejection));
  waiting.length = 0;
}

// Each part starts alone, so one part that cannot start does not prevent the others.
// With no #toast element there are no toast reports and nothing else changes.
export function init() {
  if (started) return;
  started = true;
  quiet(() => { tab = makeTab(); });
  quiet(() => window.addEventListener('error', onError));
  quiet(() => window.addEventListener('unhandledrejection', onRejection));
  quiet(() => {
    toastEl = document.getElementById('toast');
    if (!toastEl) return;
    observer = new MutationObserver(onToast);
    observer.observe(toastEl, { attributeFilter: ['hidden', 'data-kind'], childList: true,
                                characterData: true, subtree: true });
  });
  quiet(() => { timer = setInterval(tick, TICK_MS); });
}
