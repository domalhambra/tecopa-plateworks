# app/regionbuild.py
"""Region creation from dropped tracks: the pure planning helpers behind
/api/regions/plan and the subprocess orchestration behind /api/regions/build.

The heavy fetch stack (py3dep/pynhd/pandas/geopandas) NEVER imports here -- the
build runs region_prep.py as a subprocess in its own venv (.venv-prep), exactly the
separation requirements-regionprep.txt was made for. Planning cost, by contrast, is
pure logic: region_prep.plan_build imports with the core stack."""
from __future__ import annotations
import math
import os
import re
import shutil
import subprocess
from collections import deque

# 3 km padding floor: enough ground for a crop to breathe around a short walk.
PAD_FRAC = 0.20
PAD_FLOOR_M = 3000.0
_M_PER_DEG_LAT = 111320.0

# USGS 3DEP terrain is US-only. A bbox must sit FULLY inside one envelope --
# straddling a border would bake truncated terrain and lie about it.
US_ENVELOPES = (
    (-125.5, 24.3, -66.8, 49.5),    # CONUS
    (-170.0, 51.0, -129.0, 71.6),   # Alaska (3DEP coverage, not the Aleutian tail)
    (-160.6, 18.8, -154.7, 22.4),   # Hawaii
)


def derive_bbox(w: float, s: float, e: float, n: float) -> tuple:
    """Track bounds -> region bbox: pad each side by max(20% of span, 3 km)."""
    mid = math.radians((s + n) / 2.0)
    floor_lat = PAD_FLOOR_M / _M_PER_DEG_LAT
    floor_lon = PAD_FLOOR_M / (_M_PER_DEG_LAT * max(0.2, math.cos(mid)))
    pad_lon = max(PAD_FRAC * (e - w), floor_lon)
    pad_lat = max(PAD_FRAC * (n - s), floor_lat)
    return (w - pad_lon, s - pad_lat, e + pad_lon, n + pad_lat)


def utm_epsg(bbox: tuple) -> int:
    """The northern-hemisphere UTM zone EPSG for the bbox centroid (US => north)."""
    lon = (bbox[0] + bbox[2]) / 2.0
    zone = int((lon + 180.0) // 6.0) + 1
    return 32600 + max(1, min(60, zone))


def bbox_covered(bbox: tuple) -> bool:
    w, s, e, n = bbox
    return any(w >= ew and e <= ee and s >= es and n <= en
               for ew, es, ee, en in US_ENVELOPES)


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", (name or "").lower()).strip("_")
    return slug or "region"


def unique_id(slug: str, existing) -> str:
    if slug not in existing:
        return slug
    for i in range(2, 100):
        cand = f"{slug}_{i}"
        if cand not in existing:
            return cand
    raise ValueError(f"no free id for slug {slug!r}")


def run_build(params: dict, repo_root: str, regions_root: str,
              prep_python: str, prep_script: str, labels_script: str,
              set_progress, env: dict | None = None, cwd: str | None = None) -> dict:
    """Spawn region_prep in the prep venv, stream its stdout into set_progress,
    then run the GNIS labels build (non-fatal). Raises RuntimeError with the last
    output lines on prep failure -- after sweeping the partial region dir so a
    retry starts clean. The id is trusted here only as far as its shape: callers
    (the build endpoint) enforce ^[a-z0-9_]+$ before ever reaching this.
    An order build adds `resolution` and `out_root` to params, and passes `env`
    (the shared HyRiver cache). Without them the commands are exactly the
    in-app build's. `out_root`, when given, must be `regions_root` (the same
    folder, however spelled): region_prep writes under out_root, and the failure
    sweep removes regions_root/<id>, so any other pairing sweeps the wrong
    folder. A mismatch raises ValueError before anything is spawned. Both are
    resolved against repo_root, where region_prep runs, and the resolved absolute
    folder is what region_prep, the labels bake and the sweep all use.

    `cwd`, when given, is the working directory both subprocesses run in instead
    of `repo_root`. Only an order build passes it (app/orderprep.py): it moves a
    fetch-stack library's own hardcoded-relative write (pygeoogc's
    ArcGISRESTful.failed_path, "cache/failed_ids*.txt" -- no env override exists
    for it) off the public repo's cache/ dir. It is safe only because an order
    build's script paths and out_root are already absolute, so nothing here
    depends on the process's cwd to find anything; the in-app build never passes
    it and keeps running with cwd=repo_root exactly as before."""
    rid = params["id"]
    if not re.fullmatch(r"[a-z0-9_]+", rid):
        raise ValueError(f"unsafe region id {rid!r}")
    out_root = params.get("out_root")
    sweep_root = regions_root
    if out_root:
        # join leaves an absolute path unchanged
        out_root = os.path.abspath(os.path.join(repo_root, out_root))
        if out_root != os.path.abspath(os.path.join(repo_root, regions_root)):
            raise ValueError(f"out_root {params['out_root']!r} must be regions_root "
                             f"{regions_root!r}: a failed build sweeps regions_root")
        sweep_root = out_root
    w, s, e, n = params["bbox"]
    cmd = [prep_python, prep_script,
           "--id", rid, "--name", params["name"],
           "--bbox", str(w), str(s), str(e), str(n),
           "--epsg", str(params["epsg"])]
    if params.get("resolution") is not None:
        cmd += ["--resolution", str(params["resolution"])]
    if out_root:
        cmd += ["--out-root", out_root]
    run_cwd = cwd or repo_root
    tail: deque = deque(maxlen=10)
    proc = subprocess.Popen(cmd, cwd=run_cwd, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, bufsize=1,
                            env=env)
    for line in proc.stdout:
        line = line.rstrip()
        if line:
            tail.append(line)
            set_progress(line)
    rc = proc.wait()
    if rc != 0:
        shutil.rmtree(os.path.join(sweep_root, rid), ignore_errors=True)
        raise RuntimeError(
            f"region build failed (exit {rc}). Last output:\n" + "\n".join(tail))
    set_progress("Building place-name labels (GNIS)...")
    labels_note = None
    lab_cmd = [prep_python, labels_script]
    if out_root:
        lab_cmd += ["--root", out_root]
    lab_cmd.append(rid)
    lab = subprocess.run(lab_cmd, cwd=run_cwd, capture_output=True, text=True,
                         env=env)
    if lab.returncode != 0:
        hint = f"python {labels_script} "
        if out_root:
            hint += f"--root {out_root} "
        hint += rid
        labels_note = ("Place-name labels failed to build -- the region works "
                       "without them. Rebuild later with: " + hint)
    return {"labels_note": labels_note}
