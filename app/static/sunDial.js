// sunDial.js — the Journey Light sun widget: a compass-style dial where the sun's
// bearing is the angle around the ring and its altitude is the distance from the rim
// (rim = low sun near the horizon, center = high sun). One draggable handle encodes
// both; two role="slider" affordances (azimuth, altitude) make it keyboard- and
// screen-reader-operable. Writes style.sunAzimuth / style.sunAltitude through the store
// choke-point and re-proofs live. Shown only in journey light mode.
import { state, setField, subscribe } from './store.js';
import { fmtHour } from './controls.js';
import * as proof from './proof.js';

const AZ_MIN = 0, AZ_MAX = 360;
const ALT_MIN = 8, ALT_MAX = 80;
const R = 74, CX = 90, CY = 90;   // svg geometry

let host = null;

export function mount(hostEl) {
  host = hostEl;
  if (!host) return;
  host.className = 'sun-dial';
  host.innerHTML = `
    <svg viewBox="0 0 180 180" class="dial-svg" aria-hidden="true">
      <circle cx="${CX}" cy="${CY}" r="${R}" class="dial-ring"></circle>
      <circle cx="${CX}" cy="${CY}" r="${R * 0.5}" class="dial-ring dim"></circle>
      <line x1="${CX}" y1="${CY - R}" x2="${CX}" y2="${CY - R + 8}" class="dial-n"></line>
      <text x="${CX}" y="18" class="dial-card">N</text>
      <path class="dial-glow" d=""></path>
      <circle class="dial-sun" r="9"></circle>
    </svg>
    <div class="dial-readout">
      <button type="button" class="dial-axis" id="dialAz" role="slider"
        aria-label="Sun azimuth" aria-valuemin="${AZ_MIN}" aria-valuemax="${AZ_MAX}"></button>
      <button type="button" class="dial-axis" id="dialAlt" role="slider"
        aria-label="Sun altitude" aria-valuemin="${ALT_MIN}" aria-valuemax="${ALT_MAX}"></button>
      <div class="dial-hour" id="dialHour"></div>
    </div>`;

  const svg = host.querySelector('.dial-svg');
  const sun = host.querySelector('.dial-sun');
  let dragging = false;
  const toValues = (clientX, clientY) => {
    const rect = svg.getBoundingClientRect();
    const x = (clientX - rect.left) * (180 / rect.width) - CX;
    const y = (clientY - rect.top) * (180 / rect.height) - CY;
    // azimuth: 0 = north (up), clockwise; altitude: rim = ALT_MIN, center = ALT_MAX
    let az = (Math.atan2(x, -y) * 180 / Math.PI + 360) % 360;
    const dist = Math.min(Math.hypot(x, y), R) / R;      // 0 center .. 1 rim
    const alt = ALT_MAX - dist * (ALT_MAX - ALT_MIN);
    return { az: Math.round(az), alt: Math.round(alt) };
  };
  const commit = ({ az, alt }) => {
    setField('style.sunAzimuth', az);
    setField('style.sunAltitude', alt);
    setField('style.sunHour', null);        // an explicit dial position overrides the hour
    reflect();
    proof.scheduleAutoProof(); proof.refreshProofUI();
  };
  svg.addEventListener('pointerdown', (e) => { dragging = true; svg.setPointerCapture(e.pointerId); commit(toValues(e.clientX, e.clientY)); });
  svg.addEventListener('pointermove', (e) => { if (dragging) commit(toValues(e.clientX, e.clientY)); });
  window.addEventListener('pointerup', () => { dragging = false; });

  wireAxis(host.querySelector('#dialAz'), () => resolved().az, (v) => commit({ az: (v + 360) % 360, alt: resolved().alt }), 5);
  wireAxis(host.querySelector('#dialAlt'), () => resolved().alt, (v) => commit({ az: resolved().az, alt: clamp(v, ALT_MIN, ALT_MAX) }), 2);

  subscribe((path) => { if (path === null || path === 'style.lightMode' || String(path).startsWith('style.sun')) reflect(); });
  reflect();
}

function wireAxis(el, get, set, step) {
  el.onkeydown = (e) => {
    const d = { ArrowRight: step, ArrowUp: step, ArrowLeft: -step, ArrowDown: -step }[e.key];
    if (d == null) return;
    e.preventDefault();
    set(get() + d);
  };
}

const clamp = (v, lo, hi) => Math.min(Math.max(v, lo), hi);

// The sun to show: the explicit az/alt if set, else the journey's resolved sun (from
// upload/continue meta), else a sensible archival default (NW, 45°).
function resolved() {
  const s = state.style;
  const meta = state.journeyLight && state.journeyLight.sun;
  const az = s.sunAzimuth != null ? s.sunAzimuth : (meta && meta.azimuth_deg != null ? Math.round(meta.azimuth_deg) : 315);
  const alt = s.sunAltitude != null ? s.sunAltitude : (meta && meta.altitude_deg != null ? Math.round(meta.altitude_deg) : 45);
  return { az, alt };
}

function reflect() {
  if (!host) return;
  const journey = state.style.lightMode === 'journey';
  host.hidden = !journey;
  if (!journey) return;
  const { az, alt } = resolved();
  const dist = (ALT_MAX - alt) / (ALT_MAX - ALT_MIN);   // 0 center .. 1 rim
  const rad = (az - 0) * Math.PI / 180;
  const px = CX + Math.sin(rad) * R * dist;
  const py = CY - Math.cos(rad) * R * dist;
  const sun = host.querySelector('.dial-sun');
  sun.setAttribute('cx', px.toFixed(1)); sun.setAttribute('cy', py.toFixed(1));
  const glow = host.querySelector('.dial-glow');
  glow.setAttribute('d', `M ${CX} ${CY} L ${px.toFixed(1)} ${py.toFixed(1)}`);
  const azEl = host.querySelector('#dialAz'), altEl = host.querySelector('#dialAlt');
  azEl.textContent = `Bearing ${az}°`; azEl.setAttribute('aria-valuenow', az); azEl.setAttribute('aria-valuetext', `${az} degrees`);
  altEl.textContent = `Height ${alt}°`; altEl.setAttribute('aria-valuenow', alt); altEl.setAttribute('aria-valuetext', `${alt} degrees`);
  const hourEl = host.querySelector('#dialHour');
  const meta = state.journeyLight && state.journeyLight.sun;
  hourEl.textContent = state.style.sunHour != null ? fmtHour(state.style.sunHour)
    : (state.style.sunAzimuth != null ? 'Custom sun' : (meta && meta.hour_local != null ? `${fmtHour(meta.hour_local)} · from your GPX` : 'Summit light'));
}
