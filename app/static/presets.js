// presets.js — named style presets. A preset is a partial snapshot of picture decisions
// (paths → values from controls.js); applying it merges into the live look through
// store.applySnapshot, which stales the proof (and, via the accept gate, forces a fresh
// re-proof — an old proof is never reused for a final). Curated looks ship with the app;
// the user can save the current look and reapply it. Everything is client-side; presets
// never touch the reprint recipe of an already-rendered PNG.
import { snapshot, applySnapshot, loadPrefs, savePref } from './store.js';
import { toast } from './ui.js';

// Curated bundles. Each touches only existing spec fields. "Archival" is the reset-look
// (spec defaults); the others are opinionated combinations of the same knobs.
export const CURATED = [
  { id: 'archival', name: 'Archival', snap: {
    'style.lightMode': 'archival', 'style.golden': 0.7, 'style.oblique': 0.0,
    'style.shadow': 0.5, 'style.terrain': 1.0, 'style.trackColorBy': 'none',
    'biome': false, 'contours': false, 'labels': false } },
  { id: 'golden', name: 'Golden Hour', snap: {
    'style.lightMode': 'journey', 'style.golden': 0.9, 'style.shadow': 0.7, 'style.terrain': 1.1 } },
  { id: 'highrelief', name: 'High Relief', snap: {
    'style.oblique': 0.8, 'style.shadow': 0.8, 'style.terrain': 1.3, 'style.halo': 0.8 } },
  { id: 'storybook', name: 'Storybook', snap: {
    'biome': true, 'labels': true, 'style.labelPlace': 'smart', 'style.trackColorBy': 'elevation',
    'contours': true } },
  { id: 'clean', name: 'Clean', snap: {
    'contours': false, 'biome': false, 'labels': false, 'style.halo': 0.85,
    'style.furniture': 0.9, 'style.oblique': 0.0 } },
];

export function apply(snap, name) {
  applySnapshot(snap);      // notifies (path=null) -> app re-reflects + schedules a re-proof
  if (name) toast(`Applied “${name}” — re-proofing…`, 'info');
}

function userPresets() { return loadPrefs().stylePresets || []; }
function setUserPresets(list) { savePref('stylePresets', list); }

export function saveCurrent(name) {
  const list = userPresets().filter((p) => p.name !== name);
  list.push({ name, snap: snapshot() });
  setUserPresets(list);
}

export function deleteUser(name) { setUserPresets(userPresets().filter((p) => p.name !== name)); }

// Render the presets bar (curated chips + saved chips + a Save-look button) into a host.
export function renderInto(host, { onApply } = {}) {
  const draw = () => {
    host.innerHTML = '';
    const bar = document.createElement('div');
    bar.className = 'preset-bar';
    for (const p of CURATED) bar.appendChild(chip(p.name, () => { apply(p.snap, p.name); onApply && onApply(); }));
    for (const p of userPresets()) {
      const c = chip(p.name, () => { apply(p.snap, p.name); onApply && onApply(); }, true, () => { deleteUser(p.name); draw(); });
      bar.appendChild(c);
    }
    const save = document.createElement('button');
    save.type = 'button'; save.className = 'mini preset-save'; save.textContent = '+ Save look';
    save.onclick = () => {
      const name = prompt('Name this look:');
      if (name && name.trim()) { saveCurrent(name.trim()); draw(); toast(`Saved “${name.trim()}”.`, 'ok'); }
    };
    bar.appendChild(save);
    host.appendChild(bar);
  };
  draw();
}

function chip(label, onClick, deletable = false, onDelete = null) {
  const b = document.createElement('button');
  b.type = 'button'; b.className = 'preset-chip'; b.textContent = label;
  b.onclick = onClick;
  if (deletable) {
    const x = document.createElement('span');
    x.className = 'preset-x'; x.textContent = '×'; x.title = 'Delete this look';
    x.onclick = (e) => { e.stopPropagation(); onDelete && onDelete(); };
    b.appendChild(x);
  }
  return b;
}
