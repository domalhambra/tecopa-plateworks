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
                        "proof_error": "the disk is full The client proof files were "
                                       "removed; save again to write them."}
    assert od.read_state(order)["manual"]["spec"]


def test_a_failed_proof_removes_the_old_client_files(client, order, monkeypatch):
    from app import orderproof
    proof_dir = os.path.join(order.dir, "out", "proof")
    os.makedirs(proof_dir)
    stem = orderspec.file_stem(order.title)
    old = [os.path.join(proof_dir, f"{stem}-proof.{ext}") for ext in ("jpg", "pdf")]
    for path in old:
        open(path, "wb").write(b"old")
    keep = os.path.join(proof_dir, "notes.txt")
    open(keep, "w").write("not a client proof")

    def fail(*a, **kw):
        raise od.OrderError("the disk is full")
    monkeypatch.setattr(orderproof, "write_proofs", fail)
    opened = _open(client, order)
    _proof(client, opened)
    r = _post(client, "save", opened)
    assert r.status_code == 200
    assert r.json()["proof_error"].endswith(
        " The client proof files were removed; save again to write them.")
    assert not any(os.path.exists(p) for p in old)
    assert os.path.exists(keep)


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


@pytest.fixture
def built_order(order):
    """The order whose plate sits in its own work/plate, as Prepare builds one: inside the
    orders folder and outside REGIONS_ROOT."""
    import shutil
    state = od.read_state(order)
    src = os.path.join(state["plate"]["root"], state["plate"]["id"])
    dst = os.path.join(order.plate_root, state["plate"]["id"])
    shutil.copytree(src, dst, symlinks=True)
    od.write_state(order, {"plate": {**state["plate"], "root": order.plate_root}})
    return order


def test_a_built_plates_overview_is_served(client, built_order):
    from app.main import REGIONS
    plate = od.read_state(built_order)["plate"]["id"]
    try:
        opened = _open(client, built_order)
        assert opened["overview"] == f"/api/order/plate/{plate}/overview.png"
        r = client.get(opened["overview"])
        assert r.status_code == 200 and r.headers["content-type"] == "image/png"
        assert r.content.startswith(b"\x89PNG")
    finally:
        REGIONS.pop(plate, None)


def test_a_curated_plate_keeps_the_regions_overview(client, order):
    from app import regions
    from app.main import REGIONS
    curated = regions.Region("lassen_ca", "regions")
    plate = od.read_state(order)["plate"]
    od.write_state(order, {"plate": {**plate, "root": "regions"}})
    try:
        opened = _open(client, order)
        assert opened["overview"] == "/regions/lassen_ca/overview.png"
        assert opened["region"] == curated.id
    finally:
        REGIONS.pop("lassen_ca", None)
        REGIONS["lassen_ca"] = curated


def test_the_overview_route_refuses_what_is_not_an_orders_plate(client, order):
    from app import regions
    from app.main import REGIONS
    assert client.get("/api/order/plate/no_such_plate/overview.png").status_code == 404
    # a registered plate whose folder is outside the orders folder
    plate = od.read_state(order)["plate"]
    outside = regions.Region(plate["id"], plate["root"])
    saved = REGIONS.get(plate["id"])
    REGIONS[plate["id"]] = outside
    try:
        assert client.get(f"/api/order/plate/{plate['id']}/overview.png").status_code == 404
    finally:
        if saved is None:
            REGIONS.pop(plate["id"], None)
        else:
            REGIONS[plate["id"]] = saved


def test_a_corrupt_saved_spec_is_409_not_500(client, order):
    state = od.read_state(order)
    crs = json.load(open(os.path.join(state["plate"]["root"], state["plate"]["id"],
                                      "region.json")))["crs"]
    for bad in ({"crs": crs, "tracks": "not tracks"}, "not a spec", {"crs": crs}):
        od.set_manual(order, "spec", bad)
        r = client.post("/api/order/open", data={"folder": order.dir})
        assert r.status_code == 409, (bad, r.text)
        assert "cannot be read" in r.json()["detail"] or "Run Prepare" in r.json()["detail"]


def test_a_malformed_region_json_is_409_not_500(client, built_order):
    plate = od.read_state(built_order)["plate"]
    path = os.path.join(plate["root"], plate["id"], "region.json")
    os.remove(path)
    open(path, "w").write("{not json")
    r = client.post("/api/order/open", data={"folder": built_order.dir})
    assert r.status_code == 409 and "Run Prepare" in r.json()["detail"]


@pytest.mark.parametrize("change,words", [
    (dict(output_kind="wallpaper"), "not a wallpaper"),
    (dict(print_w_in=17.0, print_h_in=22.0), "not the order's size"),
    (dict(panels=2, panel_gap_in=2.0), "not the order's size")])
def test_save_refuses_a_spec_that_is_not_the_orders_print(client, order, change, words):
    import dataclasses
    opened = _open(client, order)
    _proof(client, opened)
    spec = session.get(opened["session"])["spec"]
    session.update(opened["session"], spec=dataclasses.replace(spec, **change))
    r = _post(client, "save", opened)
    assert r.status_code == 409 and words in r.json()["detail"]
    assert "spec" not in (od.read_state(order).get("manual") or {})


def test_save_records_the_inputs_the_spec_was_framed_on(client, order):
    od.write_state(order, {"inputs_hash": "inputs-at-prepare"})
    opened = _open(client, order)
    _proof(client, opened)
    assert _post(client, "save", opened).status_code == 200
    assert od.read_state(order)["manual"]["spec_inputs_hash"] == "inputs-at-prepare"


def test_a_proof_with_no_changes_saves_the_spec_prepare_proofed(client, order):
    """Prepare's proof is the default spec. Open, proof with no change and Save must save
    that same spec, or the client's first proof is not the print."""
    default = orderspec.default_spec(order, od.read_state(order))
    opened = _open(client, order)
    _proof(client, opened)
    assert orderspec.spec_hash(session.get(opened["session"])["spec"]) == \
        orderspec.spec_hash(default)
    assert _post(client, "save", opened).status_code == 200
    state = od.read_state(order)
    assert orderspec.spec_hash(orderspec.order_spec(order, state)) == \
        orderspec.spec_hash(default)


def test_main_keeps_the_credit_line_it_always_had():
    from app import credit, main
    assert main.credit_line is credit.credit_line
    assert main.CREDIT_DATASETS is credit.CREDIT_DATASETS
