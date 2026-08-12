#!/usr/bin/env python3
# scripts/hero_plate.py
"""Hero plate: perform a poster's terrain through Blender Cycles, then let the
engine paint its own water, route, markers, labels and furniture over it.

Operator CLI, deliberately not an app feature (design 2026-08-10): stills only,
print only, flat sheet only. The output carries the SOURCE manifest unchanged --
the file stays a save file (/api/reprint returns the archival edition); the hero
pixels are a performance, recorded by engine_version like any other build's.

    source .venv/bin/activate
    python scripts/hero_plate.py poster.png [--blender /path] [--samples 512] \\
        [--z 1.0] [--dpi 300] [--out hero.png] [--allow-plate-mismatch]

Requires a Blender >= 4.2 LTS the operator installed (https://blender.org/download);
found via --blender, TECOPA_BLENDER, or PATH.

REGISTRATION -- the one thing this file must get right. Everything geometric is
derived from `render.terrain_window(spec, dpi, region_dir, cfg)`: the PADDED window
the relief would have been shaded on, not the trimmed sheet. Cycles renders that
window, at that window's pixel count, over that window's ground extent, and the
result goes straight back through `rasterize(terrain_override=...)`, which checks the
shape. One window, both sides, no calibration step."""
from __future__ import annotations
import argparse
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from PIL import Image

from app import provenance, regions, relief, render
from app.spec import FINAL_DPI, SpecError

BLENDER_MIN = (4, 2)
SUN_ANGULAR_SIZE_DEG = 3.0      # ~6x the real sun: soft, readable penumbra


class HeroError(SystemExit):
    """A refusal with its reason as the exit message (never a traceback)."""


# ---- what v1 honestly does, and what it refuses -----------------------------------

def check_supported(spec, dpi=FINAL_DPI):
    if spec.output_kind != "print":
        raise HeroError("hero plates are prints; render the poster spec, not a wallpaper")
    if spec.bleed_in > 0:
        raise HeroError("hero v1 renders the trim sheet only -- re-export without bleed")
    if spec.oblique > 0:
        raise HeroError("hero v1 renders the flat sheet; High relief (oblique) is its own projection")
    # The zoom cap and the output ceiling are enforced inside rasterize() -- which
    # runs AFTER Cycles. At hero render times that is hours of work thrown away on a
    # --dpi the spec was never going to accept, so ask the spec the same question now.
    try:
        spec.validate(dpi)
    except SpecError as e:
        raise HeroError(f"this poster can't be rendered at {dpi} dpi: {e}")


def find_blender(cli_path):
    cand = cli_path or os.environ.get("TECOPA_BLENDER") or shutil.which("blender")
    if not cand or not os.path.exists(cand):
        raise HeroError(
            "No Blender found. Install it (free) from https://blender.org/download,\n"
            "then pass --blender /path/to/blender or set TECOPA_BLENDER.")
    out = subprocess.run([cand, "--version"], capture_output=True, text=True, timeout=30)
    first = (out.stdout or "").splitlines()[0] if out.stdout else ""
    try:
        ver = tuple(int(p) for p in first.split()[1].split(".")[:2])
    except Exception:
        raise HeroError(f"Could not read a Blender version from {cand!r} ({first!r})")
    if ver < BLENDER_MIN:
        raise HeroError(f"Blender {ver[0]}.{ver[1]} is older than the "
                        f"{BLENDER_MIN[0]}.{BLENDER_MIN[1]} LTS floor -- please upgrade")
    return cand


# ---- the scene, as pure math (tested without Blender) ------------------------------

def sun_angles(spec, cfg):
    """(azimuth, altitude) in degrees -- the light the poster was PAINTED with, so the
    Cycles performance is the same sun the archival edition shows. Journey Light rides
    the spec; archival rides the plate, exactly as `_paint_terrain` reads them."""
    if spec.light_mode == "journey":
        az, alt = spec.sun_azimuth_deg, spec.sun_altitude_deg
        # A hand-edited or crafted manifest can say "journey" and carry no resolved
        # sun; float(None) is a bare TypeError traceback, which is not how this CLI
        # refuses anything else.
        if not (isinstance(az, (int, float)) and isinstance(alt, (int, float))
                and not isinstance(az, bool) and not isinstance(alt, bool)):
            raise HeroError("this poster claims Journey Light but carries no resolved "
                            "sun, so there is no light to perform it under.")
        return float(az), float(alt)
    return float(cfg.get("light_azimuth", 315.0)), float(cfg.get("light_altitude", 45.0))


def sun_rotation_euler(az_deg, alt_deg):
    """Blender XYZ euler for a SUN lamp shining FROM compass bearing `az` at height
    `alt`, in a scene whose +X is east and +Y is north.

    A sun lamp emits along its local -Z, so its +Z axis must point at the sun:
    (sin az cos alt, cos az cos alt, sin alt). With R = Rz(c) . Ry(0) . Rx(a) the
    lamp's +Z lands on (sin a sin c, -sin a cos c, cos a), so a = 90 deg - alt and
    c = 180 deg - az. (The intuitive c = -az mirrors the sun east-west; an east sun
    would light the western faces. tests/test_hero_plate.py checks the vector.)"""
    return (math.pi / 2 - math.radians(alt_deg), 0.0,
            math.pi - math.radians(az_deg))


def sun_vector(az_deg, alt_deg):
    """The unit vector TOWARD the sun in scene axes -- the thing the euler above must
    reproduce, kept here so the test asserts the physics, not the arithmetic."""
    a, e = math.radians(az_deg), math.radians(alt_deg)
    return (math.sin(a) * math.cos(e), math.cos(a) * math.cos(e), math.sin(e))


def scene_params(shape, res_m, az_deg, alt_deg, samples):
    """The scene Blender builds, derived ENTIRELY from the terrain window.

    `shape` is the padded window's (rows, cols) and `res_m` its ground metres per
    pixel, so the plane is exactly the ground those pixels cover and the render is
    exactly that many pixels -- which is what makes the result a legal
    `terrain_override`. Deriving any of it from `spec.crop` or `spec.pixel_size`
    instead would silently drop the render margin and shift the whole sheet.

    `ortho_scale` is Blender's frame size along the camera's LARGER pixel dimension,
    so a portrait sheet takes the ground HEIGHT, not the width."""
    h, w = int(shape[0]), int(shape[1])
    ground_w, ground_h = w * float(res_m), h * float(res_m)
    return {"resolution": [w, h],
            "plane_size": [ground_w, ground_h],
            "ortho_scale": ground_w if w >= h else ground_h,
            "samples": int(samples),
            "sun": {"azimuth_deg": az_deg, "altitude_deg": alt_deg,
                    "angular_size_deg": SUN_ANGULAR_SIZE_DEG,
                    "rotation_euler": list(sun_rotation_euler(az_deg, alt_deg))}}


# ---- the two textures Blender reads ------------------------------------------------

def write_heightmap(path, elev):
    """The window's elevation as a 16-bit grayscale PNG, plus (lo, hi) in metres.

    16-bit PNG rather than EXR on purpose: Blender reads both, PIL writes this one
    with no extra dependency, and 65536 levels over a poster's elevation range is
    ~1.5 cm per level -- far below anything a displaced plane can show. The caller
    multiplies the 0..1 texture back up by (hi - lo)."""
    lo, hi = float(np.nanmin(elev)), float(np.nanmax(elev))
    norm = (elev.astype("float64") - lo) / max(1e-9, hi - lo)
    q = np.clip(np.rint(norm * 65535.0), 0, 65535).astype("uint16")
    # No `mode=` argument: Pillow deprecated passing one to convert data types and
    # removes it in 13.0 (2026-10-15). A uint16 array already infers "I;16", so the
    # inference IS the contract now (tests/test_hero_plate.py fails on the warning).
    Image.fromarray(q).save(path)
    return lo, hi


def write_color_texture(path, spec, dpi, region_dir, cfg, shape):
    """The engine's OWN unlit colour -- the hypsometric ramp plus the biome tint --
    on the same window, draped over the Cycles terrain as base colour.

    `relief.base_colour` is the very expression `shaded_relief` uses for its "color"
    stage, so the hero sheet is the archival sheet's palette with Cycles supplying
    all of the light. Nothing here shades: no hillshade, no texture, no tonal curve,
    no grain. Those are the engine's way of faking the light Cycles actually traces."""
    elev, res_m, shp = render.terrain_window(spec, dpi, region_dir, cfg)
    # Not an assert: `python -O` strips those, and this is the check that keeps the
    # colour texture on the same grid as the heightmap. Two windows that disagree
    # would drape the palette a few pixels off the terrain it belongs to.
    if tuple(shp) != tuple(shape):
        raise HeroError(f"the colour texture's window {tuple(shp)} doesn't match the "
                        f"heightmap's {tuple(shape)} -- they would not register.")
    biome = (render._biome_layers(region_dir, cfg, spec.crop,
                                  _window_pads(spec, dpi), shp, dpi)
             if spec.biome else None)
    rgb = relief.base_colour(elev, cfg["elevation_min"], cfg["elevation_max"],
                             biome=biome)
    Image.fromarray(np.clip(rgb * 255.0, 0, 255).astype("uint8"), "RGB").save(path)


def _window_pads(spec, dpi):
    """(pad_x, pad_y) for the symmetric render margin -- the same expression
    `_read_window` uses, so the biome tint lands on the terrain window's own grid."""
    out_w, out_h = spec.pixel_size(dpi)
    return (round(out_w * render.MARGIN_FRAC), round(out_h * render.MARGIN_FRAC))


# ---- reading the poster ------------------------------------------------------------

def read_poster(path, allow_plate_mismatch=False):
    """(spec, manifest, region_dir, cfg) for a poster PNG, through the ONE untrusted
    door (`provenance.spec_from_manifest`), then the same plate check /api/reprint
    makes -- a rebuilt plate WARNS and proceeds under the override, it does not
    refuse a customer's reorder."""
    with open(path, "rb") as f:
        manifest = provenance.extract(f.read())
    if manifest is None:
        raise HeroError(f"{path} carries no Tecopa Plateworks manifest -- "
                        f"a hero plate is rendered FROM a poster, not from any PNG.")
    spec = provenance.spec_from_manifest(manifest)
    reg = regions.discover()
    region = reg.get(spec.region_id)
    if region is None:
        raise HeroError(f"Region {spec.region_id!r} isn't built here, so this poster "
                        f"can't be performed. Build the plate first.")
    file_pv = _file_pack_version(manifest)
    if file_pv:
        server = provenance.region_pack_block(region.dir, labels=spec.labels,
                                              biome=spec.biome)
        if server is not None and server["pack_version"] != file_pv:
            msg = (f"this poster was painted on the {spec.region_id} plate {file_pv}; "
                   f"this machine has {server['pack_version']}.")
            if not allow_plate_mismatch:
                raise HeroError(msg + " The terrain has changed, so the hero plate will "
                                      "not match the original. Re-run with "
                                      "--allow-plate-mismatch to perform it on the "
                                      "current plate.")
            print(f"warning: {msg} Performing on the current plate.", file=sys.stderr)
    return spec, manifest, region.dir, region.cfg


def _file_pack_version(manifest):
    """The manifest's plate identity, only when it can NAME a plate -- the same
    12-hex predicate app/main.py applies, so the CLI and the endpoint agree."""
    rp = (manifest or {}).get("region_pack")
    pv = rp.get("pack_version") if isinstance(rp, dict) else None
    if isinstance(pv, str) and len(pv) == 12 and all(c in "0123456789abcdef" for c in pv):
        return pv
    return None


# ---- the run -----------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Perform a poster's terrain through Blender Cycles.")
    ap.add_argument("poster")
    ap.add_argument("--blender", default=None)
    ap.add_argument("--samples", type=int, default=512)
    ap.add_argument("--z", type=float, default=1.0, help="vertical exaggeration")
    ap.add_argument("--dpi", type=int, default=FINAL_DPI,
                    help=f"render dpi (default {FINAL_DPI}, the print final)")
    ap.add_argument("--out", default=None)
    ap.add_argument("--allow-plate-mismatch", action="store_true")
    a = ap.parse_args(argv)

    blender = find_blender(a.blender)
    spec, manifest, region_dir, cfg = read_poster(
        a.poster, allow_plate_mismatch=a.allow_plate_mismatch)
    check_supported(spec, a.dpi)

    with tempfile.TemporaryDirectory(prefix="tecopa-hero-") as td:
        elev, res_m, shape = render.terrain_window(spec, a.dpi, region_dir, cfg)
        height_png = os.path.join(td, "height.png")
        lo, hi = write_heightmap(height_png, elev)
        color_png = os.path.join(td, "color.png")
        write_color_texture(color_png, spec, a.dpi, region_dir, cfg, shape)
        az, alt = sun_angles(spec, cfg)
        side = dict(scene_params(shape, res_m, az, alt, a.samples))
        side.update({"height_png": height_png, "color_png": color_png,
                     "elev_range_m": hi - lo, "z_exaggeration": a.z,
                     "out": os.path.join(td, "cycles.png")})
        side_path = os.path.join(td, "scene.json")
        with open(side_path, "w") as f:
            json.dump(side, f)
        print(f"Rendering {side['resolution'][0]}x{side['resolution'][1]} px "
              f"at {a.samples} samples -- this is Cycles, expect minutes-to-hours...")
        subprocess.run([blender, "--background", "--factory-startup", "--python",
                        os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                     "hero_scene.py"),
                        "--", side_path], check=True)
        cycles = np.asarray(Image.open(side["out"]).convert("RGB"))
        if cycles.shape[:2] != tuple(shape):
            raise HeroError(f"Blender wrote {cycles.shape[:2]} px, expected {tuple(shape)} "
                            f"-- the render was resized or cropped, so it cannot register.")
        sheet = render.rasterize(spec, a.dpi, region_dir, cfg=cfg,
                                 terrain_override=cycles)
        out = a.out or os.path.splitext(a.poster)[0] + "_hero.png"
        # the SOURCE manifest, unchanged: the hero file still reprints its archival
        # edition, because what the manifest describes is the score, not this
        # performance of it.
        sheet.save(out, pnginfo=provenance.manifest_pnginfo(manifest))
        print(f"Hero plate written: {out}\n"
              f"The file still reprints its archival edition -- the hero pixels are "
              f"a performance, not the record.")


if __name__ == "__main__":
    main()
