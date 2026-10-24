# app/orderstudio.py
"""The studio's side of an order: the list of orders, Save to order, and Approve.

Save to order writes the spec the studio proofed into the order (state.json, manual.spec)
and writes the proof files again from it. Approve records the hash of that spec in
state.json as the approval. Finish (app/orderfinish) prints only when approval_ok.

The hash is always spec_hash(order_spec(order, state)): the spec after its rebind to the
plate on disk now, computed the same way here and in Finish.

This file never imports app.main (plan decision P8). app.main imports it."""
from __future__ import annotations

import datetime
import os

from PIL.ImageCms import PyCMSError

from app import order as od
from app import orderproof, orderspec
from app.order import Order, OrderError
from app.serialize import spec_to_json

NOT_SAVED = "Save to order first: the studio's proof differs from the saved one."


def _prepared(order: Order, state: dict) -> bool:
    try:
        orderspec.plate_dir(state)
        return True
    except OrderError:
        return False


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
    files written, and the reason they were not written ("" when they were)."""
    od.set_manual(order, "spec", spec_to_json(spec))
    state = od.read_state(order)
    if state.get("approval") and not approval_ok(order, state):
        state = od.write_state(order, {"approval": None})
    try:
        written = orderproof.write_proofs(order, orderspec.order_spec(order, state),
                                          orderspec.plate_dir(state))
    except (OrderError, PyCMSError) as ex:
        return {"state": state, "proof": [], "proof_error": str(ex)}
    return {"state": state, "proof": written["files"], "proof_error": ""}


def approve(order: Order, spec) -> dict:
    """Record the approval of the saved spec. `spec` is the studio's proofed spec: it must
    be the saved one, or the approval would name a print nobody looked at. Returns the
    new state."""
    state = od.read_state(order)
    if not (state.get("manual") or {}).get("spec"):
        raise OrderError(NOT_SAVED)
    saved = orderspec.spec_hash(orderspec.order_spec(order, state))
    if orderspec.spec_hash(spec) != saved:
        raise OrderError(NOT_SAVED)
    at = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    return od.write_state(order, {"approval": {"at": at, "hash": saved}})
