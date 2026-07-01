// canvas.js — all map drawing and the two pointer interactions:
//   tracks mode  -> drag a hotspot to reposition it (persisted via /api/markers/move)
//   frame  mode  -> draw an aspect-locked crop box (fixed to grow in all 4 directions)
// The side-list (markers.js) stays the unambiguous identity-edit surface, so the map
// only handles MOVE — no click-vs-drag ambiguity on the dot.
import { state, activeRegion, metresPerPx, cropOverviewPx } from './state.js';
import * as api from './api.js';

const BASE_W = 680;            // internal canvas width in px; scaled to overview
const HIT_R = 10;              // marker hit radius (canvas px)
const DRAG_THRESH = 3;         // px of motion before a marker press becomes a drag
const DOT = '#D8A23A';         // on-map marker gold (matches the design mockup)
const DOT_STROKE = 'rgba(40,28,18,0.9)';
const PILL_FILL = '#F3EDDF';   // cream label plate
const PILL_TEXT = '#2B2A28';

let cv, ctx, hooks = {};
let mode = null;               // 'tracks' | 'frame' | null
let drag = null;               // active pointer gesture
let dragTipShown = false;
const img = new Image();

export function init(canvasEl, h = {}) {
  cv = canvasEl; ctx = cv.getContext('2d'); hooks = h;
  cv.addEventListener('pointerdown', onDown);
  cv.addEventListener('pointermove', onMove);
  cv.addEventListener('keydown', onKey);              // keyboard crop control (a11y)
  window.addEventListener('pointerup', onUp);
  window.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && drag && drag.type === 'crop') {
      state.crop = drag.prev; drag = null; draw();   // cancel an in-progress crop draw
    }
  });
  img.onload = draw;
}

// Point the canvas at a region overview and size it to the overview aspect.
export function setOverview(src, ovSize) {
  state.ovSize = ovSize;
  state.scale = BASE_W / ovSize[0];
  cv.width = BASE_W;
  cv.height = Math.round(ovSize[1] * state.scale);
  img.src = src;                                       // triggers img.onload -> draw
}

export function setMode(m) {
  mode = m;
  cv.style.cursor = m === 'frame' ? 'crosshair' : 'default';
  if (m === 'frame' && !state.crop && state.starterCrop) resetFrame();
  draw();
}

// Reset the frame to the server-computed starter crop (clears only the crop). The
// server sizes the starter for 18x24; if the active print size was restored to
// something else, re-fit so the crop matches that aspect and clears ITS zoom floor
// on entry (else a returning operator's first proof would trip the cap).
export function resetFrame() {
  if (!state.starterCrop) return;
  const s = state.scale;
  const [x0, y0, x1, y1] = state.starterCrop;         // overview px -> canvas px
  state.crop = [x0 * s, y0 * s, x1 * s, y1 * s];
  if (state.printW !== 18 || state.printH !== 24) { refitForSize(); return; }
  draw();
  hooks.onCropChange && hooks.onCropChange();
}

// Re-fit the current crop to a new print aspect: keep center, grow to the new size's
// zoom-cap floor when the region allows, clamp inside the overview. Never leaves a
// stale aspect mismatch.
export function refitForSize() {
  const c = cropOverviewPx(); const r = activeRegion(); const mpp = metresPerPx();
  if (!c || !r || !mpp) return;
  const [ovW, ovH] = state.ovSize;
  const aspect = state.printW / state.printH;
  const cx = (c[0] + c[2]) / 2, cy = (c[1] + c[3]) / 2;
  const floorOv = (r.native_resolution_m * Math.round(state.printW * 300)) / mpp;
  let w = Math.max(c[2] - c[0], floorOv);
  w = Math.min(w, ovW, ovH * aspect);                 // fit the overview box
  let h = w / aspect;
  if (h > ovH) { h = ovH; w = h * aspect; }
  const x0 = Math.min(Math.max(cx - w / 2, 0), ovW - w);
  const y0 = Math.min(Math.max(cy - h / 2, 0), ovH - h);
  const s = state.scale;
  state.crop = [x0 * s, y0 * s, (x0 + w) * s, (y0 + h) * s];
  draw();
  hooks.onCropChange && hooks.onCropChange();
}

// --- geometry helpers ---
const toCanvas = (px, py) => [px * state.scale, py * state.scale];
const toOverview = (cx, cy) => [cx / state.scale, cy / state.scale];
const clamp = (v, lo, hi) => Math.min(Math.max(v, lo), hi);

// Is the current crop below the zoom-cap floor for the selected print width?
export function cropBelowFloor() {
  const c = cropOverviewPx(); const r = activeRegion(); const mpp = metresPerPx();
  if (!c || !r || !mpp) return false;
  const groundW = (c[2] - c[0]) * mpp;
  return groundW < r.native_resolution_m * Math.round(state.printW * 300);
}

// Can NO in-region crop satisfy the zoom floor at the selected size? (region width <
// the floor width). Then even the whole region is too small for this print size, so
// the honest fix is a SMALLER size -- not "draw wider".
export function sizeInfeasibleForRegion() {
  const r = activeRegion();
  if (!r) return false;
  const regionW = r.bounds[2] - r.bounds[0];
  return r.native_resolution_m * Math.round(state.printW * 300) > regionW;
}

function cropAnnouncement() {
  const c = cropOverviewPx(); const mpp = metresPerPx();
  if (!c || !mpp) return 'Frame updated';
  const wkm = ((c[2] - c[0]) * mpp / 1000).toFixed(1);
  const hkm = ((c[3] - c[1]) * mpp / 1000).toFixed(1);
  return `Frame ${wkm} by ${hkm} kilometres` + (cropBelowFloor() ? ' — too tight to print sharp' : '');
}

// Keyboard crop control on the Frame step (a11y): arrows move the frame, Shift+arrows
// resize it (aspect-locked), Enter renders the proof. Mirrors the pointer geometry.
function onKey(e) {
  if (mode !== 'frame' || !state.crop) return;
  if (e.key === 'Enter') { e.preventDefault(); hooks.onRenderProof && hooks.onRenderProof(); return; }
  const arrows = ['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'];
  if (!arrows.includes(e.key)) return;
  e.preventDefault();
  const ar = state.printW / state.printH;
  const STEP = 12;
  let [ax, ay, bx, by] = [Math.min(state.crop[0], state.crop[2]), Math.min(state.crop[1], state.crop[3]),
                          Math.max(state.crop[0], state.crop[2]), Math.max(state.crop[1], state.crop[3])];
  let w = bx - ax, h = by - ay;
  if (e.shiftKey) {                                    // resize, aspect-locked
    const grow = (e.key === 'ArrowRight' || e.key === 'ArrowUp') ? STEP : -STEP;
    w = Math.max(20, w + grow); h = w / ar;
  } else {                                             // move
    if (e.key === 'ArrowLeft') ax -= STEP;
    else if (e.key === 'ArrowRight') ax += STEP;
    else if (e.key === 'ArrowUp') ay -= STEP;
    else if (e.key === 'ArrowDown') ay += STEP;
  }
  w = Math.min(w, cv.width); h = w / ar;
  if (h > cv.height) { h = cv.height; w = h * ar; }
  ax = clamp(ax, 0, cv.width - w); ay = clamp(ay, 0, cv.height - h);
  state.crop = [ax, ay, ax + w, ay + h];
  draw();
  hooks.onCropChange && hooks.onCropChange();
  hooks.announce && hooks.announce(cropAnnouncement());
}

// --- pointer handlers ---
function localXY(e) {
  const rect = cv.getBoundingClientRect();
  // account for CSS scaling of the canvas element
  return [(e.clientX - rect.left) * (cv.width / rect.width),
          (e.clientY - rect.top) * (cv.height / rect.height)];
}

function hotspotAt(cx, cy) {
  for (let i = state.hotspots.length - 1; i >= 0; i--) {
    const [hx, hy] = toCanvas(...state.hotspots[i].px);
    if (Math.hypot(cx - hx, cy - hy) <= HIT_R) return i;
  }
  return -1;
}

function onDown(e) {
  const [cx, cy] = localXY(e);
  if (mode === 'tracks') {
    const i = hotspotAt(cx, cy);
    if (i >= 0) { drag = { type: 'marker', i, moved: false, sx0: cx, sy0: cy }; cv.setPointerCapture(e.pointerId); }
  } else if (mode === 'frame') {
    drag = { type: 'crop', startX: cx, startY: cy, prev: state.crop };
    cv.setPointerCapture(e.pointerId);
  }
}

function onMove(e) {
  const [cx, cy] = localXY(e);
  if (!drag) {
    if (mode === 'tracks' && !dragTipShown && hotspotAt(cx, cy) >= 0) {
      dragTipShown = true;
      hooks.onDragTip && hooks.onDragTip();           // one-shot "drag to reposition" tip
    }
    return;
  }
  if (drag.type === 'marker') {
    if (Math.hypot(cx - drag.sx0, cy - drag.sy0) > DRAG_THRESH) drag.moved = true;
    if (drag.moved) {                                 // only reposition past the threshold,
      const [ovx, ovy] = toOverview(clamp(cx, 0, cv.width), clamp(cy, 0, cv.height));
      state.hotspots[drag.i].px = [ovx, ovy];         // so a sub-threshold press never nudges
      draw();                                          // the dot without persisting (onUp gate)
    }
  } else if (drag.type === 'crop') {
    const ar = state.printW / state.printH;
    const x0 = Math.min(drag.startX, cx), x1 = Math.max(drag.startX, cx);
    let w = x1 - x0;
    let h = w / ar;
    // grow up or down depending on drag direction (the 4-direction fix)
    let y0 = (cy < drag.startY) ? (drag.startY - h) : drag.startY;
    // clamp inside the canvas, preserving aspect
    if (y0 < 0) { y0 = 0; }
    if (y0 + h > cv.height) { h = cv.height - y0; w = h * ar; }
    if (x0 + w > cv.width) { w = cv.width - x0; h = w / ar; }
    state.crop = [x0, y0, x0 + w, y0 + h];
    draw();
  }
}

function onUp() {
  if (!drag) return;
  const g = drag; drag = null;
  if (g.type === 'marker' && g.moved) {
    const [ovx, ovy] = state.hotspots[g.i].px;
    api.moveMarker(state.session, g.i, ovx, ovy).then((res) => {
      state.hotspots[g.i].px = [res.px, res.py];      // snap to the clamped position
      draw();
      hooks.onMarkerMoved && hooks.onMarkerMoved(g.i);
    }).catch(() => { hooks.onMarkerMoved && hooks.onMarkerMoved(g.i); });
  } else if (g.type === 'crop') {
    hooks.onCropChange && hooks.onCropChange();
  }
}

// --- drawing ---
export function draw() {
  if (!ctx) return;
  ctx.clearRect(0, 0, cv.width, cv.height);
  if (img.complete && img.naturalWidth && state.ovSize) {
    ctx.drawImage(img, 0, 0, cv.width, cv.height);
  }
  // tracks
  ctx.strokeStyle = 'rgba(43,42,40,.75)'; ctx.lineWidth = 1.3;
  for (const t of state.tracks) {
    ctx.beginPath();
    t.forEach(([px, py], i) => { const [x, y] = toCanvas(px, py); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
    ctx.stroke();
  }
  if (mode === 'frame' && state.crop) drawCrop();
  drawMarkers();
}

function drawCrop() {
  const [a, b, c, d] = state.crop;
  const x0 = Math.min(a, c), y0 = Math.min(b, d), x1 = Math.max(a, c), y1 = Math.max(b, d);
  // dim outside the frame
  ctx.save();
  ctx.fillStyle = 'rgba(15,13,11,0.5)';
  ctx.beginPath();
  ctx.rect(0, 0, cv.width, cv.height);
  ctx.rect(x0, y0, x1 - x0, y1 - y0);
  ctx.fill('evenodd');
  ctx.restore();
  const tooTight = cropBelowFloor();
  const stroke = tooTight ? '#C0552F' : '#D4B464';    // red-ish below the zoom floor
  // thirds guides
  ctx.strokeStyle = 'rgba(212,180,100,0.35)'; ctx.lineWidth = 1;
  for (let k = 1; k <= 2; k++) {
    const gx = x0 + (x1 - x0) * k / 3, gy = y0 + (y1 - y0) * k / 3;
    ctx.beginPath(); ctx.moveTo(gx, y0); ctx.lineTo(gx, y1); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(x0, gy); ctx.lineTo(x1, gy); ctx.stroke();
  }
  // box + corner handles
  ctx.strokeStyle = stroke; ctx.lineWidth = 2;
  ctx.strokeRect(x0, y0, x1 - x0, y1 - y0);
  ctx.fillStyle = stroke;
  for (const [hx, hy] of [[x0, y0], [x1, y0], [x0, y1], [x1, y1]]) {
    ctx.fillRect(hx - 3, hy - 3, 6, 6);
  }
}

function drawMarkers() {
  ctx.font = '12px Georgia, serif';
  for (const h of state.hotspots) {
    const [x, y] = toCanvas(...h.px);
    ctx.beginPath(); ctx.arc(x, y, 6, 0, 2 * Math.PI);
    ctx.fillStyle = DOT; ctx.fill();
    ctx.lineWidth = 2; ctx.strokeStyle = DOT_STROKE; ctx.stroke();
    if (h.label) {                                    // on-map cream label pill
      const w = ctx.measureText(h.label).width;
      ctx.fillStyle = PILL_FILL;
      roundRect(x + 12, y - 10, w + 14, 20, 6); ctx.fill();
      ctx.fillStyle = PILL_TEXT; ctx.fillText(h.label, x + 19, y + 4);
    }
  }
}

function roundRect(x, y, w, h, r) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}
