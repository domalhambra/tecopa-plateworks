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
//
// The order's photos (photoView, the engine's orderstudio.photo_view) are listed in
// #orderPhotos and their boxes outlined over the proof in #orderBoxes. Every photo edit goes
// to POST /api/order/photo, which reruns Prepare's layout, clears the approval and unstamps
// the proof; the proof then renders again. Proof pixels are the engine's: the sheet at
// photoView.dpi from the trim's corner, so a click or a drag on the image is a fraction of
// the image times photoView.sheet_px, and a box offset is proof pixels ÷ photoView.dpi.
import { state, subscribe } from './store.js';
import * as api from './api.js';
import * as canvas from './canvas.js';
import * as compose from './compose.js';
import * as markers from './markers.js';
import * as proof from './proof.js';
import { $, toast, announce, wireSegmented } from './ui.js';

let open = null;
let busy = false;

let photoView = null;      // the engine's last photo answer for the open order
let photoSerial = -1;      // the proof serial photoView was measured on (-1: Open's spec)
let measuring = false;     // a read-only photo answer is on its way
let armed = null;          // the photo a click on the proof will place, or null
let bandSeg = null;
const NUDGE_IN = 0.1, NUDGE_BIG_IN = 0.5, NUDGE_SEND_MS = 500;

export function initOrder() {
  $('orderOpen').onclick = openSelected;
  $('orderSave').onclick = save;
  $('orderApprove').onclick = approve;
  $('orderSelect').onchange = refresh;
  bandSeg = wireSegmented($('orderBandSide').querySelector('.segmented'),
    (side) => { if (photoView && side !== photoView.band_side) editPhoto('', { band_side: side }); });
  $('orderPhotos').addEventListener('click', onPhotoClick);
  $('orderPhotos').addEventListener('change', onPhotoChange);
  $('orderBoxes').addEventListener('pointerdown', onBoxesDown);
  $('orderBoxes').addEventListener('keydown', onBoxKey);
  $('orderBoxes').addEventListener('dblclick', (e) => e.stopPropagation());   // not a zoom
  window.addEventListener('keydown', (e) => { if (e.key === 'Escape' && armed) disarm(true); });
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
    armed = null;
    photoView = j.order.photo_view || null;
    photoSerial = -1;
    renderPhotos();
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
  if (open && state.session !== open.session) { open = null; photoView = null; armed = null; renderPhotos(); }
  refreshPhotos();
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

// ---- photos ----------------------------------------------------------------------------
const TAGS = { gps: 'GPS', time: 'Time', manual: 'By hand' };
const photoTag = (p) => (!p.readable ? 'Unreadable' : p.dropped ? 'Dropped'
  : p.tray ? 'Tray' : TAGS[p.source] || 'Placed');
const byFile = (file) => (photoView ? photoView.photos.find((p) => p.file === file) : null);
const round3 = (v) => Math.round(v * 1000) / 1000;

// Send one photo change; the engine answers the new photo list. An edit re-proofs.
async function editPhoto(file, change) {
  if (!open || busy) return;
  busy = true; refresh();
  try {
    const j = await api.orderPhoto(open.session, file, change);
    if (!open || state.session !== open.session) return;
    photoView = j;
    photoSerial = proof.proofCount();
    if (j.edited) {
      open.approved = !!j.approved;
      open.dirty = true; open.current = null;
      state.hotspots = j.hotspots;
      markers.render($('markerList'), (msg) => toast(msg, 'info'));
      if (j.reframed) { state.starterCrop = j.crop_px; canvas.resetFrame(); }
      else canvas.draw();
      state.proofStale = true;
      proof.refreshProofUI();
      const warned = (j.warnings || []).filter((w) => !file || w.startsWith(file + ':'));
      toast(warned.length ? warned[0] : 'Photo changed: re-proofing', warned.length ? 'error' : 'info');
    }
    renderPhotos();
    if (j.edited) proof.renderProof({ auto: true });
  } catch (e) {
    open.note = e.message; open.noteError = true; open.sig = sig();
    toast(e.message, 'error');
    renderPhotos();          // put a dragged box back where the engine has it
  } finally {
    busy = false; refresh();
  }
}

// A new proof was stamped: measure the boxes on it (its crop is the studio's frame now).
function refreshPhotos() {
  const btns = $('orderPhotos').querySelectorAll('button, input');
  btns.forEach((b) => { b.disabled = busy || !open || (b.dataset.off === '1'); });
  if (!open || busy || measuring || !photoView || !photoView.photos.length) return;
  const serial = proof.proofCount();
  if (serial === photoSerial || !state.hasSpec || state.proofStale) return;
  photoSerial = serial; measuring = true;
  const session = open.session;
  api.orderPhoto(session, '', {})
    .then((j) => { if (open && open.session === session && !busy) { photoView = j; renderPhotos(); } })
    .catch(() => { /* the boxes stay as they were measured */ })
    .finally(() => { measuring = false; });
}

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}

function button(label, act, file, off = false) {
  const b = el('button', 'mini', label);
  b.type = 'button'; b.dataset.act = act; b.dataset.file = file;
  if (off) { b.dataset.off = '1'; b.disabled = true; }
  return b;
}

function slider(axis, label, p) {
  const wrap = el('label', '', label);
  const r = el('input', axis);
  r.type = 'range'; r.min = '0'; r.max = '1'; r.step = '0.05'; r.name = axis;
  r.dataset.file = p.file;
  r.value = String(p.crop ? p.crop[axis] : 0.5);
  r.setAttribute('aria-label', `${label} crop focus of ${p.file}`);
  if (!p.placed) { r.dataset.off = '1'; r.disabled = true; }
  return [wrap, r];
}

// The list and the band's end, from photoView; then the outlines over the proof.
function renderPhotos() {
  const host = $('orderPhotos'), band = $('orderBandSide');
  host.innerHTML = '';
  const photos = (open && photoView) ? photoView.photos : [];
  host.hidden = !photos.length;
  band.hidden = !(photos.length && photoView.layout === 'band');
  if (!band.hidden) bandSeg.reflect(photoView.band_side);
  for (const p of photos) {
    const row = el('div', 'order-photo' + (p.dropped ? ' is-dropped' : ''));
    row.dataset.file = p.file;
    const head = el('div', 'op-head');
    head.append(el('span', 'op-name', p.file), el('span', 'op-tag', photoTag(p)));
    head.firstChild.title = p.file;
    const cap = el('input', 'op-caption');
    cap.type = 'text'; cap.maxLength = 60; cap.value = p.caption || '';
    cap.placeholder = 'Caption'; cap.dataset.file = p.file;
    cap.setAttribute('aria-label', `Caption of ${p.file}`);
    const crop = el('div', 'op-crop');
    crop.append(...slider('cx', 'Across', p), ...slider('cy', 'Down', p));
    const acts = el('div', 'op-actions');
    const place = button(armed === p.file ? 'Click the proof…' : (p.tray ? 'Place' : 'Move spot'),
      'place', p.file, p.dropped || !p.readable);
    place.title = 'Then click the proof where the photo was taken';
    if (armed === p.file) place.classList.add('is-armed');
    acts.append(place, button(p.dropped ? 'Restore' : 'Drop', 'drop', p.file));
    if (p.moved && !p.dropped) acts.append(button('Auto box', 'auto', p.file));
    row.append(head, cap, crop, acts);
    if (p.warnings.length) {
      const ul = el('ul', 'op-warn');
      for (const w of p.warnings) ul.append(el('li', '', w));
      row.append(ul);
    }
    host.append(row);
  }
  const general = photoView && open ? photoView.warnings.filter(
    (w) => !photos.some((p) => w.startsWith(p.file + ':') || w.includes(` ${p.file} `))) : [];
  if (general.length) {
    const ul = el('ul', 'op-warn');
    for (const w of general) ul.append(el('li', '', w));
    host.append(ul);
  }
  drawBoxes();
  refreshPhotos();
}

// One outline per open-ground box, in percent of the sheet so it scales with the image.
function drawBoxes() {
  const layer = $('orderBoxes');
  layer.innerHTML = '';
  layer.classList.toggle('is-armed', !!armed);
  const show = !!(open && photoView && photoView.layout === 'open' && state.hasSpec);
  layer.hidden = !(show || armed);
  if (!show) return;
  const [W, H] = photoView.sheet_px;
  for (const p of photoView.photos) {
    if (!p.box_px) continue;
    const [x0, y0, x1, y1] = p.box_px;
    const b = el('div', 'order-box');
    b.dataset.file = p.file; b.tabIndex = 0;
    b.setAttribute('role', 'button');
    b.setAttribute('aria-label', `Box of ${p.file}: drag it, or move it with the arrow keys`);
    Object.assign(b.style, { left: `${(x0 / W) * 100}%`, top: `${(y0 / H) * 100}%`,
                             width: `${((x1 - x0) / W) * 100}%`, height: `${((y1 - y0) / H) * 100}%` });
    b.append(el('span', '', p.file));
    layer.append(b);
  }
}

function armPlace(file) {
  if (!proof.hasFreshProof()) { toast('Render a proof first, then place the photo on it.', 'error'); return; }
  armed = file;
  renderPhotos();
  toast(`Click the proof where ${file} was taken. Esc cancels.`, 'info');
  announce(`Placing ${file}: click the proof`);
}

function disarm(cancelled = false) {
  armed = null;
  renderPhotos();
  if (cancelled) toast('Placing cancelled', 'info');
}

function onPhotoClick(e) {
  const b = e.target.closest('button[data-act]');
  if (!b || !open) return;
  const p = byFile(b.dataset.file);
  if (!p) return;
  if (b.dataset.act === 'place') { armed === p.file ? disarm(true) : armPlace(p.file); }
  else if (b.dataset.act === 'drop') editPhoto(p.file, { dropped: !p.dropped });
  else if (b.dataset.act === 'auto') editPhoto(p.file, { box: null });
}

function onPhotoChange(e) {
  const t = e.target, file = t.dataset.file;
  if (!file || !byFile(file)) return;
  if (t.classList.contains('op-caption')) { editPhoto(file, { caption: t.value }); return; }
  if (t.name === 'cx' || t.name === 'cy') {
    const row = t.closest('.order-photo');
    editPhoto(file, { crop: { cx: Number(row.querySelector('input[name="cx"]').value),
                              cy: Number(row.querySelector('input[name="cy"]').value) } });
  }
}

// The sheet px per screen px of the image as shown (the viewer's zoom included).
function sheetScale() {
  const r = $('posterImg').getBoundingClientRect();
  return { r, sx: photoView.sheet_px[0] / r.width, sy: photoView.sheet_px[1] / r.height };
}

// The offset (inches) that puts the photo square's centre at (cx, cy) proof px.
function offsetFor(p, cx, cy) {
  return { dx_in: round3((cx - p.spot_px[0]) / photoView.dpi),
           dy_in: round3((cy - p.spot_px[1]) / photoView.dpi) };
}

function onBoxesDown(e) {
  if (!photoView || busy || e.button !== 0) return;
  if (armed) {
    e.preventDefault(); e.stopPropagation();
    const { r, sx, sy } = sheetScale();
    const px = (e.clientX - r.left) * sx, py = (e.clientY - r.top) * sy;
    const file = armed;
    armed = null;
    if (px < 0 || py < 0 || px > photoView.sheet_px[0] || py > photoView.sheet_px[1]) {
      toast('That click is off the sheet: press Place again.', 'error'); renderPhotos(); return;
    }
    editPhoto(file, { spot_px: { px, py } });
    return;
  }
  const box = e.target.closest('.order-box');
  const p = box && byFile(box.dataset.file);
  if (!p || !p.box_px) return;                       // the viewer pans
  e.preventDefault(); e.stopPropagation();
  const { sx, sy } = sheetScale();
  const [W, H] = photoView.sheet_px;
  const start = { x: e.clientX, y: e.clientY, x0: p.box_px[0], y0: p.box_px[1] };
  let dx = 0, dy = 0;
  box.setPointerCapture(e.pointerId);
  box.classList.add('is-dragging');
  box.onpointermove = (ev) => {
    dx = (ev.clientX - start.x) * sx; dy = (ev.clientY - start.y) * sy;
    box.style.left = `${((start.x0 + dx) / W) * 100}%`;
    box.style.top = `${((start.y0 + dy) / H) * 100}%`;
  };
  box.onpointerup = box.onpointercancel = (ev) => {
    box.onpointermove = box.onpointerup = box.onpointercancel = null;
    box.classList.remove('is-dragging');
    if (box.hasPointerCapture(ev.pointerId)) box.releasePointerCapture(ev.pointerId);
    if (ev.type === 'pointercancel' || Math.hypot(dx, dy) < 2) { drawBoxes(); return; }
    const [x0, y0, x1, y1] = p.box_px;
    editPhoto(p.file, { box: offsetFor(p, (x0 + x1) / 2 + dx, (y0 + y1) / 2 + dy) });
  };
}

// Arrow keys move a focused box by 0.1 in (Shift: 0.5 in); the move is sent once the keys
// rest, so a run of presses is one edit and one proof.
let nudge = null;
function onBoxKey(e) {
  const step = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] }[e.key];
  const box = e.target.closest('.order-box');
  const p = box && byFile(box.dataset.file);
  if (!step || !p || !p.box_px || busy) return;
  e.preventDefault();
  const inch = (e.shiftKey ? NUDGE_BIG_IN : NUDGE_IN) * photoView.dpi;
  if (!nudge || nudge.file !== p.file) nudge = { file: p.file, dx: 0, dy: 0, timer: null };
  nudge.dx += step[0] * inch; nudge.dy += step[1] * inch;
  const [W, H] = photoView.sheet_px;
  box.style.left = `${((p.box_px[0] + nudge.dx) / W) * 100}%`;
  box.style.top = `${((p.box_px[1] + nudge.dy) / H) * 100}%`;
  clearTimeout(nudge.timer);
  nudge.timer = setTimeout(() => {
    const n = nudge; nudge = null;
    const [x0, y0, x1, y1] = p.box_px;
    editPhoto(p.file, { box: offsetFor(p, (x0 + x1) / 2 + n.dx, (y0 + y1) / 2 + n.dy) });
  }, NUDGE_SEND_MS);
}
