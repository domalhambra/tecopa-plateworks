"""Print how much of a lon/lat bbox each 3DEP layer covers, as one line of JSON:

    {"1": 0.9981, "3": 0.0, "10": 1.0, "30": 1.0, "60": 1.0}

Runs in .venv-prep (py3dep). Order planning (app/orderprep.py) calls it as a
subprocess, so the fetch stack never enters .venv (invariant 13).

    .venv-prep/bin/python scripts/dem_coverage.py <west> <south> <east> <north>
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main(argv):
    if len(argv) != 4:
        print("usage: dem_coverage.py <west> <south> <east> <north>", file=sys.stderr)
        return 2
    import region_prep   # sets SSL_CERT_FILE before anything imports aiohttp
    bbox = tuple(float(v) for v in argv)
    cov = region_prep.layer_coverage(bbox)
    print(json.dumps({str(k): round(v, 4) for k, v in cov.items()}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
