# tests/test_order.py
import os

import pytest

from app import order as od

TOML = 'title = "Smith home ground"\nsize = "12x18"\n'


def _order(tmp_path, toml=TOML, files=("trip.gpx",)):
    d = tmp_path / "2026-10-001-smith"
    (d / "in").mkdir(parents=True)
    for name in files:
        (d / "in" / name).write_bytes(b"<gpx/>")
    if toml is not None:
        (d / "order.toml").write_text(toml)
    return d


def test_parse_size_short_side_first():
    assert od.parse_size("18x12") == (12.0, 18.0)
    assert od.parse_size(" 8.5 × 11 ") == (8.5, 11.0)


def test_parse_size_refuses_wider_than_the_printer():
    with pytest.raises(od.OrderError, match="17"):
        od.parse_size("18x24")


@pytest.mark.parametrize("bad", ["big", "0x10", "12", ""])
def test_parse_size_refuses_bad_text(bad):
    with pytest.raises(od.OrderError):
        od.parse_size(bad)


def test_load_and_defaults(tmp_path):
    o = od.load(str(_order(tmp_path, toml='title = "Smith home ground"\n')))
    assert o.title == "Smith home ground"
    assert o.size == (12.0, 18.0) and o.orientation == "portrait"
    assert o.print_in() == (12.0, 18.0)
    assert o.id == "order_2026_10_001_smith"


def test_landscape_swaps_the_print(tmp_path):
    o = od.load(str(_order(tmp_path, toml=TOML + 'orientation = "landscape"\n')))
    assert o.print_in() == (18.0, 12.0)


@pytest.mark.parametrize("toml,match", [
    (None, "order.toml"),
    ('size = "12x18"\n', "title"),
    (TOML + 'orientation = "square"\n', "orientation"),
    ("title = \n", "parse"),
])
def test_load_refuses(tmp_path, toml, match):
    with pytest.raises(od.OrderError, match=match):
        od.load(str(_order(tmp_path, toml=toml)))


def test_track_files_skip_photos_and_dotfiles(tmp_path):
    files = ("b.GPX", "a.kml", "c.kmz", "IMG_1.HEIC", "._b.gpx", "notes.txt")
    o = od.load(str(_order(tmp_path, files=files)))
    assert [p.rsplit("/", 1)[1] for p in o.track_files()] == ["a.kml", "b.GPX", "c.kmz"]


def test_write_state_keeps_manual(tmp_path):
    o = od.load(str(_order(tmp_path)))
    od.set_manual(o, "frame", [1, 2, 3, 4])
    od.write_state(o, {"frame": [0, 0, 1, 1], "manual": {}})
    s = od.read_state(o)
    assert s["manual"] == {"frame": [1, 2, 3, 4]}
    assert s["frame"] == [0, 0, 1, 1]
    assert list((tmp_path / "2026-10-001-smith" / "work").glob("state.*.tmp")) == []


def test_read_state_refuses_a_corrupt_file(tmp_path):
    o = od.load(str(_order(tmp_path)))
    os.makedirs(o.work_dir, exist_ok=True)
    with open(o.state_path, "w") as f:
        f.write('{"frame": [0, 0,')
    with pytest.raises(od.OrderError, match="work/state.json is not readable"):
        od.read_state(o)


def test_failed_state_write_leaves_no_tmp(tmp_path, monkeypatch):
    o = od.load(str(_order(tmp_path)))
    od.write_state(o, {"frame": [0, 0, 1, 1]})

    def boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(od.json, "dump", boom)
    with pytest.raises(OSError, match="disk full"):
        od.write_state(o, {"frame": [0, 0, 2, 2]})
    monkeypatch.undo()
    assert list((tmp_path / "2026-10-001-smith" / "work").glob("state.*.tmp")) == []
    assert od.read_state(o)["frame"] == [0, 0, 1, 1]


def test_inputs_hash_follows_tracks_and_size(tmp_path):
    d = _order(tmp_path)
    h1 = od.load(str(d)).inputs_hash()
    (d / "in" / "trip.gpx").write_bytes(b"<gpx>changed</gpx>")
    h2 = od.load(str(d)).inputs_hash()
    (d / "order.toml").write_text('title = "Smith home ground"\nsize = "8x10"\n')
    h3 = od.load(str(d)).inputs_hash()
    assert len({h1, h2, h3}) == 3


def test_orders_root_env(monkeypatch, tmp_path):
    monkeypatch.setenv("TECOPA_ORDERS_DIR", str(tmp_path))
    assert od.orders_root() == str(tmp_path)
    assert od.cache_path() == str(tmp_path / "_cache" / "aiohttp_cache.sqlite")
