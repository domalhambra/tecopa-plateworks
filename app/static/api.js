// api.js — thin fetch wrappers for every endpoint the wizard uses. Each returns
// parsed JSON / a Blob, or throws a typed ApiError carrying the HTTP status and the
// server's message so callers can humanize it (e.g. the zoom-cap 422).
export class ApiError extends Error {
  constructor(status, message) { super(message || `HTTP ${status}`); this.status = status; }
}

async function postForm(url, fields) {
  const fd = new FormData();
  for (const [k, v] of Object.entries(fields)) {
    if (v !== undefined && v !== null) fd.append(k, v);
  }
  return fetch(url, { method: 'POST', body: fd });
}

async function asJson(res) {
  if (!res.ok) throw new ApiError(res.status, (await res.text()).slice(0, 300));
  return res.json();
}

export async function getRegions() {
  const res = await fetch('/api/regions');
  if (!res.ok) throw new ApiError(res.status, 'could not load regions');
  return res.json();
}

export async function upload(files, { sessionId, regionId } = {}) {
  const fd = new FormData();
  for (const f of files) fd.append('files', f);
  if (sessionId) fd.append('session_id', sessionId);
  else if (regionId) fd.append('region_id', regionId);   // else the server auto-detects
  const res = await fetch('/api/upload', { method: 'POST', body: fd });
  return asJson(res);
}

export async function setMarkers(sessionId, markers) {
  const res = await postForm('/api/markers', { session_id: sessionId, markers: JSON.stringify(markers) });
  return asJson(res);
}

export async function uploadPhoto(sessionId, i, file) {
  const fd = new FormData();
  fd.append('session_id', sessionId); fd.append('i', i); fd.append('file', file);
  const res = await fetch('/api/photo', { method: 'POST', body: fd });
  return asJson(res);
}

export async function moveMarker(sessionId, i, px, py) {
  const res = await postForm('/api/markers/move', { session_id: sessionId, i, px, py });
  return asJson(res);   // { ok, px, py } — clamped snap-back position
}

// Render a proof; resolves to a PNG Blob, throws ApiError(422, "<zoom msg>") when
// the crop trips the cap so the caller can show the humanized message.
export async function proof(sessionId, cropOv, printW, printH) {
  const [x0, y0, x1, y1] = cropOv;
  const res = await postForm('/api/proof', {
    session_id: sessionId, x0, y0, x1, y1, print_w: printW, print_h: printH,
  });
  if (!res.ok) throw new ApiError(res.status, (await res.text()).slice(0, 300));
  return res.blob();
}

export async function submitFinal(sessionId) {
  const res = await postForm('/api/final/submit', { session_id: sessionId });
  return asJson(res);   // { job }
}

export async function jobStatus(jid) {
  const res = await fetch(`/api/jobs/${jid}`);
  return asJson(res);   // { state, error, result? }
}

export async function fetchBlob(url) {
  const res = await fetch(url);
  if (!res.ok) throw new ApiError(res.status, 'result fetch failed');
  return res.blob();
}
