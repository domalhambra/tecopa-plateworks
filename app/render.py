# app/render.py
from __future__ import annotations
import json, os
import numpy as np
import rasterio
from rasterio.windows import from_bounds
from rasterio.enums import Resampling
from scipy.ndimage import gaussian_filter
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from app.spec import CompositionSpec
from app.relief import shaded_relief, grain, TEXTURE_RADIUS_M, VALLEY_RADIUS_M

MARGIN_FRAC = 0.06   # read a little past the crop so shadows entering the frame are correct

# ---- track cartography: a pronounced desert-gold route laid onto the paper ----
TRACK_INK = (214, 158, 58)      # desert gold -- warm, saturated, reads against earthy terrain
TRACK_CASING = (54, 40, 30)     # dark umber halo -> the gold line pops off any background
CASING_STRENGTH = 0.34          # a soft dark outline that frames the gold
CASING_PAD_PT = 0.8             # halo reach beyond the line, in points
CASING_BLUR_PX = 1.4
INK_FREQ_K = 1.15               # visitation -> opacity saturation (1 pass ~0.68, 2x -> cap)
INK_EDGE_FEATHER_PX = 0.6       # soften the hard PIL edge
INK_GRAIN = 0.16                # paper texture carried onto the line
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

def _crs_to_px(x, y, crop, out_w, out_h):
    px = (x - crop[0]) / (crop[2]-crop[0]) * out_w
    py = (crop[3] - y) / (crop[3]-crop[1]) * out_h
    return px, py

def _coverage(spec, out_w, out_h, width_px):
    """Anti-aliased per-pixel visit count: how many track-passes cover each pixel.
    Drawing each track on its own layer and summing makes overlap = frequency."""
    cov = np.zeros((out_h, out_w), np.float32)
    for coords in spec.tracks:
        pts = [_crs_to_px(x, y, spec.crop, out_w, out_h) for x, y in coords]
        if len(pts) < 2:
            continue
        layer = Image.new("L", (out_w, out_h), 0)
        ImageDraw.Draw(layer).line(pts, fill=255, width=max(1, width_px), joint="curve")
        cov += np.asarray(layer, np.float32) / 255.0
    return cov

def _ink_tracks(rgb_u8, spec, out_w, out_h, dpi):
    """Composite tracks as inked, visitation-weighted, cased lines that pick up
    the terrain texture and paper grain instead of floating on top."""
    img = rgb_u8.astype(np.float32) / 255.0
    ink_w = max(1, round(_pt_to_px(spec.track_width_pt, dpi)))
    casing_w = ink_w + 2 * max(1, round(_pt_to_px(CASING_PAD_PT, dpi)))

    # 1) soft dark umber casing under the line -> a thin outline that frames the gold
    casing = gaussian_filter(_coverage(spec, out_w, out_h, casing_w), CASING_BLUR_PX)
    casing_op = (CASING_STRENGTH * np.clip(casing, 0, 1))[..., None]
    casing_col = np.array(TRACK_CASING, np.float32) / 255.0
    img = img * (1 - casing_op) + casing_col[None, None, :] * casing_op

    # 2) the line: frequency -> saturating opacity, feathered, grain-textured, painted toward gold
    visits = gaussian_filter(_coverage(spec, out_w, out_h, ink_w), INK_EDGE_FEATHER_PX)
    op = np.clip(1.0 - np.exp(-INK_FREQ_K * visits), 0.0, spec.track_max_darken)
    gf = np.clip(grain((out_h, out_w), max(1.0, spec.grain_cell_in * dpi), INK_GRAIN, spec.seed), 0, 1)
    op = (op * gf)[..., None]
    ink = np.array(TRACK_INK, np.float32) / 255.0
    # alpha-blend toward the gold so the hue reads true and pronounced (a multiply
    # toward gold would only darken the terrain to a muddy brown); grain in `op`
    # keeps the paper texture so it still sits on the sheet rather than floating.
    img = img * (1 - op) + ink[None, None, :] * op

    return (np.clip(img, 0, 1) * 255).astype(np.uint8)

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
    for hs in spec.hotspots:
        cx, cy = _crs_to_px(hs["x"], hs["y"], spec.crop, out_w, out_h)
        if not in_frame(cx, cy):
            continue
        # contrast ring: light on dark terrain, dark on light
        yy = int(np.clip(cy, 0, out_h-1)); xx = int(np.clip(cx, 0, out_w-1))
        ring = (243, 237, 223, 235) if elev_lum[yy, xx] < 0.5 else (43, 42, 40, 230)
        fill = (190, 158, 92, 255)   # muted rabbitbrush gold
        d.ellipse([cx-r, cy-r, cx+r, cy+r], fill=fill, outline=ring,
                  width=max(1, round(dia * 0.09)))
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
            d.polygon(pts, fill=WATER_FILL + (255,), outline=WATER_SHORELINE + (255,), width=sw)
    for r in hydro.get("rivers", []):
        wpt = min(RIVER_MAX_PT, RIVER_BASE_PT + RIVER_STEP_PT * max(0, r.get("order", 3) - 3))
        wpx = max(1, round(_pt_to_px(wpt, dpi)))
        pts = [_crs_to_px(x, y, spec.crop, out_w, out_h) for x, y, *_ in (r.get("coords") or [])]
        if len(pts) >= 2:
            d.line(pts, fill=RIVER_COLOR + (255,), width=wpx, joint="curve")
    return img

def rasterize(spec: CompositionSpec, dpi: int, region_dir: str,
              watermark: bool = False, hydro=None) -> Image.Image:
    spec.validate(dpi)
    cfg = json.load(open(os.path.join(region_dir, "region.json")))
    out_w, out_h = spec.pixel_size(dpi)

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
    img = _draw_markers(img, spec, lum, out_w, out_h, dpi)

    if spec.title_text:
        d = ImageDraw.Draw(img)
        size = max(10, round(_pt_to_px(spec.title_pt, dpi)))
        try:
            font = ImageFont.truetype("Georgia.ttf", size)
        except Exception:
            font = ImageFont.load_default()
        d.text((round(0.04*out_w), round(0.94*out_h)), spec.title_text,
               fill=(43, 42, 40), font=font)

    if watermark:
        d = ImageDraw.Draw(img, "RGBA")
        d.text((out_w//2 - 120, out_h//2), "PROOF", fill=(255, 255, 255, 90))
    return img.convert("RGB")

def save_print(img: Image.Image, path: str, dpi: int):
    img.save(path, dpi=(dpi, dpi))   # embeds DPI so a print shop reads true size
