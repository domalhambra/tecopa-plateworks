// social.js — the Social Media studio: repurpose the accepted composition for feeds and
// stories. A format gallery re-fits the proof into each social aspect (Reel 9:16,
// Portrait 4:5, Square 1:1, plus any custom) with live safe-zone overlays drawn from the
// server's own keep-out fractions (caption/actions on a Reel, the lock-screen bands on a
// phone), and badges any format the region is too small to satisfy — reusing the exact
// zoom-floor math the frame step uses. A caption + alt-text helper writes copy from the
// poster's own stats; a prominent privacy switch makes the share copy (no embedded route
// coordinates) a one-tap choice; and the Share Kit queues the poster, the chosen social
// stills, and a film as one named group in Exports.
import { state, totalTrackMetres } from './store.js';
import * as api from './api.js';
import * as jobs from './jobs.js';
import * as canvas from './canvas.js';
import * as proof from './proof.js';
import { $, toast, escapeHtml, updateSaveFileNote } from './ui.js';

const selected = new Set();     // social preset ids ticked for the gallery / kit
let includePoster = true, includeFilm = false;

function socialPresets() { return state.wpPresets.filter((p) => p.device_class === 'social'); }

export function buildSocial() {
  const preview = $('socialPreview');
  const panel = $('panel-social');
  if (!proof.hasFreshProof()) {
    preview.innerHTML = '<div class="home-head"><h1>Social studio</h1><p class="lede">Render and accept a proof first — then repurpose it here for Reels, feed posts, and stories.</p></div>';
    panel.innerHTML = '<section class="insp-group"><p class="lede insp-empty">A fresh proof unlocks the social formats, the caption helper, and the share kit.</p></section>';
    return;
  }
  renderGallery(preview);
  renderPanel(panel);
}

// ---- the format gallery (center) --------------------------------------------------
function renderGallery(host) {
  const url = proof.currentProofUrl();
  const presets = socialPresets();
  host.innerHTML = '';
  const head = document.createElement('div');
  head.className = 'home-head';
  head.innerHTML = `<h1 id="h-social" tabindex="-1">Social studio</h1>
    <p class="lede">Your accepted composition, re-framed for each format. The hatched bands are safe zones — where captions, action buttons, or the lock-screen clock sit; auto-placed labels avoid them. Tap a format to add it to your kit.</p>`;
  host.appendChild(head);

  const gallery = document.createElement('div');
  gallery.className = 'format-gallery';
  for (const p of presets) {
    const infeasible = canvas.presetInfeasibleForRegion(p);
    const aspect = p.px[0] / p.px[1];
    const { w, h } = fitFrame(aspect);
    const card = document.createElement('div');
    card.className = 'format-card' + (infeasible ? ' infeasible' : '') + (selected.has(p.id) ? ' sel' : '');
    const top = (p.top_clear_frac || 0) * 100;
    const bot = (p.bottom_clear_frac || 0) * 100;
    card.innerHTML =
      `<div class="format-frame" style="width:${w}px;height:${h}px">` +
      `<img src="${url}" alt="${escapeHtml(p.name)} preview">` +
      (top ? `<div class="safe-zone top" style="height:${top}%"></div>` : '') +
      (bot ? `<div class="safe-zone bottom" style="height:${bot}%"></div>` : '') +
      (infeasible ? `<span class="format-badge">Region too small</span>` : '') +
      `</div>` +
      `<div class="format-name">${escapeHtml(p.name)}</div>` +
      `<div class="format-dims">${p.px[0]}×${p.px[1]}${bot ? ` · ${Math.round(bot)}% caption band` : ''}</div>`;
    if (!infeasible) {
      card.style.cursor = 'pointer';
      card.setAttribute('role', 'button');
      card.setAttribute('aria-pressed', selected.has(p.id) ? 'true' : 'false');
      card.tabIndex = 0;
      const toggle = () => { toggleFormat(p.id); renderGallery(host); syncKit(); };
      card.onclick = toggle;
      card.onkeydown = (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle(); } };
    }
    gallery.appendChild(card);
  }
  host.appendChild(gallery);
}

function fitFrame(aspect) {
  const maxW = 168, maxH = 214;
  let w = maxW, h = w / aspect;
  if (h > maxH) { h = maxH; w = h * aspect; }
  return { w: Math.round(w), h: Math.round(h) };
}

function toggleFormat(id) { if (selected.has(id)) selected.delete(id); else selected.add(id); }

// ---- the inspector panel ----------------------------------------------------------
function renderPanel(panel) {
  panel.innerHTML = '';

  // caption + alt text
  const capGroup = document.createElement('section');
  capGroup.className = 'insp-group';
  capGroup.innerHTML =
    `<div class="insp-head"><span class="insp-title">Caption &amp; alt text</span></div>` +
    `<textarea class="social-caption" id="socialCaption" aria-label="Caption"></textarea>` +
    `<div class="foot-actions" style="margin-top:8px">` +
    `<button class="ghost" id="capCopy" type="button">Copy caption</button>` +
    `<button class="ghost" id="altCopy" type="button">Copy alt text</button></div>`;
  panel.appendChild(capGroup);
  $('socialCaption').value = generateCaption();
  $('capCopy').onclick = () => copy($('socialCaption').value, 'Caption copied');
  $('altCopy').onclick = () => copy(generateAlt(), 'Alt text copied');

  // privacy
  const privGroup = document.createElement('section');
  privGroup.className = 'insp-group';
  privGroup.innerHTML =
    `<div class="insp-head"><span class="insp-title">Privacy</span></div>` +
    `<div class="switch-row"><span class="switch-label">Share copy <span class="ctl-hint">· strips exact route coordinates</span></span>` +
    `<span class="switch"><input type="checkbox" id="socialShareCopy"><span class="slider"></span></span></div>` +
    `<p class="privacy-note" id="socialPrivacyNote"></p>`;
  panel.appendChild(privGroup);
  const shareChk = $('socialShareCopy');
  shareChk.checked = !state.embedSpec;   // "share copy" is the inverse of "reprintable"
  shareChk.onchange = () => {
    state.embedSpec = !shareChk.checked;
    const foot = $('embedSpecChk'); if (foot) foot.checked = state.embedSpec;
    updateSaveFileNote(); reflectPrivacyNote();
  };
  reflectPrivacyNote();

  // kit
  const kitGroup = document.createElement('section');
  kitGroup.className = 'insp-group';
  kitGroup.innerHTML =
    `<div class="insp-head"><span class="insp-title">Share kit</span>` +
    `<span class="insp-note">one download, all parts</span></div>` +
    `<div class="kit-list" id="kitList"></div>` +
    `<p class="insp-note" id="kitSummary" style="margin:8px 0"></p>` +
    `<button class="primary" id="kitBuild" type="button">Build kit</button>`;
  panel.appendChild(kitGroup);
  renderKitList();
  $('kitBuild').onclick = buildKit;
  syncKit();

  // wall-art mockups
  const mockGroup = document.createElement('section');
  mockGroup.className = 'insp-group';
  mockGroup.innerHTML =
    `<div class="insp-head"><span class="insp-title">Stage on the wall</span></div>` +
    `<p class="insp-note" style="margin-bottom:8px">Photograph the poster as a physical object — an embossed plate and a matted frame on a gallery wall — for a scroll-stopping feed post.</p>` +
    `<button class="ghost" id="mockBuild" type="button">Stage as wall art</button>`;
  panel.appendChild(mockGroup);
  $('mockBuild').onclick = stageMockups;
}

async function stageMockups() {
  const btn = $('mockBuild'); if (btn) btn.disabled = true;
  toast('Rendering a poster to stage…', 'working');
  try {
    let blob;
    if (state.lastFinal) {
      blob = await api.fetchBlob(state.lastFinal.url);
    } else {
      // no accepted final yet — render one first (reprintable, for the caption placard)
      const { job } = await api.submitFinal(state.session, 'png', state.embedSpec);
      const url = await jobs.track(job, { kind: 'final', label: 'Poster for mockup', group: 'Wall art', runningMsg: 'Rendering poster…' });
      if (!url) { if (btn) btn.disabled = false; return; }
      blob = await api.fetchBlob(url);
    }
    const file = new File([blob], 'poster.png', { type: 'image/png' });
    const { job } = await api.submitMockups(file, { variants: 'plate,frame', sizes: '1080x1080,1080x1350' });
    jobs.track(job, { kind: 'mockup', label: 'Wall-art mockups', group: 'Wall art', runningMsg: 'Staging on the wall…' });
    toast('Staging wall-art mockups — see Exports.', 'ok');
    hooksGoExports();
  } catch (e) { toast('Mockups failed: ' + e.message, 'error'); }
  if (btn) btn.disabled = false;
}

function reflectPrivacyNote() {
  const note = $('socialPrivacyNote');
  if (!note) return;
  note.textContent = state.embedSpec
    ? 'Reprintable: the file carries the recipe (and exact coordinates). Best for your own archive — turn on Share copy before posting publicly.'
    : 'Share copy: no manifest, no exact route coordinates. WebP and MP4 films are always share copies.';
}

function renderKitList() {
  const host = $('kitList');
  host.innerHTML = '';
  const items = [
    { key: 'poster', label: 'Poster PNG (full resolution)', get: () => includePoster, set: (v) => (includePoster = v) },
    ...socialPresets().map((p) => ({ key: p.id, label: `${p.name} · ${p.px[0]}×${p.px[1]}`, isFormat: true })),
    { key: 'film', label: 'Reel film (WebP, share copy)', get: () => includeFilm, set: (v) => (includeFilm = v) },
  ];
  for (const it of items) {
    const lab = document.createElement('label');
    lab.className = 'kit-item';
    const cb = document.createElement('input'); cb.type = 'checkbox';
    if (it.isFormat) { cb.checked = selected.has(it.key); cb.onchange = () => { toggleFormat(it.key); syncKit(); renderGallery($('socialPreview')); }; }
    else { cb.checked = it.get(); cb.onchange = () => { it.set(cb.checked); syncKit(); }; }
    const span = document.createElement('span'); span.textContent = it.label;
    lab.append(cb, span); host.appendChild(lab);
  }
}

function syncKit() {
  // keep kit checkboxes and gallery selection agreeing
  renderKitListSelectionOnly();
  const parts = (includePoster ? 1 : 0) + selected.size + (includeFilm ? 1 : 0);
  const sum = $('kitSummary');
  if (sum) sum.textContent = parts ? `${parts} item${parts === 1 ? '' : 's'} — queued together in Exports.` : 'Pick at least one item.';
  const btn = $('kitBuild'); if (btn) btn.disabled = !parts;
}

function renderKitListSelectionOnly() {
  const host = $('kitList'); if (!host) return;
  const boxes = host.querySelectorAll('.kit-item');
  const presets = socialPresets();
  boxes.forEach((lab, i) => {
    const cb = lab.querySelector('input');
    if (i === 0) cb.checked = includePoster;
    else if (i === boxes.length - 1) cb.checked = includeFilm;
    else cb.checked = selected.has(presets[i - 1].id);
  });
}

async function buildKit() {
  if (!proof.hasFreshProof()) { toast('Re-proof first — the kit renders the accepted composition.', 'error'); return; }
  const group = 'Share kit';
  const queued = [];
  try {
    if (includePoster) {
      const { job } = await api.submitFinal(state.session, 'png', state.embedSpec);
      queued.push(jobs.track(job, { kind: 'final', label: 'Poster PNG', group, runningMsg: 'Rendering poster…' }));
    }
    if (selected.size) {
      const sub = await api.submitWallpapers(state.session, [...selected], state.embedSpec);
      queued.push(jobs.track(sub.job, { kind: 'bundle', label: `Social stills · ${sub.count}`, group, runningMsg: 'Rendering social sizes…' }));
    }
    if (includeFilm) {
      const reel = socialPresets().find((p) => /reel|story/i.test(p.name)) || socialPresets()[0];
      const sub = await api.submitTimelapse(state.session, {
        maxFrames: state.tlFrames, wpPreset: reel ? reel.id : '', embedSpec: false, format: 'webp', lightMotion: 'none',
      });
      queued.push(jobs.track(sub.job, { kind: 'film', label: `Reel film · ${sub.frames} frames`, group, runningMsg: 'Painting the film…' }));
    }
    if (!queued.length) { toast('Pick at least one item for the kit.', 'error'); return; }
    toast(`Building a kit of ${queued.length} — see Exports.`, 'ok');
    hooksGoExports();   // each part downloads itself as it finishes and stays in Exports for re-save
  } catch (e) { toast('Kit failed: ' + e.message, 'error'); }
}

let _goExports = null;
export function setNav({ goExports }) { _goExports = goExports; }
function hooksGoExports() { if (_goExports) _goExports(); }

// ---- caption / alt text -----------------------------------------------------------
function stats() {
  const miles = totalTrackMetres() / 1609.34;
  const journeys = state.tracks.length;
  const named = state.hotspots.filter((h) => h.label).map((h) => h.label);
  const place = state.title && state.title !== '-' ? state.title : state.regionName;
  return { miles, journeys, named, place };
}

function generateCaption() {
  const { miles, journeys, named, place } = stats();
  const bits = [];
  bits.push(`${place || 'My trails'} 🗺️`);
  const line2 = [];
  if (journeys) line2.push(`${journeys} journey${journeys === 1 ? '' : 's'}`);
  if (miles >= 1) line2.push(`${miles.toFixed(miles < 10 ? 1 : 0)} miles`);
  if (state.yearSpan) line2.push(state.yearSpan);
  if (state.edition >= 2) line2.push(`Edition ${state.edition}`);
  if (line2.length) bits.push(line2.join(' · '));
  if (named.length) bits.push(`Favorite spots: ${named.slice(0, 4).join(', ')}.`);
  bits.push('Every mile I actually walked, printed as shaded-relief terrain. #tecopaprintworks #hiking #mapmaking');
  return bits.join('\n');
}

function generateAlt() {
  const { journeys, named, place } = stats();
  let alt = `A shaded-relief poster of ${place || 'a mountain region'} with ${journeys || 'several'} hiking route${journeys === 1 ? '' : 's'} drawn in gold over the terrain`;
  if (named.length) alt += `, marking ${named.slice(0, 3).join(', ')}`;
  return alt + '.';
}

async function copy(text, ok) {
  try { await navigator.clipboard.writeText(text); toast(ok, 'ok'); }
  catch { toast('Copy failed — select and copy manually.', 'error'); }
}
