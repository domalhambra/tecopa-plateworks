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
(P6).

Every check that needs no picture runs before the render: the approval, the spec's size,
panels and gap against state.json (orderspec.matches_order), bleed, the roll, and every
hotspot photo still readable. Then the files go in place in four steps, so a failed run
keeps the files of the last run:

  1. write every file (the TIFFs, record.png, PRINT.txt) under a temporary name;
  2. rename the TIFFs and record.png to their names;
  3. remove each print file of an earlier Finish that this Finish did not write, so the
     folder holds one print and no other;
  4. rename PRINT.txt.

A failure in step 1 deletes the temporary files and leaves the last run untouched. Each
file step 3 removes gets a `Removed: <name>` line in the log and at the end of PRINT.txt.

This module never imports app.main (plan decision P8)."""
from __future__ import annotations

import json
import os

from app import icc, orderspec, orderstudio, panels as panel_geo, papers, provenance
from app import order as od
from app.order import OrderError
from app.orderproof import size_key

NOT_APPROVED = "Approve the proof in the studio first."
CHANGED = "The order changed after approval: approve it again."
SIZE_MISMATCH = ("The saved studio spec is not this order's size: open the order, proof, "
                 "save and approve again.")
BLEED = ("The render is {have[0]} × {have[1]} px and the print is {want[0]} × {want[1]} px: "
         "a print with bleed cannot go to the roll as it is.")
PHOTOS_GONE = ("{n} photo(s) on the approved proof can no longer be read: open the order, "
               "attach them again, save and approve.")
NOT_PLACED = "The print files cannot be put in place ({why}): run Finish again."
NOT_REMOVED = ("The print file of an earlier Finish cannot be removed: {name} ({why}). "
               "Remove it, then run Finish again.")

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


def _tmp_name(path: str) -> str:
    return f"{path}.{os.getpid()}.tmp"


def _why(ex: BaseException) -> str:
    return (ex.strerror if isinstance(ex, OSError) and ex.strerror else str(ex)) or \
        type(ex).__name__


def _stage(path: str, write) -> str:
    """Write a file under its temporary name with `write(tmp)`, and return that name.
    On a failure the temporary file is deleted and an OSError becomes an OrderError."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = _tmp_name(path)
    try:
        write(tmp)
    except BaseException as ex:
        _discard([tmp])
        if isinstance(ex, OSError):
            raise OrderError(f"The print file cannot be written to {path}: "
                             f"{_why(ex)}") from ex
        raise
    return tmp


def _discard(tmps) -> None:
    for tmp in tmps:
        try:
            os.remove(tmp)
        except OSError:
            pass


def _photo_count(spec) -> int:
    return sum(1 for hs in spec.hotspots or [] if isinstance(hs, dict) and hs.get("photo"))


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
    # every check that needs no picture comes before the render
    if orderspec.matches_order(spec, state):
        raise OrderError(SIZE_MISMATCH)
    dpi = spec.final_dpi() if dpi is None else dpi
    want = (round(spec.print_w_in * dpi), round(spec.print_h_in * dpi))
    if spec.pixel_size(dpi) != want:
        raise OrderError(BLEED.format(have=spec.pixel_size(dpi), want=want))
    pw, ph = panel_geo.panel_size_in(spec)
    rotation = papers.feed_rotation(pw, ph, paper.roll_in)
    photos = _photo_count(spec)
    spec = provenance.build_final_spec(spec, max(24, round(spec.photo_box_in * dpi)))
    if _photo_count(spec) < photos:       # build_final_spec drops a photo it cannot read
        raise OrderError(PHOTOS_GONE.format(n=photos - _photo_count(spec)))
    plate = orderspec.plate_dir(state)
    with open(os.path.join(plate, "region.json")) as f:
        cfg = json.load(f)

    log(f"Painting {order.title} at {_inches(dpi)} ppi ...")
    sheet = render.rasterize(spec, dpi=dpi, region_dir=plate, watermark=False, cfg=cfg)
    sheet = sheet.convert("RGB")
    if sheet.size != want:
        raise OrderError(BLEED.format(have=sheet.size, want=want))
    srgb = icc.srgb_profile()
    manifest = provenance.build_manifest(
        spec, region_pack=provenance.region_pack_block(
            plate, labels=spec.labels, biome=spec.biome, dry_lakes=spec.dry_lakes))

    # the pieces: a set is cut at its panels (the gap strips are dropped), a sheet is one
    parts = panel_geo.cut(sheet, spec, dpi) if panel_geo.is_set(spec) else [sheet]
    count = len(parts)
    stem, size = orderspec.file_stem(order.title), _size_word(spec)
    print_dir = os.path.join(order.dir, *PRINT_DIR)
    note_path = os.path.join(print_dir, NOTE_NAME)

    # 1. every file under a temporary name; a failure leaves the last run untouched
    files, pieces, staged = [], [], []        # staged: (temporary name, final name)
    try:
        for k, part in enumerate(parts, 1):
            if rotation:
                part = part.rotate(rotation, expand=True)
            name = f"{stem}-{size}-{k}of{count}.tif" if count > 1 else f"{stem}-{size}.tif"
            path = os.path.join(print_dir, name)
            staged.append((_stage(path, lambda tmp, part=part: part.save(
                tmp, "TIFF", compression=None, dpi=(dpi, dpi), icc_profile=srgb)), path))
            files.append(path)
            w_in, h_in = (ph, pw) if rotation else (pw, ph)
            pieces.append({"name": name, "w_in": w_in, "h_in": h_in, "w_px": part.width,
                           "h_px": part.height, "ppi": dpi, "rotation": rotation,
                           "panel": (k, count) if count > 1 else None})
        record = os.path.join(order.work_dir, RECORD_NAME)
        staged.append((_stage(record, lambda tmp: sheet.save(
            tmp, "PNG", dpi=(dpi, dpi), icc_profile=srgb,
            pnginfo=provenance.manifest_pnginfo(manifest))), record))
        # a print file of an earlier Finish (another title or size) must not stand
        # beside this one
        removed = [name for name in sorted(os.listdir(print_dir))
                   if name.lower().endswith(".tif")
                   and os.path.join(print_dir, name) not in files]
        note = print_note(order, spec, paper, pieces, approval, removed)

        def write_note(tmp):
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(note)
        note_tmp = _stage(note_path, write_note)
    except BaseException:
        _discard(tmp for tmp, _ in staged)
        raise

    # 2. the TIFFs and record.png to their names
    for i, (tmp, path) in enumerate(staged):
        try:
            os.replace(tmp, path)
        except OSError as ex:
            _discard([t for t, _ in staged[i:]] + [note_tmp])
            raise OrderError(NOT_PLACED.format(why=_why(ex))) from ex
        if path in files:
            log(f"Wrote {path}")

    # 3. the print files of an earlier Finish
    for name in removed:
        try:
            os.remove(os.path.join(print_dir, name))
        except FileNotFoundError:
            pass
        except OSError as ex:
            _discard([note_tmp])
            raise OrderError(NOT_REMOVED.format(name=name, why=_why(ex))) from ex
        log(f"Removed: {name}")

    # 4. the note that names them all
    try:
        os.replace(note_tmp, note_path)
    except OSError as ex:
        _discard([note_tmp])
        raise OrderError(NOT_PLACED.format(why=_why(ex))) from ex
    return {"files": files, "print_note": note_path}
