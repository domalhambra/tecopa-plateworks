# app/order.py
"""One customer order on disk (order pipeline spec, section 1).

    ~/Tecopa Orders/<order>/in/         the customer's files; only `order new` writes
                                        here, and it adds a file and replaces none
                            order.toml  Dom's decisions: title, size, orientation;
                                        a set's gap; the preview's sizes. From the
                                        intake: order_number, returning, client, email
                            work/       plate/, state.json, report.txt
                            out/        print and customer files (later sub-projects)

Customer data stays outside the repo, which is public. TECOPA_ORDERS_DIR moves the
root. state.json holds what Prepare and the studio decide; its "manual" key holds
Dom's studio changes, and Prepare never erases them."""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import tomllib
from dataclasses import dataclass

from app import panels as panel_geo
from app.regionbuild import slugify

ORDERS_ENV = "TECOPA_ORDERS_DIR"
TRACK_EXTS = (".gpx", ".kml", ".kmz")
MAX_WIDTH_IN = 17.0            # the PRO-1100 feeds at most 17 in wide
DEFAULT_SIZE = "11x17"         # the menu is 11x17 and 17x22 (decisions, 2026-10-10)
ORIENTATIONS = ("portrait", "landscape")
SET_SIZES = {"two": 2, "three": 3}     # a set of 17 x 22 in panels (spec, 2026-10-11)
DEFAULT_GAP = 2.0                      # inches between two panels on the wall
SIZE_KEYS = ("11x17", "17x22", "two", "three")     # what a preview can offer
_SIZE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*[x×]\s*(\d+(?:\.\d+)?)\s*$")
# The intake's order number, TP-YY-NNN (client intake spec, 2026-10-12). It ends a
# Payment Link, so nothing but these characters may be in it.
ORDER_NUMBER = re.compile(r"TP-[0-9]{2}-[0-9]{3,5}")
# An address for the To line of the preview email: one @, no space, no character that
# a mail header or a URL reads as a separator.
EMAIL = re.compile(r"[A-Za-z0-9.!#$%&'*+/=^_`{|}~-]{1,64}@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
CLIENT_MAX_CHARS = 80


class OrderError(ValueError):
    """The order folder or its order.toml is not usable. The message is for Dom."""


def orders_root() -> str:
    return os.environ.get(ORDERS_ENV) or os.path.join(os.path.expanduser("~"),
                                                      "Tecopa Orders")


def cache_path() -> str:
    """The HyRiver request cache every order's plate build shares."""
    return os.path.join(orders_root(), "_cache", "aiohttp_cache.sqlite")


def _repo_root() -> str:
    """This checkout's root: the parent of the `app` package dir. A test
    monkeypatches this to point the inside-the-repo check at a throwaway tmp dir."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def refuse_inside_repo(path) -> None:
    """Raise OrderError if `path` resolves (realpath, so a symlink can't dodge it)
    inside this repo. The repo is public; an order folder holds a customer's
    private tracks and photos, and TECOPA_ORDERS_DIR must not point into it either."""
    repo = os.path.realpath(_repo_root())
    real = os.path.realpath(os.path.abspath(os.path.expanduser(str(path))))
    if real == repo or real.startswith(repo + os.sep):
        raise OrderError(f"Order folders must live outside the repo, which is "
                         f"public: {path}. Use ~/Tecopa Orders.")


def parse_size(text) -> tuple:
    """'17x11' -> (11.0, 17.0), short side first."""
    m = _SIZE.match(str(text))
    if not m:
        raise OrderError(f'size {text!r} is not like 11x17, and is not "two" or "three"')
    short, long_ = sorted((float(m.group(1)), float(m.group(2))))
    if short <= 0:
        raise OrderError(f"size {text!r} must be larger than zero")
    if short > MAX_WIDTH_IN:
        raise OrderError(f"size {text!r} is wider than the PRO-1100's "
                         f"{MAX_WIDTH_IN:g} in")
    return (short, long_)


def parse_order_size(text) -> tuple:
    """'11x17' -> ((11.0, 17.0), 1). 'two' -> ((17.0, 22.0), 2): a set, by its panel."""
    key = str(text).strip().lower()
    if key in SET_SIZES:
        return ((panel_geo.PANEL_SHORT_IN, panel_geo.PANEL_LONG_IN), SET_SIZES[key])
    return (parse_size(text), 1)


def parse_gap(value) -> float:
    """The gap of a set, in inches: 0, 2 or 4."""
    # membership on the value itself: float() of a 400-digit integer overflows
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or value not in panel_geo.GAPS_IN):
        text = repr(value) if len(repr(value)) <= 40 else repr(value)[:40] + "..."
        raise OrderError(f"gap must be 0, 2 or 4 (inches), not {text}")
    return float(value) + 0.0          # -0.0 becomes 0.0: one hash, and "0 in gap"


def parse_sizes(value) -> tuple:
    """The sizes a preview must offer, from order.toml. () means the fit rule decides."""
    if value is None:
        return ()
    if (not isinstance(value, list) or not value
            or any(not isinstance(v, str) or v not in SIZE_KEYS for v in value)):
        raise OrderError(f"sizes must be a list of {', '.join(SIZE_KEYS)}, not {value!r}")
    return tuple(value)


def parse_order_number(value) -> str:
    """The intake's order number, or "" for an order made before the intake."""
    if value is None:
        return ""
    if not isinstance(value, str) or not ORDER_NUMBER.fullmatch(value):
        raise OrderError(f"order_number must be like TP-26-001, not {value!r}")
    return value


def parse_returning(value) -> bool:
    """True for a next-year order: the next-year prices and Payment Links."""
    if value is None:
        return False
    if not isinstance(value, bool):
        raise OrderError(f"returning must be true or false, not {value!r}")
    return value


def parse_client(value) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise OrderError(f"client must be text in quotes, not {value!r}")
    value = " ".join(value.split())
    if len(value) > CLIENT_MAX_CHARS:
        raise OrderError(f"client has {len(value)} characters, and the most is {CLIENT_MAX_CHARS}")
    return value


def parse_email(value) -> str:
    if value is None:
        return ""
    if not isinstance(value, str) or len(value) > 254 or not EMAIL.fullmatch(value):
        raise OrderError(f"email {value!r} is not an email address")
    return value


@dataclass(frozen=True)
class Order:
    dir: str
    title: str
    subtitle: str
    size: tuple
    orientation: str
    notes: str
    panels: int = 1          # 2 or 3: a set of 17 x 22 in panels
    gap: float = 0.0         # inches between two panels; 0.0 for a single sheet
    sizes: tuple = ()        # the preview's override list
    order_number: str = ""   # TP-26-001, from the intake; "" for an older order
    returning: bool = False  # a next-year order: the next-year prices and links
    client: str = ""         # the client's name, for the preview email
    email: str = ""          # the client's address, for the To line of that email

    @property
    def id(self) -> str:
        return "order_" + slugify(os.path.basename(os.path.normpath(self.dir)))

    @property
    def in_dir(self) -> str:
        return os.path.join(self.dir, "in")

    @property
    def work_dir(self) -> str:
        return os.path.join(self.dir, "work")

    @property
    def plate_root(self) -> str:
        return os.path.join(self.work_dir, "plate")

    @property
    def state_path(self) -> str:
        return os.path.join(self.work_dir, "state.json")

    def print_in(self) -> tuple:
        """(width, height) in inches as printed. A set gives its hung sheet, gaps
        included: landscape is panels 22 in across, portrait is 17 in across."""
        short, long_ = self.size
        landscape = self.orientation != "portrait"
        if self.panels > 1:
            across = long_ if landscape else short
            return (self.panels * across + (self.panels - 1) * self.gap,
                    short if landscape else long_)
        return (long_, short) if landscape else (short, long_)

    def track_files(self) -> list:
        if not os.path.isdir(self.in_dir):
            return []
        return sorted(os.path.join(self.in_dir, f) for f in os.listdir(self.in_dir)
                      if not f.startswith(".") and f.lower().endswith(TRACK_EXTS))

    def payloads(self) -> list:
        """(bytes, filename) pairs, the shape app.ingest reads."""
        out = []
        for path in self.track_files():
            with open(path, "rb") as f:
                out.append((f.read(), os.path.basename(path)))
        return out

    def inputs_hash(self) -> str:
        """Changes when a track file, the size, the orientation, or a set's panel
        count or gap changes."""
        h = hashlib.sha256()
        for data, name in self.payloads():
            h.update(name.encode())
            h.update(hashlib.sha256(data).digest())
        h.update(repr((self.size, self.orientation)).encode())
        if self.panels > 1:        # a single sheet's hash is what it always was
            h.update(repr((self.panels, self.gap)).encode())
        return h.hexdigest()


def load(folder) -> Order:
    folder = os.path.abspath(os.path.expanduser(str(folder)))
    refuse_inside_repo(folder)
    toml_path = os.path.join(folder, "order.toml")
    if not os.path.isfile(toml_path):
        raise OrderError(f"no order.toml in {folder}")
    try:
        with open(toml_path, "rb") as f:
            cfg = tomllib.load(f)
    except tomllib.TOMLDecodeError as ex:
        raise OrderError(f"order.toml does not parse: {ex}") from ex
    title = str(cfg.get("title", "")).strip()
    if not title:
        raise OrderError("order.toml needs a title")
    orientation = str(cfg.get("orientation", "portrait")).lower()
    if orientation not in ORIENTATIONS:
        raise OrderError(f"orientation must be portrait or landscape, not {orientation!r}")
    size, panels = parse_order_size(cfg.get("size", DEFAULT_SIZE))
    gap = parse_gap(cfg.get("gap", DEFAULT_GAP)) if panels > 1 else 0.0
    return Order(dir=folder, title=title,
                 subtitle=str(cfg.get("subtitle", "")).strip(),
                 size=size, orientation=orientation, notes=str(cfg.get("notes", "")),
                 panels=panels, gap=gap, sizes=parse_sizes(cfg.get("sizes")),
                 order_number=parse_order_number(cfg.get("order_number")),
                 returning=parse_returning(cfg.get("returning")),
                 client=parse_client(cfg.get("client")), email=parse_email(cfg.get("email")))


def read_state(order: Order) -> dict:
    try:
        with open(order.state_path) as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except ValueError as ex:
        raise OrderError(f"work/state.json is not readable ({ex}). "
                         "Fix or delete it, then run Prepare again.") from ex


def write_state(order: Order, updates: dict) -> dict:
    """Merge `updates` into state.json. The "manual" key is skipped: only set_manual
    writes it, so Prepare can never erase a studio change."""
    state = read_state(order)
    for key, value in updates.items():
        if key != "manual":
            state[key] = value
    _dump(order, state)
    return state


def set_manual(order: Order, key: str, value) -> dict:
    state = read_state(order)
    state.setdefault("manual", {})[key] = value
    _dump(order, state)
    return state


def _dump(order: Order, state: dict) -> None:
    """Write through a unique temp file, so two writers at once (Prepare and the
    studio) never share a temp name, and a reader never sees half a file."""
    os.makedirs(order.work_dir, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=order.work_dir, prefix="state.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(state, f, indent=2)
        os.replace(tmp, order.state_path)
    except BaseException:
        try:
            os.remove(tmp)
        except FileNotFoundError:
            pass
        raise
