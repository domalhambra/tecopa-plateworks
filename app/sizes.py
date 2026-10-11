# app/sizes.py
"""The names and prices of the sizes, as data. Dom owns config/sizes.toml."""
import os
import tomllib

from app.order import SIZE_KEYS, OrderError

NO_PRICE = "Price on request"


def default_path() -> str:
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "config", "sizes.toml")


def load(path=None) -> dict:
    """{key: {"name", "price"}} in menu order. Every size must have a row."""
    path = path or default_path()
    try:
        with open(path, "rb") as f:
            cfg = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError) as ex:
        raise OrderError(f"config/sizes.toml cannot be read: {ex}") from ex
    table = cfg.get("size", [])
    if not isinstance(table, list) or any(not isinstance(row, dict) for row in table):
        raise OrderError("config/sizes.toml: size must be a list of [[size]] tables")
    rows = {}
    for row in table:
        key = row.get("key")
        if key not in SIZE_KEYS:
            raise OrderError(f"config/sizes.toml: {key!r} is not one of {', '.join(SIZE_KEYS)}")
        if key in rows:
            raise OrderError(f"config/sizes.toml: {key!r} is there twice")
        name = str(row.get("name", "")).strip()
        if not name:
            raise OrderError(f"config/sizes.toml: {key!r} needs a name")
        rows[key] = {"name": name, "price": str(row.get("price", "")).strip() or NO_PRICE}
    missing = [k for k in SIZE_KEYS if k not in rows]
    if missing:
        raise OrderError(f"config/sizes.toml has no row for {', '.join(missing)}")
    return {k: rows[k] for k in SIZE_KEYS}
