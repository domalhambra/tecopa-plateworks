// ui.js — tiny shared DOM helpers used across the studio modules. No app logic here;
// just the things every module would otherwise re-declare ($ , escaping, the live
// region, transient toasts, a motion-safe view transition wrapper, and the honest
// save-file note that several surfaces show).
import { state } from './store.js';
export const $ = (id) => document.getElementById(id);

export const escapeHtml = (s) => String(s)
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

// A polite live-region announcement for screen readers (keyboard crop, region switch,
// marker moves). Mirrors the old announce() — one shared #a11yStatus node.
export function announce(msg) { const el = $('a11yStatus'); if (el) el.textContent = msg || ''; }

// A transient status line in the shell footer. `kind` tints it (info|working|ok|error).
// Empty message clears it. Progress narration and one-liners both land here.
let toastTimer = null;
export function toast(msg, kind = 'info') {
  const el = $('toast');
  if (!el) return;
  el.textContent = msg || '';
  el.dataset.kind = msg ? kind : '';
  el.hidden = !msg;
  if (toastTimer) { clearTimeout(toastTimer); toastTimer = null; }
  // ok/error messages are terminal — let them linger, then fade; working/info persist
  if (msg && (kind === 'ok' || kind === 'error')) {
    toastTimer = setTimeout(() => { el.hidden = true; el.textContent = ''; }, 6000);
  }
}

// Run a DOM mutation inside a View Transition when the platform supports it and the
// user hasn't asked for reduced motion; otherwise just run it. Section swaps use this.
export function withTransition(fn) {
  const ok = document.startViewTransition &&
    window.matchMedia('(prefers-reduced-motion: no-preference)').matches;
  if (ok) document.startViewTransition(fn); else fn();
}

// The save-file sentence, told true for the CURRENT export choice. A share copy carries
// no manifest (and keeps exact route coordinates out of the file); a PDF never carries
// the recipe; a reprintable PNG is the save file that becomes next year's edition. Shown
// in the inspector foot and echoed by the Social privacy control. (Ported from app.js's
// updateSaveFileNote — the honest-copy language is a red-team fix, kept verbatim.)
export function updateSaveFileNote() {
  const el = $('saveFileNote');
  if (!el) return;
  if (!state.embedSpec) {
    el.textContent = 'Reprintable file is off: this download is a share copy — your exact route coordinates stay out of the file, and it can never reprint or continue. Keep a reprintable copy as your save file.';
  } else if (state.output !== 'wallpaper' && state.finalFormat === 'pdf') {
    el.textContent = 'A PDF is for the print shop: it can’t carry the reprint recipe. Download a PNG as well — that file is your save file and reprints from itself alone.';
  } else {
    el.textContent = `This PNG is your save file: the whole poster rides inside it and reprints from the file alone, for as long as its terrain plate survives. Keep it — next year it becomes Edition ${state.edition + 1}.`;
  }
}

// Trigger a browser download of a blob under a chosen filename, then release the URL
// (a 300-dpi PNG is ~50 MB — don't leak it). Used by every "save" path.
export function saveBlob(blob, filename) {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 60000);
}

// Wire a segmented control (a native-feeling face, WAI-ARIA radio-group: roving
// tabindex, arrow keys move selection + focus). onSet(value) fires on user choice.
// Returns { reflect(value) } which updates the face WITHOUT firing onSet — used to
// mirror programmatic state changes. If the group has data-for, its hidden <select> is
// kept in sync for form/AT semantics.
export function wireSegmented(seg, onSet) {
  const btns = [...seg.querySelectorAll('button')];
  const sel = seg.dataset.for ? $(seg.dataset.for) : null;
  const reflect = (val) => {
    for (const b of btns) {
      const on = b.dataset.val === String(val);
      b.classList.toggle('on', on);
      b.setAttribute('aria-checked', on ? 'true' : 'false');
      b.tabIndex = on ? 0 : -1;
    }
    if (sel) sel.value = val;
  };
  const set = (val, focus) => {
    reflect(val);
    if (focus) btns.find((b) => b.dataset.val === String(val))?.focus();
    onSet(val);
  };
  btns.forEach((b, i) => {
    b.onclick = () => set(b.dataset.val, false);
    b.onkeydown = (e) => {
      const step = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[e.key];
      if (!step) return;
      e.preventDefault();
      set(btns[(i + step + btns.length) % btns.length].dataset.val, true);
    };
  });
  return { reflect };
}
