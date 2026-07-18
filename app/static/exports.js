// exports.js — the Exports center: a live view of every render this session over the
// shared jobs store. Queued/running/done/error with a spinner, self-documenting
// re-downloads (the server names each file), and kit grouping so a "share kit" shows its
// parts together. Purely a renderer of jobs.list(); it never polls (jobs.js owns that).
import * as jobs from './jobs.js';
import * as api from './api.js';
import { $, toast, saveBlob } from './ui.js';

const KIND_ICON = { final: '▣', bundle: '▤', film: '▷', mockup: '◱', reprint: '↺', render: '⇩' };

export function initExports() {
  jobs.subscribe(render);
  render(jobs.list());
}

export function render(list = jobs.list()) {
  const host = $('jobList');
  if (!host) return;
  host.innerHTML = '';
  $('jobEmpty').hidden = list.length > 0;

  // group runs: kit groups box together, standalone jobs render on their own.
  const groups = new Map();
  const singles = [];
  for (const j of list) {
    if (j.group) { if (!groups.has(j.group)) groups.set(j.group, []); groups.get(j.group).push(j); }
    else singles.push(j);
  }
  for (const [name, items] of groups) {
    const h = document.createElement('div'); h.className = 'job-group-label'; h.textContent = name;
    host.appendChild(h);
    for (const j of items) host.appendChild(row(j));
  }
  for (const j of singles) host.appendChild(row(j));
}

function row(j) {
  const el = document.createElement('div');
  el.className = 'job-row';
  const ico = document.createElement('div'); ico.className = 'job-ico'; ico.textContent = KIND_ICON[j.kind] || '⇩';
  const main = document.createElement('div'); main.className = 'job-main';
  const label = document.createElement('div'); label.className = 'job-label'; label.textContent = j.label;
  const st = document.createElement('div'); st.className = 'job-state';
  main.append(label, st);
  el.append(ico, main);

  if (j.state === 'error') { st.classList.add('error'); st.textContent = j.error || 'failed'; }
  else if (j.state === 'done') {
    st.classList.add('done'); st.textContent = j.filename ? `Saved · ${j.filename}` : 'Ready';
    const dl = document.createElement('button'); dl.className = 'ghost'; dl.type = 'button';
    dl.textContent = j.filename ? 'Save again' : 'Download';
    dl.onclick = () => download(j);
    el.appendChild(dl);
  } else {
    st.textContent = j.state === 'running' ? j.runningMsg : 'Queued…';
    const sp = document.createElement('div'); sp.className = 'job-spinner';
    el.appendChild(sp);
  }
  return el;
}

async function download(j) {
  if (!j.result) return;
  try {
    const { blob, filename } = await api.fetchDownload(j.result, `${j.label.toLowerCase().replace(/\s+/g, '_')}`);
    saveBlob(blob, filename);
    jobs.markDownloaded(j.jid, filename);
    toast('Downloaded.', 'ok');
  } catch (e) { toast('That result has expired — re-render it.', 'error'); }
}
