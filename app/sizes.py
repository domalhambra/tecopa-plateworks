# app/sizes.py
"""The names and prices of the sizes, as data. Dom owns config/sizes.toml.

The file is read before a preview builds anything, and it is read strictly: a client
reads these words, so a wrong file stops the preview and never prints a guess. A name
and a price are TOML strings, a row has no other field than `key`, `name` and `price`,
and both have a length the page can hold."""
import os
import tomllib

from app.order import SIZE_KEYS, OrderError

NO_PRICE = "Price on request"
ROW_FIELDS = ("key", "name", "price")
# What the preview's pages hold (app/previewpdf.py): on the wall page a caption wraps
# at 3.2 in, and a longer name makes every size smaller. The shipped names are 10 to
# 12 characters, and "$1,250 framed" is 13.
NAME_MAX_CHARS = 40
PRICE_MAX_CHARS = 24
_LIMITS = {"name": NAME_MAX_CHARS, "price": PRICE_MAX_CHARS}
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


def load(path=None) -> dict:
    """{key: {"name", "price"}} in menu order. Every size must have a row."""
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
    table = cfg.get("size", [])
    if not isinstance(table, list) or any(not isinstance(row, dict) for row in table):
        raise OrderError(f"{_FILE}: size must be a list of [[size]] tables")
    rows = {}
    for row in table:
        key = row.get("key")
        if not isinstance(key, str) or key not in SIZE_KEYS:
            raise OrderError(f"{_FILE}: {key!r} is not one of {', '.join(SIZE_KEYS)}")
        if key in rows:
            raise OrderError(f"{_FILE}: {key!r} is there twice")
        unknown = sorted(k for k in row if k not in ROW_FIELDS)
        if unknown:
            raise OrderError(f'{_FILE}: size "{key}" has {_fields(unknown)}. '
                             f"A row may have {', '.join(ROW_FIELDS)}")
        name = _text(row, key, "name")
        if not name:
            raise OrderError(f"{_FILE}: {key!r} needs a name")
        rows[key] = {"name": name, "price": _text(row, key, "price") or NO_PRICE}
    missing = [k for k in SIZE_KEYS if k not in rows]
    if missing:
        raise OrderError(f"{_FILE} has no row for {', '.join(missing)}")
    return {k: rows[k] for k in SIZE_KEYS}
