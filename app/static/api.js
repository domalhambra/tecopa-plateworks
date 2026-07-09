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

// Surface the server's humanized `detail` sentence, not the raw JSON envelope --
// the operator used to see `{"detail":"Tracks don't fall..."}` verbatim.
async function errText(res) {
  const txt = await res.text();
  try {
    const j = JSON.parse(txt);
    if (j && j.detail) return String(j.detail).slice(0, 300);
  } catch { /* not JSON */ }
  return txt.slice(0, 300);
}

async function asJson(res) {
  if (!res.ok) throw new ApiError(res.status, await errText(res));
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

// Living editions: open a TrailPrint PNG for its next edition. Resurrects a session
// from the file's embedded manifest and returns the /api/upload response shape plus a
// `prefill` block (style, title, size, output, edition, lineage) and `edition`.
export async function continuePoster(file) {
  const fd = new FormData();
  fd.append('file', file);
  const res = await fetch('/api/continue', { method: 'POST', body: fd });
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

// Render a proof; resolves to a PNG Blob, throws ApiError(422, "<detail>") when the
// crop trips the zoom cap / off-DEM / aspect guard so the caller can show it.
// `title` rides along ('' -> region-name default on the server; '-' -> no block);
// `contours`/`compass` are the optional furniture toggles.
export async function proof(sessionId, cropOv, printW, printH,
                            { title = '', contours = false, compass = true,
                              biome = false, labels = false, style = {},
                              output = 'print', wpPreset = '' } = {}) {
  const [x0, y0, x1, y1] = cropOv;
  const res = await postForm('/api/proof', {
    session_id: sessionId, x0, y0, x1, y1, print_w: printW, print_h: printH,
    output, wallpaper_preset: output === 'wallpaper' ? wpPreset : undefined,
    title: title || undefined,
    contours: contours ? 'true' : 'false', compass: compass ? 'true' : 'false',
    biome: biome ? 'true' : 'false', labels: labels ? 'true' : 'false',
    track_width_pt: style.width, track_halo: style.halo,
    track_color: style.color || undefined,
    marker_size_in: style.marker, marker_ring: style.ring,
    photo_style: style.photoStyle, furniture_scale: style.furniture,
    terrain_depth: style.terrain, shadow_strength: style.shadow,
  });
  if (!res.ok) throw new ApiError(res.status, await errText(res));
  return res.blob();
}

export async function submitFinal(sessionId, format = 'png', embedSpec = true) {
  const res = await postForm('/api/final/submit',
    { session_id: sessionId, format, embed_spec: embedSpec ? 'true' : 'false' });
  return asJson(res);   // { job }
}

export async function getWallpaperPresets() {
  const res = await fetch('/api/wallpapers/presets');
  if (!res.ok) throw new ApiError(res.status, 'could not load wallpaper presets');
  return res.json();    // [{ id, name, px, ppi, device_class, top_clear_frac }]
}

export async function submitWallpapers(sessionId, presetIds, embedSpec = true) {
  const res = await postForm('/api/wallpapers/submit',
    { session_id: sessionId, presets: presetIds.join(','),
      embed_spec: embedSpec ? 'true' : 'false' });
  return asJson(res);   // { job, count, skipped: [{preset, reason}] }
}

// Time-lapse: render the accepted composition as a film (the day-ordered journeys
// accumulate to the complete poster). Returns { job, frames }; poll like any render.
export async function submitTimelapse(sessionId, { maxFrames = 40, wpPreset = '',
                                                   embedSpec = true } = {}) {
  const res = await postForm('/api/timelapse/submit', {
    session_id: sessionId, max_frames: maxFrames,
    wallpaper_preset: wpPreset || undefined,
    embed_spec: embedSpec ? 'true' : 'false',
  });
  return asJson(res);   // { job, frames }
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
