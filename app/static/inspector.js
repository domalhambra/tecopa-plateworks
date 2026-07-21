// inspector.js — renders the registry (controls.js) into inspector panels and keeps
// them reflecting the store. One renderControl() per control type is reused by the
// Style/Layers/Light panels here and by the Social/Films sections. Every edit flows
// through store.setField (the stale-proof choke-point); proof-affecting edits schedule
// an auto-proof. This is the generic half of the UI — the section modules own the bits
// that need bespoke wiring (geometry, upload, film submit, social kit).
import { state, setField } from './store.js';
import { CONTROLS, GROUPS, forSection, panelsOf, fmtHour } from './controls.js';
import { $, wireSegmented } from './ui.js';
import * as proof from './proof.js';

// path -> reflect() closure for every rendered control, so a store change re-reflects
// exactly the affected control (and visibility is recomputed for dependents).
const reflectors = new Map();
const rendered = [];   // { control, container, reflect } for visibility passes

// After any edit: proof-affecting controls schedule a live re-proof and refresh the
// proof UI; every edit recomputes dependent visibility (labels->smart, profile->height).
function afterChange(c) {
  applySideEffects(c);
  if (c.affectsProof) { proof.scheduleAutoProof(); proof.refreshProofUI(); }
  reflectVisibility();
}

// Controls whose edit implies a second write: turning Journey Light on/off or moving the
// time-of-day scrubber re-derives the sun, so any explicitly restored az/alt is cleared
// (mirrors the old app.js handlers — the scrubber/toggle override an explicit sun).
function applySideEffects(c) {
  if (c.id === 'lightMode' || c.id === 'sunHour') {
    state.style.sunAzimuth = null;
    state.style.sunAltitude = null;
  }
}

// Build one control row. Returns its container element (with .visibleWhen bookkeeping).
export function renderControl(c) {
  const wrap = document.createElement('div');
  wrap.className = 'ctl';
  wrap.dataset.ctl = c.id;
  const cur = read(c);

  if (c.type === 'slider') {
    wrap.innerHTML =
      `<div class="slider-top"><label for="c_${c.id}">${c.label}${hint(c)}</label>` +
      `<output id="o_${c.id}"></output></div>` +
      `<input type="range" id="c_${c.id}" min="${c.min}" max="${c.max}" step="${c.step}">`;
    const input = wrap.querySelector('input');
    const out = wrap.querySelector('output');
    const reflect = () => {
      const v = read(c);
      input.value = v == null ? (c.id === 'sunHour' ? 17 : c.default ?? c.min) : v;
      out.textContent = c.fmt ? c.fmt(v == null ? input.value : v) : String(v);
    };
    input.oninput = () => { setField(c.path, Number(input.value)); out.textContent = c.fmt ? c.fmt(input.value) : input.value; afterChange(c); };
    reflect(); register(c, wrap, reflect);
  } else if (c.type === 'toggle' || c.type === 'toggleMap') {
    wrap.classList.remove('ctl'); wrap.classList.add('switch-row');
    wrap.innerHTML =
      `<span class="switch-label">${c.label}${hint(c)}</span>` +
      `<span class="switch"><input type="checkbox" id="c_${c.id}"><span class="slider"></span></span>`;
    const input = wrap.querySelector('input');
    const on = () => c.type === 'toggleMap' ? read(c) === c.onValue : !!read(c);
    const reflect = () => { input.checked = on(); };
    input.onchange = () => {
      setField(c.path, c.type === 'toggleMap' ? (input.checked ? c.onValue : c.offValue) : input.checked);
      afterChange(c);
    };
    reflect(); register(c, wrap, reflect);
  } else if (c.type === 'select') {
    const numeric = c.options.length && typeof c.options[0].value === 'number';
    wrap.classList.remove('ctl'); wrap.classList.add('field');
    wrap.innerHTML = `<label for="c_${c.id}">${c.label}${hint(c)}</label>` +
      `<div class="select-wrap"><select id="c_${c.id}">` +
      c.options.map((o) => `<option value="${o.value}">${o.label}</option>`).join('') +
      `</select></div>`;
    const sel = wrap.querySelector('select');
    const reflect = () => { const v = read(c); if (v != null) sel.value = String(v); };
    sel.onchange = () => { setField(c.path, numeric ? Number(sel.value) : sel.value); afterChange(c); };
    reflect(); register(c, wrap, reflect);
  } else if (c.type === 'segmented') {
    wrap.classList.remove('ctl'); wrap.classList.add('field');
    wrap.innerHTML = `<label>${c.label}${hint(c)}</label>` +
      `<div class="segmented" role="radiogroup" aria-label="${c.label}">` +
      c.options.map((o) => `<button type="button" role="radio" data-val="${o.value}">${o.label}</button>`).join('') +
      `</div>`;
    const seg = wrap.querySelector('.segmented');
    const { reflect } = wireSegmented(seg, (val) => { setField(c.path, val); afterChange(c); });
    const doReflect = () => reflect(read(c));
    doReflect(); register(c, wrap, doReflect);
  } else if (c.type === 'swatch') {
    wrap.classList.remove('ctl'); wrap.classList.add('swatch-row');
    wrap.innerHTML = `<span class="field-label">${c.label}</span>` +
      `<div class="swatches" role="radiogroup" aria-label="${c.label}">` +
      c.swatches.map((s) => `<button type="button" class="swatch" data-hex="${s.hex}" style="--sw:${s.hex}" aria-label="${s.label}"></button>`).join('') +
      `</div>`;
    const btns = [...wrap.querySelectorAll('.swatch')];
    const reflect = () => {
      const v = (read(c) || '').toLowerCase();
      for (const b of btns) b.classList.toggle('sel', (b.dataset.hex || '').toLowerCase() === v);
    };
    btns.forEach((b) => { b.onclick = () => { setField(c.path, b.dataset.hex); reflect(); afterChange(c); }; });
    reflect(); register(c, wrap, reflect);
  } else {
    return null;   // dial + text + geometry types are handled by their bespoke owners
  }
  attachHelp(wrap, c.help);
  return wrap;
}

function hint(c) { return c.hint ? ` <span class="ctl-hint">· ${c.hint}</span>` : ''; }

// Every control explains itself: a small ? toggle reveals one plain sentence INLINE
// below the row (not a hover tooltip — works for touch and keyboard, and stays put
// while the reader adjusts the control). Exported so static rows (page setup, film
// target) get the identical affordance.
export function attachHelp(row, help) {
  if (!help) return row;
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'ctl-help';
  btn.setAttribute('aria-label', 'What is this?');
  btn.setAttribute('aria-expanded', 'false');
  btn.textContent = '?';
  const text = document.createElement('p');
  text.className = 'ctl-help-text';
  text.textContent = help;
  text.hidden = true;
  btn.onclick = (e) => {
    e.preventDefault(); e.stopPropagation();
    text.hidden = !text.hidden;
    btn.setAttribute('aria-expanded', text.hidden ? 'false' : 'true');
  };
  // the toggle rides the row's label line; the sentence lands after the whole row
  const anchor = row.querySelector('label, .switch-label, .field-label, .slider-top label');
  (anchor || row).appendChild(btn);
  row.appendChild(text);
  return row;
}

function read(c) {
  const dot = c.path.indexOf('.');
  return dot < 0 ? state[c.path] : state[c.path.slice(0, dot)]?.[c.path.slice(dot + 1)];
}

function register(c, wrap, reflect) {
  reflectors.set(c.path, reflect);
  rendered.push({ control: c, container: wrap, reflect });
}

// Build a whole section's inspector panel, grouped by the controls' `panel`, as
// collapsible <details> groups (all open by default — collapsing is a reading aid, not
// a hiding place). `panels` restricts to named groups so a section can split across
// hosts (film pacing right, film output left). Skips advanced-only controls (they
// surface in the command palette / all-options search).
export function buildSectionPanel(section, host, { includeAdvanced = false, panels = null } = {}) {
  host.innerHTML = '';
  for (const panel of panelsOf(section)) {
    if (panels && !panels.includes(panel)) continue;
    const items = forSection(section).filter((c) => c.panel === panel && (includeAdvanced || !c.advanced));
    const usable = items.filter((c) => ['slider', 'toggle', 'toggleMap', 'select', 'segmented', 'swatch'].includes(c.type));
    if (!usable.length) continue;
    const group = document.createElement('details');
    group.className = 'insp-group';
    group.open = true;
    const head = document.createElement('summary');
    head.className = 'insp-head';
    head.innerHTML = `<span class="insp-title">${panel}</span>`;
    group.appendChild(head);
    if (GROUPS[panel]) {
      const desc = document.createElement('p');
      desc.className = 'insp-desc';
      desc.textContent = GROUPS[panel];
      group.appendChild(desc);
    }
    for (const c of usable) {
      const el = renderControl(c);
      if (el) group.appendChild(el);
    }
    host.appendChild(group);
  }
  reflectVisibility();
}

// Recompute which controls are visible (visibleWhen predicates) — cheap, run after any
// edit so dependent rows (smart labels under Place names, sun controls under Journey
// Light, profile height under the profile toggle) appear/disappear live.
export function reflectVisibility() {
  for (const r of rendered) {
    const vw = r.control.visibleWhen;
    r.container.hidden = vw ? !vw(state) : false;
  }
}

// Re-reflect every rendered control from the store (after a preset/variant/snapshot
// apply, or a continue-restore). Cheap; called on a null-path store notification.
export function reflectAll() {
  for (const reflect of reflectors.values()) { try { reflect(); } catch { /* isolate */ } }
  reflectVisibility();
}

// Reflect just the control bound to a path (a single setField from elsewhere).
export function reflectPath(path) {
  const r = reflectors.get(path);
  if (r) { try { r(); } catch { /* isolate */ } }
}

export { fmtHour };
