"""Run one customer order: `preview` and `prepare`. `preview` frames every size,
builds a coarse plate and writes out/preview/<title>-preview.pdf for the client, with
work/preview/report.txt. `prepare` builds the plate and the frame of the size in
order.toml, with work/state.json and work/report.txt. See docs/changing-things.md >
Run an order.

    .venv/bin/python scripts/order.py preview "~/Tecopa Orders/2026-10-001-smith"
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
from app.orderpreview import preview  # noqa: E402
from app.spec import SpecError  # noqa: E402


def main(argv=None, tools=None) -> int:
    """`tools` is for tests only: stub subprocesses in place of the real ones."""
    ap = argparse.ArgumentParser(prog="order.py", description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prepare", help="build or reuse the order's plate and frame the tracks")
    p.add_argument("folder", help="the order folder, holding in/ and order.toml")
    v = sub.add_parser("preview", help="frame every size, build a coarse plate and "
                                       "write the preview PDF")
    v.add_argument("folder", help="the order folder, holding in/ and order.toml")
    args = ap.parse_args(argv)
    folder = os.path.abspath(os.path.expanduser(args.folder))
    run, report = {"prepare": (prepare, ("work", "report.txt")),
                   "preview": (preview, ("work", "preview", "report.txt"))}[args.cmd]
    try:
        run(folder, tools or default_tools(ROOT))
    except (OrderError, PlateError, RuntimeError, SpecError) as ex:
        print(f"{args.cmd} stopped: {ex}", file=sys.stderr)
        return 1
    with open(os.path.join(folder, *report)) as f:
        print(f.read(), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
