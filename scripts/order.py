"""Run one customer order. Sub-project 1 ships `prepare`: the plate, the frame,
work/state.json and work/report.txt. See docs/changing-things.md > Run an order.

    .venv/bin/python scripts/order.py prepare "~/Tecopa Orders/2026-10-001-smith"
"""
import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.order import OrderError  # noqa: E402
from app.orderplate import PlateError  # noqa: E402
from app.orderprep import default_tools, prepare  # noqa: E402


def main(argv=None, tools=None) -> int:
    """`tools` is for tests only: stub subprocesses in place of the real ones."""
    ap = argparse.ArgumentParser(prog="order.py", description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prepare", help="build or reuse the order's plate and frame the tracks")
    p.add_argument("folder", help="the order folder, holding in/ and order.toml")
    args = ap.parse_args(argv)
    folder = os.path.abspath(os.path.expanduser(args.folder))
    try:
        prepare(folder, tools or default_tools(ROOT))
    except (OrderError, PlateError, RuntimeError) as ex:
        print(f"prepare stopped: {ex}", file=sys.stderr)
        return 1
    with open(os.path.join(folder, "work", "report.txt")) as f:
        print(f.read(), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
