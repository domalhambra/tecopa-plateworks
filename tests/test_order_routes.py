# tests/test_order_routes.py
# The order studio's routes: GET /api/orders, POST /api/order/open, /save and /approve.
# Open puts an order's plate and spec in the studio, Save to order writes the spec the
# studio proofed into the order, and Approve records the hash Finish checks. The plate is
# the synthetic Lassen mirror (order_with_plate in tests/conftest.py); the studio's proof
# is the real /api/proof over it.
import json
import os

import pytest
from fastapi.testclient import TestClient

from app import order as od
from app import orderspec, orderstudio, session
from app.main import app

SPEC_KEYS = {"session", "region", "name", "overview", "tracks", "hotspots", "starter_crop",
             "prefill", "proof_form", "edition", "files", "final_dpi"}


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def order(order_with_plate):
    return order_with_plate


def _form(proof_form):
    # the way a form sends it: a boolean is "true" or "false"
    return {k: ("true" if v else "false") if isinstance(v, bool) else v
            for k, v in proof_form.items()}


def _open(client, order):
    r = client.post("/api/order/open", data={"folder": order.dir})
    assert r.status_code == 200, r.text
    return r.json()


def _proof(client, opened, **changes):
    """The studio's proof of the opened order: its own proof_form and starter crop,
    with `changes` (a new title, say) on top."""
    crop = dict(zip(("x0", "y0", "x1", "y1"), opened["starter_crop"]))
    r = client.post("/api/proof", data={"session_id": opened["session"], **crop,
                                        **_form(opened["proof_form"]), **changes})
    assert r.status_code == 200, r.text


def _post(client, route, opened):
    return client.post(f"/api/order/{route}", data={"session_id": opened["session"]})


def test_open_save_approve_round_trip(client, order):
    opened = _open(client, order)
    assert SPEC_KEYS <= set(opened)
    assert opened["order"] == {"folder": os.path.realpath(order.dir),
                               "title": "Smith home ground", "approved": False}
    assert opened["prefill"]["title"] == "Smith home ground"
    _proof(client, opened)

    saved = _post(client, "save", opened)
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["saved"] is True and body["approved"] is False
    assert any(p.endswith("-proof.pdf") for p in body["proof"])
    assert all(os.path.isfile(p) for p in body["proof"])
    state = od.read_state(order)
    assert state["manual"]["spec"]["title_text"] == "Smith home ground"

    approved = _post(client, "approve", opened)
    assert approved.status_code == 200, approved.text
    assert set(approved.json()) == {"approved", "at"} and approved.json()["approved"] is True
    state = od.read_state(order)
    assert state["approval"]["hash"] == orderspec.spec_hash(orderspec.order_spec(order, state))
    assert state["approval"]["at"] == approved.json()["at"]
    assert orderstudio.approval_ok(order, state)
    # the next Open shows it
    assert _open(client, order)["order"]["approved"] is True


def test_open_registers_the_orders_plate(client, order):
    from app.main import REGIONS
    plate = od.read_state(order)["plate"]["id"]
    REGIONS.pop(plate, None)
    try:
        opened = _open(client, order)
        assert opened["region"] == plate and plate in REGIONS
        assert session.get(opened["session"])["order_dir"] == os.path.realpath(order.dir)
    finally:
        REGIONS.pop(plate, None)


def test_open_refuses_a_folder_outside_the_orders_root(client, order, tmp_path):
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (outside / "order.toml").write_text('title = "Not here"\n')
    assert client.post("/api/order/open", data={"folder": str(outside)}).status_code == 404
    # a .. that leaves the root, and a symlink inside the root that points out of it
    dotdot = os.path.join(od.orders_root(), "..", "elsewhere")
    assert client.post("/api/order/open", data={"folder": dotdot}).status_code == 404
    link = os.path.join(od.orders_root(), "2026-10-002-link")
    os.symlink(str(outside), link)
    assert client.post("/api/order/open", data={"folder": link}).status_code == 404
    # the root itself is not an order
    assert client.post("/api/order/open", data={"folder": od.orders_root()}).status_code == 404


def test_open_before_prepare_is_409(client, order):
    state = od.read_state(order)
    state.pop("plate")
    with open(order.state_path, "w") as f:
        json.dump(state, f)
    r = client.post("/api/order/open", data={"folder": order.dir})
    assert r.status_code == 409 and "Run Prepare first" in r.json()["detail"]


def test_save_before_a_proof_is_409(client, order):
    opened = _open(client, order)
    r = _post(client, "save", opened)
    assert r.status_code == 409 and "Render a proof first" in r.json()["detail"]
    assert "spec" not in (od.read_state(order).get("manual") or {})
    assert _post(client, "approve", opened).status_code == 409


def test_a_session_not_opened_from_an_order_cannot_save(client, order):
    opened = _open(client, order)
    _proof(client, opened)
    session.update(opened["session"], order_dir=None)
    r = _post(client, "save", opened)
    assert r.status_code == 409 and "not opened from an order" in r.json()["detail"]
    assert _post(client, "approve", opened).status_code == 409


def test_approve_before_a_save_is_409(client, order):
    opened = _open(client, order)
    _proof(client, opened)
    r = _post(client, "approve", opened)
    assert r.status_code == 409 and "Save to order first" in r.json()["detail"]
    assert not od.read_state(order).get("approval")


def test_approve_after_an_unsaved_change_is_409(client, order):
    opened = _open(client, order)
    _proof(client, opened)
    assert _post(client, "save", opened).status_code == 200
    _proof(client, opened, title="Smith home ground, again")
    r = _post(client, "approve", opened)
    assert r.status_code == 409 and "Save to order first" in r.json()["detail"]
    assert not od.read_state(order).get("approval")


def test_saving_a_changed_spec_clears_the_approval(client, order):
    opened = _open(client, order)
    _proof(client, opened)
    _post(client, "save", opened)
    assert _post(client, "approve", opened).status_code == 200
    # saving the same spec again keeps the approval, and says so
    again = _post(client, "save", opened).json()
    assert again["approved"] is True and od.read_state(order)["approval"]
    # a changed spec drops it
    _proof(client, opened, title="Smith home ground, again")
    changed = _post(client, "save", opened).json()
    assert changed["saved"] is True and changed["approved"] is False
    state = od.read_state(order)
    assert state["approval"] is None and not orderstudio.approval_ok(order, state)
    assert state["manual"]["spec"]["title_text"] == "Smith home ground, again"


def test_a_proof_that_cannot_be_written_still_saves(client, order, monkeypatch):
    from app import orderproof

    def fail(*a, **kw):
        raise od.OrderError("the disk is full")
    monkeypatch.setattr(orderproof, "write_proofs", fail)
    opened = _open(client, order)
    _proof(client, opened)
    r = _post(client, "save", opened)
    assert r.status_code == 200, r.text
    assert r.json() == {"saved": True, "approved": False, "proof": [],
                        "proof_error": "the disk is full"}
    assert od.read_state(order)["manual"]["spec"]


def test_a_pycms_error_in_the_proof_still_saves(client, order, monkeypatch):
    from PIL.ImageCms import PyCMSError
    from app import orderproof

    def fail(*a, **kw):
        raise PyCMSError("cannot build transform")
    monkeypatch.setattr(orderproof, "write_proofs", fail)
    opened = _open(client, order)
    _proof(client, opened)
    r = _post(client, "save", opened)
    assert r.status_code == 200 and "cannot build transform" in r.json()["proof_error"]


def test_orders_lists_newest_first_with_their_state(client, order):
    other = os.path.join(od.orders_root(), "2026-10-009-jones")
    os.makedirs(other)
    with open(os.path.join(other, "order.toml"), "w") as f:
        f.write('title = "Jones"\norder_number = "TP-26-009"\n')
    os.makedirs(os.path.join(od.orders_root(), "_cache"))
    rows = client.get("/api/orders").json()
    assert [r["name"] for r in rows] == ["2026-10-009-jones", "2026-10-001-smith"]
    jones, smith = rows
    assert jones == {"folder": other, "name": "2026-10-009-jones",
                     "order_number": "TP-26-009", "title": "Jones",
                     "prepared": False, "approved": False}
    assert smith["prepared"] is True and smith["approved"] is False
    assert set(smith) == {"folder", "name", "order_number", "title", "prepared", "approved"}


def test_approval_ok_needs_a_saved_spec_and_a_matching_hash(order):
    state = od.read_state(order)
    h = orderspec.spec_hash(orderspec.order_spec(order, state))
    # an approval with no saved spec stands for nothing
    od.write_state(order, {"approval": {"at": "x", "hash": h}})
    assert not orderstudio.approval_ok(order, od.read_state(order))
    od.set_manual(order, "spec", None)           # Prepare leaves None when it sets a spec aside
    assert not orderstudio.approval_ok(order, od.read_state(order))


def test_continue_still_answers_its_shape(client):
    from app.main import _proof_form_for  # noqa: F401  (the helper continue shares with Open)
    sample = open("tests/fixtures/sample.gpx", "rb").read()
    j = client.post("/api/upload", files=[("files", ("a.gpx", sample, "application/gpx+xml"))]).json()
    cfg = json.load(open("regions/lassen_ca/region.json"))
    ovw, ovh = j["overview_size"]
    cw = ovw * (40000.0 / (cfg["bounds"][2] - cfg["bounds"][0]))
    ch = cw / 0.75
    x0, y0 = ovw * 0.5 - cw / 2, ovh * 0.5 - ch / 2
    r = client.post("/api/proof", data={"session_id": j["session"], "x0": x0, "y0": y0,
                                        "x1": x0 + cw, "y1": y0 + ch,
                                        "print_w": 6, "print_h": 8, "title": "Trip"})
    assert r.status_code == 200, r.text
    png = client.post("/api/final", data={"session_id": j["session"]}).content
    cont = client.post("/api/continue", files={"file": ("p.png", png, "image/png")})
    assert cont.status_code == 200, cont.text
    body = cont.json()
    assert SPEC_KEYS <= set(body) and "order" not in body
    assert body["edition"] == 2 and body["prefill"]["title"] == "Trip"
    assert "order_dir" not in session.get(body["session"])
