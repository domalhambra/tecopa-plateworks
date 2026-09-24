"""Print how much of a lon/lat bbox each 3DEP layer covers, as one line of JSON:

    {"1": 0.9981, "3": 0.0, "10": 1.0, "30": 1.0, "60": 1.0}

`--layers 10,30,60` measures only those layers (default: all five), and the line
then carries only their keys.

Runs in .venv-prep (py3dep). Order planning (app/orderprep.py) calls it as a
subprocess, so the fetch stack never enters .venv (invariant 13).

    .venv-prep/bin/python scripts/dem_coverage.py <west> <south> <east> <north> \
        [--layers 10,30,60]
"""
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

USAGE = ("usage: dem_coverage.py <west> <south> <east> <north> [--layers 10,30,60]\n"
         "  layers: a comma list from 1, 3, 10, 30, 60 (default: all)")
# region_prep.COVERAGE_LAYERS_M, repeated so a bad argument is refused before the
# fetch stack is imported
LAYERS_M = (1, 3, 10, 30, 60)


def _bbox(argv):
    """Four finite numbers, or None."""
    if len(argv) != 4:
        return None
    try:
        bbox = tuple(float(v) for v in argv)
    except ValueError:
        return None
    return bbox if all(math.isfinite(v) for v in bbox) else None


def _split(argv):
    """(the four bbox words, the layers tuple), or None. Parsed by hand: argparse
    reads a negative longitude as an option."""
    argv = list(argv)
    layers = LAYERS_M
    if "--layers" in argv:
        i = argv.index("--layers")
        if i + 1 >= len(argv):
            return None
        try:
            layers = tuple(sorted({int(v) for v in argv[i + 1].split(",")}))
        except ValueError:
            return None
        if not layers or any(r not in LAYERS_M for r in layers):
            return None
        del argv[i:i + 2]
    return argv, layers


def main(argv):
    split = _split(argv)
    bbox = _bbox(split[0]) if split else None
    if bbox is None:
        print(USAGE, file=sys.stderr)
        return 2
    layers = split[1]
    import region_prep   # sets SSL_CERT_FILE before anything imports aiohttp
    if tuple(region_prep.COVERAGE_LAYERS_M) != LAYERS_M:
        raise SystemExit("dem_coverage.LAYERS_M is out of step with region_prep")
    cov = region_prep.layer_coverage(bbox, layers=layers)
    print(json.dumps({str(k): round(v, 4) for k, v in cov.items()}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
