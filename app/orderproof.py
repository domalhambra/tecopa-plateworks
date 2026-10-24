# app/orderproof.py
"""The proof files of an order: the proof the client approves, and Dom's soft proof on
the roll's paper.

Prepare writes them, and the studio's Save to order writes them again. Both paint one
spec (orderspec.order_spec), the spec Finish prints, so what the client approves is the
print. The proof is the print's picture with the word PROOF across it; a set shows its
gap strips in the wall tone.

This module never imports app.main (plan decision P8)."""
from __future__ import annotations

import json
import os

from PIL import Image

from app import icc, orderspec, panels as panel_geo, papers, proofpdf, sizes
from app.order import Order, OrderError

PROOF_DPI = 96.0
JPEG_QUALITY = 90

# What the client reads on the proof's page (Dom reviews this copy).
LINE_PROOF = "Proof of your Tecopa Plateworks map, {size}."
LINE_REPLY = ("Reply to approve it, or ask for your one round of changes. "
              "Nothing prints before you approve.")


def size_key(spec) -> str | None:
    """The config/sizes.toml row of the spec's size, or None for a size the table does
    not name."""
    if spec.panels > 1:
        return {2: "two", 3: "three"}.get(spec.panels)
    short, long_ = sorted((float(spec.print_w_in), float(spec.print_h_in)))
    return {(11.0, 17.0): "11x17", (17.0, 22.0): "17x22"}.get((short, long_))


def size_name(spec) -> str:
    """The name of the spec's size as the client reads it, from config/sizes.toml."""
    key = size_key(spec)
    if key is not None:
        return sizes.table()[key]["name"]
    short, long_ = sorted((float(spec.print_w_in), float(spec.print_h_in)))
    return f"{short:g} × {long_:g} in"


def client_lines(spec) -> list:
    return [LINE_PROOF.format(size=size_name(spec)), LINE_REPLY]


def _save(img, path, fmt, **kw) -> None:
    """Write under a temporary name and rename, so a failed write keeps the last file."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    try:
        img.save(tmp, fmt, **kw)
        os.replace(tmp, path)
    except BaseException as ex:
        try:
            os.remove(tmp)
        except OSError:
            pass
        if isinstance(ex, OSError):
            raise OrderError(f"The proof cannot be written to {path}: "
                             f"{ex.strerror or ex}") from ex
        raise


def write_proofs(order: Order, spec, plate: str, dpi: float = PROOF_DPI, paper=None,
                 profile_dirs=icc.PROFILE_DIRS) -> dict:
    """Render `spec` once and write the proof files in the order's folder:

      work/proof.png                     the proof, sRGB profile embedded
      work/softproof.png                 the proof through the paper's profile and
                                         intent (skipped when the profile is not installed)
      out/proof/<stem>-proof.jpg         the client's proof
      out/proof/<stem>-proof.pdf         one page: the title, the map and the client lines

    Returns {"files", "soft_proof", "soft_proof_why", "hash"}."""
    from app import render           # here, so importing this module needs no renderer
    paper = paper or papers.enabled_paper()
    with open(os.path.join(plate, "region.json")) as f:
        cfg = json.load(f)
    img = render.rasterize(spec, dpi=dpi, region_dir=plate, watermark=True,
                           watermark_text="PROOF", cfg=cfg)
    img = panel_geo.paint_gaps(img, spec, dpi).convert("RGB")
    srgb = icc.srgb_profile()
    stem = orderspec.file_stem(order.title)
    work = os.path.join(order.dir, "work")
    proof_dir = os.path.join(order.dir, "out", "proof")
    files = []

    path = os.path.join(work, "proof.png")
    _save(img, path, "PNG", icc_profile=srgb)
    files.append(path)

    soft_path = os.path.join(work, "softproof.png")
    profile = icc.find_profile(paper.profile, profile_dirs)
    if profile is None:
        soft, why = None, f"{paper.profile} is not installed"
        # a soft proof of an earlier spec must not stand beside this proof
        if os.path.exists(soft_path):
            os.remove(soft_path)
    else:
        _save(icc.soft_proof(img, profile, paper.intent), soft_path, "PNG", icc_profile=srgb)
        files.append(soft_path)
        soft, why = f"{paper.profile}, {paper.intent}", None

    path = os.path.join(proof_dir, f"{stem}-proof.jpg")
    _save(img, path, "JPEG", quality=JPEG_QUALITY, icc_profile=srgb)
    files.append(path)

    path = os.path.join(proof_dir, f"{stem}-proof.pdf")
    proofpdf.write(path, img, order.title, client_lines(spec))
    files.append(path)

    return {"files": files, "soft_proof": soft, "soft_proof_why": why,
            "hash": orderspec.spec_hash(spec)}
