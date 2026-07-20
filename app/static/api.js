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

// Living editions: open a Tecopa Printworks PNG for its next edition. Resurrects a session
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
                              output = 'print', wpPreset = '',
                              customDevice = null } = {}) {
  const [x0, y0, x1, y1] = cropOv;
  const custom = output === 'wallpaper' && wpPreset === 'custom' && customDevice;
  const res = await postForm('/api/proof', {
    session_id: sessionId, x0, y0, x1, y1, print_w: printW, print_h: printH,
    output, wallpaper_preset: output === 'wallpaper' ? wpPreset : undefined,
    // print-shop bleed (v1.12): extra trimmed sheet; print-only, omitted at 0 so the
    // server default (no bleed) applies and old posters reprint byte-identically.
    bleed: output === 'print' && style.bleedIn ? style.bleedIn : undefined,
    // the escape-hatch device (wpPreset 'custom'): exact pixels + physical ppi
    custom_px_w: custom ? customDevice.px[0] : undefined,
    custom_px_h: custom ? customDevice.px[1] : undefined,
    custom_ppi: custom ? customDevice.ppi : undefined,
    title: title || undefined,
    contours: contours ? 'true' : 'false', compass: compass ? 'true' : 'false',
    biome: biome ? 'true' : 'false', labels: labels ? 'true' : 'false',
    track_width_pt: style.width, track_halo: style.halo,
    track_color: style.color || undefined,
    marker_size_in: style.marker, marker_ring: style.ring,
    photo_style: style.photoStyle, furniture_scale: style.furniture,
    terrain_depth: style.terrain, shadow_strength: style.shadow,
    oblique: style.oblique,
    // Journey Light: light_mode + the sun (hour from the scrubber, or explicit az/alt on
    // the continue-restore path), the golden grade, the elevation profile, and coloring.
    light_mode: style.lightMode || 'archival',
    sun_hour: style.lightMode === 'journey' && style.sunHour != null ? style.sunHour : undefined,
    sun_azimuth_deg: style.sunAzimuth != null ? style.sunAzimuth : undefined,
    sun_altitude_deg: style.sunAltitude != null ? style.sunAltitude : undefined,
    golden_strength: style.golden,
    profile: style.profile ? 'true' : 'false',
    profile_height_in: style.profileHeight,
    // profile_rev (v1.12): a continued poster passes its own stored rev; a NEW proof
    // omits it and the server default (2, the corrected strip) applies.
    profile_rev: style.profileRev != null ? style.profileRev : undefined,
    track_color_by: style.trackColorBy || 'none',
    // smart label placement + chronological weave (v1.10): new posters default to the
    // enhanced look; the continue-restore path passes the poster's own stored values.
    label_place: style.labelPlace || 'smart',
    track_weave: style.trackWeave === false ? 'false' : 'true',
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
// accumulate to the complete poster). format: 'apng' (archival, default) or a share
// twin ('webp' | 'mp4' — no manifest, embed_spec is moot). Pacing (stepMs/holdMs/
// leaderMs) rides the manifest's animation block, not the spec — it is not a picture
// decision, so it never stales the proof. Returns { job, frames }; poll like any render.
export async function submitTimelapse(sessionId, { maxFrames = 40, wpPreset = '',
                                                   embedSpec = true, format = 'apng',
                                                   lightMotion = 'none',
                                                   stepMs, holdMs, leaderMs } = {}) {
  const res = await postForm('/api/timelapse/submit', {
    session_id: sessionId, max_frames: maxFrames,
    // pacing knobs (omitted when unset so the server default applies and a reprint of a
    // pre-feature film stays byte-identical)
    step_ms: stepMs, hold_ms: holdMs, leader_ms: leaderMs,
    wallpaper_preset: wpPreset || undefined,
    embed_spec: embedSpec ? 'true' : 'false',
    format,
    // Journey Light film: 'none' is the archival reveal; 'auto'/'diurnal'/'seasonal'
    // make the sun travel with the hike (a share twin -- webp/mp4 only).
    light_motion: lightMotion,
  });
  return asJson(res);   // { job, frames }
}

// Living editions / Library: read a poster's provenance without rendering (which region,
// source hashes, edition, lineage, plate verdict). Pure manifest read; safe on any PNG.
export async function inspectPoster(file) {
  const fd = new FormData();
  fd.append('file', file);
  const res = await fetch('/api/reprint/inspect', { method: 'POST', body: fd });
  return asJson(res);   // { region_id, region_available, edition, lineage, plate, ... }
}

// Reprint a poster from the file alone (stateless — the recipe rides the manifest).
// A still returns { blob, filename } for immediate download; a film returns { job } (poll
// it like any render). The caller branches on the shape. embedSpec carries into the copy.
export async function reprint(file, { format = 'png', embedSpec = true } = {}) {
  const fd = new FormData();
  fd.append('file', file);
  fd.append('format', format);
  fd.append('embed_spec', embedSpec ? 'true' : 'false');
  const res = await fetch('/api/reprint', { method: 'POST', body: fd });
  if (!res.ok) throw new ApiError(res.status, await errText(res));
  // a film re-render comes back as JSON {job}; a still is a binary stream.
  const ct = res.headers.get('Content-Type') || '';
  if (ct.includes('application/json')) return { job: (await res.json()).job };
  const filename = dispositionFilename(res.headers.get('Content-Disposition')) || `tecopa.${format}`;
  return { blob: await res.blob(), filename };
}

// Wall-art mockups: stage a finished poster (or film) as photographed objects (the
// embossed Plate, the matted Frame) for social. Stateless — send the final's bytes.
// Returns { job } (poll like any render); the result is one zip of JPEGs/MP4s.
export async function submitMockups(file, { variants = 'plate,frame',
                                            sizes = '1080x1080,1080x1350',
                                            video = false, caption = true } = {}) {
  const fd = new FormData();
  fd.append('file', file);
  fd.append('variants', variants);
  fd.append('sizes', sizes);
  fd.append('video', video ? 'true' : 'false');
  fd.append('caption', caption ? 'true' : 'false');
  const res = await fetch('/api/mockups/submit', { method: 'POST', body: fd });
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

// The server names every deliverable (tecopa_<region>[_edition-N][_years]….ext,
// a pure function of the spec) via Content-Disposition — same-origin fetch exposes
// the header. Returns { blob, filename }; `fallback` covers a missing/odd header so
// the download never loses its old generic name.
function dispositionFilename(header) {
  const m = /filename="([^"]+)"/.exec(header || '');
  return m ? m[1] : '';
}

export async function fetchDownload(url, fallback) {
  const res = await fetch(url);
  if (!res.ok) throw new ApiError(res.status, 'result fetch failed');
  const filename = dispositionFilename(res.headers.get('Content-Disposition')) || fallback;
  return { blob: await res.blob(), filename };
}

// GPX-first region creation (when no built plate covers the dropped tracks):
//   plan  -> the cost card (padded bbox + UTM zone + honest estimate + name prefill).
//            Takes the SAME File[] the failed upload had. Pure logic server-side --
//            never fetches, never writes. Returns {us_covered, prep_ready, over_budget,
//            bbox, epsg, id, name_prefill, resolution_m, grid, est_dem_mb, n_slices}.
//   build -> enqueue the background build on the dedicated build queue. Returns {job}.
//   buildStatus -> poll {state, progress, error, result:{region, labels_note}}.
export async function planRegion(files) {
  const fd = new FormData();
  for (const f of files) fd.append('files', f);
  const res = await fetch('/api/regions/plan', { method: 'POST', body: fd });
  return asJson(res);
}
export async function buildRegion(params) {
  const res = await fetch('/api/regions/build', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params) });
  return asJson(res);
}
export async function buildStatus(jid) {
  const res = await fetch(`/api/regions/build/${jid}`);
  return asJson(res);
}
