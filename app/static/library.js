// library.js — the Library home: the region gallery and the "reopen a poster" flow.
// A TrailPrint PNG carries its whole recipe, so dropping one here first INSPECTS it
// (a pure manifest read: region, edition, lineage, and the plate verdict — can this
// server reproduce these exact pixels?) and then offers to continue it as next year's
// edition or reprint it at full resolution. Surfaces /api/reprint(/inspect), which the
// old wizard never reached.
import { state } from './store.js';
import * as api from './api.js';
import * as compose from './compose.js';
import { $, toast, saveBlob, escapeHtml } from './ui.js';

let hooks = {};
let pendingFile = null;         // the poster being inspected (kept for continue/reprint)
let posterInputEl = null;

export function initLibrary(h = {}) {
  hooks = h;
  // library owns its own file input so it can inspect-first (the map's Continue button
  // uses the shared #posterInput, which goes straight to continue).
  posterInputEl = document.createElement('input');
  posterInputEl.type = 'file'; posterInputEl.accept = 'image/png,.png'; posterInputEl.hidden = true;
  document.body.appendChild(posterInputEl);
  posterInputEl.onchange = (e) => { const f = e.target.files[0]; e.target.value = ''; if (f) openPoster(f); };
  $('continuePosterRegion').onclick = () => posterInputEl.click();

  // the poster drop area highlights; the actual drop is handled by the global router in
  // app.js (drag-anywhere), which calls openPoster for a PNG.
  const drop = $('posterDrop');
  drop.addEventListener('dragover', (e) => { e.preventDefault(); drop.classList.add('over'); });
  drop.addEventListener('dragleave', () => drop.classList.remove('over'));
  drop.addEventListener('drop', (e) => {
    e.preventDefault(); e.stopPropagation(); drop.classList.remove('over');
    const f = e.dataTransfer.files[0]; if (f) openPoster(f);
  });
}

export function buildRegionGallery() {
  const host = $('regionGallery');
  host.innerHTML = '';
  for (const r of state.regions) {
    // DOM API, not interpolated HTML: a hostile/typo'd region name renders as text.
    const b = document.createElement('button');
    b.type = 'button'; b.className = 'region-card'; b.dataset.id = r.id;
    if (r.id === state.region) b.classList.add('sel');
    const img = document.createElement('img'); img.src = r.overview; img.alt = '';
    const span = document.createElement('span'); span.textContent = r.name;
    b.append(img, span);
    b.onclick = () => { compose.selectRegion(r.id); toast(`${r.name} — drop your GPX to begin.`, 'info'); hooks.goCompose && hooks.goCompose(); };
    host.appendChild(b);
  }
}

// Inspect a dropped/picked poster and show its provenance card with continue/reprint.
export async function openPoster(file) {
  pendingFile = file;
  toast('Reading poster…', 'working');
  try {
    const info = await api.inspectPoster(file);
    renderProvenance(info);
    toast('', 'info');
  } catch (e) {
    // not a TrailPrint PNG / no manifest (a share copy) — say so honestly.
    renderNoManifest(e.message);
    toast('That file carries no reprint recipe.', 'error');
  }
}

const VERDICT_LABEL = {
  verified: 'Plate verified — reprints exactly',
  mismatch: 'Plate mismatch — pixels may differ',
  unverifiable: 'Plate unverifiable',
  region_missing: 'Region not installed here',
};

function renderProvenance(info) {
  const card = $('provenanceCard');
  const size = info.print_size_in && info.print_size_in[0] ? `${info.print_size_in[0]}×${info.print_size_in[1]} in` : '—';
  const lineage = (info.lineage || []).length;
  const isFilm = !!info.animation;
  card.hidden = false;
  card.innerHTML = `
    <h3>${escapeHtml(info.title || 'Untitled poster')}</h3>
    <div class="provenance-row"><span>Region</span><b>${escapeHtml(info.region_id || '—')}${info.region_available ? '' : ' (not installed)'}</b></div>
    <div class="provenance-row"><span>Edition</span><b>${info.edition || 1}${lineage ? ` · ${lineage} prior` : ''}</b></div>
    <div class="provenance-row"><span>Print size</span><b>${escapeHtml(size)}</b></div>
    <div class="provenance-row"><span>Tracks · places</span><b>${info.tracks || 0} · ${info.hotspots || 0}</b></div>
    <div class="provenance-row"><span>File</span><b>${isFilm ? 'Time-lapse film' : 'Still poster'}</b></div>
    <div class="provenance-row"><span>Plate</span><span class="verdict ${info.plate}">${VERDICT_LABEL[info.plate] || info.plate}</span></div>
    <div class="provenance-actions">
      <button class="primary" id="pvContinue" type="button" ${info.region_available ? '' : 'disabled'}>Add this year — Edition ${(info.edition || 1) + 1}</button>
      <button class="ghost" id="pvReprint" type="button" ${info.region_available ? '' : 'disabled'}>Reprint PNG</button>
    </div>`;
  $('pvContinue').onclick = () => { if (pendingFile) { hooks.goCompose && hooks.goCompose(); compose.continueFromPoster(pendingFile); } };
  $('pvReprint').onclick = () => reprintPending();
}

function renderNoManifest(msg) {
  const card = $('provenanceCard');
  card.hidden = false;
  card.innerHTML = `<h3>No reprint recipe</h3>
    <p class="lede">This PNG doesn't carry a TrailPrint manifest — it's a share copy (or not a TrailPrint poster), so it can't be reprinted or continued. Open a reprintable copy instead.</p>
    <p class="insp-note">${escapeHtml(msg || '')}</p>`;
}

async function reprintPending() {
  if (!pendingFile) return;
  toast('Reprinting at full resolution…', 'working');
  try {
    const res = await api.reprint(pendingFile, { format: 'png', embedSpec: state.embedSpec });
    if (res.blob) { saveBlob(res.blob, res.filename); toast('Reprint downloaded.', 'ok'); }
    else if (res.job) { toast('Film reprint queued — see Exports.', 'info'); hooks.trackReprint && hooks.trackReprint(res.job); }
  } catch (e) { toast('Reprint failed: ' + e.message, 'error'); }
}
