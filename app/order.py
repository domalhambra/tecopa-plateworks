# app/order.py
"""One customer order on disk (order pipeline spec, section 1).

    ~/Tecopa Orders/<order>/in/         the customer's files; nothing writes here
                            order.toml  Dom's decisions: title, size, orientation
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

from app.regionbuild import slugify

ORDERS_ENV = "TECOPA_ORDERS_DIR"
TRACK_EXTS = (".gpx", ".kml", ".kmz")
MAX_WIDTH_IN = 17.0            # the PRO-1100 feeds at most 17 in wide
ORIENTATIONS = ("portrait", "landscape")
_SIZE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*[x×]\s*(\d+(?:\.\d+)?)\s*$")


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
    """'12x18' -> (12.0, 18.0), short side first."""
    m = _SIZE.match(str(text))
    if not m:
        raise OrderError(f"size {text!r} is not like 12x18")
    short, long_ = sorted((float(m.group(1)), float(m.group(2))))
    if short <= 0:
        raise OrderError(f"size {text!r} must be larger than zero")
    if short > MAX_WIDTH_IN:
        raise OrderError(f"size {text!r} is wider than the PRO-1100's "
                         f"{MAX_WIDTH_IN:g} in")
    return (short, long_)


@dataclass(frozen=True)
class Order:
    dir: str
    title: str
    subtitle: str
    size: tuple
    orientation: str
    notes: str

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
        """(width, height) in inches as printed."""
        short, long_ = self.size
        return (short, long_) if self.orientation == "portrait" else (long_, short)

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
        """Changes when a track file, the size or the orientation changes."""
        h = hashlib.sha256()
        for data, name in self.payloads():
            h.update(name.encode())
            h.update(hashlib.sha256(data).digest())
        h.update(repr((self.size, self.orientation)).encode())
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
    return Order(dir=folder, title=title,
                 subtitle=str(cfg.get("subtitle", "")).strip(),
                 size=parse_size(cfg.get("size", "12x18")),
                 orientation=orientation, notes=str(cfg.get("notes", "")))


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
