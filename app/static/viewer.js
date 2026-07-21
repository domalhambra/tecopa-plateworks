// viewer.js — zoom/pan for the proof stage. The poster card is laid out at a FIXED
// CSS size per sheet aspect (set as --proof-w/--proof-h custom properties), and all
// zooming is a translate+scale transform on the .viewport-content wrapper. Because the
// layout size never changes when #posterImg swaps draft → refined pixels, the zoom
// state {s, tx, ty} survives every swap — the picture just sharpens in place. 100%
// means 1 image pixel : 1 device pixel of the CURRENT image (the draft's honest
// ceiling until the refine lands).
import { $ } from './ui.js';

const BASE_W = 620;         // the card's layout width in CSS px (the old display cap,
                            // now just an arbitrary layout unit under the transform)
const CARD_PAD = 10;        // .poster-card padding (both sides add 2x)
const FIT_MARGIN = 24;      // breathing room around the fitted sheet
const WHEEL_K = 0.0015;     // wheel-to-zoom exponent

let viewport = null, content = null, card = null, img = null;
let baseW = BASE_W, baseH = BASE_W * 4 / 3;
let aspect = null;          // img naturalWidth / naturalHeight currently laid out
let s = 1, tx = 0, ty = 0;
let fitLocked = true;       // auto re-fit on container resize until the user zooms
let drag = null;

function cardW() { return baseW + 2 * CARD_PAD; }
function cardH() { return baseH + 2 * CARD_PAD; }

function fitScale() {
  const vw = viewport.clientWidth, vh = viewport.clientHeight;
  return Math.max(0.05, Math.min((vw - FIT_MARGIN) / cardW(), (vh - FIT_MARGIN) / cardH()));
}

// 1 image pixel : 1 device pixel. Uses the CURRENT image's pixels, so the same
// button means "the sharpest truth I have right now".
function scale100() {
  if (!img || !img.naturalWidth) return 1;
  return img.naturalWidth / (baseW * (window.devicePixelRatio || 1));
}

function apply() {
  content.style.transform = `translate(${tx}px, ${ty}px) scale(${s})`;
  const pct = $('zoomPct');
  if (pct) pct.textContent = `${Math.round((s / scale100()) * 100)}%`;
}

export function fit() {
  s = fitScale();
  tx = (viewport.clientWidth - cardW() * s) / 2;
  ty = (viewport.clientHeight - cardH() * s) / 2;
  fitLocked = true;
  apply();
}

function zoomAt(px, py, ns) {
  const wx = (px - tx) / s, wy = (py - ty) / s;
  s = ns;
  tx = px - wx * s; ty = py - wy * s;
  fitLocked = false;
  apply();
}

export function zoom100() {
  zoomAt(viewport.clientWidth / 2, viewport.clientHeight / 2, scale100());
}

// Called on every #posterImg load (draft, refined, restored). Re-lays-out the card
// only when the sheet's aspect genuinely changed (a new print size / device); a
// same-aspect swap keeps {s, tx, ty} untouched so the refine never jolts the view.
export function imageLoaded() {
  if (!img || !img.naturalWidth) return;
  const a = img.naturalWidth / img.naturalHeight;
  if (aspect === null || Math.abs(a / aspect - 1) > 0.005) {
    aspect = a;
    baseW = BASE_W; baseH = BASE_W / a;
    card.style.setProperty('--proof-w', `${baseW}px`);
    card.style.setProperty('--proof-h', `${baseH}px`);
    fit();
  } else {
    apply();   // same sheet: only the 100% meaning (and the % label) may have changed
  }
}

export function reset() {
  aspect = null; fitLocked = true;
}

export function initViewer() {
  viewport = $('proofViewport'); content = $('proofContent');
  card = $('posterCard'); img = $('posterImg');
  if (!viewport || !content) return;

  img.addEventListener('load', imageLoaded);
  const fitBtn = $('zoomFitBtn'); if (fitBtn) fitBtn.onclick = fit;
  const hundred = $('zoom100Btn'); if (hundred) hundred.onclick = zoom100;

  viewport.addEventListener('wheel', (e) => {
    if (!aspect) return;
    e.preventDefault();
    const r = viewport.getBoundingClientRect();
    const lo = fitScale() * 0.4, hi = scale100() * 4;
    const ns = Math.min(hi, Math.max(lo, s * Math.exp(-e.deltaY * WHEEL_K)));
    zoomAt(e.clientX - r.left, e.clientY - r.top, ns);
  }, { passive: false });

  viewport.addEventListener('pointerdown', (e) => {
    if (!aspect || e.button !== 0) return;
    drag = { x: e.clientX, y: e.clientY };
    viewport.setPointerCapture(e.pointerId);
    viewport.classList.add('is-panning');
  });
  viewport.addEventListener('pointermove', (e) => {
    if (!drag) return;
    tx += e.clientX - drag.x; ty += e.clientY - drag.y;
    drag = { x: e.clientX, y: e.clientY };
    fitLocked = false;
    apply();
  });
  const endDrag = (e) => {
    if (!drag) return;
    drag = null;
    viewport.classList.remove('is-panning');
    if (e.pointerId != null && viewport.hasPointerCapture(e.pointerId)) {
      viewport.releasePointerCapture(e.pointerId);
    }
  };
  viewport.addEventListener('pointerup', endDrag);
  viewport.addEventListener('pointercancel', endDrag);

  viewport.addEventListener('dblclick', () => {
    if (!aspect) return;
    // near fit -> jump to 100%; anywhere else -> back to fit
    (Math.abs(s / fitScale() - 1) < 0.05 ? zoom100 : fit)();
  });

  new ResizeObserver(() => { if (aspect && fitLocked) fit(); }).observe(viewport);
}
