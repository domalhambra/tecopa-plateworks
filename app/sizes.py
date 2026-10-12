# app/sizes.py
"""The names, prices, shipping and Payment Links of the sizes, as data. Dom owns
config/sizes.toml.

The file is read before a preview builds anything, and it is read strictly: a client
reads these words, so a wrong file stops the preview and never prints a guess. A name,
a price and a shipping charge are TOML strings, a row has no other field than
ROW_FIELDS, and each text has a length the page can hold. A Payment Link is a
https://buy.stripe.com/ address and nothing more: the preview email adds the order
number to it (client intake spec, 2026-10-12, section 5.2).

The four sheet sizes are the rows the preview frames. The row `digital` is the digital
poster: it is in the preview email and never in the PDF, and it ships nothing."""
import os
import re
import tomllib

from app.order import SIZE_KEYS, OrderError

NO_PRICE = "Price on request"
DIGITAL = "digital"
ROW_KEYS = SIZE_KEYS + (DIGITAL,)
ROW_FIELDS = ("key", "name", "price", "next_price", "shipping", "link", "next_link")
TEXT_FIELDS = ("name", "price", "next_price", "shipping")
LINK_FIELDS = ("link", "next_link")
# What the preview's pages hold (app/previewpdf.py): on the wall page a caption wraps
# at 3.2 in, and a longer name makes every size smaller. The shipped names are 10 to
# 14 characters, and "$1,250 framed" is 13.
NAME_MAX_CHARS = 40
PRICE_MAX_CHARS = 24
_LIMITS = {"name": NAME_MAX_CHARS, "price": PRICE_MAX_CHARS,
           "next_price": PRICE_MAX_CHARS, "shipping": PRICE_MAX_CHARS}
# A Payment Link's id is letters, digits and "_" (a test-mode link starts "test_").
# No query and no fragment: the email appends ?client_reference_id=<order number>.
PAYMENT_LINK = re.compile(r"https://buy\.stripe\.com/[A-Za-z0-9_]{1,64}")
_FILE = "config/sizes.toml"


def default_path() -> str:
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "config", "sizes.toml")


def _fields(names) -> str:
    return ("an unknown field " if len(names) == 1 else "unknown fields ") + ", ".join(names)


def _text(row, key, field) -> str:
    """One field of a row as one line of text. Anything but a TOML string is refused:
    `price = 69` would print as "69", and `name = 1117` as "1117"."""
    value = row.get(field, "")
    if not isinstance(value, str):
        raise OrderError(f'{_FILE}: size "{key}": {field} must be text in quotes, not {value}')
    value = " ".join(value.split())
    if len(value) > _LIMITS[field]:
        raise OrderError(f'{_FILE}: size "{key}": {field} has {len(value)} characters, '
                         f"and the page holds at most {_LIMITS[field]}")
    return value


def _link(row, key, field) -> str:
    """A Payment Link, or "" when the row has none yet."""
    value = row.get(field, "")
    if value == "":
        return ""
    if not isinstance(value, str) or not PAYMENT_LINK.fullmatch(value):
        shown = repr(value) if isinstance(value, str) else value
        raise OrderError(f'{_FILE}: size "{key}": {field} must be a Payment Link, '
                         f"https://buy.stripe.com/ and its id, not {shown}")
    return value


def table(path=None) -> dict:
    """{key: {name, price, next_price, shipping, link, next_link}} for each row of the
    file: the four sheet sizes in menu order, then `digital` when it has a row. A field
    that is not in the file is "". Every sheet size must have a row."""
    path = path or default_path()
    try:
        with open(path, "rb") as f:
            cfg = tomllib.load(f)
    except UnicodeDecodeError as ex:
        raise OrderError(f"{_FILE} cannot be read: it is not UTF-8 text ({ex}). "
                         f"Save it as UTF-8.") from ex
    except (OSError, tomllib.TOMLDecodeError) as ex:
        raise OrderError(f"{_FILE} cannot be read: {ex}") from ex
    unknown = sorted(k for k in cfg if k != "size")
    if unknown:
        raise OrderError(f"{_FILE} has an unknown key {', '.join(unknown)}. The file holds "
                         f"[[size]] rows, and a row may have {', '.join(ROW_FIELDS)}")
    rows_in = cfg.get("size", [])
    if not isinstance(rows_in, list) or any(not isinstance(row, dict) for row in rows_in):
        raise OrderError(f"{_FILE}: size must be a list of [[size]] tables")
    rows = {}
    for row in rows_in:
        key = row.get("key")
        if not isinstance(key, str) or key not in ROW_KEYS:
            raise OrderError(f"{_FILE}: {key!r} is not one of {', '.join(ROW_KEYS)}")
        if key in rows:
            raise OrderError(f"{_FILE}: {key!r} is there twice")
        unknown = sorted(k for k in row if k not in ROW_FIELDS)
        if unknown:
            raise OrderError(f'{_FILE}: size "{key}" has {_fields(unknown)}. '
                             f"A row may have {', '.join(ROW_FIELDS)}")
        if key == DIGITAL and "shipping" in row:
            raise OrderError(f'{_FILE}: size "{key}" ships nothing, so it has no shipping field')
        out = {field: _text(row, key, field) for field in TEXT_FIELDS}
        if not out["name"]:
            raise OrderError(f"{_FILE}: {key!r} needs a name")
        out.update({field: _link(row, key, field) for field in LINK_FIELDS})
        rows[key] = out
    missing = [k for k in SIZE_KEYS if k not in rows]
    if missing:
        raise OrderError(f"{_FILE} has no row for {', '.join(missing)}")
    return {k: rows[k] for k in ROW_KEYS if k in rows}


def load(path=None, returning=False) -> dict:
    """{key: {"name", "price"}} of the four sheet sizes in menu order: what the PDF
    prints. `returning` gives the next-year prices. A size with no price for this
    client prints NO_PRICE."""
    rows = table(path)
    field = "next_price" if returning else "price"
    return {k: {"name": rows[k]["name"], "price": rows[k][field] or NO_PRICE} for k in SIZE_KEYS}
