"""Run one customer order: `new`, `preview`, `prepare` and `finish`. `new` copies the intake's
job folder from Dropbox into a new order folder with order.toml. `preview` frames every size,
builds a coarse plate and writes out/preview/<title>-preview.pdf for the client, with
work/preview/report.txt. `prepare` builds the plate and the frame of the size in
order.toml, with work/state.json and work/report.txt. `finish` writes the print TIFFs
and out/print/PRINT.txt of an order whose proof Dom approved in the studio. See
docs/changing-things.md > Run an order.

    .venv/bin/python scripts/order.py new TP-26-001
    .venv/bin/python scripts/order.py preview "~/Tecopa Orders/TP-26-001-smith"
    .venv/bin/python scripts/order.py prepare "~/Tecopa Orders/TP-26-001-smith"
    .venv/bin/python scripts/order.py finish "~/Tecopa Orders/TP-26-001-smith"
"""
import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app import ordernew, orderfinish  # noqa: E402
from app.order import OrderError  # noqa: E402
from app.orderplate import PlateError  # noqa: E402
from app.orderprep import default_tools, prepare  # noqa: E402
from app.orderpreview import preview  # noqa: E402
from app.papers import PaperError  # noqa: E402
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
    f = sub.add_parser("finish", help="write the print TIFFs and PRINT.txt of an approved order")
    f.add_argument("folder", help="the order folder, holding in/ and order.toml")
    n = sub.add_parser("new", help="copy the intake's job folder from Dropbox into a new "
                                   "order folder, and write its order.toml")
    n.add_argument("number", help="the order number, like TP-26-001")
    args = ap.parse_args(argv)
    if args.cmd == "new":
        try:
            report = ordernew.new(args.number)
        except (OrderError, OSError) as ex:
            print(f"new stopped: {ex}", file=sys.stderr)
            return 1
        print(report, end="")
        return 0
    folder = os.path.abspath(os.path.expanduser(args.folder))
    if args.cmd == "finish":
        try:
            result = orderfinish.finish(folder, log=lambda m: print(m, file=sys.stderr))
        except (OrderError, PaperError, SpecError, RuntimeError, OSError) as ex:
            print(f"finish stopped: {ex}", file=sys.stderr)
            return 1
        with open(result["print_note"], encoding="utf-8") as f:
            print(f.read(), end="")
        return 0
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
