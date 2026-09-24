# app/orderprep.py
"""Prepare, step 1 of an order (order pipeline spec, section 2). Sub-project 1 ships
the plate: read the tracks, frame them nestled, reuse a curated plate that already
holds the print, or build one under work/plate/. Writes work/state.json and
work/report.txt. Later sub-projects add the paper table, photos and the proof.

The fetch stack runs only as .venv-prep subprocesses (invariant 13): the coverage
query (scripts/dem_coverage.py) and the build (region_prep.py and
scripts/build_labels.py, through regionbuild.run_build). Tests swap in stubs."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass

from app.ingest import lonlat_extent
from app.order import (OrderError, cache_path, load, orders_root, read_state,
                       refuse_inside_repo, write_state)
from app.orderplate import (FILL_WARN, MAX_UPSAMPLE, PLATE_PAD_M, PlateError,
                            choose_grid, conus_covered, curated_fit, needed_resolution,
                            nestled_frame, order_epsg, plate_bounds, project_bbox,
                            to_lonlat_bbox, track_fill, widen_for_upsample)
from app.regionbuild import run_build
from app.regions import Region

# One pass per 3DEP layer (region_prep.COVERAGE_LAYERS_M: 1, 3, 10, 30, 60). That
# module needs the prep stack, so it is counted here, not imported (invariant 13).
MAX_PLAN_PASSES = 5
# At a need of COARSE_NEED_M or more, only the 10 and 30 m layers can shape the
# grid: the fine layers matter just above 10 m, through choose_grid's step-down
# when the 10 m layer is uncovered, and not past 20 m. Asking for 1 m lidar over a
# corridor-sized box times out (acceptance, Reno to Salt Lake). 60 m is left out
# entirely: the static 60 m 3DEP tiles cover Alaska only, so the index always
# reads 0.0 for it in the lower 48 -- querying it wastes a request and never
# changes the plan (region_prep.py, choose_grid's docstring in orderplate.py).
COARSE_NEED_M = 20.0
COARSE_LAYERS_M = (10, 30)
# A built plate is complete with all three; region.json and dem.tif are load-
# bearing (Region.readiness needs them), landcover.tif is the optional biome look
# and is gated separately (LANDCOVER_REBUILD_LIMIT below). Hydro with no lakes or
# rivers is real (desert).
CORE_PLATE_FILES = ("region.json", "dem.tif")
LANDCOVER_WARNING = ("Land cover did not download, so the biome look is not "
                     "available on this plate. Run Prepare again to retry.")
LANDCOVER_GAVE_UP_WARNING = ("Land cover was retried once and still failed. "
                             "The plate is kept without it.")
# A built plate missing only landcover.tif is rebuilt automatically once
# (state["landcover_rebuilds"] < this). A repeatable failure (the service is down,
# not a fluke) otherwise rebuilds -- rmtree included -- on every later Prepare
# forever, and can lose an otherwise-usable plate to a failed rebuild (acceptance,
# 2026-09-24: an east-west order's land cover kept failing). Past the limit the
# plate is kept as is, with a warning, and Prepare stops touching it until the
# order's inputs actually change.
LANDCOVER_REBUILD_LIMIT = 1
PREP_VENV_HELP = "docs/changing-things.md › Set up a machine"


@dataclass(frozen=True)
class Tools:
    """The subprocesses Prepare calls, and where the curated plates live."""
    prep_python: str
    prep_script: str
    labels_script: str
    coverage_script: str
    repo_root: str
    curated_root: str


def default_tools(repo_root: str) -> Tools:
    """The real tools. TECOPA_PREP_PYTHON, TECOPA_PREP_SCRIPT and TECOPA_LABELS_SCRIPT
    move them, with app/main.py's names and defaults. main.py's paths are relative to
    the server's cwd, the repo root; here a relative path is joined to `repo_root`."""
    def env_path(var, default):
        return os.path.join(repo_root, os.environ.get(var, default))
    return Tools(prep_python=env_path("TECOPA_PREP_PYTHON", ".venv-prep/bin/python"),
                 prep_script=env_path("TECOPA_PREP_SCRIPT", "region_prep.py"),
                 labels_script=env_path("TECOPA_LABELS_SCRIPT", "scripts/build_labels.py"),
                 coverage_script=os.path.join(repo_root, "scripts", "dem_coverage.py"),
                 repo_root=repo_root,
                 curated_root=os.path.join(repo_root, "regions"))


def _real_terrain(root: str, rid: str):
    """The plate's Region if its DEM is ready (present, bounds and CRS matching
    region.json) and real, else None. A customer must never get invented terrain:
    tests/conftest.py hydrates synthetic stand-ins into a checkout missing its real
    DEMs, marked with the GeoTIFF tag synthetic=1, and a stand-in reads as ready."""
    try:
        region = Region(rid, root)
        if not region.readiness().get("ready"):
            return None
        import rasterio
        dem = os.path.join(region.dir, region.cfg.get("dem_path", "dem.tif"))
        with rasterio.open(dem) as ds:
            if ds.tags().get("synthetic") == "1":   # tests/conftest.py's mark
                return None
    except Exception:            # a malformed region.json or an unreadable DEM
        return None
    return region


def curated_regions(root: str) -> list:
    """Curated plates with real, ready terrain, as the dicts curated_fit reads."""
    out = []
    if not os.path.isdir(root):
        return out
    for rid in sorted(os.listdir(root)):
        if not os.path.isfile(os.path.join(root, rid, "region.json")):
            continue
        region = _real_terrain(root, rid)
        if region is None:
            continue
        cfg = region.cfg
        out.append({"id": rid, "crs": cfg["crs"], "bounds": cfg["bounds"],
                    "native_resolution_m": cfg["native_resolution_m"]})
    return out


def read_coverage(tools: Tools, bbox, env, layers=None) -> dict:
    """{layer metres: covered share}, for `layers` only when given. choose_grid
    reads a layer left out as uncovered."""
    cmd = [tools.prep_python, tools.coverage_script, *map(str, bbox)]
    if layers:
        cmd += ["--layers", ",".join(str(r) for r in layers)]
    run = subprocess.run(cmd, cwd=tools.repo_root, capture_output=True, text=True,
                         env=env)
    if run.returncode != 0:
        raise PlateError("The 3DEP coverage check failed:\n" + run.stderr[-800:])
    try:
        raw = json.loads(run.stdout.strip().splitlines()[-1])
        return {int(k): float(v) for k, v in raw.items()}
    except (ValueError, IndexError) as ex:
        raise PlateError(f"The 3DEP coverage check printed no result: {ex}") from ex


def _plate_present(plate, landcover_rebuilds=0) -> bool:
    if not plate:
        return False
    if plate.get("kind") == "curated":
        return _real_terrain(plate["root"], plate["id"]) is not None
    return _built_complete(plate["root"], plate["id"], landcover_rebuilds)


def _core_complete(root, rid) -> bool:
    """The load-bearing files (not landcover.tif) are present."""
    return all(os.path.isfile(os.path.join(root, rid, name))
               for name in CORE_PLATE_FILES)


def _has_landcover(root, rid) -> bool:
    return os.path.isfile(os.path.join(root, rid, "landcover.tif"))


def _built_complete(root, rid, landcover_rebuilds=0) -> bool:
    """A built plate is current with every CORE_PLATE_FILES file, plus landcover.tif.
    Missing region.json or dem.tif always rebuilds. Missing only landcover.tif rebuilds
    too, but just once (landcover_rebuilds < LANDCOVER_REBUILD_LIMIT): past the
    limit the plate reads as current anyway, so a repeatable failure stops being
    rebuilt on every later Prepare (see LANDCOVER_REBUILD_LIMIT)."""
    if not _core_complete(root, rid):
        return False
    if _has_landcover(root, rid):
        return True
    return landcover_rebuilds >= LANDCOVER_REBUILD_LIMIT


def _plan_grid(tools, frame, epsg, print_w_in, env):
    """The grid for the frame, widening the frame until the data holds it.

    Coverage is read again for each widened plate, which covers more ground. At a
    coverage edge the wider plate can lose a layer, and the next coarser layer then
    asks for another widening (the spec's Errors table). Each widening moves to a
    coarser layer, so one pass per layer is enough. Returns the frame, the grid and
    the layer that first forced a widening (None if none did): the warning names
    that one, since a finer layer can come back into cover on the larger plate."""
    forced_by = None
    for _ in range(MAX_PLAN_PASSES):
        need = needed_resolution(frame, print_w_in)
        cov = read_coverage(tools, to_lonlat_bbox(plate_bounds(frame), epsg,
                                                  pad_m=PLATE_PAD_M), env,
                            layers=COARSE_LAYERS_M if need >= COARSE_NEED_M else None)
        grid = choose_grid(need, cov)
        if not grid["widen"]:
            return frame, grid, forced_by
        if forced_by is None:
            forced_by = grid["layer_m"]
        wider = widen_for_upsample(frame, grid["layer_m"], print_w_in)
        if wider[2] - wider[0] <= frame[2] - frame[0]:
            raise PlateError(f"The frame did not grow when widened for the "
                             f"{grid['layer_m']:g} m layer, so the terrain data "
                             f"stays too coarse for this print size.")
        frame = wider
    raise PlateError("The terrain data is still too coarse for this print size "
                     f"after {MAX_PLAN_PASSES} widenings.")


def prepare(order_dir: str, tools: Tools, log=print) -> dict:
    # load() already refuses an order folder inside the repo; TECOPA_ORDERS_DIR
    # (orders_root(), which cache_path() derives from) is a separate setting and
    # needs its own check, so a customer's orders can't be pointed into the public
    # repo even when the order folder given here is not.
    refuse_inside_repo(orders_root())
    order = load(order_dir)
    payloads = order.payloads()
    tracks = lonlat_extent(payloads)["bbox"]
    if tracks is None:
        raise OrderError(f"no track points in {order.in_dir}")
    # lonlat_extent merges every file's points into one bbox and skips a file it
    # can't parse (or that has none) without a trace -- a customer's one garbage
    # upload would otherwise vanish silently. Re-run it per file (the identical
    # parser) to name what it dropped; the merged bbox above already proves at
    # least one file was readable, so this is a warning, not the refusal above.
    skipped_tracks = [name for data, name in payloads
                      if lonlat_extent([(data, name)])["bbox"] is None]
    if not conus_covered(tracks):
        raise PlateError("These tracks are outside the lower 48. "
                         "Alaska and Hawaii come later.")
    state = read_state(order)
    manual = state.get("manual", {})
    inputs = order.inputs_hash()
    old_plate = state.get("plate")
    landcover_rebuilds = state.get("landcover_rebuilds", 0)
    # A manual frame is current when it is the one the last plan started from. It is
    # not compared with state["frame"]: planning may have widened it for coarse data.
    frame_current = ("frame" not in manual
                     or list(manual["frame"]) == state.get("frame_from_manual"))
    current = state.get("inputs_hash") == inputs and frame_current
    if current and _plate_present(old_plate, landcover_rebuilds):
        log(f"Plate is current: {state['plate']['id']}. Nothing to build.")
        write_report(order, state)   # the title may have changed; it is not an input
        return state
    # True when the only reason `current` plate above was not present is a missing
    # landcover.tif on an otherwise-complete built plate: the one case
    # LANDCOVER_REBUILD_LIMIT gates. Any other path here (no plate yet, inputs or
    # frame changed, dem.tif/region.json missing) starts a fresh plate generation,
    # which gets its own landcover retry budget (reset below).
    gated_landcover_retry = (current and old_plate is not None
                             and old_plate.get("kind") == "built"
                             and _core_complete(old_plate["root"], old_plate["id"])
                             and not _has_landcover(old_plate["root"], old_plate["id"]))

    pw, ph = order.print_in()
    warnings = []
    if skipped_tracks:
        warnings.append(f"Skipped {len(skipped_tracks)} track file(s) that could "
                        f"not be read: {', '.join(skipped_tracks)}.")
    fit = None if "frame" in manual else curated_fit(
        tracks, pw / ph, pw, curated_regions(tools.curated_root))
    if fit:
        epsg, frame = fit["epsg"], fit["frame"]
        region = fit["region"]
        plate = {"id": region["id"], "root": tools.curated_root, "kind": "curated",
                 "grid_m": float(region["native_resolution_m"]), "upsample": 1.0,
                 "us_share": 1.0}
        landcover_rebuilds = 0    # curated plates carry no landcover retry budget
        log(f"Reusing curated plate {region['id']}.")
    else:
        # after the curated check: reusing a curated plate needs no prep venv
        if not os.path.exists(tools.prep_python):
            raise PlateError(f"The prep venv is missing: {tools.prep_python}. "
                             f"Set it up with {PREP_VENV_HELP}.")
        if "frame" in manual:
            epsg = state.get("epsg") or order_epsg(tracks, pw / ph)
            planned = tuple(manual["frame"])
        else:
            epsg = order_epsg(tracks, pw / ph)
            planned = nestled_frame(project_bbox(tracks, epsg), pw / ph)
        # absolute: a relative TECOPA_ORDERS_DIR would resolve against the
        # subprocess's cwd (the repo root), not ours
        cache = os.path.abspath(cache_path())
        env = dict(os.environ, HYRIVER_CACHE_NAME=cache)
        os.makedirs(os.path.dirname(cache), exist_ok=True)
        frame, grid, forced_by = _plan_grid(tools, planned, epsg, pw, env)
        if forced_by is not None:
            fill = track_fill(project_bbox(tracks, epsg), frame)
            note = (f"The terrain here is {forced_by:g} m data, too coarse for a "
                    f"nestled {pw:g}x{ph:g}. The frame was widened, and the tracks now "
                    f"fill {fill:.0%} of it.")
            if fill < FILL_WARN:
                note += " A smaller print would keep them nestled."
            warnings.append(note)
        if grid["upsample"] > 1.0:
            warnings.append(f"Terrain is upsampled {grid['upsample']:.2f}x "
                            f"(the limit is {MAX_UPSAMPLE:g}x).")
        if grid["us_share"] < 0.995:
            warnings.append(f"About {1 - grid['us_share']:.0%} of this plate has "
                            f"no US elevation data (ocean or across a border).")
        plate, labels_note = _build(order, tools, frame, epsg, grid, env, log)
        if labels_note:
            warnings.append(labels_note)
        if _has_landcover(plate["root"], plate["id"]):
            landcover_rebuilds = 0
        elif gated_landcover_retry:
            # this build WAS the one automatic retry LANDCOVER_REBUILD_LIMIT allows
            landcover_rebuilds += 1
            warnings.append(LANDCOVER_GAVE_UP_WARNING if
                            landcover_rebuilds >= LANDCOVER_REBUILD_LIMIT
                            else LANDCOVER_WARNING)
        else:
            # a fresh plate generation (new inputs/frame, or no plate before): its
            # own retry budget starts at 0, untouched by this first failure
            landcover_rebuilds = 0
            warnings.append(LANDCOVER_WARNING)

    track_m = project_bbox(tracks, epsg)
    state = write_state(order, {
        "inputs_hash": inputs, "epsg": epsg, "print_in": [pw, ph],
        "frame": list(frame), "track_bounds_m": list(track_m),
        "frame_from_manual": list(manual["frame"]) if "frame" in manual else None,
        "fill": round(track_fill(track_m, frame), 3),
        "need_m": round(needed_resolution(frame, pw), 3),
        "plate": plate, "warnings": warnings,
        "landcover_rebuilds": landcover_rebuilds})
    write_report(order, state)
    return state


def _build(order, tools, frame, epsg, grid, env, log):
    """Build the order's plate under work/plate/<order id>/. region.json keeps the
    name as it was at build time, and a title change does not rebuild the plate, so
    later steps must take the title from order.title, never from region.json."""
    rid = order.id
    params = {"id": rid, "name": order.title,
              "bbox": to_lonlat_bbox(plate_bounds(frame), epsg, pad_m=PLATE_PAD_M),
              "epsg": epsg, "resolution": grid["grid_m"],
              "out_root": order.plate_root}
    os.makedirs(order.plate_root, exist_ok=True)
    shutil.rmtree(os.path.join(order.plate_root, rid), ignore_errors=True)
    log(f"Building plate {rid}: {grid['grid_m']:g} m grid from the "
        f"{grid['layer_m']:g} m 3DEP layer.")
    started = time.monotonic()
    # work/build.log keeps every line of the build, so a failure can be read after
    # run_build sweeps the partial plate.
    with open(os.path.join(order.work_dir, "build.log"), "w") as build_log:
        def progress(line):
            build_log.write(line + "\n")
            log(line)
        result = run_build(params, repo_root=tools.repo_root,
                           regions_root=order.plate_root,
                           prep_python=tools.prep_python, prep_script=tools.prep_script,
                           labels_script=tools.labels_script, set_progress=progress,
                           env=env)
    plate = {"id": rid, "root": order.plate_root, "kind": "built",
             "grid_m": grid["grid_m"], "layer_m": grid["layer_m"],
             "upsample": round(grid["upsample"], 3), "us_share": grid["us_share"],
             "build_seconds": round(time.monotonic() - started, 1)}
    return plate, result["labels_note"]


def write_report(order, state) -> str:
    plate, frame = state["plate"], state["frame"]
    grid = f"{plate['grid_m']:g} m grid"
    if plate.get("layer_m") is not None:
        grid += f" from the {plate['layer_m']:g} m 3DEP layer"
    lines = [f"Order: {order.title}",
             f"Print: {state['print_in'][0]:g} x {state['print_in'][1]:g} in",
             f"Plate: {plate['id']} ({plate['kind']}), {grid}",
             f"Frame: {(frame[2] - frame[0]) / 1000:.1f} x "
             f"{(frame[3] - frame[1]) / 1000:.1f} km, tracks fill {state['fill']:.0%}",
             f"Upsampling: {plate['upsample']:.2f}x (limit {MAX_UPSAMPLE:g}x)"]
    if plate.get("build_seconds") is not None:
        lines.append(f"Build time: {plate['build_seconds']:.0f} s")
    if state["warnings"]:
        lines.append("Warnings:")
        lines += [f"- {w}" for w in state["warnings"]]
    else:
        lines.append("Warnings: none")
    text = "\n".join(lines) + "\n"
    with open(os.path.join(order.work_dir, "report.txt"), "w") as f:
        f.write(text)
    return text
