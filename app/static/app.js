const cv = document.getElementById('map');
const ctx = cv.getContext('2d');
const overview = new Image();
let state = { session: null, ovSize: null, tracks: [], hotspots: [], crop: null, scale: 1 };

const $ = (id) => document.getElementById(id);
const setStatus = (m) => { $('status').textContent = m || ''; };

// overview pixels <-> canvas pixels (the canvas is the overview scaled to fit)
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

$('gpx').onchange = async (e) => {
  if (!e.target.files[0]) return;
  const fd = new FormData(); fd.append('gpx', e.target.files[0]);
  setStatus('Uploading…');
  const r = await fetch('/api/upload', { method: 'POST', body: fd });
  if (!r.ok) { setStatus('Upload failed: ' + (await r.text())); return; }
  const j = await r.json();
  state.session = j.session; state.ovSize = j.overview_size;
  state.scale = cv.width / j.overview_size[0];
  cv.height = Math.round(j.overview_size[1] * state.scale);
  state.tracks = j.tracks; state.hotspots = j.hotspots; state.crop = null;
  overview.onload = draw; overview.src = j.overview;
  $('proofBtn').disabled = false; $('acceptBtn').disabled = true;
  setStatus(`${j.tracks.length} track(s) loaded — drag a crop box`);
};

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
