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
    assert {k: v for k, v in opened["order"].items() if k != "photo_view"} == \
        {"folder": os.path.realpath(order.dir), "title": "Smith home ground",
         "approved": False}
    assert opened["order"]["photo_view"]["photos"] == []       # an order with no photos
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


@pytest.mark.parametrize("error", ["paper", "spec"])
def test_a_paper_table_or_spec_error_in_the_proof_still_saves(client, order, monkeypatch,
                                                              error):
    from app import orderproof
    from app.papers import PaperError
    from app.spec import SpecError

    def fail(*a, **kw):
        raise (PaperError("config/papers.toml cannot be read") if error == "paper"
               else SpecError("the crop is off the DEM"))
    monkeypatch.setattr(orderproof, "write_proofs", fail)
    opened = _open(client, order)
    _proof(client, opened)
    r = _post(client, "save", opened)
    assert r.status_code == 200 and r.json()["proof_error"].endswith(
        " The client proof files were removed; save again to write them.")
    assert od.read_state(order)["manual"]["spec"]


def test_save_records_the_client_proof_it_wrote(client, order):
    opened = _open(client, order)
    _proof(client, opened)
    body = _post(client, "save", opened).json()
    state = od.read_state(order)
    assert state["proof"]["files"] == body["proof"]
    assert state["proof"]["hash"] == orderspec.spec_hash(orderspec.order_spec(order, state))


def test_approve_refuses_when_the_client_proof_was_not_written(client, order, monkeypatch):
    from app import orderproof
    opened = _open(client, order)
    _proof(client, opened)
    real = orderproof.write_proofs

    def fail(*a, **kw):
        raise od.OrderError("the disk is full")
    monkeypatch.setattr(orderproof, "write_proofs", fail)
    assert "proof_error" in _post(client, "save", opened).json()
    assert od.read_state(order)["proof"] is None
    r = _post(client, "approve", opened)
    assert r.status_code == 409
    assert r.json()["detail"] == "The client proof was not written: save again before approving."
    assert not od.read_state(order).get("approval")
    # saving again writes the proof, and the approval goes through
    monkeypatch.setattr(orderproof, "write_proofs", real)
    assert "proof_error" not in _post(client, "save", opened).json()
    assert _post(client, "approve", opened).status_code == 200


# ---- the studio's photo controls (order photos, Task 8) --------------------------------
# An order with three photos: one with GPS, one with only a time (it lands on the track
# halfway along, as it was taken halfway through), one with neither (the tray). Its plate
# sits in the order's work/plate, as Prepare builds one, and its state is current, so a
# second Prepare takes the "Plate is current" path a Prepare after a studio edit takes.

T0 = 1791043200            # 2026-10-03 16:00:00 UTC, the track's start
GPS_AT = (5000.0, -6000.0)  # metres from the plate's centre: right of and below the track
TRAY_AT = (-5000.0, 6000.0)  # where the tray photo is placed: left of and above the track


def _gpx_with_times(to_ll, cx, cy):
    import time as _t
    pts = []
    for (dx, dy), t in (((-3000, -5000), T0), ((0, 0), T0 + 1800), ((3000, 5000), T0 + 3600)):
        lon, lat = to_ll.transform(cx + dx, cy + dy)
        pts.append(f'<trkpt lat="{lat}" lon="{lon}"><time>'
                   f'{_t.strftime("%Y-%m-%dT%H:%M:%SZ", _t.gmtime(t))}</time></trkpt>')
    return ('<?xml version="1.0"?><gpx version="1.1" creator="t" '
            'xmlns="http://www.topografix.com/GPX/1/1"><trk><name>t</name>'
            f"<trkseg>{''.join(pts)}</trkseg></trk></gpx>")


def _centre(order):
    f = od.read_state(order)["open_frame"]
    return (f[0] + f[2]) / 2, (f[1] + f[3]) / 2


@pytest.fixture
def photo_order(built_order):
    from pyproj import Transformer

    from app import orderprep
    from tests.test_photos import _make
    order = built_order
    state = od.read_state(order)
    cfg = json.load(open(os.path.join(state["plate"]["root"], state["plate"]["id"],
                                      "region.json")))
    f = state["frame"]
    cx, cy = (f[0] + f[2]) / 2, (f[1] + f[3]) / 2
    to_ll = Transformer.from_crs(cfg["crs"], "EPSG:4326", always_xy=True)
    with open(os.path.join(order.in_dir, "trip.gpx"), "w") as fh:
        fh.write(_gpx_with_times(to_ll, cx, cy))
    lon, lat = to_ll.transform(cx + GPS_AT[0], cy + GPS_AT[1])
    big = (700, 500)
    _make(os.path.join(order.in_dir, "a_gps.jpg"), size=big,
          gps=(abs(lat), "N" if lat >= 0 else "S", abs(lon), "E" if lon >= 0 else "W"))
    _make(os.path.join(order.in_dir, "b_time.jpg"), size=big,
          taken="2026:10:03 09:30:00", offset="-07:00")
    _make(os.path.join(order.in_dir, "c_tray.jpg"), size=big)
    order = od.load(order.dir)
    od.write_state(order, {"inputs_hash": order.inputs_hash(), "photo_plan": True,
                           "plate": {**state["plate"], "kind": "built", "upsample": 1.0,
                                     "us_share": 1.0},
                           "landcover_rebuilds": 1, "open_frame": list(f),
                           "track_bounds_m": [cx - 3000, cy - 5000, cx + 3000, cy + 5000]})
    state = orderprep.place_photos(order, od.read_state(order), log=lambda s: None)
    assert state["photo_layout"] == "open"
    yield order
    from app.main import REGIONS
    REGIONS.pop(state["plate"]["id"], None)


def _photo(client, opened, file, change, raw=None):
    return client.post("/api/order/photo", data={
        "session_id": opened["session"], "file": file,
        "change": raw if raw is not None else json.dumps(change)})


def _by_file(view):
    return {p["file"]: p for p in view["photos"]}


def _sheet_in(order, x, y):
    spec = orderspec.order_spec(order, od.read_state(order))
    return orderspec.ground_to_sheet_in(spec, x, y)


def test_open_answers_the_photos(client, photo_order):
    opened = _open(client, photo_order)
    view = opened["order"]["photo_view"]
    assert view["layout"] == "open" and view["dpi"] == 96
    assert view["sheet_px"] == [pytest.approx(11 * 96), pytest.approx(17 * 96)]
    a, b, c = (_by_file(view)[f] for f in ("a_gps.jpg", "b_time.jpg", "c_tray.jpg"))
    assert a["source"] == "gps" and b["source"] == "time"
    assert c["tray"] is True and c["spot"] is None and c["box_px"] is None
    for p in (a, b):
        assert p["placed"] and len(p["box_px"]) == 4 and len(p["spot_px"]) == 2
        assert p["box_px"][2] - p["box_px"][0] == pytest.approx(view["box_in"] * 96)


def test_place_a_tray_photo_by_proof_pixel(client, photo_order):
    order = photo_order
    opened = _open(client, order)
    cx, cy = _centre(order)
    target = (cx + TRAY_AT[0], cy + TRAY_AT[1])
    spec = orderspec.order_spec(order, od.read_state(order))
    px, py = orderstudio.ground_to_proof_px(spec, 96, *target)
    r = _photo(client, opened, "c_tray.jpg", {"spot_px": {"px": px, "py": py}})
    assert r.status_code == 200, r.text
    c = _by_file(r.json())["c_tray.jpg"]
    assert c["source"] == "manual" and c["tray"] is False and c["placed"] is True
    assert (c["spot"]["x"], c["spot"]["y"]) == (pytest.approx(target[0], abs=1e-6),
                                                pytest.approx(target[1], abs=1e-6))
    assert c["spot_px"] == [pytest.approx(px), pytest.approx(py)]
    assert c["box_px"] is not None                      # the layout gave it open ground
    saved = od.read_state(order)["manual"]["photos"]["c_tray.jpg"]["spot"]
    assert (saved["x"], saved["y"]) == (pytest.approx(target[0], abs=1e-6),
                                        pytest.approx(target[1], abs=1e-6))
    st = session.get(opened["session"])
    assert st["spec"] is None                           # proof again to see it
    photos = [h for h in st["hotspots"] if h.get("photo")]
    assert any(h["photo"].endswith("c_tray.jpg.jpg") for h in photos) and len(photos) == 3
    assert len(r.json()["hotspots"]) == len(st["hotspots"])


def test_drag_a_box_sets_its_offset_in_inches(client, photo_order):
    order = photo_order
    opened = _open(client, order)
    before = _by_file(opened["order"]["photo_view"])
    r = _photo(client, opened, "a_gps.jpg", {"box": {"dx_in": -1.6, "dy_in": -1.9}})
    assert r.status_code == 200, r.text
    a = _by_file(r.json())["a_gps.jpg"]
    assert a["box"] == {"dx_in": -1.6, "dy_in": -1.9} and a["moved"] is True
    x0, y0, x1, y1 = a["box_px"]
    assert (x0 + x1) / 2 == pytest.approx(a["spot_px"][0] - 1.6 * 96, abs=1e-6)
    assert (y0 + y1) / 2 == pytest.approx(a["spot_px"][1] - 1.9 * 96, abs=1e-6)
    assert od.read_state(order)["manual"]["photos"]["a_gps.jpg"]["box"] == \
        {"dx_in": -1.6, "dy_in": -1.9}
    hs = [h for h in session.get(opened["session"])["hotspots"]
          if h.get("photo", "").endswith("a_gps.jpg.jpg")]
    assert hs[0]["box"] == {"dx_in": -1.6, "dy_in": -1.9}
    assert before["a_gps.jpg"]["moved"] is False
    assert not any("route" in w for w in r.json()["warnings"])


def test_a_drop_on_a_route_is_kept_and_warned(client, photo_order):
    order = photo_order
    opened = _open(client, order)
    cx, cy = _centre(order)
    sx, sy = _sheet_in(order, cx + GPS_AT[0], cy + GPS_AT[1])
    tx, ty = _sheet_in(order, cx, cy)                    # the track's middle point
    box = {"dx_in": round(tx - sx, 4), "dy_in": round(ty - sy, 4)}
    r = _photo(client, opened, "a_gps.jpg", {"box": box})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["layout"] == "open"
    assert _by_file(body)["a_gps.jpg"]["box"] == box  # kept where it was dropped
    assert "a_gps.jpg: its box is over a route. It stays where you put it." in body["warnings"]
    assert od.read_state(order)["manual"]["photos"]["a_gps.jpg"]["box"] == box


def test_a_box_over_another_photos_spot_is_kept_and_warned(client, photo_order):
    order = photo_order
    opened = _open(client, order)
    cx, cy = _centre(order)
    target = (cx + TRAY_AT[0], cy + TRAY_AT[1])
    assert _photo(client, opened, "c_tray.jpg",
                  {"spot": {"x": target[0], "y": target[1]}}).status_code == 200
    sx, sy = _sheet_in(order, cx + GPS_AT[0], cy + GPS_AT[1])
    tx, ty = _sheet_in(order, *target)
    box = {"dx_in": round(tx - sx, 4), "dy_in": round(ty - sy, 4)}
    body = _photo(client, opened, "a_gps.jpg", {"box": box}).json()
    assert body["layout"] == "open"                      # never silently sent to the band
    assert _by_file(body)["a_gps.jpg"]["box"] == box
    assert _by_file(body)["c_tray.jpg"]["box_px"] is not None
    assert ("a_gps.jpg: its box is over c_tray.jpg's spot. It stays where you put it."
            in body["warnings"])


def test_proof_px_and_ground_round_trip(client, photo_order):
    order = photo_order
    spec = orderspec.order_spec(order, od.read_state(order))
    x0, y0, x1, y1 = spec.crop
    assert orderstudio.ground_to_proof_px(spec, 96, x0, y1) == \
        (pytest.approx(0.0, abs=1e-6), pytest.approx(0.0, abs=1e-6))
    assert orderstudio.ground_to_proof_px(spec, 96, x1, y0) == \
        (pytest.approx(11 * 96), pytest.approx(17 * 96))
    for gx, gy in ((x0 + 1234.5, y0 + 9876.5), ((x0 + x1) / 2, (y0 + y1) / 2), (x1, y1)):
        px, py = orderstudio.ground_to_proof_px(spec, 96, gx, gy)
        assert orderstudio.proof_px_to_ground(spec, 96, px, py) == \
            (pytest.approx(gx, abs=1e-6), pytest.approx(gy, abs=1e-6))
    # the proof image is the sheet at the proof's dpi, the bleed cropped off: proof px
    # are sheet inches x dpi from the trim's corner, with a bleed or without
    from PIL import Image
    import io
    opened = _open(client, order)
    crop = dict(zip(("x0", "y0", "x1", "y1"), opened["starter_crop"]))
    view = opened["order"]["photo_view"]
    for bleed in ("0", "0.125"):
        r = client.post("/api/proof", data={"session_id": opened["session"], **crop,
                                            **_form(opened["proof_form"]), "bleed": bleed})
        assert r.status_code == 200, r.text
        w, h = Image.open(io.BytesIO(r.content)).size
        assert abs(w - view["sheet_px"][0]) <= 1 and abs(h - view["sheet_px"][1]) <= 1


def test_drop_and_restore(client, photo_order):
    order = photo_order
    opened = _open(client, order)
    body = _photo(client, opened, "b_time.jpg", {"dropped": True}).json()
    b = _by_file(body)["b_time.jpg"]
    assert b["dropped"] is True and b["placed"] is False and b["box_px"] is None
    photos = [h["photo"] for h in session.get(opened["session"])["hotspots"] if h.get("photo")]
    assert not any(p.endswith("b_time.jpg.jpg") for p in photos)
    assert od.read_state(order)["manual"]["photos"]["b_time.jpg"]["dropped"] is True
    body = _photo(client, opened, "b_time.jpg", {"dropped": False}).json()
    b = _by_file(body)["b_time.jpg"]
    assert b["dropped"] is False and b["placed"] is True and b["box_px"] is not None
    photos = [h["photo"] for h in session.get(opened["session"])["hotspots"] if h.get("photo")]
    assert any(p.endswith("b_time.jpg.jpg") for p in photos)


def test_edits_survive_prepare_again(client, photo_order):
    import sys

    from app import orderprep
    from tests.test_orderprep import _Fake
    order = photo_order
    opened = _open(client, order)
    cx, cy = _centre(order)
    target = (cx + TRAY_AT[0], cy + TRAY_AT[1])
    for file, change in (("c_tray.jpg", {"spot": {"x": target[0], "y": target[1]}}),
                         ("a_gps.jpg", {"box": {"dx_in": -1.6, "dy_in": -1.9},
                                        "crop": {"cx": 0.2, "cy": 0.8}}),
                         ("b_time.jpg", {"caption": "Lunch stop"})):
        assert _photo(client, opened, file, change).status_code == 200
    manual = od.read_state(order)["manual"]["photos"]
    tools = orderprep.Tools(prep_python=sys.executable, prep_script="-", labels_script="-",
                            coverage_script="-", repo_root=order.dir, curated_root=order.dir)
    fake = _Fake()
    state = orderprep.prepare(order.dir, tools, log=lambda s: None, proofs=fake)
    assert fake.calls                                    # the current path: no build
    assert state["manual"]["photos"] == manual
    p = {e["file"]: e for e in state["photos"]}
    assert p["c_tray.jpg"]["source"] == "manual"
    assert p["c_tray.jpg"]["spot"] == {"x": pytest.approx(target[0]),
                                       "y": pytest.approx(target[1])}
    assert p["a_gps.jpg"]["box"] == {"dx_in": -1.6, "dy_in": -1.9}
    assert p["a_gps.jpg"]["crop"] == {"cx": 0.2, "cy": 0.8}
    assert p["b_time.jpg"]["caption"] == "Lunch stop"


def test_an_edit_clears_the_approval(client, photo_order):
    order = photo_order
    opened = _open(client, order)
    _proof(client, opened)
    assert _post(client, "save", opened).status_code == 200
    assert _post(client, "approve", opened).status_code == 200      # photo fields ride
    r = _photo(client, opened, "b_time.jpg", {"caption": "Lunch stop"})
    assert r.status_code == 200 and r.json()["approved"] is False
    state = od.read_state(order)
    assert state["approval"] is None and not orderstudio.approval_ok(order, state)
    assert _post(client, "approve", opened).status_code == 409       # proof again first


def test_an_empty_change_only_answers(client, photo_order):
    order = photo_order
    opened = _open(client, order)
    _proof(client, opened)
    _post(client, "save", opened)
    _post(client, "approve", opened)
    before = od.read_state(order)
    body = _photo(client, opened, "", {}).json()
    assert body["approved"] is True
    was = opened["order"]["photo_view"]["photos"]
    assert [(p["file"], p["box"]) for p in body["photos"]] == \
        [(p["file"], p["box"]) for p in was]
    assert od.read_state(order) == before
    assert session.get(opened["session"])["spec"] is not None


def test_the_studio_proof_paints_the_orders_photo_fields(client, photo_order, monkeypatch):
    from app import orderprep, photolayout
    order = photo_order
    monkeypatch.setattr(photolayout, "OPEN_MAX", 0)       # every photo hangs in the band
    state = orderprep.place_photos(order, od.read_state(order), log=lambda s: None)
    assert state["photo_layout"] == "band"
    opened = _open(client, order)
    _proof(client, opened)
    spec = session.get(opened["session"])["spec"]
    assert (spec.photo_layout, spec.photo_band_side, spec.photo_box_in) == \
        ("band", "top", state["photo_box_in"])
    assert _post(client, "save", opened).status_code == 200
    assert _post(client, "approve", opened).status_code == 200


def test_a_band_side_change_moves_the_band_and_reframes(client, photo_order, monkeypatch):
    from app import orderplate, orderprep, photolayout
    order = photo_order
    monkeypatch.setattr(photolayout, "OPEN_MAX", 0)
    orderprep.place_photos(order, od.read_state(order), log=lambda s: None)
    opened = _open(client, order)
    assert opened["order"]["photo_view"]["band_side"] == "top"
    r = _photo(client, opened, "", {"band_side": "bottom"})
    assert r.status_code == 200, r.text
    body = r.json()
    state = od.read_state(order)
    assert state["manual"]["band_side"] == "bottom" and state["photo_band_side"] == "bottom"
    assert orderspec.photo_band_side(state) == "bottom"
    bh = orderspec.band_height_for(state["photo_box_in"])
    want = orderplate.band_frame(state["open_frame"], 17.0, bh, "bottom")
    assert state["frame"] == [pytest.approx(v) for v in want]
    assert body["band_side"] == "bottom" and body["reframed"] is True
    assert body["crop_px"] != opened["starter_crop"]
    # the next proof paints the bottom band on the moved frame
    session_st = session.get(opened["session"])
    assert session_st["order_photo"]["photo_band_side"] == "bottom"
    # a side Prepare left in state is not the one Dom chose: Dom's wins
    assert orderspec.photo_band_side({"photo_band_side": "top",
                                      "manual": {"band_side": "bottom"}}) == "bottom"


@pytest.mark.parametrize("file,raw,status,words", [
    ("nope.jpg", '{"caption": "x"}', 404, "No photo named"),
    ("a_gps.jpg", "{not json", 422, "change must be JSON"),
    ("a_gps.jpg", '["caption"]', 422, "change must be a JSON object"),
    ("a_gps.jpg", '{"colour": "red"}', 422, "unknown change"),
    ("a_gps.jpg", '{"box": {"dx_in": 99, "dy_in": 0}}', 422, "box must be"),
    ("a_gps.jpg", '{"box": {"dx_in": "NaN", "dy_in": 0}}', 422, "box must be"),
    ("a_gps.jpg", '{"crop": {"cx": 1.5, "cy": 0.5}}', 422, "crop must be"),
    ("a_gps.jpg", '{"caption": 7}', 422, "caption must be"),
    ("a_gps.jpg", '{"dropped": "yes"}', 422, "dropped must be"),
    ("a_gps.jpg", '{"spot": {"x": 1e30, "y": 0}}', 422, "spot"),
    ("a_gps.jpg", '{"band_side": "bottom"}', 422, "band_side"),
    ("", '{"band_side": "left"}', 422, "band_side"),
    ("", '{"caption": "x"}', 422, "Name a photo"),
    ("c_tray.jpg", '{"box": {"dx_in": 1, "dy_in": 1}}', 422, "Place c_tray.jpg"),
])
def test_a_bad_photo_change_is_refused_and_writes_nothing(client, photo_order, file, raw,
                                                          status, words):
    opened = _open(client, photo_order)
    before = od.read_state(photo_order)
    r = _photo(client, opened, file, None, raw=raw)
    assert r.status_code == status, r.text
    assert words in r.json()["detail"]
    assert od.read_state(photo_order) == before


def test_the_photo_route_needs_an_order_session(client, photo_order):
    opened = _open(client, photo_order)
    session.update(opened["session"], order_dir=None)
    assert _photo(client, opened, "a_gps.jpg", {"caption": "x"}).status_code == 409


# ---- fix round 1: the layout is computed on the crop that will print -------------------
# The studio's frame can be wider than Prepare's (refitForSize grows it to the plate's 1x
# target). The layout, its warnings and box_px follow the live view's crop.

WIDE = (16500.0, 25500.0)    # half-width, half-height of a wider 11:17 view (frame: 9000)


def _proof_at(client, opened, order, half=WIDE):
    """The studio's proof of the opened order with its frame widened about the centre."""
    from app.geo import crs_to_overview_px
    from app.main import REGIONS
    region = REGIONS[opened["region"]]
    cx, cy = _centre(order)
    x0, y1 = crs_to_overview_px(region.geo, cx - half[0], cy + half[1])
    x1, y0 = crs_to_overview_px(region.geo, cx + half[0], cy - half[1])
    crop = {"x0": min(x0, x1), "y0": min(y0, y1), "x1": max(x0, x1), "y1": max(y0, y1)}
    r = client.post("/api/proof", data={"session_id": opened["session"], **crop,
                                        **_form(opened["proof_form"])})
    assert r.status_code == 200, r.text
    return session.get(opened["session"])["spec"]


def test_a_spot_inside_a_wider_view_is_not_outside_the_frame(client, photo_order):
    order = photo_order
    opened = _open(client, order)
    view = _proof_at(client, opened, order)
    cx, cy = _centre(order)
    spot = {"x": cx - 12000.0, "y": cy + 6000.0}         # in the view, past the frame
    assert not (od.read_state(order)["frame"][0] <= spot["x"])
    body = _photo(client, opened, "c_tray.jpg", {"spot": spot}).json()
    c = _by_file(body)["c_tray.jpg"]
    assert not any("outside the frame" in w for w in body["warnings"])
    assert c["box_px"] is not None and c["placed"]
    assert od.read_state(order)["layout_crop"] == [pytest.approx(v) for v in view.crop]


def test_a_box_dropped_on_the_views_route_is_warned(client, photo_order):
    order = photo_order
    opened = _open(client, order)
    view = _proof_at(client, opened, order)
    cx, cy = _centre(order)
    sx, sy = orderspec.ground_to_sheet_in(view, cx + GPS_AT[0], cy + GPS_AT[1])
    tx, ty = orderspec.ground_to_sheet_in(view, cx, cy)
    box = {"dx_in": round(tx - sx, 4), "dy_in": round(ty - sy, 4)}
    body = _photo(client, opened, "a_gps.jpg", {"box": box}).json()
    assert "a_gps.jpg: its box is over a route. It stays where you put it." in body["warnings"]
    assert not any("past the sheet's edge" in w for w in body["warnings"])


def test_a_reframe_then_a_measure_lays_the_boxes_out_again(client, photo_order):
    order = photo_order
    opened = _open(client, order)
    view = _proof_at(client, opened, order)
    assert od.read_state(order)["layout_crop"] != [pytest.approx(v) for v in view.crop]
    body = _photo(client, opened, "", {}).json()
    assert body["relaid"] is True and body["edited"] is False
    state = od.read_state(order)
    assert state["layout_crop"] == [pytest.approx(v) for v in view.crop]
    boxes = [p["box_px"] for p in body["photos"] if p["box_px"]]
    assert len(boxes) == 2
    a, b = boxes
    assert not (a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3])
    assert session.get(opened["session"])["spec"] is None          # proof again
    # the next measure on the same frame lays nothing out again
    _proof(client, opened, **dict(zip(("x0", "y0", "x1", "y1"), body["crop_px"])))
    assert _photo(client, opened, "", {}).json()["relaid"] is False


def test_prepare_after_a_save_lays_out_on_the_saved_crop(client, photo_order):
    import sys

    from app import orderprep
    from tests.test_orderprep import _Fake
    order = photo_order
    opened = _open(client, order)
    _proof_at(client, opened, order)
    cx, cy = _centre(order)
    assert _photo(client, opened, "c_tray.jpg",
                  {"spot": {"x": cx - 12000.0, "y": cy + 6000.0}}).status_code == 200
    _proof_at(client, opened, order)
    assert _post(client, "save", opened).status_code == 200
    saved = od.read_state(order)["manual"]["spec"]["crop"]
    tools = orderprep.Tools(prep_python=sys.executable, prep_script="-", labels_script="-",
                            coverage_script="-", repo_root=order.dir, curated_root=order.dir)
    state = orderprep.prepare(order.dir, tools, log=lambda s: None, proofs=_Fake())
    assert state["layout_crop"] == [pytest.approx(v) for v in saved]
    assert not any("outside the frame" in w for w in state["photo_warnings"])
    assert {p["file"]: p for p in state["photos"]}["c_tray.jpg"]["box"] is not None


# ---- fix round 1: review minors ---------------------------------------------------------

@pytest.mark.parametrize("raw", [
    '{"spot": {"x": %s, "y": 0}}' % (10 ** 400),
    '{"spot_px": {"px": %s, "py": 10}}' % (10 ** 400),
    '{"box": {"dx_in": NaN, "dy_in": 0}}',
])
def test_a_huge_integer_or_a_nan_is_refused_not_a_500(client, photo_order, raw):
    opened = _open(client, photo_order)
    before = od.read_state(photo_order)
    r = _photo(client, opened, "a_gps.jpg", None, raw=raw)
    assert r.status_code == 422, r.text
    assert od.read_state(photo_order) == before


def test_a_path_for_a_file_name_is_404(client, photo_order):
    opened = _open(client, photo_order)
    before = od.read_state(photo_order)
    for name in ("../order.toml", "../in/a_gps.jpg", "/etc/passwd"):
        r = _photo(client, opened, name, {"caption": "x"})
        assert r.status_code == 404 and "No photo named" in r.json()["detail"]
    assert od.read_state(photo_order) == before


def test_a_long_caption_is_cut_to_60(client, photo_order):
    opened = _open(client, photo_order)
    body = _photo(client, opened, "b_time.jpg", {"caption": "x" * 10_000}).json()
    assert _by_file(body)["b_time.jpg"]["caption"] == "x" * 60
    assert od.read_state(photo_order)["manual"]["photos"]["b_time.jpg"]["caption"] == "x" * 60


def test_an_edit_then_proof_save_and_approve_approves_again(client, photo_order):
    order = photo_order
    opened = _open(client, order)
    _proof(client, opened)
    _post(client, "save", opened)
    assert _post(client, "approve", opened).status_code == 200
    body = _photo(client, opened, "b_time.jpg", {"caption": "Lunch stop"}).json()
    assert body["approved"] is False
    _proof(client, opened, **dict(zip(("x0", "y0", "x1", "y1"), body["crop_px"])))
    assert _post(client, "save", opened).status_code == 200
    assert _post(client, "approve", opened).status_code == 200
    state = od.read_state(order)
    assert orderstudio.approval_ok(order, state)
    assert {p["file"]: p for p in state["photos"]}["b_time.jpg"]["caption"] == "Lunch stop"


def test_the_edit_and_the_cleared_approval_are_one_write(client, photo_order, monkeypatch):
    from app import orderprep
    order = photo_order
    opened = _open(client, order)
    _proof(client, opened)
    _post(client, "save", opened)
    _post(client, "approve", opened)
    writes = []
    real = od._dump
    monkeypatch.setattr(od, "_dump", lambda o, s: (writes.append(dict(s)), real(o, s)))

    def fail(*a, **kw):
        raise od.OrderError("the layout failed")
    monkeypatch.setattr(orderprep, "place_photos", fail)
    r = _photo(client, opened, "b_time.jpg", {"caption": "Lunch stop"})
    assert r.status_code == 409
    assert len(writes) == 1
    assert writes[0]["approval"] is None
    assert writes[0]["manual"]["photos"]["b_time.jpg"]["caption"] == "Lunch stop"


def test_the_marker_routes_leave_an_order_photo_alone(client, photo_order):
    opened = _open(client, photo_order)
    st = session.get(opened["session"])
    i = next(k for k, h in enumerate(st["hotspots"]) if h.get("photo"))
    assert opened["hotspots"][i].get("order_photo") is True
    label = st["hotspots"][i]["label"]
    r = client.post("/api/markers", data={"session_id": opened["session"],
                                          "markers": json.dumps([{"i": i, "label": "Renamed"}])})
    assert r.status_code == 200
    assert session.get(opened["session"])["hotspots"][i]["label"] == label
    r = client.post("/api/markers/move", data={"session_id": opened["session"], "i": i,
                                               "px": 10, "py": 10})
    assert r.status_code == 409 and "Order panel" in r.json()["detail"]
    r = client.post("/api/photo", data={"session_id": opened["session"], "i": i},
                    files={"file": ("x.jpg", b"not read", "image/jpeg")})
    assert r.status_code == 409


def test_a_box_over_a_seam_is_named_a_seam():
    import numpy as np

    from app import orderprep
    from app.render import Occupancy
    occ = Occupancy(size_px=(1000, 1000), route=np.zeros((1000, 1000), bool),
                    rects=[(480, 0, 520, 1000), (0, 900, 300, 1000)], dpi=100.0,
                    trim_px=(0, 0, 1000, 1000))
    spots = [(3.0, 5.0)]
    out = orderprep._fixed_warnings(spots, {0: (2.0, 0.0)}, {0: (2.0, 0.0)}, ["a.jpg"],
                                    1.0, occ, (0.0, 0.0, 0.0), seams=[(480, 0, 520, 1000)])
    assert [w for _, w in out] == [
        "a.jpg: its box is over a seam between panels. It stays where you put it."]
    out = orderprep._fixed_warnings([(1.0, 8.5)], {0: (0.5, 1.0)}, {0: (0.5, 1.0)},
                                    ["a.jpg"], 1.0, occ, (0.0, 0.0, 0.0),
                                    seams=[(480, 0, 520, 1000)])
    assert [w for _, w in out] == [
        "a.jpg: its box is over the poster's furniture. It stays where you put it."]


# ---- final fix M1: an approved order never loses its approval to a read-only measure ---

REFRAMED_NOTE = "The frame differs from the approved one: save to lay the photos out again."


def test_an_approved_order_is_not_relaid_by_a_read_only_measure(client, photo_order):
    order = photo_order
    opened = _open(client, order)
    _proof(client, opened)
    assert _post(client, "save", opened).status_code == 200
    assert _post(client, "approve", opened).status_code == 200
    before = od.read_state(order)
    view = _proof_at(client, opened, order)                 # refitForSize, on open
    assert before["layout_crop"] != [pytest.approx(v) for v in view.crop]
    body = _photo(client, opened, "", {}).json()
    assert body["relaid"] is False and body["edited"] is False
    assert body["note"] == REFRAMED_NOTE and body["approved"] is True
    assert od.read_state(order) == before                   # nothing written
    assert orderstudio.approval_ok(order, od.read_state(order))


def test_save_lays_the_photos_out_on_the_saved_crop_first(client, photo_order):
    order = photo_order
    opened = _open(client, order)
    _proof(client, opened)
    _post(client, "save", opened)
    _post(client, "approve", opened)
    view = _proof_at(client, opened, order)
    assert _photo(client, opened, "", {}).json()["relaid"] is False   # approved: kept
    r = _post(client, "save", opened)
    assert r.status_code == 200 and r.json()["approved"] is False
    state = od.read_state(order)
    assert state["layout_crop"] == [pytest.approx(v) for v in view.crop]
    assert state["proof"]["hash"] == orderspec.spec_hash(orderspec.order_spec(order, state))


def test_an_unapproved_order_still_relays_on_a_measure(client, photo_order):
    order = photo_order
    opened = _open(client, order)
    _proof_at(client, opened, order)
    body = _photo(client, opened, "", {}).json()
    assert body["relaid"] is True and "note" not in body


def test_an_order_with_no_layout_crop_is_not_relaid_by_a_measure(client, photo_order):
    # an order prepared before layout_crop existed: its boxes stand until an edit
    order = photo_order
    state = od.read_state(order)
    state.pop("layout_crop", None)
    with open(os.path.join(order.work_dir, "state.json"), "w") as f:
        json.dump(state, f)
    opened = _open(client, order)
    _proof_at(client, opened, order)
    body = _photo(client, opened, "", {}).json()
    assert body["relaid"] is False and "layout_crop" not in od.read_state(order)
