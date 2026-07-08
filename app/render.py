# app/render.py
from __future__ import annotations
import json, math as _m, os
import numpy as np
import rasterio
from rasterio.windows import from_bounds
from rasterio.enums import Resampling
from scipy.ndimage import gaussian_filter
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from app.spec import CompositionSpec, OffDemError
from app.relief import shaded_relief, grain, TEXTURE_RADIUS_M, VALLEY_RADIUS_M

MARGIN_FRAC = 0.06   # read a little past the crop so shadows entering the frame are correct
# Fabricated-terrain guard (invariant 5 / red-team V1-1): if more than this fraction
# of the crop itself has no DEM coverage, the crop overhangs real data and painting it
# would invent smooth terrain under real tracks -- refuse loudly instead. A sliver of
# interior nodata below this is repaired by relief._fill_nan.
MAX_OFFDEM_NAN_FRAC = 0.01
# The coverage is measured on a FIXED probe grid (not the output-resolution window), so
# the verdict is identical at proof (96 dpi) and final (300 dpi) -- one spec, one
# coverage verdict (invariant 1). Measuring on the DPI-scaled render window let a crop
# marginally overhanging the DEM pass the proof yet be rejected at the final.
OFFDEM_PROBE_PX = 384

# ---- track cartography (V1-10 hybrid, approved by Dom): a pronounced desert-gold
# route on a light paper halo. The halo is the mapping-app legibility move: it always
# contrasts one way (light against terrain) while the gold contrasts the other, so
# the route separates from ANY ground -- dark ridge or pale basin -- and reads from
# across a room. All reach/softness values are in POINTS (invariant 2): the old
# pixel-valued blur made the proof's halo softer than the final's.
TRACK_INK = (214, 158, 58)      # desert gold -- warm, saturated, reads against earthy terrain
TRACK_CASING = (246, 240, 226)  # paper halo under the gold line
CASING_STRENGTH = 0.7           # halo opacity
CASING_PAD_PT = 1.0             # halo reach beyond the line, in points
CASING_BLUR_PT = 1.0            # halo softness, in points (was 1.4 px -- DPI-dependent)
INK_FREQ_K = 2.5                # first pass inks near-solid; the cap does the limiting
INK_EDGE_FEATHER_PT = 0.45      # soften the hard PIL edge, in points (was 0.6 px)
INK_GRAIN = 0.16                # paper texture carried onto the line
# "Lived in": a segment traveled on several distinct days physically WIDENS toward
# WORN_WIDTH_FACTOR x the base width (a desire path), instead of only darkening.
# Coverage counts one pass per track layer, so a same-day out-and-back stays base width.
WORN_WIDTH_FACTOR = 1.6
WORN_FREQ_K = 0.9               # how fast repeat days saturate the worn band
# Journey terminus marks: a small dark pin with a paper ring at each track's start/end
# -- a route with a beginning and an end reads as a story, not decoration.
TERMINUS_INK = (54, 40, 30)     # the old dark umber, kept for the pins
TERMINUS_RING = (246, 240, 226)
# ----------------------------------------------------------------------------------

# ---- water cartography: lakes filled flat, rivers as order-weighted lines ----
WATER_FILL = (104, 128, 134)    # muted slate-blue, sits with the earthy palette
WATER_SHORELINE = (74, 96, 102) # a touch darker for the lake edge
SHORELINE_PT = 0.5              # shoreline width in POINTS (DPI-scaled, never raw px)
RIVER_COLOR = (92, 118, 126)
RIVER_BASE_PT = 0.7             # width of an order-3 river, in points
RIVER_STEP_PT = 0.5             # extra width per stream order above 3
RIVER_MAX_PT = 3.0

# ---- named geography (GNIS labels, v1.4): terrain names from labels.json (ranges,
# summits, passes, valleys) + water names already in hydro.json, placed with priority
# + greedy collision avoidance. Physical sizes so proof == final; a knockout paper halo
# keeps them legible over busy relief. Ranges/deserts read as wide tracked caps (the
# cartographic convention for an area name); everything else is a titlecase point label.
GEO_LABEL_INK = (46, 38, 30)          # warm dark umber, the map-ink family
GEO_LABEL_HALO = (244, 238, 225)      # paper, drawn as a knockout halo behind the ink
GEO_HALO_PT = 1.1                     # halo stroke, points
GEO_TRACKING_EM = 0.18                # tracked-caps letterspacing for area names
# per-kind (point size in pt, ALL-CAPS tracked?, keep-rank). Rank orders both the
# collision pass and, with the density cap, which names survive on a busy sheet.
GEO_KINDS = {
    "range":   (12.5, True,  100),    # the headline: a range name in wide tracked caps
    "summit":  (7.6,  False, 85),     # peaks are the iconic terrain -> above the meadows
    "lake":    (7.0,  False, 66),
    "gap":     (7.0,  False, 60),     # passes / saddles
    "flat":    (10.0, True,  52),     # playa / desert (reads big on the NV/UT sheets)
    "basin":   (9.0,  True,  50),
    "valley":  (6.8,  False, 44),     # incl. Colorado's many "... Park" meadows
    "river":   (6.8,  False, 40),
}
GEO_LABELS_PER_100IN2 = 6.0           # density cap: ~ this many labels per 100 sq inch
GEO_EDGE_IN = 0.32                    # keep labels this far inside the sheet edge
# Curved along-feature labels: a linear landform (range, valley) sets its name along its
# own spine -- the NatGeo/USGS convention -- instead of a horizontal block at the
# centroid. Point/area kinds stay straight. A path shorter than the text falls back to a
# straight centered label, so a hairpinned or barely-in-frame feature never crams.
GEO_CURVE_KINDS = {"range", "valley"}
GEO_PATH_SMOOTH_M = 1200.0            # spine-smoothing window in GROUND metres (dpi-stable)
GEO_MIN_PATH_IN = 1.1                 # min in-frame spine length (inches) to bother curving
# ------------------------------------------------------------------------------

def _pt_to_px(pt, dpi):  # points -> pixels
    return pt * dpi / 72.0

# Terrain-depth ramp (v1.3, Dom): keyed to the DPI-INDEPENDENT map-scale denominator
# (ground metres per print metre), NOT gpp -- gpp varies with dpi, the scale does not,
# so proof and final share one depth value. 0 below ~1:150k (county scale, where the
# single-light look is already right and every relief test renders), full by ~1:430k
# (corridor scale). The Lassen proof/final MAD test sits at ~1:118k -> a strict no-op.
DEPTH_SCALE_LO = 150_000.0
DEPTH_SCALE_HI = 430_000.0

def _smoothstep(lo, hi, x):
    t = min(1.0, max(0.0, (x - lo) / (hi - lo)))
    return t * t * (3.0 - 2.0 * t)

def _terrain_depth(spec):
    """0..1 terrain-depth strength for this spec's map scale, times the client's
    terrain_depth multiplier. A pure function of the spec, so proof == final."""
    scale_denom = (spec.crop[2] - spec.crop[0]) / (spec.print_w_in * 0.0254)
    return _smoothstep(DEPTH_SCALE_LO, DEPTH_SCALE_HI, scale_denom) * spec.terrain_depth

# Cast-shadow working grid: shadows/AO are ray-marched on a grid whose GROUND
# resolution is a pure function of the spec (96 samples per print inch -- exactly the
# proof's own pixel grid), never the render DPI. The proof and the final therefore
# march the same terrain and their shadow masks agree by construction (invariant 1);
# the 300-dpi final also gets a ~3x smaller (cheaper) shadow computation for free.
SHADOW_GRID_SPI = 96.0

def _shadow_res_m(spec):
    """Ground metres per shadow-grid sample. A pure function of the spec."""
    return (spec.crop[2] - spec.crop[0]) / (spec.print_w_in * SHADOW_GRID_SPI)

def _read_window(region_dir, cfg, crop, out_w, out_h):
    """Read the DEM for the crop (plus a margin) at the output resolution.
    rasterio picks the right overview level for us (the image pyramid)."""
    # Pad by an INTEGER number of output pixels and derive the big bounds from that
    # pad, so the trimmed central window maps to the crop exactly at every DPI
    # (a continuous margin + round() leaves a sub-pixel terrain/track offset).
    pad_x = round(out_w * MARGIN_FRAC); pad_y = round(out_h * MARGIN_FRAC)
    gx = (crop[2] - crop[0]) / out_w; gy = (crop[3] - crop[1]) / out_h
    big = (crop[0]-pad_x*gx, crop[1]-pad_y*gy, crop[2]+pad_x*gx, crop[3]+pad_y*gy)
    with rasterio.open(os.path.join(region_dir, cfg["dem_path"])) as ds:
        win = from_bounds(*big, transform=ds.transform)
        elev = ds.read(1, window=win,
                       out_shape=(out_h + 2*pad_y, out_w + 2*pad_x),
                       resampling=Resampling.bilinear, boundless=True, fill_value=np.nan)
    ground_per_px = (crop[2]-crop[0]) / out_w
    return elev, pad_x, pad_y, ground_per_px

BIOME_EDGE_BLUR_PX96 = 1.6      # soften 30 m NLCD class edges (scaled by dpi)

def _biome_layers(region_dir, cfg, crop, pads, shape, dpi):
    """(tint01, weight01) aligned to the padded render window, from the region's
    baked NLCD landcover -- or None when the asset is absent (graceful fallback to
    the pure elevation tint). Same windowed-read discipline as the DEM, so the tint
    registers with the terrain by construction."""
    p = os.path.join(region_dir, cfg.get("landcover_path", "landcover.tif"))
    if not os.path.exists(p):
        return None
    from app.relief import BIOME_TINT
    pad_x, pad_y = pads
    out_h = shape[0] - 2 * pad_y
    out_w = shape[1] - 2 * pad_x
    gx = (crop[2] - crop[0]) / out_w
    gy = (crop[3] - crop[1]) / out_h
    big = (crop[0] - pad_x * gx, crop[1] - pad_y * gy,
           crop[2] + pad_x * gx, crop[3] + pad_y * gy)
    with rasterio.open(p) as ds:
        win = from_bounds(*big, transform=ds.transform)
        lc = ds.read(1, window=win, out_shape=shape,
                     resampling=Resampling.nearest, boundless=True, fill_value=0)
    tint = np.zeros(shape + (3,), np.float32)
    weight = np.zeros(shape, np.float32)
    for cls, rgb in BIOME_TINT.items():
        m = lc == cls
        tint[m] = rgb
        weight[m] = 1.0
    # soften class edges without bleeding tint into untinted ground:
    # blur(tint*weight)/blur(weight) is a weighted (normalized) blur
    sigma = BIOME_EDGE_BLUR_PX96 * dpi / 96.0
    wb = gaussian_filter(weight, sigma)
    safe = wb + 1e-6
    for ch in range(3):
        tint[..., ch] = gaussian_filter(tint[..., ch] * weight, sigma) / safe
    return tint / 255.0, np.clip(wb, 0, 1)

def _offdem_fraction(region_dir, cfg, crop):
    """Fraction of the crop (margin excluded) with no DEM coverage, sampled on a fixed
    probe grid so the value does not depend on the render DPI. Nearest resampling: we
    only care whether each probe cell hits data, not its interpolated value."""
    cw, ch = crop[2] - crop[0], crop[3] - crop[1]
    if cw <= 0 or ch <= 0:
        return 1.0
    if cw >= ch:
        pw, ph = OFFDEM_PROBE_PX, max(1, round(OFFDEM_PROBE_PX * ch / cw))
    else:
        ph, pw = OFFDEM_PROBE_PX, max(1, round(OFFDEM_PROBE_PX * cw / ch))
    with rasterio.open(os.path.join(region_dir, cfg["dem_path"])) as ds:
        win = from_bounds(*crop, transform=ds.transform)
        probe = ds.read(1, window=win, out_shape=(ph, pw),
                        resampling=Resampling.nearest, boundless=True, fill_value=np.nan)
    return float(np.isnan(probe).mean())

def _crs_to_px(x, y, crop, out_w, out_h):
    px = (x - crop[0]) / (crop[2]-crop[0]) * out_w
    py = (crop[3] - y) / (crop[3]-crop[1]) * out_h
    return px, py

def _journey_groups(spec):
    """Group spec.tracks indices into journeys. Segments sharing a (non-None) day are
    ONE journey -- a device splits a single outing into several trksegs at auto-pause,
    and those must not read as separate visits. A day-less segment stays its own
    journey. Specs without track_days (older sessions, direct callers) degrade to
    one-journey-per-track, the pre-grouping behavior."""
    days = list(spec.track_days or [])
    days += [None] * (len(spec.tracks) - len(days))          # tolerate short lists
    groups, by_day = [], {}
    for i, day in enumerate(days[:len(spec.tracks)]):
        if day is None:
            groups.append([i])
        elif day in by_day:
            by_day[day].append(i)
        else:
            by_day[day] = [i]
            groups.append(by_day[day])
    return groups

def _coverage(spec, out_w, out_h, width_px, groups=None):
    """Anti-aliased per-pixel visit count: how many distinct JOURNEYS cover each
    pixel. All segments of one journey draw onto one layer (self-overlap counts
    once); summing layers makes overlap across journeys = frequency."""
    if groups is None:
        groups = [[i] for i in range(len(spec.tracks))]
    cov = np.zeros((out_h, out_w), np.float32)
    for g in groups:
        layer = Image.new("L", (out_w, out_h), 0)
        d = ImageDraw.Draw(layer)
        drew = False
        for i in g:
            pts = [_crs_to_px(x, y, spec.crop, out_w, out_h) for x, y in spec.tracks[i]]
            if len(pts) >= 2:
                d.line(pts, fill=255, width=max(1, width_px), joint="curve")
                drew = True
        if drew:
            cov += np.asarray(layer, np.float32) / 255.0
    return cov

def _ink_tracks(rgb_u8, spec, out_w, out_h, dpi):
    """Composite tracks as inked, cased lines that pick up the terrain texture and
    paper grain instead of floating on top. Visitation is expressed as WIDTH: any
    pass draws the base line near-solid; segments covered by 2+ distinct passes
    swell toward the worn width, like a desire path (V1-10)."""
    img = rgb_u8.astype(np.float32) / 255.0
    ink_w = max(1, round(_pt_to_px(spec.track_width_pt, dpi)))
    worn_w = max(ink_w + 2, round(ink_w * WORN_WIDTH_FACTOR))
    pad = max(1, round(_pt_to_px(CASING_PAD_PT, dpi)))
    feather = max(0.3, _pt_to_px(INK_EDGE_FEATHER_PT, dpi))
    groups = _journey_groups(spec)
    # a single journey can never be "worn" -- skip both worn rasterizations (a
    # flagship final saves ~4 s and ~300 MB; output is identical since one journey's
    # coverage never exceeds 1, so the worn terms are exactly zero).
    worn_possible = len(groups) >= 2

    # per-journey coverage at both widths (overlap across journeys = frequency)
    visits_base = gaussian_filter(_coverage(spec, out_w, out_h, ink_w, groups), feather)

    # 1) paper halo under the line (strength = the client's outline slider; 0 skips
    #    the halo work entirely), following the worn width where paths repeat.
    #    clip(cov)-1 at the halo width = presence of a 2nd+ journey -> the worn gate.
    if spec.track_halo > 0:
        cas = np.clip(_coverage(spec, out_w, out_h, ink_w + 2 * pad, groups), 0, 1)
        if worn_possible:
            cas_worn = _coverage(spec, out_w, out_h, worn_w + 2 * pad, groups)
            cas = np.maximum(cas, np.clip(cas_worn - 1, 0, 1))
            del cas_worn
        cas = gaussian_filter(cas, max(0.3, _pt_to_px(CASING_BLUR_PT, dpi)))
        casing_op = (spec.track_halo * np.clip(cas, 0, 1))[..., None]
        del cas
        casing_col = np.array(TRACK_CASING, np.float32) / 255.0
        img = img * (1 - casing_op) + casing_col[None, None, :] * casing_op
        del casing_op

    # 2) the line: base width at near-solid ink; repeat journeys widen it (saturating)
    op = 1.0 - np.exp(-INK_FREQ_K * visits_base)
    del visits_base
    if worn_possible:
        visits_worn = gaussian_filter(_coverage(spec, out_w, out_h, worn_w, groups), feather)
        op_worn = 1.0 - np.exp(-WORN_FREQ_K * np.clip(visits_worn - 1.0, 0.0, None))
        op = np.maximum(op, op_worn)
        del visits_worn, op_worn
    op = np.clip(op, 0.0, spec.track_max_darken)
    gf = np.clip(grain((out_h, out_w), max(1.0, spec.grain_cell_in * dpi), INK_GRAIN, spec.seed), 0, 1)
    op = (op * gf)[..., None]
    ink = np.array(spec.track_rgb, np.float32) / 255.0   # client's swatch; TRACK_INK default
    # alpha-blend toward the gold so the hue reads true and pronounced (a multiply
    # toward gold would only darken the terrain to a muddy brown); grain in `op`
    # keeps the paper texture so it still sits on the sheet rather than floating.
    img = img * (1 - op) + ink[None, None, :] * op

    return (np.clip(img, 0, 1) * 255).astype(np.uint8)

def _draw_termini(img, spec, out_w, out_h, dpi):
    """A small dark pin with a paper ring at each JOURNEY's first and last point --
    the start and end anchor the story (V1-10). Pause-split segments of one day form
    one journey (see _journey_groups), so mid-route stop/resume points get no pin.
    Sized off the track width (physical units) so proof and final agree."""
    d = ImageDraw.Draw(img, "RGBA")
    # pin size rides the marker scale (physical), not the line width: at the old
    # track-width-derived ~1.7 mm the "story anchors" were invisible at poster
    # viewing distance (red-team). 0.42 x a 0.24 in marker ~ a 2.6 mm pin.
    r = max(2.0, spec.marker_diameter_in * dpi * 0.21)
    ring_w = max(1, round(r * 0.45))
    for g in _journey_groups(spec):
        segs = [spec.tracks[i] for i in g if len(spec.tracks[i]) >= 2]
        if not segs:
            continue
        for x, y in (segs[0][0], segs[-1][-1]):     # journey start, journey end
            px, py = _crs_to_px(x, y, spec.crop, out_w, out_h)
            if 0 <= px <= out_w and 0 <= py <= out_h:
                d.ellipse([px - r, py - r, px + r, py + r],
                          fill=TERMINUS_INK + (255,),
                          outline=TERMINUS_RING + (235,), width=ring_w)
    return img

# ---- rich markers (v1.1): labels, vector icons, pinned photos ----
MARKER_FILL = (190, 158, 92)        # muted rabbitbrush gold disc
ICON_INK = (38, 33, 26)             # dark vector glyph drawn inside the disc
LABEL_INK = (38, 33, 26)
LABEL_PLATE = (243, 237, 223)       # cream plate behind label text for legibility
PHOTO_FRAME = (243, 237, 223)       # cream mat around a pinned photo
PHOTO_EDGE = (54, 40, 30)           # thin dark keyline + connector stem
# -------------------------------------------------------------------

def _font(size):
    # TRAILPRINT_FONT lets the operator drop in a licensed display face (a real
    # poster face beats the DejaVu screen workhorse); then the serif chain.
    names = ([os.environ["TRAILPRINT_FONT"]] if os.environ.get("TRAILPRINT_FONT") else [])
    names += ["Georgia.ttf", "DejaVuSerif.ttf", "DejaVuSans.ttf"]
    for name in names:
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            continue
    # load_default() with no size ignores the request (~10 px bitmap font), which
    # would shrink labels -- and the sheet-scaled PROOF watermark -- to invisible
    # on a host without the TTFs above. Pillow >= 10.1 scales the default font.
    try:
        return ImageFont.load_default(size)
    except TypeError:
        return ImageFont.load_default()

def _draw_glyph(d, name, cx, cy, r, color):
    """Draw a small cartographic icon centred at (cx,cy), scaled to radius r. Vector
    primitives only (no font/emoji dependency) so the same spec renders identically
    on any machine (invariant 3)."""
    a = color + (255,)
    if name == "peak":                         # mountain triangle
        d.polygon([(cx, cy-r), (cx+r, cy+r*0.7), (cx-r, cy+r*0.7)], fill=a)
    elif name == "camp":                       # tent
        d.polygon([(cx, cy-r), (cx+r, cy+r*0.7), (cx-r, cy+r*0.7)], fill=a)
        d.line([(cx, cy-r), (cx, cy+r*0.7)], fill=PHOTO_FRAME + (255,), width=max(1, round(r*0.18)))
    elif name == "water":                      # droplet
        d.ellipse([cx-r*0.8, cy-r*0.2, cx+r*0.8, cy+r*0.9], fill=a)
        d.polygon([(cx, cy-r), (cx+r*0.62, cy+r*0.2), (cx-r*0.62, cy+r*0.2)], fill=a)
    elif name == "flag":                       # pennant on a pole
        d.line([(cx-r*0.5, cy-r), (cx-r*0.5, cy+r)], fill=a, width=max(1, round(r*0.22)))
        d.polygon([(cx-r*0.5, cy-r), (cx+r*0.8, cy-r*0.55), (cx-r*0.5, cy-r*0.1)], fill=a)
    elif name == "camera":                     # body + lens
        d.rounded_rectangle([cx-r*0.85, cy-r*0.5, cx+r*0.85, cy+r*0.6],
                            radius=max(1, round(r*0.2)), fill=a)
        d.ellipse([cx-r*0.35, cy-r*0.2, cx+r*0.35, cy+r*0.5], fill=PHOTO_FRAME + (255,))
    elif name == "star":                       # 5-point star
        import math
        pts = []
        for k in range(10):
            rad = r if k % 2 == 0 else r * 0.42
            th = -math.pi/2 + k * math.pi/5
            pts.append((cx + rad*math.cos(th), cy + rad*math.sin(th)))
        d.polygon(pts, fill=a)
    # "dot"/unknown -> bare disc (already drawn by the caller)

def _draw_markers(img, spec, elev_lum, out_w, out_h, dpi):
    dia = max(5, round(spec.marker_diameter_in * dpi))
    r = dia / 2.0
    drop = max(1, round(dia * 0.07))

    def in_frame(cx, cy):
        return 0 <= cx <= out_w and 0 <= cy <= out_h

    # soft drop shadow on its own layer -> markers sit on the paper, not over it
    shadow = Image.new("RGBA", (out_w, out_h), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    for hs in spec.hotspots:
        cx, cy = _crs_to_px(hs["x"], hs["y"], spec.crop, out_w, out_h)
        if in_frame(cx, cy):
            sd.ellipse([cx-r, cy-r+drop, cx+r, cy+r+drop], fill=(22, 19, 16, 105))
    shadow = shadow.filter(ImageFilter.GaussianBlur(max(1.0, dia * 0.11)))
    img = Image.alpha_composite(img.convert("RGBA"), shadow)

    d = ImageDraw.Draw(img, "RGBA")
    label_font = _font(max(8, round(_pt_to_px(spec.label_pt, dpi))))
    for hs in spec.hotspots:
        cx, cy = _crs_to_px(hs["x"], hs["y"], spec.crop, out_w, out_h)
        if not in_frame(cx, cy):
            continue
        # contrast ring: light on dark terrain, dark on light
        yy = int(np.clip(cy, 0, out_h-1)); xx = int(np.clip(cx, 0, out_w-1))
        on_dark = elev_lum[yy, xx] < 0.5
        ring = (243, 237, 223, 235) if on_dark else (43, 42, 40, 230)
        # ring width = the client's marker-outline slider (fraction of diameter; 0 = none)
        ring_w = round(dia * spec.marker_ring)
        d.ellipse([cx-r, cy-r, cx+r, cy+r], fill=MARKER_FILL + (255,),
                  outline=ring if ring_w > 0 else None,
                  width=max(1, ring_w))
        icon = (hs.get("icon") or "").strip()
        if icon:
            _draw_glyph(d, icon, cx, cy, r * 0.62, ICON_INK)
        label = (hs.get("label") or "").strip()
        if label:
            _draw_label(d, label, cx + r + dia*0.25, cy, label_font, out_w, out_h)
    return img

def _draw_label(d, text, x, cy, font, out_w, out_h):
    """A label on a soft cream plate, left-anchored at x and vertically centred on cy."""
    l, t, rt, b = d.textbbox((0, 0), text, font=font)
    tw, th = rt - l, b - t
    pad = max(2, round(th * 0.3))
    x = min(x, out_w - tw - 2*pad - 1)         # keep the plate inside the frame
    y = float(np.clip(cy - th/2 - pad, 0, out_h - th - 2*pad - 1))
    d.rounded_rectangle([x, y, x + tw + 2*pad, y + th + 2*pad],
                        radius=pad, fill=LABEL_PLATE + (220,))
    d.text((x + pad - l, y + pad - t), text, fill=LABEL_INK + (255,), font=font)

def _photo_frame_params(style, box, dpi):
    """(mat_side, mat_top, mat_bottom, edge_w) per photo frame style. All derived
    from the photo box (physical), so proof == final for every style."""
    m = max(2, round(box * 0.05))
    if style == "keyline":
        k = max(1, round(box * 0.012))
        return k, k, k, max(1, round(_pt_to_px(0.8, dpi)))
    if style == "borderless":
        return 0, 0, 0, 0
    if style == "polaroid":
        return m, m, max(4, round(box * 0.16)), max(1, m // 3)
    return m, m, m, max(1, m // 2)                     # "mat" (the classic default)

def _draw_photos(img, spec, out_w, out_h, dpi):
    """Pin user photos to their markers in the client's chosen frame style (classic
    mat / thin keyline / borderless / polaroid), each with a drop shadow and a short
    stem back to the anchor point. Tolerant of a missing/unreadable file (skip it)
    so one bad photo can't fail the render."""
    if not any(hs.get("photo") for hs in spec.hotspots):
        return img
    box = max(24, round(spec.photo_box_in * dpi))
    ms, mt, mb, edge_w = _photo_frame_params(spec.photo_frame_style, box, dpi)
    stem = max(1, round(box * 0.02))
    shadow_r = max(1.0, box * 0.04)
    d = ImageDraw.Draw(img, "RGBA")
    for hs in spec.hotspots:
        path = hs.get("photo")
        if not path:
            continue
        try:
            photo = Image.open(path).convert("RGB")
        except Exception:
            continue
        photo.thumbnail((box, box))
        pw, ph = photo.size
        fw, fh = pw + 2 * ms, ph + mt + mb             # frame outer size
        ax, ay = _crs_to_px(hs["x"], hs["y"], spec.crop, out_w, out_h)
        # place the framed photo up-and-right of the anchor, clamped to the frame
        fx = int(np.clip(ax + box * 0.35, 0, out_w - fw - 1))
        fy = int(np.clip(ay - fh - box * 0.35, 0, out_h - fh - 1))
        # stem from anchor to the frame's near corner
        d.line([(ax, ay), (fx + max(ms, 1), fy + fh - max(mb, 1))],
               fill=PHOTO_EDGE + (255,), width=stem)
        shadow = Image.new("RGBA", (out_w, out_h), (0, 0, 0, 0))
        ImageDraw.Draw(shadow).rectangle([fx, fy, fx + fw, fy + fh], fill=(20, 16, 12, 110))
        img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(shadow_r)))
        d = ImageDraw.Draw(img, "RGBA")
        if ms or mt or mb:
            d.rectangle([fx, fy, fx + fw, fy + fh], fill=PHOTO_FRAME + (255,))
        img.paste(photo, (fx + ms, fy + mt))
        if edge_w:
            d.rectangle([fx, fy, fx + fw, fy + fh],
                        outline=PHOTO_EDGE + (255,), width=edge_w)
    return img

# ---- finished-sheet furniture (V1-10 print-correctness): keyline + title block ----
KEYLINE_INSET_IN = 0.25         # thin frame inset from the sheet edge
KEYLINE_PT = 0.6
TITLE_INSET_IN = 0.35           # title block inset from the sheet corner
FURNITURE_BASE_IN2 = 18.0 * 24.0   # the sheet all furniture sizes were designed on
FURNITURE_SCALE_MIN = 0.75         # small sheets: shrink a little, stay legible
FURNITURE_SCALE_MAX = 2.0          # oversize sheets: grow, never into novelty
# ------------------------------------------------------------------------------------

def _furniture_scale(spec):
    """Furniture grows with the sheet (Dom): a 24x36 hangs farther from the eye than
    an 18x24, so the compass, cartouche and scale bar scale with the sheet's linear
    size (sqrt of area) relative to the 18x24 they were designed on -- then the
    client's furniture_scale slider multiplies the auto-appropriate size. A pure
    function of the spec, so proof == final at any DPI (invariant 1)."""
    s = (spec.print_w_in * spec.print_h_in / FURNITURE_BASE_IN2) ** 0.5
    return min(max(s, FURNITURE_SCALE_MIN), FURNITURE_SCALE_MAX) * spec.furniture_scale

def _year_span(spec):
    """The min-max year across the dated tracks as 'YYYY' or 'YYYY–YYYY' (en dash),
    or '' when no track carries a date. Pure function of track_days (invariant 3)."""
    years = sorted({d[:4] for d in (spec.track_days or [])
                    if isinstance(d, str) and len(d) >= 4 and d[:4].isdigit()})
    if not years:
        return ""
    return years[0] if years[0] == years[-1] else f"{years[0]}–{years[-1]}"

def _stats_line(spec, dpi):
    """A deterministic cartographic caption from the spec alone: the edition line (from
    the second edition on), approximate scale ratio, distinct days, total mileage. No
    wall clock, no locale (invariant 3)."""
    import math
    parts = []
    # living editions: a poster carried forward wears its edition + the years it spans,
    # set at the head of the caption. Edition 1 (every pre-feature poster) adds nothing,
    # so its stats line is byte-identical to before the feature.
    edition = getattr(spec, "edition", 1) or 1
    if edition >= 2:
        parts.append(f"EDITION {edition}")
        span = _year_span(spec)
        if span:
            parts.append(span)
    ratio = (spec.crop[2] - spec.crop[0]) / (spec.print_w_in * 0.0254)
    if ratio > 0:
        mag = 10 ** max(0, int(math.floor(math.log10(ratio))) - 1)
        parts.append(f"~1:{round(ratio / mag) * mag:,.0f}")
    days = {d for d in (spec.track_days or []) if d}
    if days:
        parts.append(f"{len(days)} DAY" + ("S" if len(days) != 1 else ""))
    # dedupe segments identical in BOTH day and geometry (the same file uploaded
    # twice) so the printed mileage doesn't double-count -- while the same route
    # honestly re-traveled on different days still sums (red-team).
    tdays = list(spec.track_days or [])
    tdays += [None] * (len(spec.tracks) - len(tdays))
    seen, dist_m = set(), 0.0
    for t, day in zip(spec.tracks, tdays):
        a = np.asarray(t)
        if len(a) < 2:
            continue
        key = (day, a.tobytes())
        if key in seen:
            continue
        seen.add(key)
        dist_m += float(np.hypot(np.diff(a[:, 0]), np.diff(a[:, 1])).sum())
    if dist_m > 0:
        parts.append(f"{dist_m / 1609.344:.0f} MI")
    return " · ".join(parts)

def _draw_keyline(img, out_w, out_h, dpi):
    """A thin dark frame just inside the sheet edge -- the 'deliberate' finish that
    reads as a plate mark. Physical inset/width, so proof and final agree."""
    d = ImageDraw.Draw(img, "RGBA")
    inset = round(KEYLINE_INSET_IN * dpi)
    w = max(1, round(_pt_to_px(KEYLINE_PT, dpi)))
    d.rectangle([inset, inset, out_w - 1 - inset, out_h - 1 - inset],
                outline=TERMINUS_INK + (200,), width=w)
    return img

# Cartouche conventions after the reference sheets (USGS quads, NatGeo/Swisstopo):
# tracked caps, hairline rule, a true graphic scale bar, square-cornered keyline box.
TITLE_TRACKING_EM = 0.14        # title letterspacing, fraction of font size
STATS_TRACKING_EM = 0.08
SCALE_BAR_TARGET_IN = 1.9       # aim length of the bar on the sheet
SCALE_BAR_H_IN = 0.05
NICE_MILES = (0.5, 1, 2, 3, 4, 5, 8, 10, 15, 20, 25, 30, 40, 50, 75, 100, 150, 200)

def _tracked_width(d, text, font, tracking):
    if not text:
        return 0
    return round(sum(d.textlength(ch, font=font) for ch in text)
                 + tracking * (len(text) - 1))

def _tracked_text(d, xy, text, font, fill, tracking):
    """PIL has no letterspacing; draw per glyph with an added tracking gap --
    the wide-tracked caps every classic map cartouche sets its title in."""
    x, y = xy
    for ch in text:
        d.text((x, y), ch, fill=fill, font=font)
        x += d.textlength(ch, font=font) + tracking

def _scale_bar_miles(spec, dpi, fs=1.0):
    """(miles, px) for the graphic scale bar: the 'nice' mileage whose true length
    on the sheet is closest to the target. Derived from the spec alone (invariant 3).
    `fs` scales the TARGET length only -- the returned px length is always the true
    ground length at the real output dpi, or the bar would lie on large sheets."""
    gpp = (spec.crop[2] - spec.crop[0]) / (spec.print_w_in * dpi)   # ground m / px
    target_px = SCALE_BAR_TARGET_IN * fs * dpi
    best = min(NICE_MILES, key=lambda mi: abs(mi * 1609.344 / gpp - target_px))
    return best, best * 1609.344 / gpp

def _title_block_metrics(spec, d, dpi):
    """Measured geometry of the cartouche (None when there's no title). Shared by
    _draw_title_block and the compass placement above it, so they can't drift.
    Everything physical is sized at `fdpi` -- the furniture-effective dpi -- so the
    whole plate enlarges as one engraving on big sheets; only the scale bar's ground
    length is computed at the real dpi (it must stay true)."""
    if not spec.title_text.strip():
        return None
    fs = _furniture_scale(spec)
    fdpi = dpi * fs
    title = spec.title_text.strip().upper()
    stats = _stats_line(spec, dpi)
    t_size = max(12, round(_pt_to_px(spec.title_pt, fdpi)))
    s_size = max(8, round(_pt_to_px(spec.label_pt * 0.85, fdpi)))
    title_font = _font(t_size)
    stats_font = _font(s_size)
    bar_font = _font(max(7, round(_pt_to_px(spec.label_pt * 0.7, fdpi))))
    # track off the requested size, not font.size (the bitmap fallback has none)
    t_track = round(t_size * TITLE_TRACKING_EM)
    s_track = round(s_size * STATS_TRACKING_EM)
    _, tt, _, tb = d.textbbox((0, 0), title, font=title_font)
    th = tb - tt
    tw = _tracked_width(d, title, title_font, t_track)
    if stats:
        _, st_, _, sb = d.textbbox((0, 0), stats, font=stats_font)
        sh = sb - st_
        sw = _tracked_width(d, stats, stats_font, s_track)
    else:
        st_ = sh = sw = 0
    miles, bar_px = _scale_bar_miles(spec, dpi, fs)
    bar_h = max(3, round(SCALE_BAR_H_IN * fdpi))
    _, lt, _, lb = d.textbbox((0, 0), f"{miles:g} MI", font=bar_font)
    lbl_h = lb - lt
    gap = max(3, round(0.35 * (sh or th)))
    rule_h = gap * 2                          # rule row: hairline + air on both sides
    pad = max(6, round(0.16 * fdpi))
    content_w = max(tw, sw, round(bar_px))
    bh = pad + th + rule_h + (sh + gap if stats else 0) + bar_h + 2 + lbl_h + pad
    return {"title": title, "stats": stats, "title_font": title_font,
            "stats_font": stats_font, "bar_font": bar_font,
            "t_track": t_track, "s_track": s_track,
            "tt": tt, "th": th, "tw": tw, "st": st_, "sh": sh, "sw": sw,
            "miles": miles, "bar_px": round(bar_px), "bar_h": bar_h, "lbl_h": lbl_h,
            "gap": gap, "rule_h": rule_h, "pad": pad, "fdpi": fdpi,
            "bw": content_w + 2 * pad, "bh": bh}

def _draw_title_block(img, spec, out_w, out_h, dpi):
    """The cartouche, after the reference sheets: centered tracked-caps title over a
    hairline rule, the stats caption, and a true graphic scale bar (USGS-style
    alternating segments) -- inside a square-cornered plate with a fine keyline."""
    d = ImageDraw.Draw(img, "RGBA")
    m = _title_block_metrics(spec, d, dpi)
    if m is None:
        return img
    inset = round(TITLE_INSET_IN * m["fdpi"])
    x, y = inset, out_h - inset - m["bh"]
    bw, pad = m["bw"], m["pad"]
    cx = x + bw / 2
    d.rectangle([x, y, x + bw, y + m["bh"]], fill=LABEL_PLATE + (235,))
    kl = max(1, round(_pt_to_px(0.5, m["fdpi"])))
    d.rectangle([x + kl + 1, y + kl + 1, x + bw - kl - 1, y + m["bh"] - kl - 1],
                outline=TERMINUS_INK + (170,), width=kl)
    cy = y + pad
    _tracked_text(d, (cx - m["tw"] / 2, cy - m["tt"]), m["title"],
                  m["title_font"], LABEL_INK + (255,), m["t_track"])
    cy += m["th"]
    rw = max(m["tw"], m["sw"]) * 0.8          # the hairline rule, centred
    ry = cy + m["rule_h"] / 2
    d.line([(cx - rw / 2, ry), (cx + rw / 2, ry)],
           fill=TERMINUS_INK + (110,), width=max(1, round(_pt_to_px(0.4, m["fdpi"]))))
    cy += m["rule_h"]
    if m["stats"]:
        _tracked_text(d, (cx - m["sw"] / 2, cy - m["st"]), m["stats"],
                      m["stats_font"], LABEL_INK + (205,), m["s_track"])
        cy += m["sh"] + m["gap"]
    # graphic scale bar: four alternating segments, keyline-edged, end labels
    bx = cx - m["bar_px"] / 2
    seg = m["bar_px"] / 4
    for i in range(4):
        fill = TERMINUS_INK + (230,) if i % 2 == 0 else LABEL_PLATE + (255,)
        d.rectangle([bx + i * seg, cy, bx + (i + 1) * seg, cy + m["bar_h"]], fill=fill)
    d.rectangle([bx, cy, bx + m["bar_px"], cy + m["bar_h"]],
                outline=TERMINUS_INK + (220,), width=max(1, round(_pt_to_px(0.35, m["fdpi"]))))
    ly = cy + m["bar_h"] + 2
    d.text((bx, ly), "0", fill=LABEL_INK + (190,), font=m["bar_font"])
    lbl = f"{m['miles']:g} MI"
    lw = d.textlength(lbl, font=m["bar_font"])
    d.text((bx + m["bar_px"] - lw, ly), lbl, fill=LABEL_INK + (190,), font=m["bar_font"])
    return img

# ---- optional furniture (v1.2, Dom): elevation contours + compass rose ----
CONTOUR_INK = (54, 40, 30)      # the umber ink family
CONTOUR_MINOR_OPACITY = 0.32    # visible-by-choice: the operator turned these on
CONTOUR_INDEX_OPACITY = 0.55    # every 5th level reads a touch firmer
CONTOUR_MINOR_PT = 0.45         # physical widths -> proof == final (invariant 2)
CONTOUR_INDEX_PT = 0.8
COMPASS_DIAMETER_IN = 0.85      # rose size on the sheet
# -----------------------------------------------------------------------------

CONTOUR_MAX_LINES = 26          # local-relief cap: never pack more than this across a crop
# Scale floor (Dom): the interval must track the map's zoom, like a real topo series --
# fine when zoomed into one valley, coarse across a whole corridor -- so lines stay
# legible up close and don't mat into shading when zoomed out. `ground_m_per_in` is the
# ground metres one printed inch spans (the DPI-independent zoom); the interval is held
# to at least this fraction of it, so a 24 in sheet spanning ~3.6 km/in lands on a ~200 m
# interval while a ~0.3 km/in valley crop drops to ~20 m. Conventional intervals only.
CONTOUR_SCALE_FRAC = 0.05

def _contour_interval(range_m, ground_m_per_in):
    """The finest conventional interval that is (a) coarse enough for the map scale --
    at least CONTOUR_SCALE_FRAC of the ground-per-inch, so density tracks zoom -- and
    (b) still under the local-relief line cap. Both bounds met => readable at any zoom."""
    floor = CONTOUR_SCALE_FRAC * ground_m_per_in
    for iv in (5, 10, 20, 25, 50, 100, 200, 250, 500, 1000):
        if iv >= floor and range_m / iv <= CONTOUR_MAX_LINES:
            return iv
    return 2000

def _contour_alpha(elev, interval, width_px):
    """Anti-aliased constant-screen-width contour coverage (0..1) plus each pixel's
    nearest level index. Distance-to-level in PIXELS = |frac| / |gradient|, so the
    line width holds across slopes and DPIs; flat ground (gradient ~ 0) draws no
    line rather than flooding a whole plateau that sits exactly on a level."""
    t = elev / float(interval)
    f = np.abs(t - np.round(t))
    gy, gx = np.gradient(t)
    g = np.hypot(gx, gy)
    with np.errstate(divide="ignore", invalid="ignore"):
        d_px = np.where(g > 1e-6, f / g, np.inf)
    a = np.clip(1.0 - d_px / max(width_px, 0.5), 0.0, 1.0)
    return a, np.round(t).astype(np.int64)

def _draw_contours(rgb_u8, elev_core, dpi, ground_m_per_in):
    """Composite elevation contours over the relief (under water/tracks): minor
    lines at the scale-aware interval, index lines every 5th level slightly firmer."""
    from app.relief import _fill_nan
    elev = _fill_nan(np.array(elev_core, dtype="float32", copy=True))
    rng = float(elev.max() - elev.min())
    if rng < 1.0:                              # a dead-flat crop has no contours
        return rgb_u8
    iv = _contour_interval(rng, ground_m_per_in)
    a_minor, levels = _contour_alpha(elev, iv, _pt_to_px(CONTOUR_MINOR_PT, dpi))
    a_index, _ = _contour_alpha(elev, iv, _pt_to_px(CONTOUR_INDEX_PT, dpi))
    is_index = (levels % 5 == 0)
    alpha = np.where(is_index, a_index * CONTOUR_INDEX_OPACITY,
                     a_minor * CONTOUR_MINOR_OPACITY)[..., None].astype(np.float32)
    ink = np.array(CONTOUR_INK, np.float32) / 255.0
    img = rgb_u8.astype(np.float32) / 255.0
    img = img * (1 - alpha) + ink[None, None, :] * alpha
    return (np.clip(img, 0, 1) * 255).astype(np.uint8)

def _draw_compass(img, spec, out_w, out_h, dpi):
    """An eight-point split-shaded compass rose above the cartouche, bottom-left,
    after the classic engraved roses: short intercardinal points under the long
    cardinals, a double ring, north point long, each point half umber / half paper,
    a small N above. Vector-only + physical sizes, so the same spec renders
    identically at any DPI and on any machine."""
    if not spec.compass:
        return img
    import math as _m
    d = ImageDraw.Draw(img, "RGBA")
    fdpi = dpi * _furniture_scale(spec)   # the rose enlarges as one engraving
    R = COMPASS_DIAMETER_IN * fdpi / 2.0
    inset = round(TITLE_INSET_IN * fdpi)
    m = _title_block_metrics(spec, d, dpi)
    base_y = out_h - inset - ((m["bh"] + round(0.16 * fdpi)) if m else 0)
    cx, cy = inset + R, base_y - R
    # a soft paper ground, keyline-edged so it reads as a set medallion, not a blob
    d.ellipse([cx - R * 1.16, cy - R * 1.16, cx + R * 1.16, cy + R * 1.16],
              fill=LABEL_PLATE + (160,),
              outline=TERMINUS_INK + (110,), width=max(1, round(_pt_to_px(0.35, fdpi))))
    # double ring: the outer line and an inner hairline
    d.ellipse([cx - R, cy - R, cx + R, cy + R],
              outline=TERMINUS_INK + (210,), width=max(1, round(_pt_to_px(0.6, fdpi))))
    r2 = R * 0.78
    d.ellipse([cx - r2, cy - r2, cx + r2, cy + r2],
              outline=TERMINUS_INK + (130,), width=max(1, round(_pt_to_px(0.35, fdpi))))

    def point(angle_deg, length, half_w, dark_a=235, light_a=245):
        a = _m.radians(angle_deg - 90)                     # 0 deg = north, y down
        tip = (cx + length * _m.cos(a), cy + length * _m.sin(a))
        left = (cx + half_w * _m.cos(a - _m.pi / 2), cy + half_w * _m.sin(a - _m.pi / 2))
        right = (cx + half_w * _m.cos(a + _m.pi / 2), cy + half_w * _m.sin(a + _m.pi / 2))
        d.polygon([tip, left, (cx, cy)], fill=TERMINUS_INK + (dark_a,))
        d.polygon([tip, right, (cx, cy)], fill=TERMINUS_RING + (light_a,))

    for ang in (45, 135, 225, 315):                        # intercardinals, underneath
        point(ang, R * 0.40, R * 0.09, dark_a=200, light_a=235)
    for ang, ln in ((90, R * 0.62), (180, R * 0.62), (270, R * 0.62), (0, R * 0.95)):
        point(ang, ln, R * 0.16)                           # cardinals; north last, long
    hub = R * 0.075
    d.ellipse([cx - hub, cy - hub, cx + hub, cy + hub], fill=TERMINUS_INK + (255,))
    hub2 = R * 0.032
    d.ellipse([cx - hub2, cy - hub2, cx + hub2, cy + hub2], fill=TERMINUS_RING + (255,))
    f = _font(max(10, round(_pt_to_px(11.5, fdpi))))
    nl, nt, nr, nb = d.textbbox((0, 0), "N", font=f)
    nw, nh = nr - nl, nb - nt
    nx, ny = cx - nw / 2, cy - R - nh - round(0.05 * fdpi)
    pad = max(2, round(nh * 0.22))
    # a mini paper plate behind the N (house label style) -- the bare letter sat on
    # terrain above the rose's ground disc and vanished over dark ridges
    d.rounded_rectangle([nx - pad, ny - pad, nx + nw + pad, ny + nh + pad],
                        radius=pad, fill=LABEL_PLATE + (220,))
    d.text((nx - nl, ny - nt), "N", fill=TERMINUS_INK + (240,), font=f)
    return img

def _load_hydro(region_dir):
    p = os.path.join(region_dir, "hydro.json")
    return json.load(open(p)) if os.path.exists(p) else None

def _load_labels(region_dir):
    p = os.path.join(region_dir, "labels.json")
    return json.load(open(p)) if os.path.exists(p) else None

def _label_candidates(labels, hydro, spec, out_w, out_h):
    """Build the ranked label candidates in output pixels, from the terrain names
    (labels.json) and the water names already in hydro.json. Each candidate is
    (rank, kind, text, anchor_px). A feature is a candidate only if it actually falls
    in the crop; a multi-point feature (range/valley/river) anchors at the centroid of
    the part inside the frame, so a range crossing the sheet is named where it lies."""
    def to_px(x, y):
        return _crs_to_px(x, y, spec.crop, out_w, out_h)
    def inside(px, py):
        return 0 <= px <= out_w and 0 <= py <= out_h
    cands = []
    for feat in ((labels or {}).get("features", []) if labels else []):
        kind = feat.get("kind")
        spec_kind = GEO_KINDS.get(kind)
        name = (feat.get("name") or "").strip()
        if not spec_kind or not name:
            continue
        pxs = [to_px(x, y) for x, y in (feat.get("coords") or [])]
        inpts = [(px, py) for px, py in pxs if inside(px, py)]
        if not inpts:
            continue
        ax = sum(px for px, _ in inpts) / len(inpts)
        ay = sum(py for _, py in inpts) / len(inpts)
        # linear landforms carry their ordered in-crop spine so the name can arc along
        # it (curved labels); points/areas carry no path and label at the centroid.
        path = inpts if (kind in GEO_CURVE_KINDS and len(inpts) >= 2) else None
        cands.append((spec_kind[2], kind, name, (ax, ay), path))
    # water names ride in hydro.json (lakes: polygon centroid; rivers: one label per
    # distinct name at the midpoint of its longest in-frame run).
    if hydro:
        for lake in hydro.get("lakes", []):
            name = (lake.get("name") or "").strip()
            pts = [to_px(x, y) for x, y, *_ in (lake.get("coords") or [])]
            inpts = [p for p in pts if inside(*p)]
            if name and len(inpts) >= 1:
                ax = sum(p[0] for p in inpts) / len(inpts)
                ay = sum(p[1] for p in inpts) / len(inpts)
                cands.append((GEO_KINDS["lake"][2], "lake", name, (ax, ay), None))
        rivers = {}
        for r in hydro.get("rivers", []):
            name = (r.get("name") or "").strip()
            if not name or name == " ":
                continue
            pts = [to_px(x, y) for x, y, *_ in (r.get("coords") or [])]
            inpts = [p for p in pts if inside(*p)]
            if len(inpts) > rivers.get(name, (0, None))[0]:
                mid = inpts[len(inpts) // 2]
                rivers[name] = (len(inpts), mid)
        for name, (_, mid) in rivers.items():
            if mid is not None:
                cands.append((GEO_KINDS["river"][2], "river", name, mid, None))
    cands.sort(key=lambda c: -c[0])
    return cands

def _resample_path(poly, step_px, smooth_px):
    """Densify `poly` to ~step_px spacing, then moving-average smooth it over a
    ~smooth_px window so a name laid along it follows the spine instead of jittering on
    a jagged ridge. Pure geometry; step/smooth arrive in px converted from GROUND metres
    by the caller, so the smoothed spine is identical at any DPI (proof == final)."""
    if len(poly) < 2:
        return [tuple(p) for p in poly]
    dense = []
    for (x0, y0), (x1, y1) in zip(poly, poly[1:]):
        seg = _m.hypot(x1 - x0, y1 - y0)
        n = max(1, int(seg / max(1.0, step_px)))
        for k in range(n):
            t = k / n
            dense.append((x0 + (x1 - x0) * t, y0 + (y1 - y0) * t))
    dense.append(tuple(poly[-1]))
    w = int(round(smooth_px / max(1.0, step_px)))
    if w <= 1 or len(dense) <= 2:
        return dense
    xs = [p[0] for p in dense]; ys = [p[1] for p in dense]
    n = len(dense)
    return [((sum(xs[max(0, i-w):min(n, i+w+1)]) / (min(n, i+w+1) - max(0, i-w))),
             (sum(ys[max(0, i-w):min(n, i+w+1)]) / (min(n, i+w+1) - max(0, i-w))))
            for i in range(n)]

def _arclen(poly):
    cum = [0.0]
    for (x0, y0), (x1, y1) in zip(poly, poly[1:]):
        cum.append(cum[-1] + _m.hypot(x1 - x0, y1 - y0))
    return cum

def _point_at(poly, cum, s):
    """(x, y, angle_rad) at arc-length s along poly (clamped to the ends); angle is the
    local tangent in image coords (y down)."""
    s = min(max(s, 0.0), cum[-1])
    i = 0
    while i < len(poly) - 2 and cum[i + 1] < s:
        i += 1
    seg = cum[i + 1] - cum[i]
    t = 0.0 if seg <= 0 else (s - cum[i]) / seg
    (x0, y0), (x1, y1) = poly[i], poly[i + 1]
    return x0 + (x1 - x0) * t, y0 + (y1 - y0) * t, _m.atan2(y1 - y0, x1 - x0)

def _curved_plan(d, poly, text, font, tracking, halo, min_len):
    """Lay `text` along `poly` (px), centered on the spine midpoint. Returns
    (glyphs, bbox) where glyphs is [(ch, cx, cy, angle_rad)] anchored at each glyph
    CENTRE, or None when the spine is shorter than the text or than min_len -- the caller
    then falls back to a straight centered label, so nothing ever crams or hairpins."""
    cum = _arclen(poly); L = cum[-1]
    if L < min_len:
        return None
    advances = [d.textlength(ch, font=font) + tracking for ch in text]
    T = sum(advances) - tracking                       # drop the trailing track
    if T > L:
        return None
    # reading direction: if the spine mostly points left, reverse it so text is upright
    _, _, a0 = _point_at(poly, cum, L * 0.25)
    _, _, a1 = _point_at(poly, cum, L * 0.75)
    if _m.cos(a0) + _m.cos(a1) < 0:
        poly = poly[::-1]; cum = _arclen(poly)
    ascent, descent = font.getmetrics(); th = ascent + descent
    s = (L - T) / 2.0
    glyphs = []; minx = miny = 1e18; maxx = maxy = -1e18
    for ch, adv in zip(text, advances):
        gw = adv - tracking
        cx, cy, ang = _point_at(poly, cum, s + gw / 2.0)
        glyphs.append((ch, cx, cy, ang))
        r = th / 2 + gw / 2 + halo                     # conservative per-glyph footprint
        minx = min(minx, cx - r); maxx = max(maxx, cx + r)
        miny = min(miny, cy - r); maxy = max(maxy, cy + r)
        s += adv
    return glyphs, (round(minx), round(miny), round(maxx), round(maxy))

def _draw_glyph_rotated(img, ch, center, angle_rad, font, halo):
    """One glyph, centred at `center` and rotated to the path tangent, with the same
    knockout paper halo the straight labels use. angle_rad is measured y-down, so the
    tile rotates by -angle to align its +x axis with the tangent."""
    l, t, r, b = font.getbbox(ch)
    gw, gh = r - l, b - t
    if gw <= 0 or gh <= 0:
        return
    pad = halo + 2
    tile = Image.new("RGBA", (gw + 2 * pad, gh + 2 * pad), (0, 0, 0, 0))
    td = ImageDraw.Draw(tile)
    ox, oy = pad - l, pad - t
    for dx in (-halo, 0, halo):
        for dy in (-halo, 0, halo):
            if dx or dy:
                td.text((ox + dx, oy + dy), ch, font=font, fill=GEO_LABEL_HALO + (235,))
    td.text((ox, oy), ch, font=font, fill=GEO_LABEL_INK + (255,))
    rot = tile.rotate(-_m.degrees(angle_rad), expand=True, resample=Image.BILINEAR)
    img.alpha_composite(rot, (round(center[0] - rot.width / 2),
                              round(center[1] - rot.height / 2)))

def _draw_labels(img, labels, hydro, spec, out_w, out_h, dpi):
    """Place named geography with priority + greedy collision avoidance: strongest
    names first (range > summit > lake > pass > valley > river), each kept only if its
    haloed text box clears every already-placed box and the bottom-left cartouche/
    compass keep-out. A density cap keeps a name-dense region from over-inking."""
    cands = _label_candidates(labels, hydro, spec, out_w, out_h)
    if not cands:
        return img
    d = ImageDraw.Draw(img, "RGBA")
    edge = round(GEO_EDGE_IN * dpi)
    halo = max(1, round(_pt_to_px(GEO_HALO_PT, dpi)))
    cap = max(6, round(spec.print_w_in * spec.print_h_in / 100.0 * GEO_LABELS_PER_100IN2))
    # keep-out for the furniture stack (cartouche + compass, bottom-left corner)
    fs = _furniture_scale(spec)
    # only reserve the bottom-left corner when the furniture stack actually draws
    # there (cartouche needs a title; compass has its own toggle) -- a wallpaper (or a
    # title-less print) must not blot labels out of a third of the sheet for nothing.
    keepout = ([(0, out_h - round(2.5 * fs * dpi), round(3.4 * fs * dpi), out_h)]
               if (spec.title_text or spec.compass) else [])
    if spec.top_clear_frac > 0:
        # phone/tablet wallpapers: the OS draws the lock-screen clock across the top,
        # so auto-placed geography stays out of that band (user-placed markers don't).
        keepout.append((0, 0, out_w, round(spec.top_clear_frac * out_h)))
    placed, occupied = [], list(keepout)

    def overlaps(box):
        ax0, ay0, ax1, ay1 = box
        for bx0, by0, bx1, by1 in occupied:
            if ax0 < bx1 and bx0 < ax1 and ay0 < by1 and by0 < ay1:
                return True
        return False

    # ground metres per output px -> spine smoothing sized in GROUND units, so the
    # curved geometry (and thus every glyph angle) is identical at proof and final dpi.
    gpp = (spec.crop[2] - spec.crop[0]) / out_w
    smooth_px = GEO_PATH_SMOOTH_M / gpp
    min_path = round(GEO_MIN_PATH_IN * dpi)

    def in_frame(box):
        return not (box[0] < edge or box[1] < edge or box[2] > out_w - edge or box[3] > out_h - edge)

    for rank, kind, name, (ax, ay), path in cands:
        if len(placed) >= cap:
            break
        pt_size, caps, _ = GEO_KINDS[kind]
        text = name.upper() if caps else name
        tracking = _pt_to_px(pt_size, dpi) * GEO_TRACKING_EM if caps else 0
        font = _font(max(9, round(_pt_to_px(pt_size, dpi))))

        # curved along the spine for a long-enough linear landform; else straight.
        if kind in GEO_CURVE_KINDS and path and len(path) >= 2:
            spine = _resample_path(path, max(1.0, smooth_px / 6.0), smooth_px)
            plan = _curved_plan(d, spine, text, font, tracking, halo, min_path)
            if plan is not None:
                glyphs, box = plan
                if in_frame(box) and not overlaps(box):
                    occupied.append(box)
                    placed.append(("curved", glyphs, font, halo))
                continue

        tw = _tracked_width(d, text, font, tracking)
        l, t, r, b = d.textbbox((0, 0), text, font=font)
        th = b - t
        x0 = round(ax - tw / 2)              # centered on the anchor
        y0 = round(ay - th / 2)
        box = (x0 - halo, y0 - halo, x0 + tw + halo, y0 + th + halo)
        if not in_frame(box) or overlaps(box):
            continue
        occupied.append(box)
        placed.append(("straight", x0, y0 - t, text, font, tracking, halo))

    for entry in placed:
        if entry[0] == "curved":
            _, glyphs, font, halo = entry
            for ch, cx, cy, ang in glyphs:
                _draw_glyph_rotated(img, ch, (cx, cy), ang, font, halo)
        else:
            _, x0, y0, text, font, tracking, halo = entry
            # knockout paper halo: the tracked string stamped around the ink so the name
            # reads over dark ridges and bright snow alike (classic map label halo).
            for dx in (-halo, 0, halo):
                for dy in (-halo, 0, halo):
                    if dx or dy:
                        _tracked_text(d, (x0 + dx, y0 + dy), text, font,
                                      GEO_LABEL_HALO + (235,), tracking)
            _tracked_text(d, (x0, y0), text, font, GEO_LABEL_INK + (255,), tracking)
    return img

def _draw_hydro(img, hydro, spec, out_w, out_h, dpi):
    """Composite baked water over the relief: lakes filled flat with a DPI-scaled
    shoreline, rivers as order-weighted lines. All widths in physical units."""
    if not hydro:
        return img
    d = ImageDraw.Draw(img, "RGBA")
    sw = max(1, round(_pt_to_px(SHORELINE_PT, dpi)))
    for lake in hydro.get("lakes", []):
        # tolerate missing key + 3-tuple (z) coords, matching what the baker emits
        pts = [_crs_to_px(x, y, spec.crop, out_w, out_h) for x, y, *_ in (lake.get("coords") or [])]
        if len(pts) >= 3:
            # 235 alpha, not opaque: a whisper of the lakebed relief ghosts through, so
            # lakes sit IN the toothy sheet instead of reading as flat vinyl stickers
            # (red-team beauty finding). The shoreline stays crisp at full ink.
            d.polygon(pts, fill=WATER_FILL + (235,), outline=WATER_SHORELINE + (255,), width=sw)
    for r in hydro.get("rivers", []):
        wpt = min(RIVER_MAX_PT, RIVER_BASE_PT + RIVER_STEP_PT * max(0, r.get("order", 3) - 3))
        wpx = max(1, round(_pt_to_px(wpt, dpi)))
        pts = [_crs_to_px(x, y, spec.crop, out_w, out_h) for x, y, *_ in (r.get("coords") or [])]
        if len(pts) >= 2:
            d.line(pts, fill=RIVER_COLOR + (255,), width=wpx, joint="curve")
    return img

def rasterize(spec: CompositionSpec, dpi: int, region_dir: str,
              watermark: bool = False, hydro=None, cfg=None, labels=None) -> Image.Image:
    spec.validate(dpi)
    if cfg is None:                        # callers holding regions.Region pass .cfg
        with open(os.path.join(region_dir, "region.json")) as f:
            cfg = json.load(f)
    out_w, out_h = spec.pixel_size(dpi)

    # Off-DEM guard: refuse a plausible-but-wrong poster before any painting invents
    # terrain under the tracks (red-team V1-1). DPI-independent probe, so proof and
    # final agree on the same spec (invariant 1).
    nan_frac = _offdem_fraction(region_dir, cfg, spec.crop)
    if nan_frac > MAX_OFFDEM_NAN_FRAC:
        raise OffDemError(
            f"The selected frame extends past the available elevation data "
            f"({nan_frac * 100:.0f}% of it has no DEM coverage). "
            f"Pan or shrink the crop to keep it inside the region.")

    elev, pad_x, pad_y, gpp = _read_window(region_dir, cfg, spec.crop, out_w, out_h)
    # optional biome tint (Dom, v1.2): hue from the region's baked NLCD land cover,
    # lightness from elevation + shade; None (asset absent or toggle off) falls back
    # to the pure elevation tint.
    biome = (_biome_layers(region_dir, cfg, spec.crop, (pad_x, pad_y), elev.shape, dpi)
             if spec.biome else None)
    rgb = shaded_relief(
        elev, res_m=gpp,
        elev_min=cfg["elevation_min"], elev_max=cfg["elevation_max"],
        azimuth=cfg["light_azimuth"], altitude=cfg["light_altitude"],
        z_factor=cfg["z_factor"], seed=spec.seed,
        grain_cell_px=max(1.0, spec.grain_cell_in * dpi),
        grain_strength=spec.grain_strength,
        # physical (ground-metre) blur radii -> identical relief at any DPI
        texture_radius_px=max(1.0, TEXTURE_RADIUS_M / gpp),
        valley_radius_px=max(1.0, VALLEY_RADIUS_M / gpp),
        biome=biome, depth=_terrain_depth(spec),
        shadow=spec.shadow_strength, shadow_res_m=_shadow_res_m(spec))
    # trim the margin back to the exact crop
    rgb = rgb[pad_y:pad_y+out_h, pad_x:pad_x+out_w, :]

    # optional elevation contours: over the relief, under water/tracks, computed on
    # the SAME trimmed elevation window the relief was painted from (registration).
    if spec.contours:
        # ground metres one printed inch spans -- the DPI-independent zoom the contour
        # interval tracks (proof and final share it, so they draw the same lines).
        gmpi = (spec.crop[2] - spec.crop[0]) / spec.print_w_in
        rgb = _draw_contours(rgb, elev[pad_y:pad_y+out_h, pad_x:pad_x+out_w], dpi, gmpi)

    # water sits on the relief, under the tracks (relief -> water -> tracks -> markers)
    if hydro is None:
        hydro = _load_hydro(region_dir)
    if hydro and hydro.get("crs") and hydro["crs"] != cfg["crs"]:
        # invariant 4: water must be in the region CRS or it mis-registers silently
        raise ValueError(f"hydro CRS {hydro['crs']} != region CRS {cfg['crs']}")
    himg = _draw_hydro(Image.fromarray(rgb, "RGB").convert("RGBA"),
                       hydro, spec, out_w, out_h, dpi)
    # named geography: on the terrain, under the route/markers (the journey stays the
    # subject). Opt-in (spec.labels); terrain names from labels.json, water from hydro.
    if spec.labels:
        if labels is None:
            labels = _load_labels(region_dir)
        himg = _draw_labels(himg, labels, hydro, spec, out_w, out_h, dpi)
    rgb = np.asarray(himg.convert("RGB"))

    lum = (0.2126*rgb[...,0] + 0.7152*rgb[...,1] + 0.0722*rgb[...,2]) / 255.0
    rgb = _ink_tracks(rgb, spec, out_w, out_h, dpi)
    img = Image.fromarray(rgb, "RGB").convert("RGBA")
    img = _draw_termini(img, spec, out_w, out_h, dpi)  # journey start/end pins, under markers
    img = _draw_markers(img, spec, lum, out_w, out_h, dpi)
    img = _draw_photos(img, spec, out_w, out_h, dpi)   # personal photos: the top layer

    if spec.keyline:
        img = _draw_keyline(img, out_w, out_h, dpi)
    img = _draw_compass(img, spec, out_w, out_h, dpi)   # above the title block
    img = _draw_title_block(img, spec, out_w, out_h, dpi)

    if watermark:
        # scale to the sheet (the old fixed 120 px offset + default font was invisible
        # at poster sizes) and center properly; translucent so the proof stays readable.
        d = ImageDraw.Draw(img, "RGBA")
        wm_font = _font(max(24, round(out_w * 0.09)))
        l, t, rt, b = d.textbbox((0, 0), "PROOF", font=wm_font)
        # upper third, not dead center: starter_crop centers the journey mid-sheet,
        # and the mark was parking exactly on the corridor being judged (red-team).
        d.text(((out_w - (rt - l)) / 2 - l, out_h * 0.24 - t), "PROOF",
               fill=(255, 255, 255, 80), font=wm_font)
    return img.convert("RGB")
