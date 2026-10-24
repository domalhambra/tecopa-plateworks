// order.js — the Order panel: open a customer order in the studio, proof it, save the
// proofed spec to the order, approve it. The engine owns every rule (what a save writes,
// what an approval covers); this module opens, asks, and shows what the engine answered.
//
// What the panel knows about the open order is `open`:
//   session  the studio session Open made; a different session means the order is gone
//   approved the engine's last answer (Open, Save or Approve)
//   current  the proof serial known to be the saved spec, or null (see refresh)
//   dirty    an edit has been seen since Open or the last Save
//   seen     the last proof serial refresh looked at
//   note     the last result (a save, an approval, a 409); cleared when the proof changes
import { state, subscribe } from './store.js';
import * as api from './api.js';
import * as compose from './compose.js';
import * as proof from './proof.js';
import { $, toast, announce } from './ui.js';

let open = null;
let busy = false;

export function initOrder() {
  $('orderOpen').onclick = openSelected;
  $('orderSave').onclick = save;
  $('orderApprove').onclick = approve;
  $('orderSelect').onchange = refresh;
  subscribe(() => refresh());
  // an order made or prepared while the studio stays open shows up on return to it
  window.addEventListener('focus', () => { loadOrders(); });
  loadOrders();
}

// ---- the list ---------------------------------------------------------------------
async function loadOrders() {
  let list = [];
  try { list = await api.listOrders(); } catch { list = []; }
  const sel = $('orderSelect');
  const keep = sel.value;
  sel.innerHTML = '';
  for (const o of list) {
    const opt = document.createElement('option');
    opt.value = o.folder;
    const label = [o.order_number, o.title || o.name].filter(Boolean).join(' · ');
    opt.textContent = label + (o.approved ? ' — approved' : o.prepared ? '' : ' — not prepared');
    opt.disabled = !o.prepared;
    sel.appendChild(opt);
  }
  if (keep && [...sel.options].some((o) => o.value === keep && !o.disabled)) sel.value = keep;
  else {
    const first = [...sel.options].find((o) => !o.disabled);
    if (first) sel.value = first.value;
  }
  // no orders (or no orders folder): the panel stays out of the way
  $('orderPanel').hidden = !list.length;
  refresh();
}

// ---- open -------------------------------------------------------------------------
async function openSelected() {
  const folder = $('orderSelect').value;
  if (!folder || busy) return;
  busy = true; refresh();
  toast('Opening order…', 'working');
  try {
    const j = await api.openOrder(folder);
    // the order's plate joined the engine's regions on Open: fetch the list again so the
    // region name and the zoom cap resolve, as the plate-building flow does
    try { state.regions = await api.getRegions(); } catch { /* keep the old list */ }
    compose.landOpened(j);
    open = { session: j.session, folder: j.order.folder, title: j.order.title,
             approved: !!j.order.approved, current: null, dirty: false,
             seen: proof.proofCount(), note: '', noteError: false, sig: '' };
    toast(`Order opened: ${j.order.title || j.name}`, 'ok');
    announce(`Opened order ${j.order.title || ''}`);
  } catch (e) {
    toast('Could not open that order: ' + e.message, 'error');
    if (!open) setStatus('Could not open that order: ' + e.message, true);
  } finally {
    busy = false; refresh();
  }
}

// ---- save and approve ---------------------------------------------------------------
const baseName = (p) => String(p).split(/[\\/]/).pop();

async function save() {
  if (!open || busy) return;
  const serial = proof.proofCount();
  busy = true; refresh();
  try {
    const r = await api.saveOrder(open.session);
    open.approved = !!r.approved;
    // the engine saved the spec of the last stamped proof. If another proof landed while
    // the request ran, which proof was saved is not known: leave `current` unset.
    const same = proof.proofCount() === serial && !state.proofStale;
    open.current = same ? serial : null;
    if (same) open.dirty = false;
    const files = (r.proof || []).map(baseName);
    if (r.proof_error) {
      open.note = `Saved to the order, but the proof files were not written: ${r.proof_error}`;
      open.noteError = true;
    } else {
      open.note = 'Saved to the order.' + (files.length ? ` Proof files: ${files.join(', ')}.` : '')
        + (open.approved ? ' Approved.' : '');
      open.noteError = false;
    }
    open.sig = sig();
    toast(r.proof_error ? 'Saved, but the proof files were not written' : 'Saved to the order',
      r.proof_error ? 'error' : 'ok');
  } catch (e) {
    open.note = e.message; open.noteError = true; open.sig = sig();
    toast(e.message, 'error');
  } finally {
    busy = false; refresh();
  }
}

async function approve() {
  if (!open || busy) return;
  busy = true; refresh();
  try {
    await api.approveOrder(open.session);
    open.approved = true;
    open.note = 'Approved. Finish prints this proof.'; open.noteError = false; open.sig = sig();
    toast('Order approved', 'ok');
    announce('Order approved');
  } catch (e) {
    open.note = e.message; open.noteError = true; open.sig = sig();
    toast(e.message, 'error');
  } finally {
    busy = false; refresh();
  }
}

// ---- the buttons and the status line ----------------------------------------------------
const sig = () => `${proof.proofCount()}:${state.proofStale ? 1 : 0}`;

function setStatus(text, isError = false) {
  const el = $('orderStatus');
  el.textContent = text;
  el.classList.toggle('is-error', !!isError);
}

// Called by app.js whenever proof state may have changed (like statusbar.refreshProof;
// markers.js flips state.proofStale without a notify) and by this module's own calls.
export function refresh() {
  const sel = $('orderSelect');
  const openBtn = $('orderOpen'), saveBtn = $('orderSave'), approveBtn = $('orderApprove');
  openBtn.disabled = busy || !sel.value;

  // another session landed (Start over, a new upload, a continued poster): the order is closed
  if (open && state.session !== open.session) open = null;
  if (!open) {
    saveBtn.disabled = true; approveBtn.disabled = true;
    if (!busy && !$('orderStatus').classList.contains('is-error')) {
      setStatus(sel.value ? 'Pick an order and open it.' : 'No order is ready to open.');
    }
    return;
  }
  $('orderStatus').classList.remove('is-error');

  const serial = proof.proofCount();
  if (state.hasSpec && state.proofStale) open.dirty = true;   // Open itself leaves proofStale set
  if (serial !== open.seen) {
    open.seen = serial;
    // An approved order has a saved spec, and the first proof after Open with no edit seen
    // is the proof of that spec: it counts as saved, so an untouched order does not read
    // "changed". An order not yet approved is saved by Save and by nothing else, and any
    // proof after an edit is not saved until Save says so.
    if (open.approved && !open.dirty && open.current === null) open.current = serial;
  }
  if (open.sig !== sig() && open.note) { open.note = ''; open.noteError = false; }
  if (!open.note) open.sig = sig();

  const fresh = state.hasSpec && !state.proofStale;
  const saved = fresh && open.current === serial;
  saveBtn.disabled = busy || !fresh;
  approveBtn.disabled = busy || !saved || open.approved;

  let text, isError = false;
  if (busy) text = 'Working…';
  else if (open.note) { text = open.note; isError = open.noteError; }
  else if (!state.hasSpec) {
    text = `${open.title || 'Order'} is open. Render a proof to save it.`;
  } else if (state.proofStale) {
    text = open.approved ? 'Changed since approval: render a proof, then save again.'
                         : 'Edited since the last proof. Render a proof to save it.';
  } else if (!saved) {
    text = open.approved ? 'Changed since approval: save again.'
                         : 'Proof ready. Save it to the order.';
  } else {
    text = open.approved ? 'Approved. Finish prints this proof.'
                         : 'Saved. Approve it when the proof looks right.';
  }
  setStatus(text, isError);
}
