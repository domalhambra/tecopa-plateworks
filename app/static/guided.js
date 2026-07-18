// guided.js — the first-run welcome. A single, skippable modal that frames the studio's
// four moves (Compose → Style/Layers/Light → Social → Exports) so a new operator isn't
// dropped into an eight-section rail with no map. Shows once per browser (a localStorage
// pref); dismissing it nudges focus toward the first step. Deliberately light — a coach-
// mark tour anchored to live elements is fragile; a clear overview + the existing
// per-step map hints do the job without brittle positioning.
import { state, loadPrefs, savePref } from './store.js';
import { $ } from './ui.js';

// Show the welcome on a fresh first visit (no saved 'guided' pref, no live session).
export function maybeStart() {
  const dlg = $('welcomeDialog');
  if (!dlg) return;
  wireStart(dlg);
  if (loadPrefs().guided === 'done' || state.session) return;
  try { dlg.showModal(); } catch { /* already open */ }
}

// Reopen on demand (from the Help affordance), regardless of the saved pref.
export function open() {
  const dlg = $('welcomeDialog');
  if (!dlg) return;
  wireStart(dlg);
  try { dlg.showModal(); } catch { /* already open */ }
}

function wireStart(dlg) {
  const start = $('welcomeStart');
  if (start && !start.dataset.wired) {
    start.dataset.wired = '1';
    start.onclick = () => finish(dlg);
    dlg.addEventListener('cancel', () => finish(dlg));   // Esc also completes the guide
  }
}

function finish(dlg) {
  savePref('guided', 'done');
  if (dlg.open) dlg.close();
  // gently point at the first step
  const rail = document.querySelector('.rail-item[data-section="compose"]');
  if (rail) {
    rail.classList.add('pulse');
    setTimeout(() => rail.classList.remove('pulse'), 3600);
  }
  const home = $('h-home');
  if (home) home.focus();
}
