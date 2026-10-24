# tests/test_orderspec.py
# One spec for an order: the proof, the studio and Finish all paint what order_spec
# returns. The plate is the synthetic Lassen mirror; the fixture is order_with_plate
# in tests/conftest.py.
import dataclasses
import json
import os

import pytest

from app import orderspec
from app.order import OrderError, read_state, set_manual, write_state
from app.serialize import spec_to_json


@pytest.fixture
def order(order_with_plate):
    return order_with_plate


def test_default_spec_frames_as_prepare_did(order):
    s = orderspec.order_spec(order, read_state(order))
    assert s.crop == tuple(read_state(order)["frame"]) and s.title_text == order.title


def test_default_spec_is_the_one_the_proof_draws(order):
    st = read_state(order)
    s = orderspec.default_spec(order, st)
    cfg = json.load(open(os.path.join(orderspec.plate_dir(st), "region.json")))
    assert (s.region_id, s.crs) == (cfg["id"], cfg["crs"])
    assert s.native_resolution_m == cfg["native_resolution_m"]
    assert (s.print_w_in, s.print_h_in) == (11.0, 17.0)
    assert (s.panels, s.panel_gap_in) == (1, 0.0)
    assert len(s.tracks) == 1 and s.hotspots == [] and s.seed == 7
    assert s.labels is True                       # the plate holds labels.json
    for k, v in orderspec.ORDER_LOOK.items():
        assert getattr(s, k) == v
    s.validate()


def test_default_spec_has_no_labels_without_labels_json(order):
    st = read_state(order)
    # the mirror's files are symlinks into the shared plate: copy the plate aside
    import shutil
    src = orderspec.plate_dir(st)
    dst = os.path.join(order.work_dir, "p2", "copy")
    shutil.copytree(src, dst, symlinks=False)
    os.remove(os.path.join(dst, "labels.json"))
    write_state(order, {"plate": {**st["plate"], "root": os.path.dirname(dst),
                                  "id": "copy"}})
    assert orderspec.default_spec(order, read_state(order)).labels is False


def test_a_saved_spec_wins_but_follows_the_current_plate(order):
    st = read_state(order)
    saved = spec_to_json(orderspec.default_spec(order, st))
    saved["region_id"] = "old_plate"
    saved["crs"] = "EPSG:32611"
    saved["native_resolution_m"] = 99
    saved["title_text"] = "Edited"
    set_manual(order, "spec", saved)
    s = orderspec.order_spec(order, read_state(order))
    assert s.title_text == "Edited" and s.region_id == st["plate"]["id"]
    assert s.crs == "EPSG:32610" and s.native_resolution_m == 10


def test_the_hash_follows_the_spec(order):
    a = orderspec.default_spec(order, read_state(order))
    assert orderspec.spec_hash(a) == orderspec.spec_hash(a)
    assert orderspec.spec_hash(a) != orderspec.spec_hash(
        dataclasses.replace(a, title_text="x"))
    assert len(orderspec.spec_hash(a)) == 64


def test_the_hash_is_the_same_for_a_spec_read_back(order):
    from app.serialize import spec_from_json
    a = orderspec.default_spec(order, read_state(order))
    b = spec_from_json(json.loads(json.dumps(spec_to_json(a))))
    assert orderspec.spec_hash(a) == orderspec.spec_hash(b)


def test_a_title_with_no_letters_names_files_poster():
    assert orderspec.file_stem("★ !!") == "poster"
    assert orderspec.file_stem("") == "poster"


def test_a_title_names_files_by_its_slug():
    assert orderspec.file_stem("Smith home ground!") == "smith_home_ground"


def test_orderpreview_keeps_its_name_for_the_look():
    from app import orderpreview
    assert orderpreview.PREVIEW_LOOK is orderspec.ORDER_LOOK


def test_no_plate_says_run_prepare(order):
    with pytest.raises(OrderError, match="Run Prepare"):
        orderspec.plate_dir({})
    with pytest.raises(OrderError, match="Run Prepare"):
        orderspec.order_spec(order, {"frame": [0, 0, 1, 1]})


def test_a_plate_with_no_region_json_says_run_prepare(order, tmp_path):
    st = {**read_state(order), "plate": {"id": "gone", "root": str(tmp_path)}}
    with pytest.raises(OrderError, match="Run Prepare"):
        orderspec.plate_dir(st)


def test_orderspec_does_not_import_the_app():
    import subprocess
    import sys
    code = ("import sys, app.orderspec, app.orderpreview; "
            "assert 'app.main' not in sys.modules")
    subprocess.run([sys.executable, "-c", code], check=True)
