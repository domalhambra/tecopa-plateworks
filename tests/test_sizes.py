# tests/test_sizes.py
import pytest

from app import sizes
from app.order import SIZE_KEYS, OrderError


def test_the_repo_file_has_the_four_sizes():
    rows = sizes.load()
    assert list(rows) == ["11x17", "17x22", "two", "three"] == list(SIZE_KEYS)
    assert rows["11x17"] == {"name": "11 × 17 in", "price": "$69"}
    assert rows["17x22"]["price"] == "$99"
    assert rows["two"] == {"name": "Two panels", "price": sizes.NO_PRICE}
    assert rows["three"]["price"] == "Price on request"


def _write(tmp_path, body):
    p = tmp_path / "sizes.toml"
    p.write_text(body)
    return str(p)


ROWS = "".join(f'[[size]]\nkey = "{k}"\nname = "{k}"\n' for k in ("11x17", "17x22", "two", "three"))


def test_a_price_is_optional(tmp_path):
    rows = sizes.load(_write(tmp_path, ROWS))
    assert all(r["price"] == sizes.NO_PRICE for r in rows.values())
    rows = sizes.load(_write(tmp_path, ROWS.replace('name = "two"\n', 'name = "two"\nprice = " "\n')))
    assert rows["two"]["price"] == sizes.NO_PRICE


def test_the_rows_come_back_in_menu_order(tmp_path):
    backwards = "".join(f'[[size]]\nkey = "{k}"\nname = "{k}"\n' for k in reversed(SIZE_KEYS))
    assert list(sizes.load(_write(tmp_path, backwards))) == list(SIZE_KEYS)


@pytest.mark.parametrize("body,words", [
    (ROWS + '[[size]]\nkey = "four"\nname = "Four"\n', "is not one of"),
    (ROWS + '[[size]]\nkey = "two"\nname = "Again"\n', "is there twice"),
    (ROWS.replace('[[size]]\nkey = "three"\nname = "three"\n', ""), "has no row for three"),
    (ROWS.replace('name = "two"', 'name = ""'), "needs a name"),
    (ROWS + '[[size]]\nname = "No key"\n', "is not one of"),
    ("size = 3\n", r"must be a list of \[\[size\]\] tables"),
    ('size = ["11x17"]\n', r"must be a list of \[\[size\]\] tables"),
    ("", "has no row for 11x17, 17x22, two, three"),
    ("[[size]\n", "cannot be read"),
])
def test_a_wrong_sizes_file_is_named(tmp_path, body, words):
    with pytest.raises(OrderError, match=words):
        sizes.load(_write(tmp_path, body))


def test_a_missing_sizes_file_is_named(tmp_path):
    with pytest.raises(OrderError, match="cannot be read"):
        sizes.load(str(tmp_path / "nowhere.toml"))
