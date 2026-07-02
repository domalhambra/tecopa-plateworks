# app/render.py
from __future__ import annotations
import json, os
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
# ------------------------------------------------------------------------------

def _pt_to_px(pt, dpi):  # points -> pixels
    return pt * dpi / 72.0

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

    # 1) paper halo under the line, following the worn width where paths repeat.
    #    clip(cov)-1 at the halo width = presence of a 2nd+ journey -> the worn gate.
    cas = np.clip(_coverage(spec, out_w, out_h, ink_w + 2 * pad, groups), 0, 1)
    if worn_possible:
        cas_worn = _coverage(spec, out_w, out_h, worn_w + 2 * pad, groups)
        cas = np.maximum(cas, np.clip(cas_worn - 1, 0, 1))
        del cas_worn
    cas = gaussian_filter(cas, max(0.3, _pt_to_px(CASING_BLUR_PT, dpi)))
    casing_op = (CASING_STRENGTH * np.clip(cas, 0, 1))[..., None]
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
    ink = np.array(TRACK_INK, np.float32) / 255.0
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
        d.ellipse([cx-r, cy-r, cx+r, cy+r], fill=MARKER_FILL + (255,), outline=ring,
                  width=max(1, round(dia * 0.09)))
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

def _draw_photos(img, spec, out_w, out_h, dpi):
    """Pin user photos to their markers: a fitted thumbnail in a cream mat with a
    thin keyline, a drop shadow, and a short stem back to the anchor point. Tolerant
    of a missing/unreadable file (skip it) so one bad photo can't fail the render."""
    if not any(hs.get("photo") for hs in spec.hotspots):
        return img
    box = max(24, round(spec.photo_box_in * dpi))
    mat = max(2, round(box * 0.05))
    stem = max(1, round(box * 0.02))
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
        ax, ay = _crs_to_px(hs["x"], hs["y"], spec.crop, out_w, out_h)
        # place the framed photo up-and-right of the anchor, clamped to the frame
        fx = int(np.clip(ax + box*0.35, 0, out_w - pw - 2*mat - 1))
        fy = int(np.clip(ay - ph - 2*mat - box*0.35, 0, out_h - ph - 2*mat - 1))
        # stem from anchor to the frame's near corner
        d.line([(ax, ay), (fx + mat, fy + ph + mat)], fill=PHOTO_EDGE + (255,), width=stem)
        shadow = Image.new("RGBA", (out_w, out_h), (0, 0, 0, 0))
        ImageDraw.Draw(shadow).rectangle([fx, fy, fx+pw+2*mat, fy+ph+2*mat], fill=(20, 16, 12, 110))
        img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(max(1.0, mat*0.8))))
        d = ImageDraw.Draw(img, "RGBA")
        d.rectangle([fx, fy, fx+pw+2*mat, fy+ph+2*mat], fill=PHOTO_FRAME + (255,))
        img.paste(photo, (fx+mat, fy+mat))
        d.rectangle([fx, fy, fx+pw+2*mat, fy+ph+2*mat], outline=PHOTO_EDGE + (255,), width=max(1, mat//2))
    return img

# ---- finished-sheet furniture (V1-10 print-correctness): keyline + title block ----
KEYLINE_INSET_IN = 0.25         # thin frame inset from the sheet edge
KEYLINE_PT = 0.6
TITLE_INSET_IN = 0.35           # title block inset from the sheet corner
# ------------------------------------------------------------------------------------

def _stats_line(spec, dpi):
    """A deterministic cartographic caption from the spec alone: approximate scale
    ratio, distinct days, total mileage. No wall clock, no locale (invariant 3)."""
    import math
    parts = []
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

def _title_block_metrics(spec, d, dpi):
    """Measured geometry of the title plate (None when there's no title). Shared by
    _draw_title_block and the compass placement above it, so they can't drift."""
    if not spec.title_text.strip():
        return None
    title = spec.title_text.strip().upper()
    stats = _stats_line(spec, dpi)
    title_font = _font(max(12, round(_pt_to_px(spec.title_pt, dpi))))
    stats_font = _font(max(8, round(_pt_to_px(spec.label_pt * 0.85, dpi))))
    tl, tt, tr, tb = d.textbbox((0, 0), title, font=title_font)
    th = tb - tt
    if stats:
        sl, st_, sr, sb = d.textbbox((0, 0), stats, font=stats_font)
        sh, sw = sb - st_, sr - sl
        gap = round(0.45 * sh)
    else:
        sl = st_ = sh = sw = gap = 0
    pad = max(4, round(0.12 * dpi))
    return {"title": title, "stats": stats,
            "title_font": title_font, "stats_font": stats_font,
            "tl": tl, "tt": tt, "th": th, "sl": sl, "st": st_, "gap": gap,
            "pad": pad, "bw": max(tr - tl, sw) + 2 * pad,
            "bh": th + (gap + sh if stats else 0) + 2 * pad}

def _draw_title_block(img, spec, out_w, out_h, dpi):
    """The finished title block: a paper plate anchored bottom-left carrying the
    title (caps, serif) over a small stats caption (scale, days, mileage). Replaces
    the old bare bottom-left caption."""
    d = ImageDraw.Draw(img, "RGBA")
    m = _title_block_metrics(spec, d, dpi)
    if m is None:
        return img
    inset = round(TITLE_INSET_IN * dpi)
    x = inset
    y = out_h - inset - m["bh"]
    pad = m["pad"]
    d.rounded_rectangle([x, y, x + m["bw"], y + m["bh"]], radius=max(2, pad // 2),
                        fill=LABEL_PLATE + (235,))
    d.text((x + pad - m["tl"], y + pad - m["tt"]), m["title"],
           fill=LABEL_INK + (255,), font=m["title_font"])
    if m["stats"]:
        d.text((x + pad - m["sl"], y + pad + m["th"] + m["gap"] - m["st"]),
               m["stats"], fill=LABEL_INK + (200,), font=m["stats_font"])
    return img

# ---- optional furniture (v1.2, Dom): elevation contours + compass rose ----
CONTOUR_INK = (54, 40, 30)      # the umber ink family
CONTOUR_MINOR_OPACITY = 0.32    # visible-by-choice: the operator turned these on
CONTOUR_INDEX_OPACITY = 0.55    # every 5th level reads a touch firmer
CONTOUR_MINOR_PT = 0.45         # physical widths -> proof == final (invariant 2)
CONTOUR_INDEX_PT = 0.8
COMPASS_DIAMETER_IN = 0.85      # rose size on the sheet
# -----------------------------------------------------------------------------

def _contour_interval(range_m):
    """The smallest conventional interval giving at most ~18 lines across the
    crop's local relief (~26 max) -- dense enough to read, sparse enough not to shade."""
    for iv in (5, 10, 20, 25, 50, 100, 200, 250, 500, 1000):
        if range_m / iv <= 26:
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

def _draw_contours(rgb_u8, elev_core, dpi):
    """Composite elevation contours over the relief (under water/tracks): minor
    lines at the auto interval, index lines every 5th level slightly firmer."""
    from app.relief import _fill_nan
    elev = _fill_nan(np.array(elev_core, dtype="float32", copy=True))
    rng = float(elev.max() - elev.min())
    if rng < 1.0:                              # a dead-flat crop has no contours
        return rgb_u8
    iv = _contour_interval(rng)
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
    """A split-shaded four-point compass rose above the title block, bottom-left:
    thin ring, north point long, each point half umber / half paper (the classic
    rose shading), a small N above. Vector-only + physical sizes, so the same spec
    renders identically at any DPI and on any machine."""
    if not spec.compass:
        return img
    import math as _m
    d = ImageDraw.Draw(img, "RGBA")
    R = COMPASS_DIAMETER_IN * dpi / 2.0
    inset = round(TITLE_INSET_IN * dpi)
    m = _title_block_metrics(spec, d, dpi)
    base_y = out_h - inset - ((m["bh"] + round(0.16 * dpi)) if m else 0)
    cx, cy = inset + R, base_y - R
    # a soft paper ground so the rose reads over any terrain
    d.ellipse([cx - R * 1.14, cy - R * 1.14, cx + R * 1.14, cy + R * 1.14],
              fill=LABEL_PLATE + (150,))
    ring_w = max(1, round(_pt_to_px(0.6, dpi)))
    d.ellipse([cx - R, cy - R, cx + R, cy + R],
              outline=TERMINUS_INK + (210,), width=ring_w)

    def point(angle_deg, length, half_w):
        a = _m.radians(angle_deg - 90)                     # 0 deg = north, y down
        tip = (cx + length * _m.cos(a), cy + length * _m.sin(a))
        left = (cx + half_w * _m.cos(a - _m.pi / 2), cy + half_w * _m.sin(a - _m.pi / 2))
        right = (cx + half_w * _m.cos(a + _m.pi / 2), cy + half_w * _m.sin(a + _m.pi / 2))
        d.polygon([tip, left, (cx, cy)], fill=TERMINUS_INK + (235,))
        d.polygon([tip, right, (cx, cy)], fill=TERMINUS_RING + (245,))

    for ang, ln in ((90, R * 0.60), (180, R * 0.60), (270, R * 0.60), (0, R * 0.92)):
        point(ang, ln, R * 0.18)                           # north last, on top
    hub = R * 0.07
    d.ellipse([cx - hub, cy - hub, cx + hub, cy + hub], fill=TERMINUS_INK + (255,))
    f = _font(max(10, round(_pt_to_px(11.5, dpi))))
    nl, nt, nr, nb = d.textbbox((0, 0), "N", font=f)
    nw, nh = nr - nl, nb - nt
    nx, ny = cx - nw / 2, cy - R - nh - round(0.05 * dpi)
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
              watermark: bool = False, hydro=None, cfg=None) -> Image.Image:
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
    rgb = shaded_relief(
        elev, res_m=gpp,
        elev_min=cfg["elevation_min"], elev_max=cfg["elevation_max"],
        azimuth=cfg["light_azimuth"], altitude=cfg["light_altitude"],
        z_factor=cfg["z_factor"], seed=spec.seed,
        grain_cell_px=max(1.0, spec.grain_cell_in * dpi),
        grain_strength=spec.grain_strength,
        # physical (ground-metre) blur radii -> identical relief at any DPI
        texture_radius_px=max(1.0, TEXTURE_RADIUS_M / gpp),
        valley_radius_px=max(1.0, VALLEY_RADIUS_M / gpp))
    # trim the margin back to the exact crop
    rgb = rgb[pad_y:pad_y+out_h, pad_x:pad_x+out_w, :]

    # optional elevation contours: over the relief, under water/tracks, computed on
    # the SAME trimmed elevation window the relief was painted from (registration).
    if spec.contours:
        rgb = _draw_contours(rgb, elev[pad_y:pad_y+out_h, pad_x:pad_x+out_w], dpi)

    # water sits on the relief, under the tracks (relief -> water -> tracks -> markers)
    if hydro is None:
        hydro = _load_hydro(region_dir)
    if hydro and hydro.get("crs") and hydro["crs"] != cfg["crs"]:
        # invariant 4: water must be in the region CRS or it mis-registers silently
        raise ValueError(f"hydro CRS {hydro['crs']} != region CRS {cfg['crs']}")
    himg = _draw_hydro(Image.fromarray(rgb, "RGB").convert("RGBA"),
                       hydro, spec, out_w, out_h, dpi)
    rgb = np.asarray(himg.convert("RGB"))

    lum = (0.2126*rgb[...,0] + 0.7152*rgb[...,1] + 0.0722*rgb[...,2]) / 255.0
    rgb = _ink_tracks(rgb, spec, out_w, out_h, dpi)
    img = Image.fromarray(rgb, "RGB").convert("RGBA")
    img = _draw_termini(img, spec, out_w, out_h, dpi)  # journey start/end pins, under markers
    img = _draw_markers(img, spec, lum, out_w, out_h, dpi)
    img = _draw_photos(img, spec, out_w, out_h, dpi)   # personal photos: the top layer

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
