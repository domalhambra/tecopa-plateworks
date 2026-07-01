// markers.js — the accessible marker side-list (one row of real form controls per
// hotspot) and the "outside frame" cue. This list is the unambiguous, tab-able,
// screen-reader-friendly path for editing marker identity; the map handles only
// repositioning. Kept deliberately as DOM controls, never map-only popovers.
import { state, cropOverviewPx } from './state.js';
import * as api from './api.js';

const ICONS = ['dot', 'peak', 'camp', 'water', 'flag', 'camera', 'star'];
let host = null;
let onEdit = () => {};

export function render(hostEl, editCb = () => {}) {
  host = hostEl; onEdit = editCb;
  host.innerHTML = '';
  state.hotspots.forEach((h, i) => {
    const row = document.createElement('div');
    row.className = 'marker-row';
    const opts = ICONS.map((ic) =>
      `<option value="${ic}"${(h.icon || 'dot') === ic ? ' selected' : ''}>${ic}</option>`).join('');
    row.innerHTML =
      `<span class="dot" aria-hidden="true"></span>` +
      `<input class="m-label" aria-label="Marker ${i + 1} name" placeholder="Marker ${i + 1}" value="${escapeAttr(h.label || '')}">` +
      `<select class="m-icon" aria-label="Marker ${i + 1} icon">${opts}</select>` +
      `<label class="m-photo${h.photo ? ' has' : ''}" title="Attach photo">` +
      `<span aria-hidden="true">\u{1F4F7}</span><input type="file" accept="image/*" hidden></label>` +
      `<span class="off-frame" hidden>outside frame</span>`;
    row.querySelector('.m-label').onchange = (e) => { h.label = e.target.value; pushMarkers('Renamed — re-render the proof to see it'); };
    row.querySelector('.m-icon').onchange = (e) => { h.icon = e.target.value; pushMarkers('Icon changed — re-render the proof to see it'); };
    row.querySelector('.m-photo input').onchange = (e) => {
      if (e.target.files[0]) attachPhoto(i, e.target.files[0], row);
    };
    host.appendChild(row);
  });
  refreshOutOfFrame();
}

async function pushMarkers(msg) {
  if (!state.session) return;
  const markers = state.hotspots.map((h, i) => ({ i, label: h.label || '', icon: h.icon || 'dot' }));
  try {
    await api.setMarkers(state.session, markers);
    state.proofStale = true;
    onEdit(msg);
  } catch (e) { onEdit('Marker update failed: ' + e.message); }
}

async function attachPhoto(i, file, row) {
  try {
    await api.uploadPhoto(state.session, i, file);
    state.hotspots[i].photo = true;
    row.querySelector('.m-photo').classList.add('has');
    state.proofStale = true;
    onEdit('Photo attached — re-render the proof to see it');
  } catch (e) { onEdit('Photo rejected: ' + e.message); }
}

// Mirror render._draw_markers: a marker outside the current crop window is dropped
// from the poster. Because the overview<->CRS map is linear, "outside the crop's CRS
// window" is exactly "outside the crop's overview-px rectangle" — so we test in
// overview px and flag the row (muted "outside frame") so it never silently vanishes.
export function refreshOutOfFrame() {
  if (!host) return;
  const crop = cropOverviewPx();
  const rows = host.querySelectorAll('.marker-row');
  rows.forEach((row, i) => {
    const cue = row.querySelector('.off-frame');
    const h = state.hotspots[i];
    let outside = false;
    if (crop && h) {
      const [x, y] = h.px;
      outside = x < crop[0] || x > crop[2] || y < crop[1] || y > crop[3];
    }
    row.classList.toggle('outside', !!(crop && outside));
    if (cue) cue.hidden = !(crop && outside);
  });
}

function escapeAttr(s) {
  return String(s).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;');
}
