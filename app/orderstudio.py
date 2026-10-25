# app/orderstudio.py
"""The studio's side of an order: the list of orders, Save to order, Approve, and the
photo controls (place, move, crop, caption, drop, the band's end).

Save to order writes the spec the studio proofed into the order (state.json, manual.spec)
and writes the proof files again from it (state.json's "proof" records them). Approve
records the hash of that spec in state.json as the approval, and only once the client
proof of that spec is written. Finish (app/orderfinish) prints only when approval_ok.

The hash is always spec_hash(order_spec(order, state)): the spec after its rebind to the
plate on disk now, computed the same way here and in Finish.

A photo edit (edit_photo) writes manual.photos[file] (or manual.band_side), clears the
approval, and runs Prepare's photo step again (orderprep.place_photos): the layout, the
frame in use and the warnings come from the one place Prepare uses. The studio never
writes a frame (manual.frame): a band proof's frame is grown from the open frame by
Prepare, so a saved frame would be grown twice.

Proof pixels are sheet inches x the proof's dpi from the trim's top-left corner: the
studio's proof PNG is the sheet with its bleed cropped off (main.proof).

This file never imports app.main (plan decision P8). app.main imports it."""
from __future__ import annotations

import dataclasses
import datetime
import json
import os
from types import SimpleNamespace

from PIL.ImageCms import PyCMSError

from app import order as od
from app import orderproof, orderspec, provenance
from app.order import Order, OrderError
from app.papers import PaperError
from app.serialize import spec_to_json
from app.spec import SpecError

PROOF_REMOVED = "The client proof files were removed; save again to write them."
NOT_SAVED = "Save to order first: the studio's proof differs from the saved one."
NOT_PRINT = ("Save to order takes a print proof, not a wallpaper: proof the order as a "
             "print, then save.")
PROOF_NOT_WRITTEN = "The client proof was not written: save again before approving."
WRONG_SIZE = "This proof is not the order's size ({why}): open the order again, proof, then save."

# the photo controls (order photos, Task 8)
PROOF_DPI = 96.0             # the studio's proof dpi for a print (main._proof_dpi)
CAPTION_MAX = 60             # the studio's marker label limit (main.set_markers)
PHOTO_KEYS = ("spot", "spot_px", "box", "crop", "caption", "dropped")
NO_PHOTO = "No photo named {file!r} in this order."
NAME_A_PHOTO = "Name a photo: only band_side changes with no file."
BAND_SIDE_ALONE = "band_side changes with no file, alone."
BAD_BAND_SIDE = 'band_side must be "top" or "bottom".'
BAD_SPOT = "spot must be {x, y}: ground metres inside the plate."
BAD_SPOT_PX = "spot_px must be {px, py}: proof pixels, finite numbers."
BAD_BOX = "box must be {dx_in, dy_in}: finite inches within the sheet, or null."
BAD_CROP = "crop must be {cx, cy}: numbers from 0 to 1, or null."
BAD_CAPTION = "caption must be text, or null."
BAD_DROPPED = "dropped must be true or false."
PLACE_FIRST = "Place {file} before moving its box."
REFRAMED_APPROVED = ("The frame differs from the approved one: save to lay the photos out "
                     "again.")


class PhotoNotFound(OrderError):
    """The request names a photo the order does not have (the route answers 404)."""


class PhotoChangeError(ValueError):
    """A malformed photo change (the route answers 422). Nothing was written."""


def _prepared(order: Order, state: dict) -> bool:
    try:
        orderspec.plate_dir(state)
        return True
    except OrderError:
        return False


def _remove_client_proofs(order: Order) -> None:
    stem = orderspec.file_stem(order.title)
    for ext in ("jpg", "pdf"):
        try:
            os.remove(os.path.join(order.dir, "out", "proof", f"{stem}-proof.{ext}"))
        except FileNotFoundError:
            pass


def _layout_stands(state: dict, crop, orderprep) -> bool:
    """The photos were laid out on `crop` (state's layout_crop). A state with no
    layout_crop (prepared before it was recorded) counts as laid out on it: its boxes
    stand until an edit lays them out again."""
    return (state.get("layout_crop") is None
            or orderprep.same_crop(state.get("layout_crop"), crop))


def approval_ok(order: Order, state: dict) -> bool:
    """True when the order has an approval whose hash is the hash of the spec Finish
    would print, and the studio saved that spec. An unreadable spec is not approved."""
    approval = state.get("approval")
    if not approval or not (state.get("manual") or {}).get("spec"):
        return False
    try:
        return approval.get("hash") == orderspec.spec_hash(orderspec.order_spec(order, state))
    except (OrderError, AttributeError, KeyError, TypeError, ValueError):
        return False


def list_orders(root=None) -> list:
    """The orders under `root` (default: the orders folder), newest folder first. A folder
    that is not an order, or whose order.toml does not load, is left out."""
    root = root or od.orders_root()
    if not os.path.isdir(root):
        return []
    rows = []
    for name in sorted(os.listdir(root), reverse=True):
        folder = os.path.join(root, name)
        if name.startswith((".", "_")) or not os.path.isfile(os.path.join(folder, "order.toml")):
            continue
        try:
            order = od.load(folder)
            state = od.read_state(order)
        except OrderError:
            continue
        rows.append({"folder": folder, "name": name, "order_number": order.order_number,
                     "title": order.title, "prepared": _prepared(order, state),
                     "approved": approval_ok(order, state)})
    return rows


def save_spec(order: Order, spec) -> dict:
    """Write `spec` into the order as the studio's saved spec, drop the approval when the
    spec's hash is not the approved one, and write the proof files again from it.

    The spec is saved before the proofs are written, so a proof that cannot be written
    never loses the save. Returns {"state", "proof", "proof_error"}: the new state, the
    files written, and the reason they were not written ("" when they were).

    A wallpaper, or a print of another size, panel count or gap than the order Prepare
    framed, is refused (OrderError) and nothing is saved: Finish would refuse it. The
    save records the order's inputs hash (manual.spec_inputs_hash), so a later Prepare
    of a changed order sets the spec aside.

    An order with photos whose saved crop is not the one its photos were laid out on
    (state's layout_crop) is laid out again on it (orderprep.place_photos) before the
    approval is compared."""
    state = od.read_state(order)
    if spec.output_kind != "print":
        raise OrderError(NOT_PRINT)
    why = orderspec.matches_order(spec, state)
    if why:
        raise OrderError(WRONG_SIZE.format(why=why))
    state = od.update_manual(order, {"spec": spec_to_json(spec),
                                     "spec_inputs_hash": state.get("inputs_hash")})
    if state.get("photos"):
        # the boxes follow the crop that prints: a frame that moved since the last layout
        # (an approved order's read-only measure leaves it) is laid out again here,
        # before the approval is compared
        from app import orderprep                        # here: it loads the build tools
        crop = orderprep.open_crop(spec)
        if not _layout_stands(state, crop, orderprep):
            state = orderprep.place_photos(order, state, log=lambda line: None, crop=crop)
    if state.get("approval") and not approval_ok(order, state):
        state = od.write_state(order, {"approval": None})
    try:
        written = orderproof.write_proofs(order, orderspec.order_spec(order, state),
                                          orderspec.plate_dir(state))
    except (OrderError, PyCMSError, PaperError, SpecError) as ex:
        # an earlier save's client files must not stand beside this save: they are not
        # this print's proof
        _remove_client_proofs(order)
        state = od.write_state(order, {"proof": None})      # approve refuses until a save writes it
        return {"state": state, "proof": [], "proof_error": f"{ex} {PROOF_REMOVED}"}
    state = od.write_state(order, {"proof": written})
    return {"state": state, "proof": written["files"], "proof_error": ""}


def approve(order: Order, spec) -> dict:
    """Record the approval of the saved spec. `spec` is the studio's proofed spec: it must
    be the saved one, or the approval would name a print nobody looked at. The client
    proof files of that spec must be written (state.json's "proof", with its hash): the
    client approves those files. Returns the new state."""
    state = od.read_state(order)
    if not (state.get("manual") or {}).get("spec"):
        raise OrderError(NOT_SAVED)
    saved = orderspec.spec_hash(orderspec.order_spec(order, state))
    if orderspec.spec_hash(spec) != saved:
        raise OrderError(NOT_SAVED)
    proof = state.get("proof")
    if not isinstance(proof, dict) or proof.get("hash") != saved:
        raise OrderError(PROOF_NOT_WRITTEN)
    at = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    return od.write_state(order, {"approval": {"at": at, "hash": saved}})


# ---- the photo controls (order photos, Task 8) ------------------------------------------

def proof_px_to_ground(spec, dpi, px, py) -> tuple:
    """A pixel of the studio's proof of `spec` at `dpi` to ground metres. The proof is the
    sheet with no bleed, so its pixel is sheet inches x dpi from the trim's top-left
    corner, y down; the inches go to the ground through the spec's crop
    (orderspec.sheet_in_to_ground, built on app/geo.py: invariant 5)."""
    return orderspec.sheet_in_to_ground(spec, float(px) / float(dpi), float(py) / float(dpi))


def ground_to_proof_px(spec, dpi, x, y) -> tuple:
    """Ground metres to a pixel of the studio's proof of `spec` at `dpi`: the inverse of
    proof_px_to_ground."""
    x_in, y_in = orderspec.ground_to_sheet_in(spec, x, y)
    return x_in * float(dpi), y_in * float(dpi)


PX_LIMIT = 1e7               # proof pixels: far past any sheet, short of float overflow


def _finite(v) -> bool:
    """A real, finite JSON number (provenance's own test: a huge integer is finite, and
    math.isfinite would raise on it)."""
    return provenance._finite_number(v)


def _plate_bounds(state: dict) -> tuple:
    with open(os.path.join(orderspec.plate_dir(state), "region.json")) as f:
        return tuple(float(v) for v in json.load(f)["bounds"])


def _bounded(state: dict, key: str, value, why: str) -> dict:
    """`value` as a box or crop the manifest door accepts (provenance.bound_photo_keys),
    or PhotoChangeError."""
    pw, ph = (float(v) for v in state["print_in"])
    hs = {key: value}
    provenance.bound_photo_keys(SimpleNamespace(print_w_in=pw, print_h_in=ph, hotspots=[hs]))
    if key not in hs:
        raise PhotoChangeError(why)
    return hs[key]


def _checked(state: dict, file: str, change, view, dpi) -> dict:
    """The change as the values manual.photos keeps (None removes a key: the photo goes
    back to Prepare's value), or PhotoChangeError / PhotoNotFound. Writes nothing."""
    if not isinstance(change, dict):
        raise PhotoChangeError("change must be a JSON object.")
    if not file:
        unknown = sorted(set(change) - {"band_side"})
        if unknown and set(unknown) <= set(PHOTO_KEYS):
            raise PhotoChangeError(NAME_A_PHOTO)
        if unknown:
            raise PhotoChangeError(f"unknown change key(s): {', '.join(unknown)}.")
        if change.get("band_side") not in orderspec.PHOTO_BAND_SIDES:
            raise PhotoChangeError(BAD_BAND_SIDE)
        return {"band_side": change["band_side"]}
    unknown = sorted(set(change) - set(PHOTO_KEYS))
    if "band_side" in unknown:
        raise PhotoChangeError(BAND_SIDE_ALONE)
    if unknown:
        raise PhotoChangeError(f"unknown change key(s): {', '.join(unknown)}.")
    photos = {p["file"]: p for p in orderspec.effective_photos(state)}
    if file not in photos:
        raise PhotoNotFound(NO_PHOTO.format(file=file))
    out = {}
    if "spot" in change and "spot_px" in change:
        raise PhotoChangeError("Send spot or spot_px, not both.")
    if "spot_px" in change:
        sp = change["spot_px"]
        if not (isinstance(sp, dict) and _finite(sp.get("px")) and _finite(sp.get("py"))
                and abs(sp["px"]) <= PX_LIMIT and abs(sp["py"]) <= PX_LIMIT):
            raise PhotoChangeError(BAD_SPOT_PX)
        x, y = proof_px_to_ground(view, dpi, sp["px"], sp["py"])
        change = {**change, "spot": {"x": x, "y": y}}
    if "spot" in change:
        spot = change["spot"]
        if spot is None:
            out["spot"] = None
        else:
            w, s, e, n = _plate_bounds(state)
            if not (isinstance(spot, dict) and _finite(spot.get("x"))
                    and _finite(spot.get("y")) and w <= spot["x"] <= e
                    and s <= spot["y"] <= n):
                raise PhotoChangeError(BAD_SPOT)
            out["spot"] = {"x": float(spot["x"]), "y": float(spot["y"])}
    for key, why in (("box", BAD_BOX), ("crop", BAD_CROP)):
        if key in change:
            out[key] = None if change[key] is None else _bounded(state, key, change[key], why)
    if "caption" in change:
        cap = change["caption"]
        if cap is not None and not isinstance(cap, str):
            raise PhotoChangeError(BAD_CAPTION)
        out["caption"] = None if cap is None else cap.strip()[:CAPTION_MAX]
    if "dropped" in change:
        if not isinstance(change["dropped"], bool):
            raise PhotoChangeError(BAD_DROPPED)
        out["dropped"] = change["dropped"]
    if out.get("box") is not None:
        p = photos[file]
        spot = out["spot"] if "spot" in out else p.get("spot")
        dropped = out.get("dropped", p.get("dropped"))
        if not spot or dropped:
            raise PhotoChangeError(PLACE_FIRST.format(file=file))
    return out


def _photo_fields(spec) -> dict:
    return {"photo_layout": spec.photo_layout, "photo_band_side": spec.photo_band_side,
            "photo_box_in": float(spec.photo_box_in)}


def view_after(order: Order, state: dict, view):
    """The spec the studio proofs next: `view` (the spec of the proof on screen) with the
    photo fields and photo hotspots the state gives now, its crop moved as Prepare moves
    its frame when the layout or the band's end changed (orderspec.crop_for_layout).
    Returns (spec, reframed)."""
    now = orderspec.order_spec(order, state)
    if view is None:
        return now, False
    crop = orderspec.crop_for_layout(view.crop, view.photo_layout, view.photo_band_side,
                                     now.photo_layout, now.photo_band_side, now)
    plain = [h for h in view.hotspots if not (isinstance(h, dict) and h.get("photo"))]
    photos = [h for h in now.hotspots if isinstance(h, dict) and h.get("photo")]
    spec = dataclasses.replace(view, crop=tuple(crop), hotspots=plain + photos,
                               **_photo_fields(now))
    return spec, tuple(crop) != tuple(view.crop)


def photo_view(order: Order, state: dict, view, dpi: float = PROOF_DPI) -> dict:
    """What the studio's photo panel shows, measured on `view` (the spec of the proof on
    screen) at `dpi`: each photo in file-name order with its spot and its box in proof
    pixels, the layout, the band's end, the box size, the sheet in proof pixels, every
    photo warning, and whether the order is approved.

    A photo's box_px is the photo square (x0, y0, x1, y1) where the poster paints it:
    its spot plus its offset, pulled inside the sheet as the renderer pulls it. Only an
    open layout has boxes; the band places its own."""
    from app import render
    dpi = float(dpi)
    sheet_w, sheet_h = float(view.print_w_in) * dpi, float(view.print_h_in) * dpi
    layout = orderspec.photo_layout(state)
    box_in = state.get("photo_box_in")
    box_in = float(box_in) if _finite(box_in) else float(view.photo_box_in)
    fs, ft, fb = render._photo_frame_fracs(view.photo_frame_style)
    edits = (state.get("manual") or {}).get("photos") or {}
    rows = []
    for p in orderspec.effective_photos(state):
        spot = p.get("spot")
        placed = bool(spot and p.get("work") and not p.get("dropped"))
        spot_px = list(ground_to_proof_px(view, dpi, spot["x"], spot["y"])) if spot else None
        box_px = None
        if layout == "open" and placed and p.get("box"):
            h, b = box_in * dpi / 2, box_in * dpi
            cx = spot_px[0] + p["box"]["dx_in"] * dpi
            cy = spot_px[1] + p["box"]["dy_in"] * dpi
            # the frame (photo + mat), pulled inside the sheet as render._draw_photos does
            fx0 = min(max(cx - h - fs * b, 0.0), max(0.0, sheet_w - (b + 2 * fs * b)))
            fy0 = min(max(cy - h - ft * b, 0.0), max(0.0, sheet_h - (b + (ft + fb) * b)))
            x0, y0 = fx0 + fs * b, fy0 + ft * b
            box_px = [x0, y0, x0 + b, y0 + b]
        edit = edits.get(p["file"]) if isinstance(edits.get(p["file"]), dict) else {}
        rows.append({"file": p["file"], "caption": p.get("caption") or "",
                     "source": p.get("source"), "spot": spot, "spot_px": spot_px,
                     "box": p.get("box"), "box_px": box_px, "crop": p.get("crop"),
                     "dropped": bool(p.get("dropped")), "placed": placed,
                     "tray": not spot and not p.get("dropped") and bool(p.get("work")),
                     "readable": bool(p.get("work")), "moved": "box" in edit,
                     "warnings": list(p.get("warnings") or [])})
    return {"photos": rows, "layout": layout, "band_side": orderspec.photo_band_side(state),
            "box_in": box_in, "dpi": dpi, "sheet_px": [sheet_w, sheet_h],
            "warnings": list(state.get("photo_warnings") or []),
            "approved": approval_ok(order, state)}


def edit_photo(order: Order, file: str, change: dict, view=None,
               dpi: float = PROOF_DPI) -> dict:
    """Apply one studio photo change and answer what the panel shows.

    `change` holds any of spot ({"x", "y"}, ground metres) or spot_px ({"px", "py"}, a
    pixel of the proof of `view` at `dpi`, made a spot with proof_px_to_ground), box
    ({"dx_in", "dy_in"}, from a drag; null lets the layout place it again), crop
    ({"cx", "cy"}), caption (text; null goes back to Prepare's) and dropped (true or
    false), for the photo named `file`. With `file` empty, it holds band_side ("top" or
    "bottom") alone, which writes manual.band_side. An empty change writes nothing and
    only answers. A box or crop is bounded as the manifest door bounds one
    (provenance.bound_photo_keys).

    An edit writes manual.photos[file] (or manual.band_side), clears the approval and
    runs orderprep.place_photos: the photos without a fixed box are laid out again, and
    a box Dom moved stays where he put it, warned when it lies over a route, the
    furniture, another box or another photo's spot. `view` is the spec of the proof on
    screen (default: order_spec); the answer is measured on it moved to the new layout.

    The layout is computed on the view's crop (orderprep.open_crop of it), the crop that
    will print, and state's layout_crop records it. Any call, the read-only one included,
    lays the photos out again when the view's crop is not layout_crop (a reframe, then a
    proof): the boxes not fixed move to the new sheet, "relaid" says so, and the studio
    proofs again. Fixed boxes never move. An approved order's read-only call writes
    nothing: it answers relaid false and a "note" (REFRAMED_APPROVED), and Save lays the
    photos out on the saved crop.

    The edit and the cleared approval are one write; a layout that then fails leaves the
    edit saved and the order unapproved.

    Returns {"edited", "relaid", "state", "view", "reframed", **photo_view}. Raises
    PhotoNotFound, PhotoChangeError (nothing written) or OrderError."""
    from app import orderprep                            # here: it loads the build tools
    state = od.read_state(order)
    orderspec.plate_dir(state)                           # Prepare first
    if view is None:
        view = orderspec.order_spec(order, state)
    crop = orderprep.open_crop(view)
    if change == {} and isinstance(change, dict):
        if _layout_stands(state, crop, orderprep) or not state.get("photos"):
            return {"edited": False, "relaid": False, "state": state, "view": view,
                    "reframed": False, **photo_view(order, state, view, dpi)}
        if approval_ok(order, state):
            # an approved order is never relaid by a look: the next save lays it out
            return {"edited": False, "relaid": False, "state": state, "view": view,
                    "reframed": False, "note": REFRAMED_APPROVED,
                    **photo_view(order, state, view, dpi)}
        state = orderprep.place_photos(order, state, log=lambda line: None, crop=crop)
        spec, reframed = view_after(order, state, view)
        return {"edited": False, "relaid": True, "state": state, "view": spec,
                "reframed": reframed, **photo_view(order, state, spec, dpi)}
    values = _checked(state, file, change, view, dpi)
    if file:
        photos = dict((state.get("manual") or {}).get("photos") or {})
        entry = dict(photos.get(file) or {})
        for key, value in values.items():
            if value is None:
                entry.pop(key, None)
            else:
                entry[key] = value
        if entry:
            photos[file] = entry
        else:
            photos.pop(file, None)
        values = {"photos": photos}
    # an edit is a new print: the approval goes in the same write as the edit
    state = od.update_manual(order, values, {"approval": None})
    state = orderprep.place_photos(order, state, log=lambda line: None, crop=crop)
    spec, reframed = view_after(order, state, view)
    return {"edited": True, "relaid": False, "state": state, "view": spec,
            "reframed": reframed, **photo_view(order, state, spec, dpi)}
