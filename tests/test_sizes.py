# tests/test_sizes.py
import pytest

from app import sizes
from app.order import SIZE_KEYS, OrderError


def test_the_repo_file_has_the_four_sizes():
    rows = sizes.load()
    assert list(rows) == ["11x17", "17x22", "two", "three"] == list(SIZE_KEYS)
    assert rows["11x17"] == {"name": "11 × 17 in", "price": "$69"}
    assert rows["17x22"]["price"] == "$99"
    assert rows["two"] == {"name": "Two panels", "price": "$149"}
    assert rows["three"]["price"] == "$189"


def test_a_returning_client_sees_the_next_year_prices():
    assert [r["price"] for r in sizes.load(returning=True).values()] == ["$59", "$69", "$119", "$159"]
    assert sizes.load(returning=True)["two"]["name"] == "Two panels"


def test_the_repo_file_has_the_prices_shipping_and_links_of_the_design():
    # client intake spec 2026-10-12, decisions 6 and 7, and section 6.1
    rows = sizes.table()
    assert list(rows) == ["11x17", "17x22", "two", "three", "digital"]
    assert {k: (r["price"], r["next_price"], r["shipping"]) for k, r in rows.items()} == {
        "11x17": ("$69", "$59", "$8"), "17x22": ("$99", "$69", "$12"),
        "two": ("$149", "$119", "$16"), "three": ("$189", "$159", "$16"),
        "digital": ("$39", "$25", "")}
    assert rows["digital"]["name"] == "Digital poster"
    # the ten Payment Links made 2026-10-12, one per size and year
    assert rows["digital"]["link"] == "https://buy.stripe.com/fZu5kE4De0RE2Ned51afS0J"
    links = [r[f] for r in rows.values() for f in ("link", "next_link")]
    assert len(set(links)) == 10 and all(l.startswith("https://buy.stripe.com/") for l in links)
    # and the eight member links made 2026-10-12: each print size, both years, no shipping
    member = [r[f] for k, r in rows.items() if k != "digital" for f in sizes.MEMBER_FIELDS]
    assert len(set(member)) == 8 and not set(member) & set(links)
    assert rows["11x17"]["member_link"] == "https://buy.stripe.com/3cI3cwb1CgQC0F65CzafS0T"


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
    (ROWS + '[[size]]\nkey = "four"\nname = "Four"\n', "is not one of 11x17, 17x22, two, three, digital"),
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
                                         r'prise\. A row may have key, name, price, next_price, '
                                         r'shipping, link, next_link, member_link, member_next_link$'):
        sizes.load(_write(tmp_path, _row("11x17", 'prise = "$69"')))
    with pytest.raises(OrderError, match=r'size "three" has unknown fields cost, note\. '
                                         r'A row may have key, name, price, next_price, shipping, '
                                         r'link, next_link, member_link, member_next_link$'):
        sizes.load(_write(tmp_path, _row("three", 'note = "x"\ncost = "$1"')))


def test_an_unknown_key_of_the_file_is_named(tmp_path):
    with pytest.raises(OrderError, match=r'config/sizes\.toml has an unknown key currency\. The file '
                                         r'holds \[\[size\]\] rows, and a row may have key, name, '
                                         r'price, next_price, shipping, link, next_link, member_link, '
                                         r'member_next_link$'):
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
    assert "key, name, price, next_price, shipping, link, next_link,\n#   member_link, member_next_link" \
        in "".join(open(sizes.default_path(), encoding="utf-8")) and "UTF-8" in header
    assert "https://buy.stripe.com/" in header and "digital" in header


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


# Each price of config/sizes.toml that the live pages show, and where. The landing
# page has the tables "Your first poster" and "Next year"; the order page has the
# first-poster prices. On 2026-10-12 the pages show no set price, no next-year set
# price and no shipping: the client intake spec (2026-10-12, section 7) adds them,
# and tests/test_marketing_page.py gets a claim for each. Until then those prices
# are in NOT_ON_THE_PAGES_YET, and this test holds that list to exactly them, so a
# price added to the file is either on a page or named here.
ON_THE_PAGES = {
    ("11x17", "price"): ("landing", "order"), ("17x22", "price"): ("landing", "order"),
    ("digital", "price"): ("landing", "order"),
    ("11x17", "next_price"): ("landing",), ("17x22", "next_price"): ("landing",),
    ("digital", "next_price"): ("landing",),
}
NOT_ON_THE_PAGES_YET = {
    ("two", "price"), ("three", "price"), ("two", "next_price"), ("three", "next_price"),
    ("11x17", "shipping"), ("17x22", "shipping"), ("two", "shipping"), ("three", "shipping"),
}


def test_each_price_of_the_file_is_a_price_of_the_live_pages_or_named_as_not_yet():
    from tests.test_marketing_page import LANDING_PRICES, ORDER_PRICES
    pages = {"landing": LANDING_PRICES, "order": ORDER_PRICES}
    rows = sizes.table()
    priced = {(k, f) for k, r in rows.items() for f in ("price", "next_price", "shipping") if r[f]}
    assert priced == set(ON_THE_PAGES) | NOT_ON_THE_PAGES_YET
    assert not set(ON_THE_PAGES) & NOT_ON_THE_PAGES_YET
    for (key, field), where in ON_THE_PAGES.items():
        for page in where:
            assert rows[key][field] in pages[page], (key, field, page)


# ---- the fields of the client intake: next-year price, shipping, Payment Links ----

LINK = "https://buy.stripe.com/fZu5kE4De0RE2Ned51afS0J"


def test_the_new_fields_are_optional(tmp_path):
    rows = sizes.table(_write(tmp_path, ROWS))
    assert list(rows) == list(SIZE_KEYS)                    # the digital row is optional too
    assert rows["two"] == {"name": "two", "price": "", "next_price": "", "shipping": "",
                           "link": "", "next_link": "", "member_link": "", "member_next_link": ""}
    assert sizes.load(_write(tmp_path, ROWS), returning=True)["two"]["price"] == sizes.NO_PRICE


def test_a_full_row_and_the_digital_row_are_read(tmp_path):
    body = _row("two", f'price = "$149"\nnext_price = "$119"\nshipping = "$16"\nlink = "{LINK}"\n'
                       f'next_link = "https://buy.stripe.com/test_00g5kE"\n'
                       f'member_link = "https://buy.stripe.com/test_m1"\n'
                       f'member_next_link = "https://buy.stripe.com/test_m2"')
    body += f'[[size]]\nkey = "digital"\nname = "Digital poster"\nprice = "$39"\nlink = "{LINK}"\n'
    rows = sizes.table(_write(tmp_path, body))
    assert rows["two"] == {"name": "two", "price": "$149", "next_price": "$119", "shipping": "$16",
                           "link": LINK, "next_link": "https://buy.stripe.com/test_00g5kE",
                           "member_link": "https://buy.stripe.com/test_m1",
                           "member_next_link": "https://buy.stripe.com/test_m2"}
    assert rows["digital"]["price"] == "$39" and list(rows)[-1] == "digital"
    # the PDF never frames the digital poster: load() gives the four sheet sizes only
    assert list(sizes.load(_write(tmp_path, body))) == list(SIZE_KEYS)


@pytest.mark.parametrize("line,words", [
    ("next_price = 59", r'size "two": next_price must be text in quotes, not 59$'),
    ("shipping = 16", r'size "two": shipping must be text in quotes, not 16$'),
    (f'next_price = "{"9" * 25}"', r'size "two": next_price has 25 characters, and the page holds '
                                   r'at most 24$'),
    ("link = 5", r'size "two": link must be a Payment Link, https://buy\.stripe\.com/ and its id, not 5$'),
    ('link = "http://buy.stripe.com/abc"', r'size "two": link must be a Payment Link'),
    ('link = "https://buy.stripe.com.evil.example/abc"', r"link must be a Payment Link"),
    ('link = "https://buy.stripe.com/abc?prefilled_email=a@b.c"', r"link must be a Payment Link"),
    ('link = "https://buy.stripe.com/abc#x"', r"link must be a Payment Link"),
    ('link = "https://buy.stripe.com/"', r"link must be a Payment Link"),
    ('link = "https://buy.stripe.com/a/b"', r"link must be a Payment Link"),
    ('next_link = "https://example.com/abc"', r'size "two": next_link must be a Payment Link'),
    ('next_link = " https://buy.stripe.com/abc"', r"next_link must be a Payment Link"),
    ('member_link = "https://buy.stripe.com/abc?prefilled_promo_code=X"', r'size "two": member_link must be a Payment Link'),
    ("member_next_link = 3", r'size "two": member_next_link must be a Payment Link'),
    (f'link = "https://buy.stripe.com/{"a" * 80}"', r"link must be a Payment Link"),
])
def test_a_wrong_new_field_is_named(tmp_path, line, words):
    with pytest.raises(OrderError, match=words):
        sizes.load(_write(tmp_path, _row("two", line)))


def test_the_digital_poster_ships_nothing(tmp_path):
    body = ROWS + '[[size]]\nkey = "digital"\nname = "Digital poster"\nshipping = "$0"\n'
    with pytest.raises(OrderError, match=r'config/sizes\.toml: size "digital" ships nothing, so it has '
                                         r'no shipping field$'):
        sizes.load(_write(tmp_path, body))
    for field in ("member_link", "member_next_link"):
        body = ROWS + f'[[size]]\nkey = "digital"\nname = "D"\n{field} = "https://buy.stripe.com/abc"\n'
        with pytest.raises(OrderError, match=r'size "digital" ships nothing, so it has no member links$'):
            sizes.load(_write(tmp_path, body))
    with pytest.raises(OrderError, match=r"'digital' is there twice"):
        sizes.load(_write(tmp_path, ROWS + '[[size]]\nkey = "digital"\nname = "D"\n' * 2))
