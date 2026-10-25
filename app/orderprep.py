# app/orderprep.py
"""Prepare, step 1 of an order (order pipeline spec, section 2). Sub-project 1 ships
the plate: read the tracks, frame them nestled, reuse a curated plate that already
holds the print, or build one under work/plate/. A built plate's holes are measured
before anything trusts it (check_holes). Writes work/state.json and work/report.txt.
Then the photos (sub-project 3, place_photos): each photo in in/ gets an upright sRGB
work JPEG under work/photos/, a spot (its GPS, else its time on a track), a caption and
a box in open ground, or the whole poster hangs its photos in a band. Then the proof.

The fetch stack runs only as .venv-prep subprocesses (invariant 13): the coverage
query (scripts/dem_coverage.py) and the build (region_prep.py and
scripts/build_labels.py, through regionbuild.run_build). Tests swap in stubs."""
from __future__ import annotations

import dataclasses
import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, replace
from types import SimpleNamespace

from PIL.ImageCms import PyCMSError

from app import orderspec, sizes
from app.ingest import lonlat_extent
from app import order as order_mod
from app.order import (BAND_SIDES, DEFAULT_GAP, SIZE_KEYS, OrderError, cache_path, load,
                       orders_root, read_state, refuse_inside_repo, update_manual,
                       write_state)
from app.orderplate import (FILL_WARN, MAX_UPSAMPLE, PLATE_PAD_M, CoverageError,
                            PlateError, band_frame, choose_grid, conus_covered, curated_fit,
                            needed_resolution, nestled_frame, order_epsg,
                            photo_plan_frame, plate_bounds, project_bbox,
                            reference_share, to_lonlat_bbox, track_fill,
                            widen_for_upsample)
from app.papers import PaperError
from app.regionbuild import run_build
from app.regions import Region
from app.spec import SpecError

PROOF_FAILED = "PROOF NOT RENDERED: "
PROJECTION_CHANGED = ("The plate's projection changed: the studio's saved edits were "
                      "set aside; open the order and redo them.")
ORDER_CHANGED = ("The order changed (size, orientation or tracks) since the studio save: "
                 "the saved edits were set aside; open the order and redo them.")

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
# After a build the plate's no-data share is measured, not assumed: the 3DEP dynamic
# service can leave holes and say nothing (acceptance, 2026-09-24: 12.1% of the
# east-west plate was NaN where the index expected 5.6%). region_prep fills them
# from the static tiles; this is the check that the fill worked. A share more than
# HOLE_TOLERANCE past what the 3DEP index expects is a hole. The index is read on a
# lon/lat box in degrees, with outlines generalised to about 50 m, so a point of
# slack keeps a coastline from reading as a hole. A frame the index calls wholly US
# gets no slack: any no-data cell in it is a hole.
HOLE_TOLERANCE = 0.01
HOLE_DECIMATE = 8           # the share is read from every 8th cell each way

# Photos (order photos, sub-project 3). The layout reads the occupied sheet at a working
# dpi and stores inches (invariant 2). A photo is small when its upright long side has
# fewer pixels than its box at PHOTO_PPI.
PHOTO_LAYOUT_DPI = 50
PHOTO_PPI = 300
PHOTO_WORK_DIR = os.path.join("work", "photos")
PHOTO_OUTSIDE = "{file}: its spot is outside the frame. Widen the frame or drop it."
PHOTO_SMALL = "{file}: {w}×{h} px is small for a {box:g} in box at 300 ppi."
PHOTO_BEHIND_GAP = "Photo {file} is behind gap {k}."
PHOTO_OVER_BAND = "{n} photos: the band holds {most}. Drop some in the studio."
PHOTO_UNREADABLE = ("{file}: the photo could not be read ({why}). Replace it in in/, "
                    "or drop it in the studio.")
PHOTO_NO_PLACE = ("{file}: its place or time could not be read ({why}); place it in "
                  "the studio.")
PHOTO_NO_CAPTION = "{file}: its caption could not be found ({why}). Write one in the studio."
PHOTO_LAYOUT_FAILED = ("The photos could not be laid out in open ground ({why}): they "
                       "hang in the band.")
# a box Dom moved in the studio is kept where he put it, and warned (Task 8)
PHOTO_BOX_OVER = "{file}: its box is over {what}. It stays where you put it."
PHOTO_BOX_OFF_SHEET = ("{file}: its box runs past the sheet's edge, so the poster pulls "
                       "it inside.")
PHOTO_FIXED_BAND = ("The moved boxes leave no open ground for the other photos, so all of "
                    "them hang in the band. Move a box, or drop a photo.")
ROUTE_END_BEHIND_GAP = ("A route end is behind gap {k}. Move the frame, or use gap = 0 "
                        "to print every part of the map.")


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
    reads a layer left out as uncovered. A query that fails, or prints no result,
    raises CoverageError: a PlateError that the preview does not take for a size
    the terrain refuses, and so does a prep Python that cannot be started (OSError: a
    missing .venv-prep)."""
    cmd = [tools.prep_python, tools.coverage_script, *map(str, bbox)]
    if layers:
        cmd += ["--layers", ",".join(str(r) for r in layers)]
    try:
        run = subprocess.run(cmd, cwd=tools.repo_root, capture_output=True, text=True,
                             env=env)
    except OSError as ex:        # no prep venv (a studio edit reaching check_holes)
        raise CoverageError(f"The 3DEP coverage check could not run: {ex}") from ex
    if run.returncode != 0:
        raise CoverageError("The 3DEP coverage check failed:\n" + run.stderr[-800:])
    try:
        raw = json.loads(run.stdout.strip().splitlines()[-1])
        return {int(k): float(v) for k, v in raw.items()}
    except (ValueError, IndexError, AttributeError, TypeError) as ex:
        raise CoverageError(f"The 3DEP coverage check printed no result: {ex}") from ex


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


def _plan_grid(tools, frame, epsg, print_w_in, env, grow=None):
    """The grid for the frame, widening the frame until the data holds it.

    Coverage is read again for each widened plate, which covers more ground. At a
    coverage edge the wider plate can lose a layer, and the next coarser layer then
    asks for another widening (the spec's Errors table). Each widening moves to a
    coarser layer, so one pass per layer is enough. Returns the frame, the grid and
    the layer that first forced a widening (None if none did): the warning names
    that one, since a finer layer can come back into cover on the larger plate.
    `grow` maps the frame to the larger one the plate must hold (an order with photos:
    photo_plan_frame, on the current band side): coverage is read for that plate, the
    resolution for the frame."""
    forced_by = None
    for _ in range(MAX_PLAN_PASSES):
        need = needed_resolution(frame, print_w_in)
        cov = read_coverage(tools, to_lonlat_bbox(plate_bounds(grow(frame) if grow
                                                               else frame), epsg,
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


def cache_env() -> tuple:
    """(env, cache_dir) for a prep subprocess: the HyRiver caches under the orders
    root, and the folder the subprocess runs in. Prepare and the preview share it."""
    # absolute: a relative TECOPA_ORDERS_DIR would resolve against the
    # subprocess's cwd (the repo root), not ours
    cache = os.path.abspath(cache_path())
    cache_dir = os.path.dirname(cache)
    os.makedirs(cache_dir, exist_ok=True)
    # async_retriever's own request cache (py3dep) follows HYRIVER_CACHE_NAME
    # above; pygeoogc's separate HTTP cache (pynhd/pygeohydro's NHD and NLCD
    # REST calls) defaults under the repo's own cache/ too, and needs its own
    # env var to move (.venv-prep/.../pygeoogc/utils.py, HYRIVER_CACHE_NAME_HTTP).
    env = dict(os.environ, HYRIVER_CACHE_NAME=cache,
               HYRIVER_CACHE_NAME_HTTP=os.path.join(cache_dir, "http_cache.sqlite"))
    # pygeoogc.core.ArcGISRESTful (pynhd's NHD queries) writes a retry log to a
    # hardcoded "cache/failed_ids*.txt", relative to the process's cwd, with no
    # env override at all (docs/changing-things.md, Run an order). _build runs the
    # prep subprocess with its cwd here instead of the repo root, so that write
    # lands beside the shared cache too; pre-create the folder so a retry never
    # meets a missing directory.
    os.makedirs(os.path.join(cache_dir, "cache"), exist_ok=True)
    return env, cache_dir


def _render_proofs(order, state) -> dict:
    """The default `proofs` of prepare: the proof files of the spec Finish would print.
    Imported here, so Prepare never loads the renderer or app.main (plan decision P8)."""
    from app.orderproof import write_proofs
    return write_proofs(order, orderspec.order_spec(order, state),
                        orderspec.plate_dir(state))


def _as_size(order, key):
    """The same order at another menu size, for its print dimensions."""
    if key in ("two", "three"):
        gap = order.gap if order.panels > 1 else DEFAULT_GAP
        return replace(order, size=(17.0, 22.0), panels=2 if key == "two" else 3, gap=gap)
    short, long_ = (11.0, 17.0) if key == "11x17" else (17.0, 22.0)
    return replace(order, size=(short, long_), panels=1, gap=0.0)


def smaller_size(order, track_bounds_m, layer_m: float) -> str | None:
    """The key of the largest menu size below the ordered one whose nestled frame holds
    at `layer_m` data within MAX_UPSAMPLE, or None. The menu is walked from the
    largest down (three, two, 17x22, 11x17)."""
    pw, ph = order.print_in()
    for key in reversed(SIZE_KEYS):
        cand = _as_size(order, key)
        cw, ch = cand.print_in()
        if cw * ch >= pw * ph:
            continue
        frame = nestled_frame(track_bounds_m, cw / ch)
        if layer_m / needed_resolution(frame, cw) <= MAX_UPSAMPLE:
            return key
    return None


def _prove(order, state, proofs, log) -> dict:
    """Write the proof files after the plate. A failure is a warning, never a stop: the
    plate stays and `proof` is None. Only errors a proof can raise are caught, a typo in
    config/papers.toml (PaperError) among them."""
    warnings = [w for w in state.get("warnings", []) if not w.startswith(PROOF_FAILED)]
    try:
        proof = proofs(order, state)
    except (SpecError, OSError, OrderError, PyCMSError, PaperError) as ex:
        proof = None
        # a hole in the print leads the list; the proof's failure follows it
        at = 1 if warnings and warnings[0].startswith("HOLES IN THE PRINT") else 0
        warnings.insert(at, PROOF_FAILED + str(ex))
        log(PROOF_FAILED + str(ex))
    return write_state(order, {"proof": proof, "warnings": warnings})


def prepare(order_dir: str, tools: Tools, log=print, proofs=None) -> dict:
    # load() already refuses an order folder inside the repo; TECOPA_ORDERS_DIR
    # (orders_root(), which cache_path() derives from) is a separate setting and
    # needs its own check, so a customer's orders can't be pointed into the public
    # repo even when the order folder given here is not.
    refuse_inside_repo(orders_root())
    proofs = proofs or _render_proofs
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
    # An order with photos plans its plate round the union of the frame and its band
    # frame on the band's current side (B2): adding the first photo, or removing the
    # last, or changing the band's side, plans the plate again. A plan from before
    # photo_plan_side (planned for both ends) holds either side, so it stays current.
    with_photos = bool(order.photo_files())
    side = _band_side(order, manual)
    old_plate = state.get("plate")
    landcover_rebuilds = state.get("landcover_rebuilds", 0)
    # A manual frame is current when it is the one the last plan started from. It is
    # not compared with state["frame"]: planning may have widened it for coarse data.
    frame_current = ("frame" not in manual
                     or list(manual["frame"]) == state.get("frame_from_manual"))
    current = (state.get("inputs_hash") == inputs and frame_current
               and bool(state.get("photo_plan")) == with_photos
               and (not with_photos or state.get("photo_plan_side") in (None, side)))
    if current and _plate_present(old_plate, landcover_rebuilds):
        log(f"Plate is current: {state['plate']['id']}. Nothing to build.")
        state = place_photos(order, state, log, tools=tools)   # new photos, studio edits
        state = _prove(order, state, proofs, log)    # the title may have changed
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
    grow = _photo_grow(order, pw, ph, side) if with_photos else None
    holes_env = None
    hole_notes = []           # what check_holes said of the frame in use (hole_notes)
    warnings = []
    if skipped_tracks:
        warnings.append(f"Skipped {len(skipped_tracks)} track file(s) that could "
                        f"not be read: {', '.join(skipped_tracks)}.")
    fit = None if "frame" in manual else curated_fit(
        tracks, pw / ph, pw, curated_regions(tools.curated_root), grow=grow)
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
        env, cache_dir = cache_env()
        frame, grid, forced_by = _plan_grid(tools, planned, epsg, pw, env, grow=grow)
        if forced_by is not None:
            fill = track_fill(project_bbox(tracks, epsg), frame)
            note = (f"The terrain here is {forced_by:g} m data, too coarse for a "
                    f"nestled {pw:g}x{ph:g}. The frame was widened, and the tracks now "
                    f"fill {fill:.0%} of it.")
            if fill < FILL_WARN:
                key = smaller_size(order, project_bbox(tracks, epsg), forced_by)
                note += (f" {sizes.table()[key]['name']} would keep them nestled."
                         if key else " A smaller print would keep them nestled.")
            warnings.append(note)
        if grid["upsample"] > 1.0:
            warnings.append(f"Terrain is upsampled {grid['upsample']:.2f}x "
                            f"(the limit is {MAX_UPSAMPLE:g}x).")
        if grid["us_share"] < 0.995:
            warnings.append(f"About {1 - grid['us_share']:.0%} of this plate has "
                            f"no US elevation data (ocean or across a border).")
        plate, labels_note = _build(order, tools, grow(frame) if grow else frame, epsg,
                                    grid, env, log, cwd=cache_dir)
        if labels_note:
            warnings.append(labels_note)
        if with_photos:
            holes_env = env      # measured on the frame in use, once the layout settles it
        else:
            hole_notes = check_holes(tools, plate, frame, epsg,
                                     needed_resolution(frame, pw), env, log)
            _add_hole_notes(warnings, hole_notes)
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

    if not with_photos:
        # with photos, place_photos checks the route ends on the frame it settles on
        warnings += _route_ends_behind_gaps(order, payloads, epsg, frame)
    track_m = project_bbox(tracks, epsg)
    aside = _set_spec_aside(order, plate, manual, state.get("inputs_hash"), inputs)
    if aside:
        warnings.append(aside)
    state = write_state(order, {
        "inputs_hash": inputs, "epsg": epsg, "print_in": [pw, ph],
        "panels": order.panels, "gap": order.gap,
        "frame": list(frame), "track_bounds_m": list(track_m),
        "frame_from_manual": list(manual["frame"]) if "frame" in manual else None,
        "fill": round(track_fill(track_m, frame), 3),
        "need_m": round(needed_resolution(frame, pw), 3),
        "plate": plate, "warnings": warnings,
        "landcover_rebuilds": landcover_rebuilds,
        # open_frame: the frame planned for the tracks (the nestled one, a curated fit or
        # manual.frame, widened for coarse data), before any photo band. state["frame"]
        # is the frame in use: open_frame, or open_frame grown toward the band's side.
        # manual.frame is always an open frame, so Prepare never grows a grown frame: a
        # studio save of the frame saves open_frame (from a band proof, its crop through
        # orderspec.crop_for_layout(crop, "band", side, "open", side, spec)).
        "open_frame": list(frame), "photo_plan": with_photos,
        "photo_plan_side": side if with_photos else None, "hole_notes": hole_notes,
        "approval": None})            # a new plate is a new print: nothing approved stands
    state = place_photos(order, read_state(order), log, recheck_holes=False)
    if holes_env is not None:
        state = _holes_in_use(order, state, tools, holes_env, log)
    state = _prove(order, state, proofs, log)
    write_report(order, state)
    return state


def _add_hole_notes(warnings, notes) -> None:
    """A hole in the print leads the list; a hole outside it follows."""
    for note in notes:
        if note.startswith("HOLES IN THE PRINT"):
            warnings.insert(0, note)
        else:
            warnings.append(note)


def _holes_in_use(order, state, tools, env, log) -> dict:
    """check_holes for a freshly built plate of an order with photos, on the frame in use
    (the band frame when the photos hang in the band), which only the layout settles."""
    return write_state(order, _remeasure_holes(tools, state["plate"], state["frame"], state,
                                               env, state.get("warnings", []), log))


def _route_ends_behind_gaps(order, payloads, epsg, frame) -> list:
    """Plan A's warning for each gap of a window set that hides a route end: a route end
    is tied to the ground, so only the frame can move it out of a gap."""
    if not (order.panels > 1 and order.gap):
        return []
    from app.orderpreview import Candidate, gaps_hiding_ends, load_tracks_m
    cand = Candidate("", order.panels, order.orientation, order.print_in(), order.gap)
    ends = [t.coords for t in load_tracks_m(payloads, epsg)]
    return [ROUTE_END_BEHIND_GAP.format(k=k) for k in gaps_hiding_ends(ends, frame, cand)]


def _band_side(order, manual) -> str:
    """The band's current end: Dom's choice in the studio (manual.band_side), else
    order.toml's (default "top"). Prepare's plan and place_photos read it the same way."""
    side = (manual or {}).get("band_side")
    return side if side in BAND_SIDES else order.band_side


def _photo_grow(order, pw, ph, side):
    """The frame -> plan frame map of an order with photos: the union of the frame and
    its band frame on the band's current `side` (B2), at the print's scale. One side
    only: a switch to the other side replans (Prepare again)."""
    band_h = orderspec.band_height_for(orderspec.photo_box_in((pw, ph), order.panels))
    return lambda frame: photo_plan_frame(frame, ph, band_h, side)


def _read_photos(order, files, region, tracks, labels, box_in, log, known=None) -> list:
    """Prepare's own entry for each photo file: the sha256 of its bytes, its work JPEG,
    its spot and source, its caption, and the small-photo warning. One photo that cannot
    be read (or written) is warned and kept with no work JPEG and no spot: it never fails
    Prepare. A photo whose place or time cannot be read keeps its work JPEG and waits in
    the tray, warned.

    The work JPEG is written again when the photo's sha256 is not the one the last run
    recorded (`known`: {file: sha256}, from state.json), or when it is missing. Never by
    mtime: a same-named photo copied in with an older date is still a new photo."""
    known = known or {}
    from app.photocaption import nearest_name
    from app.photos import read_meta, write_work_jpeg
    from app.photospot import spot_for
    os.makedirs(os.path.join(order.dir, PHOTO_WORK_DIR), exist_ok=True)
    out = []
    for path in files:
        name = os.path.basename(path)
        digest = orderspec.file_sha256(path)
        entry = {"file": name, "work": None, "spot": None, "source": None, "caption": "",
                 "box": None, "crop": {"cx": 0.5, "cy": 0.5}, "dropped": False,
                 "warnings": [], "sha256": digest}
        work = os.path.join(PHOTO_WORK_DIR, name + ".jpg")
        dst = os.path.join(order.dir, work)
        try:
            meta = read_meta(path)
            if digest is None or known.get(name) != digest or not os.path.isfile(dst):
                tmp = dst + ".tmp"
                try:
                    write_work_jpeg(path, tmp)
                    os.replace(tmp, dst)
                finally:
                    if os.path.exists(tmp):
                        os.remove(tmp)
        except Exception as ex:          # one bad photo is a warning, never a stop
            why = f"{type(ex).__name__}: {ex}" if str(ex) else type(ex).__name__
            entry["warnings"].append(PHOTO_UNREADABLE.format(file=name, why=why[:200]))
            log(entry["warnings"][-1])
            out.append(entry)
            continue
        entry["work"] = work
        try:
            spot = spot_for(meta, tracks, region)
            if spot is not None:
                entry.update(spot={"x": spot.x, "y": spot.y}, source=spot.source,
                             caption=nearest_name(spot.x, spot.y, labels))
        except Exception as ex:          # an odd EXIF value: the photo waits in the tray
            entry.update(spot=None, source=None, caption="")
            why = f"{type(ex).__name__}: {ex}" if str(ex) else type(ex).__name__
            entry["warnings"].append(PHOTO_NO_PLACE.format(file=name, why=why[:200]))
            log(entry["warnings"][-1])
        w, h = meta.size_px
        if max(w, h) < box_in * PHOTO_PPI:
            entry["warnings"].append(PHOTO_SMALL.format(file=name, w=w, h=h, box=box_in))
        out.append(entry)
    return out


def _photo_spec(order, state, open_frame, layout, box_in, side, crop=None):
    """The spec the photos are laid out on, with no photo hotspots: order_spec at the
    open frame (a saved spec keeps its own crop), moved to `layout` and `side` by
    orderspec.crop_for_layout, the one function Prepare's frame and a saved crop share.
    `crop`, when given, is the crop of the spec that will print, as it is with open
    photos (the studio's live view, through open_crop): it replaces order_spec's."""
    spec = orderspec.order_spec(order, {**state, "frame": list(open_frame), "photos": []})
    if crop is not None:
        spec = dataclasses.replace(spec, crop=tuple(float(v) for v in crop),
                                   photo_layout="open", photo_band_side=side)
    target = dataclasses.replace(spec, hotspots=[], photo_layout=layout,
                                 photo_box_in=box_in, photo_band_side=side)
    return dataclasses.replace(target, crop=orderspec.crop_for_layout(
        spec.crop, spec.photo_layout, spec.photo_band_side, layout, side, target))


def open_crop(spec) -> tuple:
    """`spec`'s crop as it is with open photos: a band spec's crop shrunk back the way
    Prepare grows its frame (orderspec.crop_for_layout). What place_photos lays out on
    and what state's layout_crop records."""
    return tuple(orderspec.crop_for_layout(spec.crop, spec.photo_layout,
                                           spec.photo_band_side, "open", None, spec))


def same_crop(a, b, tol=1e-3) -> bool:
    """Two crops within `tol` metres at every edge."""
    try:
        return len(a) == 4 and len(b) == 4 and all(
            abs(float(x) - float(y)) <= tol for x, y in zip(a, b))
    except (TypeError, ValueError):
        return False


def _placed(p) -> bool:
    """A photo that is on the poster: a spot, a work JPEG to paint, not dropped. One with
    no work JPEG (unreadable, even if placed by hand) takes no part in the layout, the
    placed count or the band's limit."""
    return bool(p.get("spot") and p.get("work") and not p.get("dropped"))


def _visible(spot, spec) -> bool:
    """The spot is on the map the poster shows: inside the crop and, under the band, not
    under the band's strip (render._band_layout_in, the strip the renderer paints)."""
    crop = spec.crop
    if not _in_crop(spot, crop):
        return False
    if spec.photo_layout != "band":
        return True
    from app import render
    pw, ph = float(spec.print_w_in), float(spec.print_h_in)
    _, y0, _, y1 = render._band_layout_in(spec, pw, ph)["strip"]
    if spec.photo_band_side == "bottom":
        return spot["y"] >= orderspec.sheet_in_to_ground(spec, 0.0, y0)[1]
    return spot["y"] <= orderspec.sheet_in_to_ground(spec, 0.0, y1)[1]


def _in_crop(spot, crop) -> bool:
    return crop[0] <= spot["x"] <= crop[2] and crop[1] <= spot["y"] <= crop[3]


def _lay_out(order, state, photos, open_frame, box_in, side, plate, cfg, crop=None):
    """Open ground for every placed photo whose spot is on the sheet, or the band, on
    the open `crop` (see _photo_spec). Returns (layout, {photo index: (dx_in, dy_in)},
    [(photo index, warning)]). A box Dom set in the studio (a photo's bounded box, here)
    is fixed: the layout keeps it as it is, and _fixed_warnings says what it lies over."""
    from app import photolayout, render
    spec = _photo_spec(order, state, open_frame, "open", box_in, side, crop)
    todo = [i for i, p in enumerate(photos) if _placed(p) and _in_crop(p["spot"], spec.crop)]
    if not todo:
        return "open", {}, []
    occ = render.occupancy(spec, plate, PHOTO_LAYOUT_DPI, cfg=cfg)
    bleed = float(spec.bleed_in)          # the canvas is the sheet grown by the bleed
    spots = []
    for i in todo:
        x_in, y_in = orderspec.ground_to_sheet_in(spec, photos[i]["spot"]["x"],
                                                  photos[i]["spot"]["y"])
        spots.append((x_in + bleed, y_in + bleed))
    fixed = {k: (photos[i]["box"]["dx_in"], photos[i]["box"]["dy_in"])
             for k, i in enumerate(todo) if photos[i]["box"]}
    frame = render._photo_frame_fracs(spec.photo_frame_style)
    got = photolayout.layout(spots, box_in, occ, fixed=fixed, frame=frame)
    if got["layout"] != "open":
        warns = ([(None, PHOTO_FIXED_BAND)]
                 if fixed and len(todo) <= photolayout.OPEN_MAX else [])
        return got["layout"], {}, warns
    names = [photos[i]["file"] for i in todo]
    seams = (render.panel_geo.seam_bands_px(spec, occ.dpi,
                                            round(render.GEO_EDGE_IN * occ.dpi))
             if render.panel_geo.is_set(spec) else [])
    warns = [(todo[k], w) for k, w in
             _fixed_warnings(spots, got["boxes"], fixed, names, box_in, occ, frame,
                             seams=seams)]
    return got["layout"], {todo[k]: off for k, off in got["boxes"].items()}, warns


def _fixed_warnings(spots, boxes, fixed, names, box_in, occ, frame, seams=()) -> list:
    """[(k, warning)] for each fixed box (Dom's, from the studio) that lies over a route,
    the poster's furniture, a seam between panels (`seams`: the seam bands among
    occ.rects, panels.seam_bands_px), another box or another photo's spot, or past the
    sheet's edge. The rects are photolayout's, the frame the renderer paints. A pair of
    fixed boxes over each other is named once, by the earlier one."""
    from app import photolayout as pl
    dpi = float(occ.dpi)
    seam_set = {tuple(int(v) for v in r) for r in seams}
    rects = {k: pl._box_rect(spots[k], off, box_in, dpi, frame) for k, off in boxes.items()}
    w, h = occ.size_px
    tx0, ty0, tx1, ty1 = occ.trim_px if occ.trim_px is not None else (0, 0, w, h)
    out = []
    for k in sorted(fixed):
        r, file = rects[k], names[k]
        eps = pl._EPS
        if r[0] < tx0 - eps or r[1] < ty0 - eps or r[2] > tx1 + eps or r[3] > ty1 + eps:
            out.append((k, PHOTO_BOX_OFF_SHEET.format(file=file)))
        x0, y0 = max(0, int(r[0])), max(0, int(r[1]))
        x1, y1 = min(w, int(r[2]) + 1), min(h, int(r[3]) + 1)
        if x1 > x0 and y1 > y0 and occ.route[y0:y1, x0:x1].any():
            out.append((k, PHOTO_BOX_OVER.format(file=file, what="a route")))
        hit = [o for o in occ.rects if pl._rects_overlap(r, o)]
        if any(tuple(int(v) for v in o) in seam_set for o in hit):
            out.append((k, PHOTO_BOX_OVER.format(file=file, what="a seam between panels")))
        if any(tuple(int(v) for v in o) not in seam_set for o in hit):
            out.append((k, PHOTO_BOX_OVER.format(file=file, what="the poster's furniture")))
        for j in sorted(rects):
            if j != k and not (j in fixed and j < k) and pl._rects_overlap(r, rects[j]):
                out.append((k, PHOTO_BOX_OVER.format(file=file, what=f"{names[j]}'s box")))
        for j in range(len(spots)):
            if j != k and pl._covers(r, spots[j], spots[k], dpi):
                out.append((k, PHOTO_BOX_OVER.format(file=file, what=f"{names[j]}'s spot")))
    return out


def place_photos(order, state: dict, log=print, tools=None, recheck_holes=True,
                 crop=None) -> dict:
    """The photo step of Prepare, after the plate and before the proof (order photos,
    Task 7). Reads every photo in in/ (file-name order), lays the boxes out, settles
    the frame in use and writes state.json:

    - photos: one entry per file, {"file", "sha256" (of the file in in/), "work" (the
      work JPEG, relative to the order folder), "spot": {"x", "y"} | None, "source", "caption", "box": {"dx_in", "dy_in"}
      | None, "crop": {"cx", "cy"}, "dropped", "warnings"}, with manual.photos (the
      studio's edits, never written here) over Prepare's values, field by field;
    - photo_layout ("open" | "band"), photo_box_in (B6), photo_band_side (manual's, else
      order.toml's), band_frame, and frame: open_frame for the open layout, open_frame
      grown toward the band's side for the band (B2); fill and need_m follow the frame;
    - photo_warnings, and state.warnings with the last run's photo warnings replaced;
    - layout_crop: the open crop the layout was computed on.

    The layout, its occupancy, the outside, under-band and gap warnings for photos and
    the moved-box warnings use the crop of the spec that will print, as it is with open
    photos: `crop` (the studio passes its live view's, through open_crop), or, when None,
    order_spec's (a saved studio crop, else the frame). The frame in use, and its hole
    check, stay Prepare's (the plate's concern).

    When the frame in use changes here (open to band, or the band's side) on a built
    plate, its holes are measured again on the new frame (check_holes, through `tools`,
    default_tools when None) and the last measure's notes (hole_notes) are replaced, a
    hole in the print first. Prepare's fresh build passes recheck_holes=False: it measures
    the frame in use itself (_holes_in_use). An order with no photos keeps open_frame and
    gets an empty list. Returns the state."""
    from app import photocaption
    from app.geo import RegionGeo
    from app.orderpreview import load_tracks_m
    from app.photolayout import BAND_MAX

    open_frame = list(state.get("open_frame") or state["frame"])
    was_frame = state.get("frame")
    old = set(state.get("photo_warnings") or [])
    base = [w for w in state.get("warnings", []) if w not in old]
    files = order.photo_files()
    pw, ph = (float(v) for v in state["print_in"])
    if not files:
        return write_state(order, {"photos": [], "photo_layout": "open",
                                   "band_frame": False, "frame": open_frame,
                                   "photo_warnings": [], "warnings": base})
    manual = state.get("manual") or {}
    edits = manual.get("photos") if isinstance(manual.get("photos"), dict) else {}
    box_in = orderspec.photo_box_in((pw, ph), int(state.get("panels", 1)))
    side = _band_side(order, manual)
    plate = orderspec.plate_dir(state)
    with open(os.path.join(plate, "region.json")) as f:
        cfg = json.load(f)
    try:
        with open(os.path.join(plate, "labels.json")) as f:
            labels = json.load(f)
    except (OSError, ValueError):
        labels = None
    payloads = order.payloads()
    tracks = load_tracks_m(payloads, state["epsg"])
    region = RegionGeo(crs=cfg["crs"], bounds=(0.0, 0.0, 1.0, 1.0), overview_size=(1, 1))
    known = {p.get("file"): p.get("sha256") for p in state.get("photos") or []
             if isinstance(p, dict)}
    found = _read_photos(order, files, region, tracks, labels, box_in, log, known)
    state = {**state, "photos": found, "photo_box_in": box_in, "photo_band_side": side,
             "photo_layout": "open"}
    photos = orderspec.effective_photos(state)
    for p in photos:
        edit = edits.get(p["file"]) if isinstance(edits.get(p["file"]), dict) else {}
        if p["source"] == "manual" and not isinstance(edit.get("caption"), str):
            try:
                p["caption"] = photocaption.nearest_name(p["spot"]["x"], p["spot"]["y"],
                                                         labels)
            except Exception as ex:      # as on Prepare's own path: a warning, never a stop
                p["caption"] = ""
                why = f"{type(ex).__name__}: {ex}" if str(ex) else type(ex).__name__
                p["warnings"].append(PHOTO_NO_CAPTION.format(file=p["file"], why=why[:200]))

    warnings = []
    if crop is None:
        try:
            crop = _photo_spec(order, state, open_frame, "open", box_in, side).crop
        except (SpecError, OrderError, OSError, ValueError, KeyError):
            crop = tuple(open_frame)
    crop = tuple(float(v) for v in crop)
    try:
        layout, boxes, fixed_warns = _lay_out(order, state, photos, open_frame, box_in,
                                              side, plate, cfg, crop)
    except (SpecError, OrderError, OSError, ValueError, KeyError) as ex:
        layout, boxes, fixed_warns = "band", {}, []
        warnings.append(PHOTO_LAYOUT_FAILED.format(why=str(ex)[:200]))
    for i, p in enumerate(photos):
        if layout == "band":
            p["box"] = None
        elif i in boxes:
            p["box"] = {"dx_in": boxes[i][0], "dy_in": boxes[i][1]}
    frame = open_frame if layout == "open" else list(band_frame(
        open_frame, ph, orderspec.band_height_for(box_in), side))

    state = {**state, "photo_layout": layout}
    try:
        shown = _photo_spec(order, state, open_frame, layout, box_in, side, crop)
    except (SpecError, OrderError, OSError, ValueError, KeyError):
        shown = SimpleNamespace(crop=tuple(frame), photo_layout="open")
    layout_crop, crop = crop, shown.crop
    from app.orderpreview import Candidate, gaps_hiding_ends
    cand = Candidate("", order.panels, order.orientation, (pw, ph), order.gap)
    placed = [p for p in photos if _placed(p)]
    for p in photos:
        if p["dropped"]:
            p["warnings"] = []
            continue
        if not _placed(p):
            continue
        if not _visible(p["spot"], shown):
            p["warnings"].append(PHOTO_OUTSIDE.format(file=p["file"]))
            continue
        for k in gaps_hiding_ends([[(p["spot"]["x"], p["spot"]["y"])]], crop, cand):
            p["warnings"].append(PHOTO_BEHIND_GAP.format(file=p["file"], k=k))
    for i, w in fixed_warns:
        if i is None:
            warnings.append(w)
        else:
            photos[i]["warnings"].append(w)
    if len(placed) > BAND_MAX:
        warnings.append(PHOTO_OVER_BAND.format(n=len(placed), most=BAND_MAX))
    photo_warnings = ([w for p in photos for w in p["warnings"]] + warnings
                      + _route_ends_behind_gaps(order, payloads, state["epsg"], frame))
    track_m = state.get("track_bounds_m")
    updates = {"photos": photos, "photo_layout": layout, "photo_box_in": box_in,
               "photo_band_side": side, "band_frame": layout == "band",
               "frame": list(frame), "need_m": round(needed_resolution(frame, pw), 3),
               "photo_warnings": photo_warnings, "warnings": base + photo_warnings,
               "layout_crop": list(layout_crop)}
    if track_m:
        updates["fill"] = round(track_fill(track_m, frame), 3)
    plate_rec = state.get("plate") or {}
    if (recheck_holes and plate_rec.get("kind") == "built"
            and not _same_frame(was_frame, frame)):
        env, _ = cache_env()
        updates.update(_remeasure_holes(
            tools or default_tools(order_mod._repo_root()), plate_rec, frame, state, env,
            [w for w in base if w not in set(state.get("hole_notes") or [])]
            + photo_warnings, log))
    log(_photos_line({"photos": photos, "photo_layout": layout}))
    return write_state(order, updates)


def _same_frame(a, b) -> bool:
    try:
        return len(a) == 4 and all(abs(float(x) - float(y)) <= 1e-6 for x, y in zip(a, b))
    except (TypeError, ValueError):
        return False


def _remeasure_holes(tools, plate_rec, frame, state, env, warnings, log) -> dict:
    """check_holes on the new frame in use: the plate record, its notes (hole_notes) and
    `warnings` (the old notes already taken out) with the new notes in, a hole in the
    print first."""
    plate = dict(plate_rec)
    notes = check_holes(tools, plate, frame, state["epsg"],
                        needed_resolution(frame, float(state["print_in"][0])), env, log)
    warnings = list(warnings)
    _add_hole_notes(warnings, notes)
    return {"plate": plate, "hole_notes": notes, "warnings": warnings}


def _set_spec_aside(order, plate, manual, last_inputs, inputs) -> str | None:
    """Keep a studio spec that no longer fits the order as manual.spec_set_aside, so the
    default spec renders. Two cases set it aside:

    - the order's inputs (size, orientation, panels, gap or tracks) changed since the
      save: the spec still holds the old size, frame and tracks. The save records the
      inputs hash it was framed on (manual.spec_inputs_hash); a save from before that
      record is compared with the inputs of the last Prepare.
    - the plate just built is in another projection: orderspec.order_spec refuses it.

    Returns the warning, or None when the spec stays."""
    saved = manual.get("spec")
    if not saved:
        return None
    framed_on = manual.get("spec_inputs_hash") or last_inputs
    if framed_on != inputs:
        why = ORDER_CHANGED
    else:
        try:
            with open(os.path.join(plate["root"], plate["id"], "region.json")) as f:
                crs = json.load(f)["crs"]
        except (OSError, ValueError, KeyError):
            return None
        if saved.get("crs") == crs:
            return None
        why = PROJECTION_CHANGED
    update_manual(order, {"spec_set_aside": saved, "spec": None, "spec_inputs_hash": None})
    return why


def _build(order, tools, frame, epsg, grid, env, log, cwd=None, root=None, rid=None,
           build_log=None):
    """Build a plate. By default it is the order's own, under work/plate/<order id>/.
    `root` and `rid` name another place and id: the preview's coarse plate.
    `build_log` is the file that keeps the build's lines, work/build.log by default:
    the preview names its own, so it never replaces the log of the order's plate.
    region.json keeps the name as it was at build time, and a title change does not
    rebuild the plate, so later steps must take the title from order.title, never
    from region.json. `cwd`, when given, is the folder the prep subprocess runs in
    (see the comments in cache_env()) -- everything it reads or writes is already
    an absolute path, so this only affects a library's own relative writes."""
    rid = rid or order.id
    root = root or order.plate_root
    params = {"id": rid, "name": order.title,
              "bbox": to_lonlat_bbox(plate_bounds(frame), epsg, pad_m=PLATE_PAD_M),
              "epsg": epsg, "resolution": grid["grid_m"],
              "out_root": root}
    os.makedirs(root, exist_ok=True)
    shutil.rmtree(os.path.join(root, rid), ignore_errors=True)
    log(f"Building plate {rid}: {grid['grid_m']:g} m grid from the "
        f"{grid['layer_m']:g} m 3DEP layer.")
    started = time.monotonic()
    # work/build.log keeps every line of the build, so a failure can be read after
    # run_build sweeps the partial plate.
    build_log = build_log or os.path.join(order.work_dir, "build.log")
    os.makedirs(os.path.dirname(build_log), exist_ok=True)
    with open(build_log, "w") as log_file:
        def progress(line):
            log_file.write(line + "\n")
            log(line)
        result = run_build(params, repo_root=tools.repo_root,
                           regions_root=root,
                           prep_python=tools.prep_python, prep_script=tools.prep_script,
                           labels_script=tools.labels_script, set_progress=progress,
                           env=env, cwd=cwd)
    plate = {"id": rid, "root": root, "kind": "built",
             "grid_m": grid["grid_m"], "layer_m": grid["layer_m"],
             "upsample": round(grid["upsample"], 3), "us_share": grid["us_share"],
             "build_seconds": round(time.monotonic() - started, 1)}
    return plate, result["labels_note"]


def nan_shares(dem_path, frame, decimate=HOLE_DECIMATE) -> tuple:
    """(plate, frame): the share of dem.tif's cells, and of the ground inside `frame`
    (metres, the plate's CRS), with no elevation. Ground of the frame that lies outside
    dem.tif counts as no elevation: a band side the plate was not planned for (the studio
    switched sides) has none there. Both are decimated reads, every `decimate`th cell
    each way, so a corridor-sized plate is never read whole."""
    import math

    import numpy as np
    import rasterio
    from rasterio.windows import Window, from_bounds
    with rasterio.open(dem_path) as ds:
        plate = ds.read(1, out_shape=(max(1, ds.height // decimate),
                                      max(1, ds.width // decimate)))
        f = from_bounds(*frame, transform=ds.transform)
        c0, r0 = max(0, math.floor(f.col_off)), max(0, math.floor(f.row_off))
        c1 = min(ds.width, math.ceil(f.col_off + f.width))
        r1 = min(ds.height, math.ceil(f.row_off + f.height))
        covered = (max(0.0, min(f.col_off + f.width, ds.width) - max(f.col_off, 0.0))
                   * max(0.0, min(f.row_off + f.height, ds.height) - max(f.row_off, 0.0)))
        on_plate = min(1.0, covered / (f.width * f.height)) if f.width * f.height else 0.0
        if c1 <= c0 or r1 <= r0:
            return float(np.isnan(plate).mean()), 1.0
        win = Window(c0, r0, c1 - c0, r1 - r0)
        inside = ds.read(1, window=win, out_shape=(max(1, (r1 - r0) // decimate),
                                                   max(1, (c1 - c0) // decimate)))
    frame_nan = 1.0 - on_plate * (1.0 - float(np.isnan(inside).mean()))
    return float(np.isnan(plate).mean()), frame_nan


def hole_fill_record(plate_dir):
    """{layer_m, filled_share} from the plate's sources.json when region_prep filled
    holes (the source with role "hole fill"), else None. Tolerant of an old or
    missing sources.json."""
    try:
        with open(os.path.join(plate_dir, "sources.json")) as f:
            sources = json.load(f).get("sources", [])
    except (OSError, ValueError, AttributeError):
        return None
    for s in sources if isinstance(sources, list) else []:
        if isinstance(s, dict) and s.get("role") == "hole fill":
            try:
                return {"layer_m": int(s["layer_m"]),
                        "filled_share": float(s["filled_share"])}
            except (KeyError, TypeError, ValueError):
                return None
    return None


def check_holes(tools, plate, frame, epsg, need_m, env, log=print) -> list:
    """Measure a freshly built plate's holes and return the warnings they earn.
    Records nan_share, frame_nan_share and, when region_prep filled holes,
    hole_fill on `plate`. The plate is compared with 1 - us_share, what the 3DEP
    index expects to be ocean or across a border. The frame, when it has any
    no-data cell, is compared with its own share, from one more coverage query of
    the frame's box. An unreadable dem.tif is logged and skips the check."""
    plate_dir = os.path.join(plate["root"], plate["id"])
    fill = hole_fill_record(plate_dir)
    if fill:
        plate["hole_fill"] = fill
    try:
        plate_nan, frame_nan = nan_shares(os.path.join(plate_dir, "dem.tif"), frame)
    except Exception as ex:          # an unreadable or empty dem.tif
        log(f"Could not measure the plate's holes: {type(ex).__name__}: {ex}")
        return []
    plate_nan, frame_nan = round(plate_nan, 4), round(frame_nan, 4)
    plate["nan_share"], plate["frame_nan_share"] = plate_nan, frame_nan
    warnings = []
    frame_hole = None
    if frame_nan > 0:
        try:
            cov = read_coverage(tools, to_lonlat_bbox(frame, epsg), env,
                                layers=COARSE_LAYERS_M if need_m >= COARSE_NEED_M
                                else None)
            if not cov:
                raise PlateError("the coverage check returned no layers")
            expected = round(1.0 - reference_share(cov), 4)
        except PlateError as ex:
            reason = " ".join(str(ex).split())[:200]
            frame_hole = (f"HOLES IN THE PRINT: {frame_nan:.1%} of the frame has no "
                          f"elevation data, and the share the 3DEP index expects "
                          f"could not be checked ({reason}). Look at the proof "
                          f"before printing; if the holes are over land, delete "
                          f"work/plate/ and run Prepare again.")
        else:
            slack = HOLE_TOLERANCE if expected > 0 else 0.0
            if frame_nan > expected + slack:
                frame_hole = (f"HOLES IN THE PRINT: {frame_nan:.1%} of the frame "
                              f"has no elevation data, where the 3DEP index expects "
                              f"{expected:.1%}. Do not print this plate: delete "
                              f"work/plate/ and run Prepare again.")
    plate_expected = round(1.0 - plate["us_share"], 4)
    if plate_nan > plate_expected + HOLE_TOLERANCE:
        note = (f"{plate_nan:.1%} of the plate has no elevation data, where the 3DEP "
                f"index expects {plate_expected:.1%} (ocean or across a border): the "
                f"terrain service left holes.")
        if frame_hole is None:
            note += (" None of them is inside the frame." if frame_nan == 0 else
                     " The frame's own share is within what the index expects.")
        warnings.append(note)
    if frame_hole:
        warnings.append(frame_hole)
    return warnings


def _print_line(state) -> str:
    """A set names its panels, its hung size and its gap. `get` reads a state.json
    from before a set existed, which has neither key."""
    size = f"{state['print_in'][0]:g} x {state['print_in'][1]:g} in"
    if state.get("panels", 1) > 1:
        return f"Print: {state['panels']} panels, {size} hung, {state.get('gap', 0):g} in gap"
    return f"Print: {size}"


def _photos_line(state) -> str:
    """Photos: <placed> placed (<gps> by GPS, <time> by time, <manual> by hand), <tray> in
    the tray, <dropped> dropped; layout <open|band>"""
    photos = state.get("photos") or []
    kept = [p for p in photos if not p.get("dropped")]
    placed = [p for p in kept if _placed(p)]
    by = {s: sum(1 for p in placed if p.get("source") == s) for s in ("gps", "time", "manual")}
    return (f"Photos: {len(placed)} placed ({by['gps']} by GPS, {by['time']} by time, "
            f"{by['manual']} by hand), {len(kept) - len(placed)} in the tray, "
            f"{len(photos) - len(kept)} dropped; layout {state.get('photo_layout', 'open')}")


def write_report(order, state) -> str:
    plate, frame = state["plate"], state["frame"]
    grid = f"{plate['grid_m']:g} m grid"
    if plate.get("layer_m") is not None:
        grid += f" from the {plate['layer_m']:g} m 3DEP layer"
    lines = [f"Order: {order.title}",
             _print_line(state),
             f"Plate: {plate['id']} ({plate['kind']}), {grid}",
             f"Frame: {(frame[2] - frame[0]) / 1000:.1f} x "
             f"{(frame[3] - frame[1]) / 1000:.1f} km, tracks fill {state['fill']:.0%}",
             f"Upsampling: {plate['upsample']:.2f}x (limit {MAX_UPSAMPLE:g}x)"]
    if state.get("photos"):
        lines.append(_photos_line(state))
    proof = state.get("proof")
    if proof:
        lines.append(f"Proof: out/proof/{orderspec.file_stem(order.title)}-proof.jpg "
                     "and .pdf")
        lines.append(f"Soft proof: {proof['soft_proof']}" if proof.get("soft_proof")
                     else f"Soft proof: skipped, {proof.get('soft_proof_why')}")
    fill = plate.get("hole_fill")
    if fill:
        lines.append(f"Hole fill: {fill['filled_share']:.1%} of the plate from the "
                     f"3DEP {fill['layer_m']:g} m tiles (the dynamic service left "
                     f"holes)")
    if plate.get("nan_share") is not None:
        lines.append(f"No elevation: {plate['nan_share']:.1%} of the plate, "
                     f"{plate.get('frame_nan_share', 0.0):.1%} of the frame")
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
