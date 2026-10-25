# app/orderspec.py
"""One spec for an order. The proof Prepare writes, the studio's Open, Save and Approve,
and the print TIFFs Finish writes all paint the spec that order_spec returns, so the
proof the client approves is the print.

order_spec is the saved spec (state["manual"]["spec"], written by the studio's Save to
order) when there is one, else the default spec: the framing Prepare made, in the
look of a new poster. Either way the spec is bound to the plate that is on disk now.

The approval hash is always spec_hash(order_spec(order, state)), the hash of the spec
after that rebind. spec_hash hashes the spec it is given and nothing else.

An order's photos belong to its state, never to a saved spec (ruling RB1): state.json's
"photos" (what Prepare found) with "manual.photos" (the studio's edits) over them, field
by field. Both specs take their photo hotspots, photo_layout, photo_band_side and
photo_box_in from there, so an edit reaches the proof, the approval hash and the print.
An order with no photos keeps the spec it always had.

This file never imports app.main (it starts queues, caches and region discovery). It
imports app.orderpreview only inside default_spec: orderpreview takes ORDER_LOOK from
here."""
from __future__ import annotations

import dataclasses
import hashlib
import json
import math
import os
import re
from types import SimpleNamespace

from app import geo, provenance
from app.credit import credit_text
from app.order import Order, OrderError
from app.panels import PANEL_LONG_IN, PANEL_SHORT_IN
from app.regionbuild import slugify
from app.serialize import spec_from_json, spec_to_json
from app.spec import PHOTO_BAND_SIDES, PHOTO_LAYOUTS, CompositionSpec

# the look of a new poster in the studio (the defaults in app/static/store.js)
ORDER_LOOK = dict(soft_light=0.35, haze_strength=0.15, water_depth=0.5,
                  label_place="smart", track_weave=True)
SEED = 7                    # the same seed the size preview draws with
NO_PLATE = "Run Prepare first: work/state.json has no plate."
SIZE_TOL = 1e-6             # inches: a size read back from JSON is the same size
# B6: a photo box's long edge is 2.25 in on a 12 x 18 (216 sq in) and scales with the
# square root of the sheet's area, or one panel's for a set
PHOTO_BOX_REF_IN = 2.25
PHOTO_BOX_REF_AREA = 216.0
_SPEC_DEFAULTS = {f.name: f.default for f in dataclasses.fields(CompositionSpec)}


def photo_box_in(print_in, panels: int = 1) -> float:
    """The photo box's long edge in inches for a print of `print_in` (width, height), or
    for one panel of a set (B6): 2.09 on 11 x 17, 2.25 on 12 x 18, 2.96 on 17 x 22."""
    area = (PANEL_SHORT_IN * PANEL_LONG_IN if panels > 1
            else float(print_in[0]) * float(print_in[1]))
    return round(PHOTO_BOX_REF_IN * math.sqrt(area / PHOTO_BOX_REF_AREA), 2)


def band_height_for(box_in: float) -> float:
    """The photo band's height in inches for a box of `box_in`, in the order look's frame
    style and caption size (render.band_height_in): what Prepare grows a frame by (B2)."""
    from app import render       # here: Prepare loads the renderer only when it has photos
    return render.band_height_in(SimpleNamespace(
        photo_frame_style=_SPEC_DEFAULTS["photo_frame_style"], photo_box_in=box_in,
        label_pt=_SPEC_DEFAULTS["label_pt"]))


def crop_for_layout(crop, from_layout, from_side, to_layout, to_side, spec) -> tuple:
    """`crop`, framed for photos in `from_layout` (and `from_side` when that is the band),
    moved to `to_layout` / `to_side` the way Prepare moves its frame (B2): open to band
    grows toward the band's side, band to open shrinks back, a side swap moves the growth
    to the other end, anything else is the crop as it is. The band's height is Prepare's
    (band_height_for at spec.photo_box_in), and the math is orderplate's band_frame and
    unband_frame, so a saved studio crop and Prepare's frame cannot drift apart. Keeps
    Dom's framing, and the band never covers the map he framed."""
    from app.orderplate import band_frame, unband_frame
    crop = tuple(crop)
    was = (from_layout, from_side) if from_layout == "band" else ("open", None)
    now = (to_layout, to_side) if to_layout == "band" else ("open", None)
    if was == now:
        return crop
    ph, bh = float(spec.print_h_in), band_height_for(float(spec.photo_box_in))
    if was[0] == "band":
        crop = unband_frame(crop, ph, bh, was[1])
    if now[0] == "band":
        crop = band_frame(crop, ph, bh, now[1])
    return tuple(crop)


def _sheet_geo(spec) -> geo.RegionGeo:
    """The spec's crop window as a geo.RegionGeo whose "overview" is the sheet in inches,
    so geo.py's crop window math is the one coordinate source (invariant 5)."""
    return geo.RegionGeo(crs=spec.crs, bounds=tuple(spec.crop),
                         overview_size=(float(spec.print_w_in), float(spec.print_h_in)))


def ground_to_sheet_in(spec, x, y) -> tuple:
    """Ground metres (the plate's CRS) to inches on the sheet, from its top-left corner
    (the trim's corner), y down. The crop's corners are the sheet's corners."""
    px, py = geo.crs_to_overview_px(_sheet_geo(spec), x, y)
    return float(px), float(py)


def sheet_in_to_ground(spec, x_in, y_in) -> tuple:
    """Inches on the sheet (from its top-left corner, y down) to ground metres: the
    inverse of ground_to_sheet_in."""
    x, y = geo.overview_px_to_crs(_sheet_geo(spec), x_in, y_in)
    return float(x), float(y)


def _finite(v) -> bool:
    return (not isinstance(v, bool) and isinstance(v, (int, float))
            and math.isfinite(v))


def effective_photos(state: dict) -> list:
    """state.json's photos with the studio's edits (manual.photos, keyed by file name)
    over them, field by field: spot (its source becomes "manual"), box, crop, caption and
    dropped. The box, crop and source are then bounded as a manifest's are
    (provenance.bound_photo_keys); a malformed one is None. A spot that is not two
    finite numbers, a caption that is not text and a dropped that is not true or false
    are ignored. Returns new dicts; the state is not changed."""
    edits = ((state.get("manual") or {}).get("photos")) or {}
    out = []
    for entry in state.get("photos") or []:
        if not isinstance(entry, dict):
            continue
        p = dict(entry)
        edit = edits.get(p.get("file")) if isinstance(edits, dict) else None
        if isinstance(edit, dict):
            spot = edit.get("spot")
            if (isinstance(spot, dict) and _finite(spot.get("x"))
                    and _finite(spot.get("y"))):
                p["spot"] = {"x": float(spot["x"]), "y": float(spot["y"])}
                p["source"] = "manual"
            if isinstance(edit.get("caption"), str):
                p["caption"] = edit["caption"]
            if isinstance(edit.get("dropped"), bool):
                p["dropped"] = edit["dropped"]
            for key in ("box", "crop"):
                if key in edit:
                    p[key] = edit[key]
        out.append(p)
    try:
        pw, ph = (float(v) for v in state["print_in"])
    except (KeyError, TypeError, ValueError):
        pw = ph = 0.0                    # no sheet to bound against: every box goes
    provenance.bound_photo_keys(SimpleNamespace(print_w_in=pw, print_h_in=ph, hotspots=out))
    for p in out:
        for key in ("box", "crop", "source"):
            p.setdefault(key, None)
    return out


def photo_layout(state: dict) -> str:
    v = state.get("photo_layout")
    return v if v in PHOTO_LAYOUTS else "open"


def photo_band_side(state: dict) -> str:
    """The band's end: Dom's choice in the studio (manual.band_side) first, then the side
    Prepare wrote (order.toml's), then "top"."""
    v = (state.get("manual") or {}).get("band_side")
    if v in PHOTO_BAND_SIDES:
        return v
    v = state.get("photo_band_side")
    return v if v in PHOTO_BAND_SIDES else "top"


def photo_hotspots(order: Order, state: dict) -> list:
    """One hotspot per placed photo that is not dropped and has a work JPEG, in file-name
    order: {"x", "y", "weight": 1, "label": caption, "photo": the work JPEG's absolute
    path, "box", "crop", "source"}. The photo is always the order folder's own copy, never
    the engine's uploads/. A band photo carries no box: the band places it."""
    band = photo_layout(state) == "band"
    out = []
    for p in effective_photos(state):
        spot = p.get("spot")
        if p.get("dropped") or not isinstance(spot, dict) or not p.get("work"):
            continue
        hs = {"x": spot["x"], "y": spot["y"], "weight": 1, "label": p.get("caption") or "",
              "photo": os.path.join(order.dir, p["work"])}
        for key in ("box", "crop", "source"):
            if p.get(key) is not None and not (key == "box" and band):
                hs[key] = p[key]
        out.append(hs)
    return out


def _photo_fields(order: Order, state: dict) -> dict | None:
    """The spec fields an order's photos own, or None for an order with no photos (its
    spec is then the one it always was)."""
    if not state.get("photos"):
        return None
    box = state.get("photo_box_in")
    if not _finite(box) or box <= 0:
        box = photo_box_in(state["print_in"], int(state.get("panels", 1)))
    return {"hotspots": photo_hotspots(order, state), "photo_layout": photo_layout(state),
            "photo_band_side": photo_band_side(state), "photo_box_in": float(box)}


def plate_dir(state: dict) -> str:
    """The folder of the plate that Prepare chose, from state.json."""
    plate = state.get("plate")
    try:
        path = os.path.join(plate["root"], plate["id"])
    except (TypeError, KeyError):
        raise OrderError(NO_PLATE) from None
    if not os.path.isfile(os.path.join(path, "region.json")):
        raise OrderError(NO_PLATE)
    return path


def _region_config(state: dict) -> tuple:
    path = plate_dir(state)
    with open(os.path.join(path, "region.json")) as f:
        return path, json.load(f)


def default_spec(order: Order, state: dict) -> CompositionSpec:
    """The spec of the order as Prepare framed it, built as orderpreview.render_maps
    builds one for a size."""
    from app.orderpreview import load_tracks_m
    path, cfg = _region_config(state)
    tracks = load_tracks_m(order.payloads(), state["epsg"])
    photos = _photo_fields(order, state) or {"hotspots": []}
    spec = CompositionSpec(
        region_id=cfg["id"], crs=cfg["crs"], crop=tuple(state["frame"]),
        print_w_in=state["print_in"][0], print_h_in=state["print_in"][1],
        native_resolution_m=cfg["native_resolution_m"],
        tracks=[t.coords for t in tracks], track_days=[t.day for t in tracks],
        seed=SEED, title_text=order.title,
        credit_text=credit_text(path),      # as the studio's proof derives it
        labels=os.path.isfile(os.path.join(path, "labels.json")),
        panels=state["panels"], panel_gap_in=state["gap"], **photos, **ORDER_LOOK)
    return provenance.bound_photo_keys(spec)


def order_spec(order: Order, state: dict) -> CompositionSpec:
    """The spec to paint: the saved one if the studio saved one, else the default.
    Its region_id and native_resolution_m follow the plate on disk now, so a plate
    Prepare rebuilt after the save is the plate that is painted. A saved spec in another
    projection than that plate is refused: its crop is in the old metres.

    An order with photos (RB1): the saved spec's photo hotspots, photo_layout,
    photo_band_side and photo_box_in are replaced with the ones the photo state gives
    now; its hotspots that carry no photo (a plain marker) stay, ahead of the photos.
    When the layout or the band's side changed, its crop moves with them as Prepare's
    frame does (crop_for_layout), so the band never covers the saved framing."""
    saved = (state.get("manual") or {}).get("spec")
    if saved:
        _, cfg = _region_config(state)
        if saved.get("crs") != cfg["crs"]:
            raise OrderError("The plate's projection changed since the studio save: "
                             "run Prepare, then open the order and redo the edits.")
        spec = spec_from_json(saved)
        spec = dataclasses.replace(spec, region_id=cfg["id"], crs=cfg["crs"],
                                   native_resolution_m=cfg["native_resolution_m"])
        photos = _photo_fields(order, state)
        if photos is None:
            return spec
        plain = [hs for hs in spec.hotspots
                 if not (isinstance(hs, dict) and hs.get("photo"))]
        was = (spec.photo_layout, spec.photo_band_side)
        spec = dataclasses.replace(spec, **{**photos,
                                            "hotspots": plain + photos["hotspots"]})
        spec = dataclasses.replace(spec, crop=crop_for_layout(
            spec.crop, *was, spec.photo_layout, spec.photo_band_side, spec))
        return provenance.bound_photo_keys(spec)
    return default_spec(order, state)


def _size_words(w, h, panels, gap) -> str:
    return f"{w:g} x {h:g} in, {panels} panel(s), {gap:g} in gap"


def matches_order(spec: CompositionSpec, state: dict) -> str | None:
    """None when `spec` is the print Prepare framed: the print size, panel count and gap
    in state.json. Else the difference in words. A state.json from before sets has no
    panels or gap: it is a single sheet. Save to order and Finish both ask this."""
    try:
        want = (float(state["print_in"][0]), float(state["print_in"][1]),
                int(state.get("panels", 1)), float(state.get("gap", 0.0)))
    except (KeyError, IndexError, TypeError, ValueError):
        return "work/state.json names no print size: run Prepare first"
    have = (float(spec.print_w_in), float(spec.print_h_in), int(spec.panels),
            float(spec.panel_gap_in))
    if all(abs(a - b) <= SIZE_TOL for a, b in zip(have, want)):
        return None
    return f"the spec is {_size_words(*have)}; the order is {_size_words(*want)}"


def spec_hash(spec: CompositionSpec) -> str:
    """sha256 hex of the spec's canonical JSON."""
    text = json.dumps(spec_to_json(spec), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode()).hexdigest()


def file_stem(title: str) -> str:
    """The name of an order's files: the title's slug, or "poster" when the title has
    no letter or digit to make one of."""
    if not re.search(r"[a-z0-9]", (title or "").lower()):
        return "poster"
    return slugify(title)
