const cv = document.getElementById('map');
const ctx = cv.getContext('2d');
const overview = new Image();
let state = { session: null, ovSize: null, tracks: [], hotspots: [], crop: null, scale: 1, files: [], regionId: null, regions: [] };

const $ = (id) => document.getElementById(id);
const setStatus = (m) => { $('status').textContent = m || ''; };

function regionName(id) { const r = state.regions.find((x) => x.id === id); return r ? r.name : id; }

function selectRegion(id) {
  state.regionId = id;
  $('region').textContent = id ? regionName(id) : '';
  for (const el of document.querySelectorAll('.region-card'))
    el.classList.toggle('sel', el.dataset.id === id);
}

async function loadRegions() {
  let list = [];
  try { list = await (await fetch('/api/regions')).json(); } catch (e) { /* leave empty */ }
  state.regions = list;
  if (list.length <= 1) {                         // one region: no picker, just name it
    if (list.length === 1) selectRegion(list[0].id);
    return;
  }
  const host = $('regionList');
  host.innerHTML = '';
  for (const r of list) {
    const b = document.createElement('button');
    b.className = 'region-card'; b.dataset.id = r.id;
    b.innerHTML = `<img src="${r.overview}" alt=""><span>${r.name}</span>`;
    b.onclick = () => selectRegion(r.id);
    host.appendChild(b);
  }
  $('regionPicker').hidden = false;
  setStatus('Pick a region, then drop your tracks (or just drop — we’ll auto-detect)');
}

function ovToCanvas(px, py) { return [px * state.scale, py * state.scale]; }
function canvasToOv(cx, cy) { return [cx / state.scale, cy / state.scale]; }

function draw() {
  ctx.clearRect(0, 0, cv.width, cv.height);
  if (overview.complete && state.ovSize) ctx.drawImage(overview, 0, 0, cv.width, cv.height);
  ctx.strokeStyle = 'rgba(43,42,40,.75)'; ctx.lineWidth = 1.2;
  for (const t of state.tracks) {
    ctx.beginPath();
    t.forEach(([px, py], i) => { const [x, y] = ovToCanvas(px, py); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
    ctx.stroke();
  }
  for (const h of state.hotspots) {
    const [x, y] = ovToCanvas(h.px[0], h.px[1]);
    ctx.fillStyle = '#c7a955';
    ctx.beginPath(); ctx.arc(x, y, 6, 0, 2 * Math.PI); ctx.fill();
  }
  if (state.crop) {
    const [a, b, c, d] = state.crop;
    ctx.strokeStyle = '#c7a955'; ctx.lineWidth = 2;
    ctx.strokeRect(a, b, c - a, d - b);
  }
}

function renderFileList() {
  $('fileList').innerHTML = state.files.map((n) => `<li>${n}</li>`).join('');
}

const ICONS = ['dot', 'peak', 'camp', 'water', 'flag', 'camera', 'star'];

function renderMarkers() {
  const host = $('markerList');
  if (!state.hotspots.length) { $('markers').hidden = true; return; }
  $('markers').hidden = false;
  host.innerHTML = '';
  state.hotspots.forEach((h, i) => {
    const row = document.createElement('div');
    row.className = 'marker-row';
    const opts = ICONS.map((ic) => `<option value="${ic}"${(h.icon || 'dot') === ic ? ' selected' : ''}>${ic}</option>`).join('');
    row.innerHTML =
      `<span class="dot"></span>` +
      `<input class="m-label" placeholder="Marker ${i + 1}" value="${h.label || ''}">` +
      `<select class="m-icon">${opts}</select>` +
      `<label class="m-photo${h.photo ? ' has' : ''}">📷<input type="file" accept="image/*" hidden></label>`;
    row.querySelector('.m-label').onchange = (e) => { h.label = e.target.value; pushMarkers(); };
    row.querySelector('.m-icon').onchange = (e) => { h.icon = e.target.value; pushMarkers(); };
    row.querySelector('.m-photo input').onchange = (e) => { if (e.target.files[0]) uploadPhoto(i, e.target.files[0], row); };
    host.appendChild(row);
  });
}

async function pushMarkers() {
  if (!state.session) return;
  const markers = state.hotspots.map((h, i) => ({ i, label: h.label || '', icon: h.icon || 'dot' }));
  const fd = new FormData();
  fd.append('session_id', state.session); fd.append('markers', JSON.stringify(markers));
  await fetch('/api/markers', { method: 'POST', body: fd });
  setStatus('Markers updated — re-render the proof to see them');
}

async function uploadPhoto(i, file, row) {
  const fd = new FormData();
  fd.append('session_id', state.session); fd.append('i', i); fd.append('file', file);
  const r = await fetch('/api/photo', { method: 'POST', body: fd });
  if (!r.ok) { setStatus('Photo rejected: ' + (await r.text())); return; }
  state.hotspots[i].photo = true;
  row.querySelector('.m-photo').classList.add('has');
  setStatus('Photo attached — re-render the proof to see it');
}

async function uploadFiles(fileList) {
  const arr = Array.from(fileList || []);
  if (!arr.length) return;
  const fd = new FormData();
  for (const f of arr) fd.append('files', f);
  if (state.session) fd.append('session_id', state.session);
  else if (state.regionId) fd.append('region_id', state.regionId);   // else backend auto-detects
  setStatus(`Uploading ${arr.length} file(s)…`);
  const r = await fetch('/api/upload', { method: 'POST', body: fd });
  if (!r.ok) { setStatus('Upload failed: ' + (await r.text())); return; }
  const j = await r.json();
  selectRegion(j.region);                                            // reflect the bound region
  state.session = j.session; state.ovSize = j.overview_size;
  state.scale = cv.width / j.overview_size[0];
  cv.height = Math.round(j.overview_size[1] * state.scale);
  state.tracks = j.tracks; state.hotspots = j.hotspots;
  state.files.push(...arr.map((f) => f.name)); renderFileList(); renderMarkers();
  overview.onload = draw; overview.src = j.overview;
  $('proofBtn').disabled = false; $('clearBtn').disabled = false;
  setStatus(`${j.tracks.length} track(s) across ${state.files.length} file(s) — drag a crop box`);
}

// drop zone + file picker
const drop = $('drop');
drop.onclick = () => $('files').click();
$('files').onchange = (e) => { uploadFiles(e.target.files); e.target.value = ''; };
drop.ondragover = (e) => { e.preventDefault(); drop.classList.add('over'); };
drop.ondragleave = () => drop.classList.remove('over');
drop.ondrop = (e) => { e.preventDefault(); drop.classList.remove('over'); uploadFiles(e.dataTransfer.files); };

$('clearBtn').onclick = () => {
  const regions = state.regions;                       // keep the loaded region list
  state = { session: null, ovSize: null, tracks: [], hotspots: [], crop: null, scale: 1, files: [], regionId: null, regions };
  selectRegion(regions.length === 1 ? regions[0].id : null);
  renderFileList(); renderMarkers(); ctx.clearRect(0, 0, cv.width, cv.height);
  $('proofImg').removeAttribute('src');
  $('proofBtn').disabled = true; $('acceptBtn').disabled = true; $('clearBtn').disabled = true;
  setStatus('Cleared — pick a region and drop files to start a new map');
};

loadRegions();

// drag a crop rectangle locked to the chosen print aspect ratio
let dragStart = null;
cv.onmousedown = (e) => { dragStart = [e.offsetX, e.offsetY]; };
cv.onmousemove = (e) => {
  if (!dragStart) return;
  const [sw, sh] = $('size').value.split(',').map(Number);
  const ar = sw / sh;
  const w = e.offsetX - dragStart[0];
  const h = w / ar;
  state.crop = [dragStart[0], dragStart[1], dragStart[0] + w, dragStart[1] + h];
  draw();
};
cv.onmouseup = () => { dragStart = null; };

$('proofBtn').onclick = async () => {
  if (!state.crop) { setStatus('Drag a crop box first'); return; }
  const [sw, sh] = $('size').value.split(',').map(Number);
  const [a, b] = canvasToOv(state.crop[0], state.crop[1]);
  const [c, d] = canvasToOv(state.crop[2], state.crop[3]);
  const fd = new FormData();
  fd.append('session_id', state.session);
  fd.append('x0', a); fd.append('y0', b); fd.append('x1', c); fd.append('y1', d);
  fd.append('print_w', sw); fd.append('print_h', sh);
  setStatus('Rendering proof…');
  const r = await fetch('/api/proof', { method: 'POST', body: fd });
  if (!r.ok) { setStatus('Proof rejected: ' + (await r.text())); $('acceptBtn').disabled = true; return; }
  $('proofImg').src = URL.createObjectURL(await r.blob());
  $('acceptBtn').disabled = false;
  setStatus('Proof ready — accept to render the full-resolution final');
};

$('acceptBtn').onclick = async () => {
  const fd = new FormData(); fd.append('session_id', state.session);
  setStatus('Rendering final at 300 dpi…');
  const r = await fetch('/api/final', { method: 'POST', body: fd });
  if (!r.ok) { setStatus('Final failed: ' + (await r.text())); return; }
  const a = document.createElement('a');
  a.href = URL.createObjectURL(await r.blob()); a.download = 'trailprint.png'; a.click();
  setStatus('Final downloaded.');
};
