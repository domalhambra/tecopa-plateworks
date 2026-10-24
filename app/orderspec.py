# app/orderspec.py
"""One spec for an order. The proof Prepare writes, the studio's Open, Save and Approve,
and the print TIFFs Finish writes all paint the spec that order_spec returns, so the
proof the client approves is the print.

order_spec is the saved spec (state["manual"]["spec"], written by the studio's Save to
order) when there is one, else the default spec: the framing Prepare made, in the
look of a new poster. Either way the spec is bound to the plate that is on disk now.

The approval hash is always spec_hash(order_spec(order, state)), the hash of the spec
after that rebind. spec_hash hashes the spec it is given and nothing else.

This file never imports app.main (it starts queues, caches and region discovery). It
imports app.orderpreview only inside default_spec: orderpreview takes ORDER_LOOK from
here."""
from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import re

from app.credit import credit_text
from app.order import Order, OrderError
from app.regionbuild import slugify
from app.serialize import spec_from_json, spec_to_json
from app.spec import CompositionSpec

# the look of a new poster in the studio (the defaults in app/static/store.js)
ORDER_LOOK = dict(soft_light=0.35, haze_strength=0.15, water_depth=0.5,
                  label_place="smart", track_weave=True)
SEED = 7                    # the same seed the size preview draws with
NO_PLATE = "Run Prepare first: work/state.json has no plate."
SIZE_TOL = 1e-6             # inches: a size read back from JSON is the same size


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
    return CompositionSpec(
        region_id=cfg["id"], crs=cfg["crs"], crop=tuple(state["frame"]),
        print_w_in=state["print_in"][0], print_h_in=state["print_in"][1],
        native_resolution_m=cfg["native_resolution_m"],
        tracks=[t.coords for t in tracks], track_days=[t.day for t in tracks],
        hotspots=[], seed=SEED, title_text=order.title,
        credit_text=credit_text(path),      # as the studio's proof derives it
        labels=os.path.isfile(os.path.join(path, "labels.json")),
        panels=state["panels"], panel_gap_in=state["gap"], **ORDER_LOOK)


def order_spec(order: Order, state: dict) -> CompositionSpec:
    """The spec to paint: the saved one if the studio saved one, else the default.
    Its region_id and native_resolution_m follow the plate on disk now, so a plate
    Prepare rebuilt after the save is the plate that is painted. A saved spec in another
    projection than that plate is refused: its crop is in the old metres."""
    saved = (state.get("manual") or {}).get("spec")
    if saved:
        _, cfg = _region_config(state)
        if saved.get("crs") != cfg["crs"]:
            raise OrderError("The plate's projection changed since the studio save: "
                             "run Prepare, then open the order and redo the edits.")
        spec = spec_from_json(saved)
        return dataclasses.replace(spec, region_id=cfg["id"], crs=cfg["crs"],
                                   native_resolution_m=cfg["native_resolution_m"])
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
