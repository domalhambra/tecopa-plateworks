// palette.js — the Ctrl/Cmd+K command palette. A single fuzzy list over: sections (jump
// there), actions (proof / accept / express / start over / theme), presets (apply), and
// every registry control (jump to its section, focused). Built from controls.js + the
// action list, so a new control is searchable the moment it's registered. Keyboard-first:
// type to filter, ↑/↓ to move, Enter to run, Esc to close.
import { CONTROLS } from './controls.js';
import { CURATED } from './presets.js';
import * as presets from './presets.js';
import { $ } from './ui.js';

let items = [];
let filtered = [];
let active = 0;
let dlg, input, listEl;

const SECTION_LABEL = {
  library: 'Library', compose: 'Compose', style: 'Style', layers: 'Layers',
  light: 'Light', social: 'Social', films: 'Films', export: 'Export', exports: 'Exports',
};

export function initPalette({ setSection, actions }) {
  dlg = $('paletteDialog'); input = $('paletteInput'); listEl = $('paletteList');

  items = [];
  // sections
  for (const s of ['library', 'compose', 'style', 'layers', 'light', 'social', 'films', 'exports']) {
    items.push({ label: `Go to ${SECTION_LABEL[s]}`, hint: 'section', keys: [s, SECTION_LABEL[s]], run: () => setSection(s) });
  }
  // actions (provided by app.js)
  for (const a of actions) items.push({ label: a.label, hint: 'action', keys: [a.label], run: a.run });
  // presets
  for (const p of CURATED) items.push({ label: `Apply preset: ${p.name}`, hint: 'preset', keys: [p.name, 'preset'], run: () => presets.apply(p.snap, p.name) });
  // controls -> jump to their section
  for (const c of CONTROLS) {
    items.push({
      label: c.label, hint: SECTION_LABEL[c.section] || c.section,
      keys: [c.label, ...(c.keywords || []), c.section],
      run: () => { setSection(c.section === 'export' ? 'style' : c.section); setTimeout(() => $(`c_${c.id}`)?.focus(), 60); },
    });
  }

  input.addEventListener('input', () => { refilter(); });
  input.addEventListener('keydown', onKey);
  dlg.addEventListener('close', () => { input.value = ''; });
  dlg.addEventListener('click', (e) => { if (e.target === dlg) dlg.close(); });   // backdrop
}

export function open() {
  if (!dlg.open) dlg.showModal();
  input.value = ''; active = 0; refilter(); input.focus();
}

function refilter() {
  const q = input.value.trim().toLowerCase();
  filtered = !q ? items.slice(0, 40)
    : items.filter((it) => it.keys.some((k) => String(k).toLowerCase().includes(q))).slice(0, 40);
  active = 0;
  render();
}

function render() {
  listEl.innerHTML = '';
  filtered.forEach((it, i) => {
    const li = document.createElement('li');
    li.className = 'palette-item' + (i === active ? ' active' : '');
    li.setAttribute('role', 'option');
    li.innerHTML = `<span>${it.label}</span><span class="p-hint p-sec">${it.hint}</span>`;
    li.onclick = () => run(i);
    li.onmousemove = () => { if (active !== i) { active = i; render(); } };
    listEl.appendChild(li);
  });
}

function onKey(e) {
  if (e.key === 'ArrowDown') { e.preventDefault(); active = Math.min(active + 1, filtered.length - 1); render(); scrollActive(); }
  else if (e.key === 'ArrowUp') { e.preventDefault(); active = Math.max(active - 1, 0); render(); scrollActive(); }
  else if (e.key === 'Enter') { e.preventDefault(); run(active); }
  else if (e.key === 'Escape') { dlg.close(); }
}

function scrollActive() { listEl.children[active]?.scrollIntoView({ block: 'nearest' }); }

function run(i) {
  const it = filtered[i];
  if (!it) return;
  dlg.close();
  try { it.run(); } catch { /* isolate */ }
}
