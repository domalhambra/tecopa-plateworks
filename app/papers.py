# app/papers.py
"""The papers the Lab prints on, as data. Dom owns config/papers.toml.

The table is read before anything prints, and it is read strictly, like
config/sizes.toml: UTF-8, a row has the PAPER_FIELDS and no other, every field is
required, `intent` is one of INTENTS, `roll_in` is above 0, and `enabled` is true or
false. `enabled_paper` is the one paper every print uses: exactly one row is enabled.

`feed_rotation` says which way a piece goes through the printer. The roll is
`roll_in` wide, so the side of the piece that fits across the roll goes across it
(plan decision P6).

This module imports nothing from app.main (plan decision P8)."""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass

INTENTS = ("perceptual", "relative")
PAPER_FIELDS = ("key", "name", "roll_in", "profile", "intent", "preset", "enabled")
_FILE = "config/papers.toml"
_TOL = 1e-6


class PaperError(ValueError):
    """The paper table, or a piece that the roll cannot take, is wrong."""


@dataclass(frozen=True)
class Paper:
    key: str
    name: str
    roll_in: float
    profile: str
    intent: str
    preset: str
    enabled: bool


def _repo_root() -> str:
    """This checkout's root: the parent of the `app` package dir (as app/order.py)."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


PAPERS_PATH = os.path.join(_repo_root(), "config", "papers.toml")


def _text(row, key, field) -> str:
    value = row.get(field)
    if not isinstance(value, str) or not value.strip():
        raise PaperError(f'{_FILE}: paper "{key}": {field} must be text in quotes, '
                         f"not {value!r}")
    return value


def _paper(row) -> Paper:
    key = row.get("key")
    if not isinstance(key, str) or not key.strip():
        raise PaperError(f"{_FILE}: a paper needs a key in quotes, not {key!r}")
    unknown = sorted(k for k in row if k not in PAPER_FIELDS)
    if unknown:
        raise PaperError(f'{_FILE}: paper "{key}" has an unknown field '
                         f"{', '.join(unknown)}. A row has {', '.join(PAPER_FIELDS)}")
    missing = [f for f in PAPER_FIELDS if f not in row]
    if missing:
        raise PaperError(f'{_FILE}: paper "{key}" has no {", ".join(missing)}. '
                         f"A row has {', '.join(PAPER_FIELDS)}")
    roll = row["roll_in"]
    if isinstance(roll, bool) or not isinstance(roll, (int, float)) or not roll > 0:
        raise PaperError(f'{_FILE}: paper "{key}": roll_in must be a number above 0, '
                         f"not {roll!r}")
    intent = _text(row, key, "intent")
    if intent not in INTENTS:
        raise PaperError(f'{_FILE}: paper "{key}": intent must be one of '
                         f"{', '.join(INTENTS)}, not {intent!r}")
    if not isinstance(row["enabled"], bool):
        raise PaperError(f'{_FILE}: paper "{key}": enabled must be true or false '
                         f"with no quotes, not {row['enabled']!r}")
    return Paper(key=key, name=_text(row, key, "name"), roll_in=roll,
                 profile=_text(row, key, "profile"), intent=intent,
                 preset=_text(row, key, "preset"), enabled=row["enabled"])


def load_papers(path=PAPERS_PATH) -> list[Paper]:
    """Every row of the table, in file order. Raises PaperError on a wrong file."""
    try:
        with open(path, "rb") as f:
            cfg = tomllib.load(f)
    except UnicodeDecodeError as ex:
        raise PaperError(f"{_FILE} cannot be read: it is not UTF-8 text ({ex}). "
                         f"Save it as UTF-8.") from ex
    except (OSError, tomllib.TOMLDecodeError) as ex:
        raise PaperError(f"{_FILE} cannot be read: {ex}") from ex
    unknown = sorted(k for k in cfg if k != "paper")
    if unknown:
        raise PaperError(f"{_FILE} has an unknown key {', '.join(unknown)}. The file "
                         f"holds [[paper]] rows")
    rows_in = cfg.get("paper", [])
    if not isinstance(rows_in, list) or any(not isinstance(r, dict) for r in rows_in):
        raise PaperError(f"{_FILE}: paper must be a list of [[paper]] tables")
    rows = [_paper(r) for r in rows_in]
    seen = set()
    for p in rows:
        if p.key in seen:
            raise PaperError(f'{_FILE}: paper "{p.key}" is there twice')
        seen.add(p.key)
    return rows


def enabled_paper(path=PAPERS_PATH) -> Paper:
    """The one paper with enabled = true. None, or more than one, is refused."""
    on = [p for p in load_papers(path) if p.enabled]
    if len(on) != 1:
        raise PaperError(f"{_FILE} must have exactly one paper with enabled = true, "
                         f"and it has {len(on)}")
    return on[0]


def feed_rotation(w_in: float, h_in: float, roll_in: float) -> int:
    """0 or 90: the degrees counter-clockwise that turn a w_in x h_in piece so that
    a side of `roll_in` goes across the roll. A piece whose width fits prints as it
    is; one whose height fits turns 90; one with no side that fits is refused."""
    if abs(w_in - roll_in) <= _TOL:
        return 0
    if abs(h_in - roll_in) <= _TOL:
        return 90
    raise PaperError(f"A {w_in:g} x {h_in:g} in piece does not fit the {roll_in:g} in "
                     f"roll: neither side is {roll_in:g} in")
