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


# ---- a name and a price are text, a row has three fields, the file is UTF-8 ----

def _row(key, extra):
    """ROWS with one more line in the row of `key`."""
    return ROWS.replace(f'key = "{key}"\n', f'key = "{key}"\n{extra}\n')


@pytest.mark.parametrize("line,words", [
    ("price = 69", r'config/sizes\.toml: size "two": price must be text in quotes, not 69$'),
    ("price = 69.5", r'size "two": price must be text in quotes, not 69\.5$'),
    ("price = true", r'size "two": price must be text in quotes, not True$'),
    ('price = ["$69"]', r'size "two": price must be text in quotes, not \[\'\$69\'\]$'),
    ("price = 2026-10-11", r'size "two": price must be text in quotes, not '),
])
def test_a_price_that_is_not_text_is_named(tmp_path, line, words):
    with pytest.raises(OrderError, match=words):
        sizes.load(_write(tmp_path, _row("two", line)))


@pytest.mark.parametrize("value,shown", [("1117", "1117"), ("true", "True"), ('["Two"]', r"\['Two'\]")])
def test_a_name_that_is_not_text_is_named(tmp_path, value, shown):
    body = ROWS.replace('name = "two"', f"name = {value}")
    with pytest.raises(OrderError, match=rf'config/sizes\.toml: size "two": name must be text '
                                         rf'in quotes, not {shown}$'):
        sizes.load(_write(tmp_path, body))


def test_an_unknown_field_of_a_row_is_named(tmp_path):
    # `prise = "$69"` was dropped, and the client's page said "Price on request"
    with pytest.raises(OrderError, match=r'config/sizes\.toml: size "11x17" has an unknown field '
                                         r'prise\. A row may have key, name, price$'):
        sizes.load(_write(tmp_path, _row("11x17", 'prise = "$69"')))
    with pytest.raises(OrderError, match=r'size "three" has unknown fields cost, note\. '
                                         r'A row may have key, name, price$'):
        sizes.load(_write(tmp_path, _row("three", 'note = "x"\ncost = "$1"')))


def test_an_unknown_key_of_the_file_is_named(tmp_path):
    with pytest.raises(OrderError, match=r'config/sizes\.toml has an unknown key currency\. The file '
                                         r'holds \[\[size\]\] rows, and a row may have key, name, price$'):
        sizes.load(_write(tmp_path, 'currency = "USD"\n' + ROWS))
    with pytest.raises(OrderError, match=r"has an unknown key sizes\. "):      # [[sizes]] for [[size]]
        sizes.load(_write(tmp_path, ROWS.replace("[[size]]", "[[sizes]]")))


def test_a_file_that_is_not_utf8_is_named(tmp_path):
    # the file holds a multiplication sign: saved as Latin-1 it is not UTF-8
    p = tmp_path / "sizes.toml"
    p.write_bytes(ROWS.replace('name = "11x17"', 'name = "11 × 17 in"').encode("latin-1"))
    with pytest.raises(OrderError, match=r"config/sizes\.toml cannot be read: it is not UTF-8 text"):
        sizes.load(str(p))


def test_the_longest_name_and_price_a_page_holds(tmp_path):
    assert (sizes.NAME_MAX_CHARS, sizes.PRICE_MAX_CHARS) == (40, 24)
    at_the_limit = _row("two", f'price = "{"9" * 24}"').replace('name = "two"', f'name = "{"n" * 40}"')
    assert sizes.load(_write(tmp_path, at_the_limit))["two"] == {"name": "n" * 40, "price": "9" * 24}
    with pytest.raises(OrderError, match=r'config/sizes\.toml: size "two": name has 41 characters, '
                                         r'and the page holds at most 40$'):
        sizes.load(_write(tmp_path, ROWS.replace('name = "two"', f'name = "{"n" * 41}"')))
    with pytest.raises(OrderError, match=r'size "two": name has 500 characters, and the page '
                                         r'holds at most 40$'):
        sizes.load(_write(tmp_path, ROWS.replace('name = "two"', f'name = "{"n" * 500}"')))
    with pytest.raises(OrderError, match=r'config/sizes\.toml: size "17x22": price has 25 characters, '
                                         r'and the page holds at most 24$'):
        sizes.load(_write(tmp_path, _row("17x22", f'price = "{"9" * 25}"')))
    # the shipped names, the words for no price and a realistic price are inside the limits
    assert len(sizes.NO_PRICE) <= sizes.PRICE_MAX_CHARS
    assert sizes.load(_write(tmp_path, _row("three", 'price = "$1,250 framed"')))["three"]["price"] \
        == "$1,250 framed"
    assert all(len(r["name"]) <= 40 and len(r["price"]) <= 24 for r in sizes.load().values())


def test_a_name_and_a_price_are_one_line(tmp_path):
    # a TOML string can hold a line break: the caption and the report give each one line
    body = _row("two", 'price = "$250\\nframed"').replace('name = "two"', 'name = " Two \\t panels "')
    assert sizes.load(_write(tmp_path, body))["two"] == {"name": "Two panels", "price": "$250 framed"}


def test_the_header_of_the_repo_file_states_the_limits():
    with open(sizes.default_path(), encoding="utf-8") as f:
        header = "".join(line for line in f if line.startswith("#"))
    assert f"at most {sizes.NAME_MAX_CHARS} characters" in header
    assert f"at most {sizes.PRICE_MAX_CHARS} characters" in header
    assert "key, name, price" in header and "UTF-8" in header


def test_the_single_sheet_prices_are_the_prices_of_the_live_pages():
    # tests/test_marketing_page.py holds the published pages to these lists (run with
    # -m live). The PDF reads config/sizes.toml, so the two cannot drift apart silently.
    # Importing that file fetches nothing: it only defines functions and constants, and
    # its tests are not collected from here.
    from tests.test_marketing_page import LANDING_PRICES, ORDER_PRICES
    rows = sizes.load()
    for key in ("11x17", "17x22"):
        assert rows[key]["price"] in LANDING_PRICES and rows[key]["price"] in ORDER_PRICES
    assert rows["11x17"]["price"] != rows["17x22"]["price"]
