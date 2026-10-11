# tests/test_order.py
import os

import pytest

from app import order as od
from app import panels as panel_geo

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
    assert o.size == (11.0, 17.0) and o.orientation == "portrait"
    assert o.print_in() == (11.0, 17.0)
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


# ---- an order folder must live outside the repo, which is public ----

def test_load_refuses_a_folder_inside_the_repo(tmp_path, monkeypatch):
    monkeypatch.setattr(od, "_repo_root", lambda: str(tmp_path))
    inside = _order(tmp_path)
    with pytest.raises(od.OrderError, match="Order folders must live outside the "
                                            "repo, which is public"):
        od.load(str(inside))


def test_load_refuses_the_repo_root_itself(tmp_path, monkeypatch):
    monkeypatch.setattr(od, "_repo_root", lambda: str(tmp_path))
    with pytest.raises(od.OrderError, match="Use ~/Tecopa Orders"):
        od.load(str(tmp_path))


def test_load_allows_a_folder_outside_the_patched_repo(tmp_path, monkeypatch):
    monkeypatch.setattr(od, "_repo_root", lambda: str(tmp_path / "repo"))
    outside = _order(tmp_path / "orders")
    od.load(str(outside))   # must not raise


def test_refuse_inside_repo_follows_symlinks(tmp_path, monkeypatch):
    real_repo = tmp_path / "repo"
    real_repo.mkdir()
    monkeypatch.setattr(od, "_repo_root", lambda: str(real_repo))
    link = tmp_path / "link-to-repo"
    link.symlink_to(real_repo)
    inside = _order(link)
    with pytest.raises(od.OrderError, match="Order folders must live outside"):
        od.load(str(inside))


# ---- a set of panels: size "two" or "three", a gap, and the preview's sizes list ----

def test_a_set_is_named_by_a_word():
    assert od.parse_order_size("11x17") == ((11.0, 17.0), 1)
    assert od.parse_order_size(" Two ") == ((17.0, 22.0), 2)
    assert od.parse_order_size("three") == ((17.0, 22.0), 3)
    with pytest.raises(od.OrderError, match='"two" or "three"'):
        od.parse_order_size("four")


def test_a_bad_size_still_says_what_a_size_looks_like():
    with pytest.raises(od.OrderError, match="^size 'big' is not like 11x17"):
        od.parse_size("big")


def test_the_gap_is_zero_two_or_four():
    assert [od.parse_gap(g) for g in (0, 2, 4, 2.0)] == [0.0, 2.0, 4.0, 2.0]
    for bad in (1, "2", True, 3.5, None, float("nan")):
        with pytest.raises(od.OrderError, match="gap must be 0, 2 or 4"):
            od.parse_gap(bad)


def test_a_set_order_has_the_hung_sheet(tmp_path):
    d = _order(tmp_path, 'title = "Long walk"\nsize = "three"\norientation = "landscape"\n')
    o = od.load(d)
    assert (o.panels, o.gap) == (3, 2.0)
    assert o.print_in() == (70.0, 17.0)
    d2 = _order(tmp_path / "b", 'title = "Long walk"\nsize = "three"\ngap = 4\n')
    assert od.load(d2).print_in() == (59.0, 22.0)        # portrait is the default
    d3 = _order(tmp_path / "c", 'title = "Long walk"\nsize = "two"\ngap = 0\n')
    assert od.load(d3).print_in() == (34.0, 22.0)
    d4 = _order(tmp_path / "d", 'title = "Long walk"\nsize = "three"\n')
    assert od.load(d4).print_in() == (55.0, 22.0)


@pytest.mark.parametrize("word,panels", [("two", 2), ("three", 3)])
@pytest.mark.parametrize("gap", [0, 2, 4])
def test_a_set_sheet_is_the_one_the_engine_cuts(tmp_path, word, panels, gap):
    # app.panels owns the geometry; orderplate.widen_for_upsample needs whole inches
    wide, tall = panel_geo.sheet_sizes(panels, gap)
    for orientation, sheet in (("landscape", wide), ("portrait", tall)):
        d = _order(tmp_path / orientation, f'title = "T"\nsize = "{word}"\ngap = {gap}\n'
                                           f'orientation = "{orientation}"\n')
        assert od.load(d).print_in() == sheet
        assert all(float(side).is_integer() for side in sheet)


def test_a_wrong_gap_stops_the_order(tmp_path):
    d = _order(tmp_path, 'title = "Long walk"\nsize = "two"\ngap = 1\n')
    with pytest.raises(od.OrderError, match="gap must be 0, 2 or 4"):
        od.load(d)


def test_a_wrong_set_word_stops_the_order(tmp_path):
    d = _order(tmp_path, 'title = "Long walk"\nsize = "four"\n')
    with pytest.raises(od.OrderError, match='is not like 11x17, and is not "two" or "three"'):
        od.load(d)


def test_the_gap_of_a_single_sheet_is_ignored(tmp_path):
    plain = od.load(_order(tmp_path, 'title = "T"\nsize = "11x17"\n'))
    gapped = od.load(_order(tmp_path / "b", 'title = "T"\nsize = "11x17"\ngap = 4\n'))
    assert (gapped.panels, gapped.gap) == (1, 0.0)
    assert gapped.print_in() == plain.print_in() == (11.0, 17.0)
    assert gapped.inputs_hash() == plain.inputs_hash()
    # a gap that a set would refuse is not read at all on a single sheet
    od.load(_order(tmp_path / "c", 'title = "T"\nsize = "11x17"\ngap = 1\n'))


def test_the_hash_of_a_single_sheet_order_did_not_change(tmp_path):
    import hashlib
    o = od.load(_order(tmp_path, 'title = "T"\nsize = "11x17"\n'))
    h = hashlib.sha256()
    for data, name in o.payloads():
        h.update(name.encode()); h.update(hashlib.sha256(data).digest())
    h.update(repr((o.size, o.orientation)).encode())
    assert o.inputs_hash() == h.hexdigest()
    # the value Prepare stored for this order before a set existed
    assert o.inputs_hash() == ("6d6bbc66e609c88aa38e52d750a48cbb"
                               "459c663c6b10c472a21b6753315ac02b")


def test_the_hash_of_a_set_follows_the_count_and_the_gap(tmp_path):
    def digest(name, toml):
        return od.load(_order(tmp_path / name, toml)).inputs_hash()
    two = digest("a", 'title = "T"\nsize = "two"\n')
    assert two != digest("b", 'title = "T"\nsize = "three"\n')
    assert two != digest("c", 'title = "T"\nsize = "two"\ngap = 4\n')
    assert two != digest("d", 'title = "T"\nsize = "17x22"\n')


def test_the_sizes_list_is_checked(tmp_path):
    o = od.load(_order(tmp_path, 'title = "T"\nsizes = ["11x17", "three"]\n'))
    assert o.sizes == ("11x17", "three")
    assert od.load(_order(tmp_path / "b", 'title = "T"\n')).sizes == ()
    for k, bad in enumerate(('sizes = ["big"]', 'sizes = "three"', 'sizes = []')):
        with pytest.raises(od.OrderError, match="sizes must be a list of 11x17, 17x22, "
                                                "two, three"):
            od.load(_order(tmp_path / f"bad{k}", f'title = "T"\n{bad}\n'))


def test_an_order_built_by_position_is_a_single_sheet():
    o = od.Order("/nowhere", "T", "", (11.0, 17.0), "portrait", "")
    assert (o.panels, o.gap, o.sizes) == (1, 0.0, ())
    assert o.print_in() == (11.0, 17.0)
