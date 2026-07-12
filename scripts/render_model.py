#!/usr/bin/env python3
"""The orbitable plate -- tier 3 of the social-preview suite: a real GLB model.

A thin disc whose top surface is displaced by the SAME luminance height-field the
mockup emboss uses, textured with the final's own pixels -- so spinning it on the
landing page (a vendored <model-viewer>) is the physical plate, not an artist's
impression. Social feeds can't embed 3D; this is what the "spin your plate" link
points at.

Pure-python glTF 2.0 writer: numpy + struct + PIL for the embedded texture, no new
dependencies. Real-world scale (a ~22 cm plate) so a future AR Quick Look treats it
as an object, not a building. Deterministic: fixed mesh, fixed texture encode, no
clock -- same input PNG, byte-identical GLB. Share-class: no manifest aboard.
"""
from __future__ import annotations
import argparse
import io
import json
import os
import struct
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts.render_mockups import MockupError, PNG_MAGIC, _height_field  # noqa: E402

DISC_SEGMENTS  = 128       # rim segments
DISC_RINGS     = 24        # radial rings on the displaced top surface
DISC_RADIUS    = 0.11      # meters -- a 22 cm plate (real-world scale for AR later)
DISC_THICKNESS = 0.008     # meters
DISPLACE_MAX   = 0.004     # meters of terrain relief on the top surface
TEXTURE_PX     = 1024      # embedded texture long edge
HEIGHT_SAMPLE  = 256       # luminance sampling grid for vertex displacement


def _centered_square(img: Image.Image, px: int) -> Image.Image:
    w, h = img.size
    s = min(w, h)
    return img.crop(((w - s) // 2, (h - s) // 2,
                     (w - s) // 2 + s, (h - s) // 2 + s)).resize((px, px),
                                                                 Image.LANCZOS)


def _sample_height(img: Image.Image) -> np.ndarray:
    """The emboss height field, on a small grid for vertex displacement."""
    small = _centered_square(img, HEIGHT_SAMPLE)
    art = np.asarray(small.convert("RGB"), dtype=np.float32) / 255.0
    return _height_field(art)                       # [0,1], HEIGHT_SAMPLE^2


def _height_at(H: np.ndarray, u: float, v: float) -> float:
    n = H.shape[0]
    x = min(n - 1, max(0, int(round(u * (n - 1)))))
    y = min(n - 1, max(0, int(round(v * (n - 1)))))
    return float(H[y, x])


def build_plate_glb(img: Image.Image) -> bytes:
    """The disc: displaced top grid (center + DISC_RINGS rings x DISC_SEGMENTS),
    flat back (mirror grid), and a rim wall (the outer ring duplicated top+bottom
    with radial normals). One material, the final's centered square as its texture."""
    H = _sample_height(img)
    seg, rings = DISC_SEGMENTS, DISC_RINGS
    R, T, D = DISC_RADIUS, DISC_THICKNESS, DISPLACE_MAX

    pos, nrm, uv = [], [], []

    def _top_z(u, v):
        return T + _height_at(H, u, v) * D

    # top: center + rings (z displaced); normals from the height gradient
    def _uv_of(x, y):
        return 0.5 + x / (2 * R), 0.5 - y / (2 * R)

    grid = [(0.0, 0.0)]
    for j in range(1, rings + 1):
        r = R * j / rings
        for i in range(seg):
            a = 2 * np.pi * i / seg
            grid.append((r * np.cos(a), r * np.sin(a)))
    eps = R / rings
    for (x, y) in grid:
        u, v = _uv_of(x, y)
        z = _top_z(u, v)
        # finite-difference normal in world units (clamped sampling inside the disc)
        ux1, vy1 = _uv_of(min(x + eps, R), y)
        ux0, vy0 = _uv_of(max(x - eps, -R), y)
        dzdx = (_top_z(ux1, vy1) - _top_z(ux0, vy0)) / (2 * eps)
        uxa, vya = _uv_of(x, min(y + eps, R))
        uxb, vyb = _uv_of(x, max(y - eps, -R))
        dzdy = (_top_z(uxa, vya) - _top_z(uxb, vyb)) / (2 * eps)
        n = np.array([-dzdx, -dzdy, 1.0]); n /= np.linalg.norm(n)
        pos.append((x, y, z)); nrm.append(tuple(n)); uv.append((u, v))

    top_count = len(grid)                            # 1 + rings*seg
    # back: mirror grid, flat at z=0, normal -z (winding reversed in the indices)
    for (x, y) in grid:
        u, v = _uv_of(x, y)
        pos.append((x, y, 0.0)); nrm.append((0.0, 0.0, -1.0)); uv.append((u, v))
    # rim wall: outer ring duplicated (top edge at its displaced z, bottom at 0),
    # radial normals -- crisp edge shading instead of smeared smooth normals
    outer0 = 1 + (rings - 1) * seg                   # first outer-ring index in grid
    for i in range(seg):
        x, y = grid[outer0 + i]
        u, v = _uv_of(x, y)
        n = np.array([x, y, 0.0]); n /= np.linalg.norm(n)
        pos.append((x, y, _top_z(u, v))); nrm.append(tuple(n)); uv.append((u, v))
    for i in range(seg):
        x, y = grid[outer0 + i]
        u, v = _uv_of(x, y)
        n = np.array([x, y, 0.0]); n /= np.linalg.norm(n)
        pos.append((x, y, 0.0)); nrm.append(tuple(n)); uv.append((u, v))

    idx = []
    # top fan (ring 1 <-> center) then quads between rings
    for i in range(seg):
        idx += [0, 1 + i, 1 + (i + 1) % seg]
    for j in range(rings - 1):
        a0, b0 = 1 + j * seg, 1 + (j + 1) * seg
        for i in range(seg):
            i2 = (i + 1) % seg
            idx += [a0 + i, b0 + i, b0 + i2, a0 + i, b0 + i2, a0 + i2]
    # back (winding reversed so -z faces out)
    off = top_count
    for i in range(seg):
        idx += [off, off + 1 + (i + 1) % seg, off + 1 + i]
    for j in range(rings - 1):
        a0, b0 = off + 1 + j * seg, off + 1 + (j + 1) * seg
        for i in range(seg):
            i2 = (i + 1) % seg
            idx += [a0 + i, b0 + i2, b0 + i, a0 + i, a0 + i2, b0 + i2]
    # rim wall quads
    wt, wb = 2 * top_count, 2 * top_count + seg
    for i in range(seg):
        i2 = (i + 1) % seg
        idx += [wt + i, wb + i, wb + i2, wt + i, wb + i2, wt + i2]

    positions = np.asarray(pos, dtype=np.float32)
    normals = np.asarray(nrm, dtype=np.float32)
    uvs = np.asarray(uv, dtype=np.float32)
    indices = np.asarray(idx, dtype=np.uint16)

    tex = io.BytesIO()
    _centered_square(img.convert("RGB"), TEXTURE_PX).save(tex, "PNG", optimize=True)
    tex = tex.getvalue()

    def _pad4(b: bytes, fill: bytes) -> bytes:
        return b + fill * (-len(b) % 4)

    bin_parts, views = [], []
    offset = 0
    for data, target in ((positions.tobytes(), 34962), (normals.tobytes(), 34962),
                         (uvs.tobytes(), 34962), (indices.tobytes(), 34963),
                         (tex, None)):
        data = _pad4(data, b"\x00")
        view = {"buffer": 0, "byteOffset": offset, "byteLength": len(data)}
        if target:
            view["target"] = target
        views.append(view)
        bin_parts.append(data)
        offset += len(data)
    blob = b"".join(bin_parts)

    doc = {
        "asset": {"version": "2.0", "generator": "tecopa-plateworks render_model"},
        "buffers": [{"byteLength": len(blob)}],
        "bufferViews": views,
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": len(positions),
             "type": "VEC3",
             "min": [float(x) for x in positions.min(axis=0)],
             "max": [float(x) for x in positions.max(axis=0)]},
            {"bufferView": 1, "componentType": 5126, "count": len(normals),
             "type": "VEC3"},
            {"bufferView": 2, "componentType": 5126, "count": len(uvs),
             "type": "VEC2"},
            {"bufferView": 3, "componentType": 5123, "count": len(indices),
             "type": "SCALAR"},
        ],
        "images": [{"bufferView": 4, "mimeType": "image/png"}],
        "samplers": [{"magFilter": 9729, "minFilter": 9987,
                      "wrapS": 33071, "wrapT": 33071}],
        "textures": [{"sampler": 0, "source": 0}],
        "materials": [{"pbrMetallicRoughness": {
            "baseColorTexture": {"index": 0},
            "metallicFactor": 0.05, "roughnessFactor": 0.85}}],
        "meshes": [{"primitives": [{
            "attributes": {"POSITION": 0, "NORMAL": 1, "TEXCOORD_0": 2},
            "indices": 3, "material": 0}]}],
        "nodes": [{"mesh": 0, "name": "plate"}],
        "scenes": [{"nodes": [0]}],
        "scene": 0,
    }
    jbytes = _pad4(json.dumps(doc, separators=(",", ":"), sort_keys=True).encode(),
                   b" ")
    total = 12 + 8 + len(jbytes) + 8 + len(blob)
    return b"".join([
        b"glTF", struct.pack("<II", 2, total),
        struct.pack("<II", len(jbytes), 0x4E4F534A), jbytes,     # 'JSON'
        struct.pack("<II", len(blob), 0x004E4942), blob,          # 'BIN'
    ])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("final", help="a TrailPrint final PNG")
    ap.add_argument("-o", "--out", default=None)
    args = ap.parse_args(argv)
    with open(args.final, "rb") as f:
        data = f.read()
    if not data.startswith(PNG_MAGIC):
        print(f"not a PNG: {os.path.basename(args.final)}", file=sys.stderr)
        return 2
    img = Image.open(io.BytesIO(data)).convert("RGB")
    out = args.out or os.path.join(
        os.path.dirname(os.path.abspath(args.final)) or ".",
        os.path.splitext(os.path.basename(args.final))[0] + "_plate.glb")
    with open(out, "wb") as f:
        f.write(build_plate_glb(img))
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
