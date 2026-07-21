// controls.js — the declarative registry of every user-settable option. ONE entry per
// control is the single source of truth for: how the inspector renders it, how the
// command palette and search find it, how a preset diffs against it, how "reset to
// default" knows the default, and — critically — whether editing it stales the proof.
//
// Ranges mirror app/spec.py STYLE_BOUNDS (the true server bounds), not the old,
// narrower UI ranges: the studio exposes the full instrument. Defaults mirror the
// spec/proof-form defaults so "reset" and preset-diffing agree with the server.
//
// This module is pure data + pure helpers. It imports nothing from the DOM or the
// render pipeline, so it can't create import cycles with store.js (which imports the
// proof-path list FROM here via markProofPaths at boot).

// --- formatters (kept tiny; the inspector reads `fmt(value)`) -----------------------
const pt = (v) => `${Number(v).toFixed(1)} pt`;
const f2 = (v) => Number(v).toFixed(2);
const f1 = (v) => Number(v).toFixed(1);
const mult = (v) => `${Number(v).toFixed(2)}×`;
const inch = (v) => `${Number(v).toFixed(2)} in`;
const deg = (v) => `${Math.round(Number(v))}°`;
const pct = (v) => `${Math.round(Number(v) * 100)}%`;

// Local-solar hour (e.g. 17.25) -> a friendly "5:15 PM". Shared with the sun dial.
export function fmtHour(h) {
  if (h == null) return 'Summit light';
  const hh = Math.floor(h);
  const mm = Math.round((h - hh) * 60);
  const ap = hh < 12 ? 'AM' : 'PM';
  const h12 = ((hh + 11) % 12) + 1;
  return `${h12}:${String(mm).padStart(2, '0')} ${ap}`;
}

// The six curated track colors (the archival gold plus five alternates).
export const SWATCHES = [
  { hex: '#d69e3a', label: 'Desert gold' },
  { hex: '#b24c2b', label: 'Rust' },
  { hex: '#4a6936', label: 'Forest' },
  { hex: '#7a4a66', label: 'Plum' },
  { hex: '#33415e', label: 'Midnight' },
  { hex: '#3a3733', label: 'Charcoal' },
];

// One-line descriptions for each panel group, rendered under the group heading so the
// sidebar explains itself. Keys match the `panel` values below.
export const GROUPS = {
  'Page': 'The physical sheet: its size, trim, and title.',
  'Route': 'How your journeys ink onto the terrain.',
  'Terrain': 'The mountains themselves — depth, shadow, and relief.',
  'Markers': 'The gold dots marking places you returned to, and the sheet furniture.',
  'Cartography': 'Named geography and map layers painted from USGS data.',
  'Elevation profile': 'A strip graph of your climbs, sampled from the terrain itself.',
  'Journey Light': 'Light the poster with the sun your hike actually saw.',
  'Pacing': 'How fast the film inks your journeys, and how long it rests.',
  'Output': 'The film container and whether its sun travels.',
  'File': 'What the exported file carries.',
};

// --- the registry -------------------------------------------------------------------
// section: which studio section owns this control (compose|style|layers|light|films|export)
// panel:   sub-group heading within that section's inspector
// help:    one plain sentence explaining the choice, rendered behind the row's ? toggle
//          (distinct from `hint`, the terse label suffix)
// geometry: writes the sheet/crop, so it routes through the reframe helper (which stales
//           the proof) instead of a plain setField — the inspector defers to the section.
// advanced: hidden from the primary panel; reachable via the "All options" drawer/palette.
export const CONTROLS = [
  // ===== COMPOSE (page setup) =====
  { id: 'output', path: 'output', section: 'compose', panel: 'Page', label: 'Output',
    type: 'segmented', default: 'print', affectsProof: true, geometry: true,
    options: [{ value: 'print', label: 'Print' }, { value: 'wallpaper', label: 'Wallpaper' }],
    help: 'Print makes a paper poster at 300 dpi; Wallpaper fits a screen at its native pixels.',
    keywords: ['print', 'wallpaper', 'screen', 'device'] },
  { id: 'size', path: 'printSize', section: 'compose', panel: 'Page', label: 'Print size',
    type: 'sizeSelect', default: '18,24', affectsProof: true, geometry: true,
    visibleWhen: (s) => s.output !== 'wallpaper',
    help: 'The paper size in inches. Bigger sheets need a wider map crop to stay sharp.',
    keywords: ['size', 'dimensions', '18x24', '24x36', 'paper'] },
  { id: 'orientation', path: 'orientation', section: 'compose', panel: 'Page', label: 'Orientation',
    type: 'segmented', default: 'auto', affectsProof: true, geometry: true,
    visibleWhen: (s) => s.output !== 'wallpaper',
    options: [{ value: 'auto', label: 'Auto' }, { value: 'landscape', label: 'Landscape' },
              { value: 'portrait', label: 'Portrait' }],
    help: 'Auto lets the shape of your tracks decide which way the sheet turns.',
    keywords: ['landscape', 'portrait', 'rotate'] },
  { id: 'bleed', path: 'style.bleedIn', section: 'compose', panel: 'Page', label: 'Print-shop bleed',
    type: 'slider', min: 0, max: 0.5, step: 0.125, default: 0, fmt: (v) => v ? inch(v) : 'None',
    affectsProof: true, visibleWhen: (s) => s.output !== 'wallpaper',
    help: 'Extra painted margin a print lab trims off. Ask your print shop; 0.125 in is typical.',
    keywords: ['bleed', 'trim', 'print shop', 'lab'] },
  { id: 'title', path: 'title', section: 'compose', panel: 'Page', label: 'Poster title',
    type: 'text', maxlength: 60, default: '', placeholder: 'Region name — “-” for none',
    affectsProof: true, visibleWhen: (s) => s.output !== 'wallpaper',
    help: 'The cartouche title. Empty uses the region\'s name; a single dash removes the block.',
    keywords: ['title', 'name', 'caption', 'heading'] },

  // ===== STYLE (the ink) =====
  { id: 'color', path: 'style.color', section: 'style', panel: 'Route', label: 'Track color',
    type: 'swatch', swatches: SWATCHES, default: '', affectsProof: true,
    help: 'The route\'s ink. Desert gold is the archival default; five alternates match the paper.',
    keywords: ['color', 'gold', 'ink', 'route', 'line color'] },
  { id: 'width', path: 'style.width', section: 'style', panel: 'Route', label: 'Track width',
    type: 'slider', min: 0.8, max: 6.0, step: 0.1, default: 2.6, fmt: pt, affectsProof: true,
    help: 'Stroke width of the route line, in points on the printed sheet.',
    keywords: ['width', 'thickness', 'line', 'stroke'] },
  { id: 'halo', path: 'style.halo', section: 'style', panel: 'Route', label: 'Track outline',
    type: 'slider', min: 0, max: 0.9, step: 0.05, default: 0.7, fmt: f2, affectsProof: true,
    help: 'A paper-colored casing around the route so it stays readable over dark terrain.',
    keywords: ['halo', 'outline', 'paper', 'casing'] },
  { id: 'trackColorBy', path: 'style.trackColorBy', section: 'style', panel: 'Route', label: 'Color track by',
    type: 'select', default: 'none', affectsProof: true,
    options: [{ value: 'none', label: 'Solid swatch' }, { value: 'elevation', label: 'Elevation' },
              { value: 'grade', label: 'Grade' }],
    help: 'Color the route by the terrain it crossed: height above sea level, or steepness.',
    keywords: ['gradient', 'elevation', 'grade', 'ramp', 'color by'] },
  { id: 'trackWeave', path: 'style.trackWeave', section: 'style', panel: 'Route', label: 'Weave crossings',
    hint: 'newer journeys cross over older', type: 'toggle', default: true, affectsProof: true,
    help: 'Where journeys cross, newer ones pass over older ones like woven threads.',
    keywords: ['weave', 'crossings', 'over under', 'chronological'] },

  { id: 'terrain', path: 'style.terrain', section: 'style', panel: 'Terrain', label: 'Terrain depth',
    type: 'slider', min: 0, max: 1.5, step: 0.1, default: 1.0, fmt: mult, affectsProof: true,
    help: 'How deeply the hillshading models the terrain. 0 flattens it to plain paper.',
    keywords: ['terrain', 'depth', 'texture', 'relief'] },
  { id: 'shadow', path: 'style.shadow', section: 'style', panel: 'Terrain', label: 'Cast shadows',
    type: 'slider', min: 0, max: 1, step: 0.1, default: 0.5, fmt: f1, affectsProof: true,
    help: 'Long cast shadows and sky occlusion — the dramatic, physical side of the relief.',
    keywords: ['shadow', 'cast', 'blender', 'relief', 'occlusion'] },
  { id: 'oblique', path: 'style.oblique', section: 'style', panel: 'Terrain', label: 'High relief',
    hint: 'plan-oblique stand-up terrain', type: 'slider', min: 0, max: 1, step: 0.05, default: 0,
    fmt: f2, affectsProof: true, keywords: ['oblique', 'high relief', '3d', 'stand up', 'tilt'] },

  { id: 'marker', path: 'style.marker', section: 'style', panel: 'Markers', label: 'Marker size',
    type: 'slider', min: 0.1, max: 0.5, step: 0.01, default: 0.24, fmt: inch, affectsProof: true,
    help: 'Tilts the terrain up out of the sheet so ridges stand like a raised-relief model.',
    help: 'Diameter of the gold place dots, in inches on the sheet.',
    keywords: ['marker', 'dot', 'size', 'poi'] },
  { id: 'ring', path: 'style.ring', section: 'style', panel: 'Markers', label: 'Marker outline',
    type: 'slider', min: 0, max: 0.25, step: 0.01, default: 0.09, fmt: f2, affectsProof: true,
    help: 'The outline ring around each place dot, as a fraction of its size.',
    keywords: ['marker', 'ring', 'outline'] },
  { id: 'photoStyle', path: 'style.photoStyle', section: 'style', panel: 'Markers', label: 'Photo frame',
    type: 'select', default: 'mat', affectsProof: true,
    options: [{ value: 'mat', label: 'Classic mat' }, { value: 'keyline', label: 'Thin keyline' },
              { value: 'borderless', label: 'Borderless' }, { value: 'polaroid', label: 'Polaroid' }],
    help: 'How a pinned photo is framed on the sheet — mat, keyline, borderless, or polaroid.',
    keywords: ['photo', 'frame', 'mat', 'polaroid', 'keyline'] },
  { id: 'furniture', path: 'style.furniture', section: 'style', panel: 'Markers', label: 'Legend & compass size',
    type: 'slider', min: 0.6, max: 1.6, step: 0.05, default: 1.0, fmt: mult, affectsProof: true,
    help: 'Scales the legend, compass, and cartouche together relative to their automatic size.',
    keywords: ['furniture', 'legend', 'compass', 'cartouche', 'scale'] },

  // ===== LAYERS (named geography + strips) =====
  { id: 'contours', path: 'contours', section: 'layers', panel: 'Cartography', label: 'Contour lines',
    type: 'toggle', default: false, affectsProof: true, keywords: ['contour', 'elevation lines'] },
  { id: 'compass', path: 'compass', section: 'layers', panel: 'Cartography', label: 'Compass rose',
    type: 'toggle', default: true, affectsProof: true,
    visibleWhen: (s) => s.output !== 'wallpaper', keywords: ['compass', 'rose', 'north'] },
  { id: 'biome', path: 'biome', section: 'layers', panel: 'Cartography', label: 'Biome color',
    type: 'toggle', default: false, affectsProof: true,
    help: 'Elevation contour lines traced from the USGS terrain model.',
    help: 'A compass rose above the title block.',
    help: 'Tint the land by what grows there (USGS land cover): forest green, desert sage.',
    keywords: ['biome', 'land cover', 'nlcd', 'vegetation', 'color'] },
  { id: 'labels', path: 'labels', section: 'layers', panel: 'Cartography', label: 'Place names',
    type: 'toggle', default: false, affectsProof: true,
    help: 'Peak, lake, and place names from the USGS names gazetteer.',
    keywords: ['labels', 'place names', 'gnis', 'peaks', 'water'] },
  { id: 'labelPlace', path: 'style.labelPlace', section: 'layers', panel: 'Cartography', label: 'Smart labels',
    hint: 'dodge the route, leader lines', type: 'toggleMap', onValue: 'smart', offValue: 'anchor',
    default: 'smart', affectsProof: true, visibleWhen: (s) => s.labels,
    help: 'Smart placement dodges the route and adds leader lines; off pins names in place.',
    keywords: ['smart labels', 'placement', 'leader lines', 'dodge'] },
  { id: 'profile', path: 'style.profile', section: 'layers', panel: 'Elevation profile', label: 'Elevation profile',
    type: 'toggle', default: false, affectsProof: true,
    help: 'A strip graph of elevation along your journeys, drawn beneath the map.',
    keywords: ['profile', 'elevation strip', 'graph'] },
  { id: 'profileHeight', path: 'style.profileHeight', section: 'layers', panel: 'Elevation profile',
    label: 'Profile height', type: 'slider', min: 0, max: 2.5, step: 0.1, default: 0.9, fmt: inch,
    affectsProof: true, visibleWhen: (s) => s.style.profile,
    help: 'Height of the elevation strip, in inches.',
    keywords: ['profile height', 'strip'] },
  { id: 'profileRev', path: 'style.profileRev', section: 'layers', panel: 'Elevation profile',
    label: 'Profile layout', type: 'select', default: null, advanced: true, affectsProof: true,
    options: [{ value: 2, label: 'Rev 2 (corrected)' }, { value: 1, label: 'Rev 1 (legacy)' }],
    visibleWhen: (s) => s.style.profile, keywords: ['profile rev', 'layout', 'legacy'] },

  // ===== LIGHT (Journey Light) =====
  { id: 'lightMode', path: 'style.lightMode', section: 'light', panel: 'Journey Light', label: 'Journey light',
    hint: "lit by your hike's own sun", type: 'toggleMap', onValue: 'journey', offValue: 'archival',
    default: 'archival', affectsProof: true,
    help: 'Layout revision of the strip. Rev 2 is corrected; Rev 1 matches older posters.',
    help: 'Archival is the region\'s curated light; Journey lights the terrain with your hike\'s own sun.',
    keywords: ['journey light', 'sun', 'timestamp', 'golden hour'] },
  { id: 'sunHour', path: 'style.sunHour', section: 'light', panel: 'Journey Light', label: 'Time of day',
    type: 'slider', min: 5, max: 21, step: 0.25, default: null, fmt: fmtHour, affectsProof: true,
    visibleWhen: (s) => s.style.lightMode === 'journey',
    help: 'Scrub the sun through your hike\'s day — shadows and warmth follow the clock.',
    keywords: ['time of day', 'sun hour', 'golden hour', 'scrubber'] },
  { id: 'sunAzimuth', path: 'style.sunAzimuth', section: 'light', panel: 'Journey Light', label: 'Sun azimuth',
    type: 'dial', min: 0, max: 360, step: 1, default: null, fmt: deg, affectsProof: true, advanced: true,
    visibleWhen: (s) => s.style.lightMode === 'journey',
    help: 'Exact compass direction the sun shines from (advanced; the scrubber sets this for you).',
    keywords: ['azimuth', 'sun direction', 'bearing'] },
  { id: 'sunAltitude', path: 'style.sunAltitude', section: 'light', panel: 'Journey Light', label: 'Sun altitude',
    type: 'dial', min: 8, max: 80, step: 1, default: null, fmt: deg, affectsProof: true, advanced: true,
    visibleWhen: (s) => s.style.lightMode === 'journey',
    help: 'Exact sun height above the horizon (advanced; low sun means long shadows).',
    keywords: ['altitude', 'sun height', 'elevation angle'] },
  { id: 'golden', path: 'style.golden', section: 'light', panel: 'Journey Light', label: 'Golden-hour grade',
    type: 'slider', min: 0, max: 1, step: 0.05, default: 0.7, fmt: pct, affectsProof: true,
    visibleWhen: (s) => s.style.lightMode === 'journey',
    help: 'How strongly the warm/cool golden-hour color grade is applied in journey light.',
    keywords: ['golden', 'warm', 'cool', 'grade', 'tint'] },

  // ===== FILMS (time-lapse — output options, never stale the proof) =====
  { id: 'tlFrames', path: 'tlFrames', section: 'films', panel: 'Pacing', label: 'Frames',
    type: 'slider', min: 2, max: 120, step: 1, default: 40, fmt: (v) => `${v}`, affectsProof: false,
    help: 'How many frames the film paints. More frames, smoother inking, longer render.',
    keywords: ['frames', 'film length', 'timelapse'] },
  { id: 'tlStepMs', path: 'tlStepMs', section: 'films', panel: 'Pacing', label: 'Frame hold',
    type: 'slider', min: 40, max: 1000, step: 20, default: 220, fmt: (v) => `${v} ms`, affectsProof: false,
    help: 'How long each frame holds as the journeys ink in.',
    keywords: ['step', 'speed', 'pace', 'frame hold'] },
  { id: 'tlHoldMs', path: 'tlHoldMs', section: 'films', panel: 'Pacing', label: 'Final hold',
    type: 'slider', min: 40, max: 10000, step: 100, default: 2500, fmt: (v) => `${(v / 1000).toFixed(1)} s`,
    affectsProof: false, keywords: ['hold', 'final frame', 'pause'] },
  { id: 'tlLeaderMs', path: 'tlLeaderMs', section: 'films', panel: 'Pacing', label: 'Opening hold',
    type: 'slider', min: 0, max: 5000, step: 100, default: 700, fmt: (v) => `${(v / 1000).toFixed(1)} s`,
    affectsProof: false, keywords: ['leader', 'opening', 'intro'] },
  { id: 'tlFormat', path: 'tlFormat', section: 'films', panel: 'Output', label: 'Film format',
    type: 'segmented', default: 'apng', affectsProof: false,
    options: [{ value: 'apng', label: 'APNG' }, { value: 'webp', label: 'WebP' }, { value: 'mp4', label: 'MP4' }],
    help: 'How long the finished poster holds before the film loops.',
    help: 'How long the empty terrain holds before the first journey appears.',
    help: 'APNG is archival and reprints from itself; WebP and MP4 are share copies for feeds.',
    keywords: ['apng', 'webp', 'mp4', 'video', 'format'] },
  { id: 'lightMotion', path: 'lightMotion', section: 'films', panel: 'Output', label: 'Light motion',
    type: 'select', default: 'none', affectsProof: false,
    options: [{ value: 'none', label: 'Fixed sun' }, { value: 'auto', label: 'Sun travels (auto)' },
              { value: 'diurnal', label: 'Diurnal — one day' }, { value: 'seasonal', label: 'Seasonal — the year' }],
    help: 'Let the sun travel while the film plays — across one day, or the whole year.',
    keywords: ['light motion', 'sun travels', 'diurnal', 'seasonal', 'moving sun'] },

  // ===== EXPORT (privacy + print format — output options) =====
  { id: 'finalFormat', path: 'finalFormat', section: 'export', panel: 'File', label: 'Final format',
    type: 'segmented', default: 'png', affectsProof: false,
    options: [{ value: 'png', label: 'PNG' }, { value: 'pdf', label: 'PDF' }],
    help: 'PNG is the archival save file; PDF is for the print shop and carries no recipe.',
    keywords: ['png', 'pdf', 'format', 'print shop'] },
  { id: 'embedSpec', path: 'embedSpec', section: 'export', panel: 'File', label: 'Reprintable file',
    hint: 'off = share copy, strips exact route coordinates', type: 'toggle', default: true,
    affectsProof: false,
    help: 'On: the file carries its whole recipe and reprints forever. Off: a share copy without your exact coordinates.',
    keywords: ['reprint', 'manifest', 'privacy', 'share copy', 'coordinates'] },
];

// --- indexes + helpers --------------------------------------------------------------
const byId = new Map(CONTROLS.map((c) => [c.id, c]));
const byPath = new Map(CONTROLS.map((c) => [c.path, c]));

export function control(id) { return byId.get(id); }
export function controlByPath(path) { return byPath.get(path); }
export function forSection(section) { return CONTROLS.filter((c) => c.section === section); }
export function panelsOf(section) {
  const seen = [];
  for (const c of forSection(section)) if (!seen.includes(c.panel)) seen.push(c.panel);
  return seen;
}

// Every path whose edit is a picture decision — handed to store.markProofPaths at boot
// so the setField choke-point stales the proof without any per-call bookkeeping.
export function proofAffectingPaths() {
  return CONTROLS.filter((c) => c.affectsProof).map((c) => c.path);
}

// A control's display value from a state object (handles toggleMap on/off mapping).
export function displayValue(c, state) {
  const dot = c.path.indexOf('.');
  const raw = dot < 0 ? state[c.path] : state[c.path.slice(0, dot)]?.[c.path.slice(dot + 1)];
  return raw;
}

// The default a "reset" restores (the server/spec default, so reprint math agrees).
export function defaultOf(id) { return byId.get(id)?.default; }
