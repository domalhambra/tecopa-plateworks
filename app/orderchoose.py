"""Choose an order's size from its preview: `scripts/order.py choose <folder> <size>`.

The preview (app/orderpreview.py) frames every size and, for each offered one, prints
the lines to paste into order.toml (docs/changing-things.md > Run an order, step 5).
This writes those same lines for one size, so the Mac app never edits order.toml
itself (native Mac app phase 2 spec, decision 7). It changes only the top-level
`size`, `orientation` and `gap` lines and keeps every other line, comments too. The
result must load (app/order.load), or the old file is put back."""
from __future__ import annotations

import json
import os
import re

from app import order as od
from app.order import OrderError

_KEYS = ("size", "orientation", "gap")


def _line_key(line: str):
    m = re.match(r"\s*([A-Za-z_][A-Za-z0-9_]*)\s*=", line)
    return m.group(1) if m else None


def choose(folder: str, key: str) -> str:
    """Write the preview's lines for size `key` into order.toml. Return a report."""
    folder = os.path.abspath(os.path.expanduser(folder))
    od.refuse_inside_repo(folder)
    path = os.path.join(folder, "work", "preview", "preview.json")
    if not os.path.isfile(path):
        raise OrderError("Run the preview first: work/preview/preview.json is missing.")
    with open(path, encoding="utf-8") as f:
        sizes = json.load(f).get("sizes", [])
    entry = next((e for e in sizes if e.get("key") == key), None)
    if entry is None:
        known = ", ".join(e.get("key", "?") for e in sizes)
        raise OrderError(f"The preview has no size '{key}'. It has {known}.")
    if not entry.get("offered"):
        why = " ".join(str(entry.get("why", "")).split()).rstrip(".")
        raise OrderError(f"{key} is not offered: {why}.")

    want = {"size": f'"{entry["key"]}"', "orientation": f'"{entry["orientation"]}"'}
    if int(entry.get("panels", 1)) > 1:
        want["gap"] = f'{float(entry["gap"]):g}'

    toml = os.path.join(folder, "order.toml")
    with open(toml, encoding="utf-8") as f:
        before = f.read()
    kept, in_table = [], False
    for line in before.splitlines():
        if line.lstrip().startswith("["):
            in_table = True
        if not in_table and _line_key(line) in _KEYS:
            continue
        kept.append(line)
    # Top-level keys must come before any [table] in TOML.
    first_table = next((i for i, l in enumerate(kept) if l.lstrip().startswith("[")), len(kept))
    new_lines = [f"{k} = {v}" for k, v in want.items()]
    after = "\n".join(kept[:first_table] + new_lines + kept[first_table:]) + "\n"
    tmp = toml + ".choose-tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(after)
    os.replace(tmp, toml)
    try:
        od.load(folder)
    except OrderError:
        with open(toml, "w", encoding="utf-8") as f:
            f.write(before)
        raise
    return (f"Chose {entry['key']}, {entry['orientation']}. order.toml now has:\n"
            + "\n".join(f"    {l}" for l in new_lines) + "\n")
