"""order.py choose: write the preview's lines for one size into order.toml, so the
Mac app never edits order.toml itself (native Mac app phase 2 spec, decision 7)."""
import json
import os

import pytest

from app import orderchoose as oc
from app.order import OrderError

TOML = 'title = "Smith Lake"\norder_number = "TP-26-001"\n# Dom: client asked twice\nreturning = false\n'


def _order(tmp_path, toml=TOML, sizes=None):
    d = tmp_path / "TP-26-001-smith"
    (d / "in").mkdir(parents=True)
    (d / "in" / "trip.gpx").write_text("<gpx/>")
    (d / "order.toml").write_text(toml)
    if sizes is not None:
        (d / "work" / "preview").mkdir(parents=True)
        (d / "work" / "preview" / "preview.json").write_text(json.dumps({"sizes": sizes}))
    return d


SIZES = [
    {"key": "11x17", "offered": True, "orientation": "portrait", "panels": 1, "gap": 0.0},
    {"key": "17x22", "offered": True, "orientation": "landscape", "panels": 1, "gap": 0.0},
    {"key": "two", "offered": True, "orientation": "landscape", "panels": 2, "gap": 2.0},
    {"key": "three", "offered": False, "orientation": "landscape", "panels": 3, "gap": 2.0,
     "why": "the tracks span 24% of the sheet's width, under 30%"},
]


def test_choose_writes_size_and_orientation_and_keeps_every_other_line(tmp_path):
    d = _order(tmp_path, sizes=SIZES)
    out = oc.choose(str(d), "17x22")
    text = (d / "order.toml").read_text()
    assert 'size = "17x22"' in text and 'orientation = "landscape"' in text
    assert "# Dom: client asked twice" in text and 'order_number = "TP-26-001"' in text
    assert "gap" not in text
    assert "17x22" in out and "landscape" in out


def test_choose_a_set_writes_its_gap(tmp_path):
    d = _order(tmp_path, sizes=SIZES)
    oc.choose(str(d), "two")
    text = (d / "order.toml").read_text()
    assert 'size = "two"' in text and "gap = 2" in text


def test_choosing_again_replaces_the_lines_and_a_single_sheet_drops_the_gap(tmp_path):
    d = _order(tmp_path, sizes=SIZES)
    oc.choose(str(d), "two")
    oc.choose(str(d), "11x17")
    text = (d / "order.toml").read_text()
    assert text.count("size =") == 1 and 'size = "11x17"' in text
    assert text.count("orientation =") == 1 and 'orientation = "portrait"' in text
    assert "gap" not in text


def test_a_size_not_offered_is_refused_with_the_previews_reason(tmp_path):
    d = _order(tmp_path, sizes=SIZES)
    before = (d / "order.toml").read_text()
    with pytest.raises(OrderError, match="three is not offered: the tracks span 24%"):
        oc.choose(str(d), "three")
    assert (d / "order.toml").read_text() == before


def test_choose_before_the_preview_is_refused(tmp_path):
    d = _order(tmp_path)
    with pytest.raises(OrderError, match="Run the preview first"):
        oc.choose(str(d), "11x17")


def test_an_unknown_size_is_refused(tmp_path):
    d = _order(tmp_path, sizes=SIZES)
    with pytest.raises(OrderError, match="no size 'poster'"):
        oc.choose(str(d), "poster")


def test_an_order_toml_that_no_longer_loads_is_put_back(tmp_path):
    # A broken title elsewhere in the file: choose must not leave it half-written.
    d = _order(tmp_path, toml='order_number = "TP-26-001"\n', sizes=SIZES)
    before = (d / "order.toml").read_text()
    with pytest.raises(OrderError):
        oc.choose(str(d), "11x17")
    assert (d / "order.toml").read_text() == before


def test_the_cli_choose_command(tmp_path, capsys):
    import scripts.order as order_cli
    d = _order(tmp_path, sizes=SIZES)
    assert order_cli.main(["choose", str(d), "17x22"]) == 0
    assert "17x22" in capsys.readouterr().out
    assert order_cli.main(["choose", str(d), "three"]) == 1
    assert "choose stopped: three is not offered" in capsys.readouterr().err
