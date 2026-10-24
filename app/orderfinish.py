# app/orderfinish.py
"""Finish: the approved spec of an order as print TIFFs for the 17 in roll, and the note
that tells Dom how to print them.

Finish prints only what the client approved. It refuses an order with no approval, and an
order whose spec changed after the approval (orderstudio.approval_ok). It paints the one
spec the proof showed (orderspec.order_spec), once, with no watermark, and writes:

  out/print/<stem>-<size>.tif          one file for a single sheet
  out/print/<stem>-<size>-<k>of<n>.tif one file for each panel of a set (the gap strips
                                       are never printed)
  out/print/PRINT.txt                  the paper, profile, intent, preset and each file
  work/record.png                      the unrotated render with the reprint manifest

Each TIFF is the print at exactly its size (no border: plan decision P5), 8-bit RGB
(P4), uncompressed, sRGB profile embedded, turned so the 17 in side goes across the roll
(P6). It writes nothing until the render has succeeded, and it removes a print file of an
earlier Finish that this Finish did not write, so the folder holds one print and no other. Each file it removes gets a
`Removed: <name>` line in its log and at the end of PRINT.txt.

This module never imports app.main (plan decision P8)."""
from __future__ import annotations

import json
import os

from PIL import Image

from app import icc, orderspec, orderstudio, panels as panel_geo, papers, provenance
from app import order as od
from app.order import OrderError
from app.orderproof import size_key

NOT_APPROVED = "Approve the proof in the studio first."
CHANGED = "The order changed after approval: approve it again."

PRINT_DIR = ("out", "print")
NOTE_NAME = "PRINT.txt"
RECORD_NAME = "record.png"


def _inches(value: float) -> str:
    return f"{value:g}"


def _size_word(spec) -> str:
    """The <size> in a file name: the order's size key (11x17, 17x22, two, three)."""
    key = size_key(spec)
    if key is not None:
        return key
    short, long_ = sorted((float(spec.print_w_in), float(spec.print_h_in)))
    return f"{_inches(short)}x{_inches(long_)}"


def _save(img, path: str, fmt: str, **kw) -> None:
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
            raise OrderError(f"The print file cannot be written to {path}: "
                             f"{ex.strerror or ex}") from ex
        raise


def print_note(order, spec, paper, pieces, approval, removed=()) -> str:
    """The text of PRINT.txt. `pieces` is one dict for each file, in hang order:
    name, w_in and h_in (the file's size), w_px and h_px, ppi, rotation (0 or 90) and
    panel ((k, n) for a set, else None). `removed` names each .tif that Finish removed
    from the folder; the note ends with a line for each."""
    number = order.order_number or os.path.basename(os.path.normpath(order.dir))
    roll = _inches(paper.roll_in)
    at = approval.get("at", "")
    digest = str(approval.get("hash", ""))[:12]
    lines = [
        "Tecopa Plateworks print note",
        f"Order: {number} · {order.title}",
        f"Paper: {paper.name}, {roll} in roll",
        f"Profile: {paper.profile}",
        f"Intent: {paper.intent}",
        f"Preset: {paper.preset}",
        "Print at 100 %, centred, from Canon Professional Print & Layout.",
        f"Approved: {at}, hash {digest}",
    ]
    for p in pieces:
        lines += ["", f"File: {p['name']}",
                  f"  Size: {_inches(p['w_in'])} × {_inches(p['h_in'])} in, "
                  f"{p['w_px']} × {p['h_px']} px at {_inches(p['ppi'])} ppi"]
        if p["rotation"]:
            lines.append(f"  Feed: rotated {p['rotation']}° counter-clockwise, the {roll} in "
                         f"side across the roll; the map's top is on the left")
        else:
            lines.append(f"  Feed: as it is, the {roll} in side across the roll")
        if p["panel"]:
            lines.append(f"  Panel: {p['panel'][0]} of {p['panel'][1]}")
    if panel_geo.is_set(spec):
        lines += ["", f"Hang: panels 1 to {spec.panels}, left to right, with a "
                      f"{_inches(spec.panel_gap_in)} in gap"]
    if removed:
        lines.append("")
        lines += [f"Removed: {name}" for name in removed]
    return "\n".join(lines) + "\n"


def finish(order_dir: str, log=print, dpi: float | None = None) -> dict:
    """Write the print files of the approved order in `order_dir`. `dpi` is None for the
    print resolution (spec.final_dpi()); a test passes a small one. Returns
    {"files": [...], "print_note": path}."""
    order = od.load(order_dir)
    state = od.read_state(order)
    approval = state.get("approval")
    if not approval:
        raise OrderError(NOT_APPROVED)
    if not orderstudio.approval_ok(order, state):
        raise OrderError(CHANGED)
    from app import render           # here, so importing this module needs no renderer
    paper = papers.enabled_paper()
    spec = orderspec.order_spec(order, state)
    dpi = spec.final_dpi() if dpi is None else dpi
    spec = provenance.build_final_spec(spec, max(24, round(spec.photo_box_in * dpi)))
    plate = orderspec.plate_dir(state)
    with open(os.path.join(plate, "region.json")) as f:
        cfg = json.load(f)

    log(f"Painting {order.title} at {_inches(dpi)} ppi ...")
    sheet = render.rasterize(spec, dpi=dpi, region_dir=plate, watermark=False, cfg=cfg)
    sheet = sheet.convert("RGB")
    want = (round(spec.print_w_in * dpi), round(spec.print_h_in * dpi))
    if sheet.size != want:
        raise OrderError(f"The render is {sheet.size[0]} × {sheet.size[1]} px and the print "
                         f"is {want[0]} × {want[1]} px: a print with bleed cannot go to "
                         f"the roll as it is.")
    srgb = icc.srgb_profile()
    manifest = provenance.build_manifest(
        spec, region_pack=provenance.region_pack_block(
            plate, labels=spec.labels, biome=spec.biome, dry_lakes=spec.dry_lakes))

    # the pieces: a set is cut at its panels (the gap strips are dropped), a sheet is one
    parts = panel_geo.cut(sheet, spec, dpi) if panel_geo.is_set(spec) else [sheet]
    count = len(parts)
    pw, ph = panel_geo.panel_size_in(spec)
    rotation = papers.feed_rotation(pw, ph, paper.roll_in)
    stem, size = orderspec.file_stem(order.title), _size_word(spec)
    print_dir = os.path.join(order.dir, *PRINT_DIR)

    files, pieces = [], []
    for k, part in enumerate(parts, 1):
        if rotation:
            part = part.rotate(rotation, expand=True)
        name = f"{stem}-{size}-{k}of{count}.tif" if count > 1 else f"{stem}-{size}.tif"
        path = os.path.join(print_dir, name)
        _save(part, path, "TIFF", compression=None, dpi=(dpi, dpi), icc_profile=srgb)
        files.append(path)
        w_in, h_in = (ph, pw) if rotation else (pw, ph)
        pieces.append({"name": name, "w_in": w_in, "h_in": h_in, "w_px": part.width,
                       "h_px": part.height, "ppi": dpi, "rotation": rotation,
                       "panel": (k, count) if count > 1 else None})
        log(f"Wrote {path}")

    _save(sheet, os.path.join(order.work_dir, RECORD_NAME), "PNG", dpi=(dpi, dpi),
          icc_profile=srgb, pnginfo=provenance.manifest_pnginfo(manifest))

    # a print file of an earlier Finish (another title or size) must not stand beside this one
    removed = []
    for name in sorted(os.listdir(print_dir)):
        if name.lower().endswith(".tif") and os.path.join(print_dir, name) not in files:
            os.remove(os.path.join(print_dir, name))
            removed.append(name)
            log(f"Removed: {name}")

    note_path = os.path.join(print_dir, NOTE_NAME)
    note = print_note(order, spec, paper, pieces, approval, removed)
    tmp = f"{note_path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(note)
    os.replace(tmp, note_path)
    return {"files": files, "print_note": note_path}
