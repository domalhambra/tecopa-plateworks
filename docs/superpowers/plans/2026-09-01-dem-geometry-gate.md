# DEM Geometry Gate Implementation Plan

Goal: every render verb refuses a plate whose DEM on disk no longer matches its `region.json`, so a pull that orphans a DEM produces a 503 that names the drift instead of a silently misregistered poster.

Architecture: one helper in `app/main.py` (`_ready_or_503`) wraps the existing `Region.readiness()` and raises a 503 at the three places a plate is handed to a verb: `_region_or_404`, the two `_resolve_region` branches that bypass it, and `_manifest_region_or_422`. `scripts/verify_regions.py` gains a geometry row per plate so a human report separates the deliberate hash drift on four plates from a real orphan. The asset farm skips a plate whose DEM geometry drifts.

Tech Stack: Python 3.14, FastAPI, rasterio, pyproj, pytest. No new dependencies.

Design record: approved in conversation on 2026-09-01. Decisions: engine gate, not a git hook; refuse with 503, no override flag; no readiness cache; `/readyz` and `/api/reprint/inspect` unchanged; no front-end change (the studio already shows `detail`).

---

## Before you start

```bash
cd "/Users/dom/Documents/Claude/Projects/Badwater OS/Badwater Trails"
source .venv/bin/activate
git status                      # must be clean, on main
./.venv/bin/python -m pytest -q tests/test_readyz.py tests/test_region_endpoints.py
```

Expected: all pass. If `test_region_endpoints.py` skips build tests, that is the missing `.venv-prep` stub and is fine.

Known local failures that are NOT yours: the seven font-metric tests listed in `CLAUDE.md` § Known local failures. Compare failure sets, not totals.

Vocabulary in every user-facing string: **plate**, not region. The `Plate <id> can't render:` prefix is fixed; tests grep for it.

## File map

| File | Change | Responsibility |
|---|---|---|
| `app/main.py` | Modify | `_not_ready_detail`, `_ready_or_503`; gate in `_region_or_404`, `_best_region`, the single-plate branch of `_resolve_region`, and `_manifest_region_or_422` |
| `tests/test_geometry_gate.py` | Create | endpoint and unit tests for the gate |
| `scripts/verify_regions.py` | Modify | `geometry_verdict()`, one geometry row per plate, `ORPHAN` counts toward exit 1, docstring rule |
| `tests/test_verify_regions.py` | Create | ok / ORPHAN / not-checked rows and the exit code |
| `scripts/render_asset_farm.py` | Modify | `_ensure_dem` returns a reason string; a drifted DEM is a skip with its own reason |
| `tests/test_asset_farm_gate.py` | Create | the farm skip |
| `CLAUDE.md` | Modify | one sentence under the orphan bullet |

`app/regions.py` is not touched. `Region.readiness()` is already the predicate.

---

### Task 1: The gate helper and `_region_or_404`

Files:
- Modify: `app/main.py` (around line 271, `_region_or_404`)
- Create: `tests/test_geometry_gate.py`

Step 1: Write the failing tests

```python
# tests/test_geometry_gate.py
# The DEM geometry gate: a plate whose dem.tif no longer matches its region.json must
# refuse to render with a 503 that names the drift. This is the pull-orphan failure
# (CLAUDE.md § Known local failures): a cloud plate rebuild ships region.json to main,
# the gitignored DEM stays behind, and the next pull pairs new bounds with old terrain.
# Before this gate the poster painted with no error, just wrong. Every test CONSTRUCTS
# its drift in tmp_path (tests/test_plates.py rule: never inherit drift from the host).
import io
import json
import os

import numpy as np
import pytest
import rasterio
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pyproj import Transformer
from rasterio.transform import from_bounds

import app.main as main
from app import regions
from tests.test_readyz import _write_region

client = TestClient(main.app)

GOOD = (600000.0, 4400000.0, 610000.0, 4410000.0)        # UTM 10N, 10 km square
SHIFTED = (605000.0, 4405000.0, 615000.0, 4415000.0)     # the DEM moved 5 km -> orphan
FAR = (300000.0, 4000000.0, 310000.0, 4010000.0)         # a second plate, nowhere near
CRS = "EPSG:32610"


def _gpx_inside(bounds, n=12):
    """A GPX track walking the middle of `bounds`, in lon/lat, with timestamps."""
    w, s, e, nn = bounds
    tr = Transformer.from_crs(CRS, "EPSG:4326", always_xy=True)
    pts = []
    for i in range(n):
        f = 0.2 + 0.6 * i / (n - 1)
        lon, lat = tr.transform(w + f * (e - w), s + f * (nn - s))
        pts.append(f'<trkpt lat="{lat:.6f}" lon="{lon:.6f}">'
                   f'<time>2024-06-01T10:{i:02d}:00Z</time></trkpt>')
    body = ("<?xml version=\"1.0\"?><gpx version=\"1.1\" creator=\"t\" "
            "xmlns=\"http://www.topografix.com/GPX/1/1\"><trk><name>t</name><trkseg>"
            + "".join(pts) + "</trkseg></trk></gpx>")
    return body.encode()


def _upload(gpx, **fields):
    return client.post("/api/upload",
                       files=[("files", ("t.gpx", io.BytesIO(gpx), "application/gpx+xml"))],
                       data=fields)


def _rewrite_dem(region_dir, bounds):
    """Overwrite the plate's DEM with one covering `bounds` -- the orphan, in place."""
    prof = dict(driver="GTiff", dtype="float32", count=1, height=20, width=20,
                crs=CRS, transform=from_bounds(*bounds, 20, 20), nodata=np.nan)
    with rasterio.open(os.path.join(region_dir, "dem.tif"), "w", **prof) as ds:
        ds.write(np.full((20, 20), 1500.0, "float32"), 1)


@pytest.fixture
def plates(tmp_path):
    """Install tmp plates into main.REGIONS for one test; restore the real registry after.
    Yields a function: install(rid=Region, ...) replaces the registry with exactly those."""
    saved = dict(main.REGIONS)

    def install(**by_id):
        main.REGIONS.clear()
        main.REGIONS.update(by_id)
    try:
        yield install
    finally:
        main.REGIONS.clear()
        main.REGIONS.update(saved)


def _plate(tmp_path, rid, cfg_bounds, dem_bounds):
    _write_region(str(tmp_path), rid, cfg_bounds, dem_bounds, crs=CRS)
    return regions.Region(rid, root=str(tmp_path))


def test_explicit_plate_with_drifted_dem_is_503_naming_the_drift(tmp_path, plates):
    plates(orphan=_plate(tmp_path, "orphan", GOOD, SHIFTED))
    r = _upload(_gpx_inside(GOOD), region_id="orphan")
    assert r.status_code == 503, r.text
    d = r.json()["detail"]
    assert d.startswith("Plate orphan can't render:")
    assert "5000.00 m" in d and "region.json" in d
    assert "verify_regions.py" in d


def test_healthy_plate_still_uploads(tmp_path, plates):
    plates(good=_plate(tmp_path, "good", GOOD, GOOD))
    r = _upload(_gpx_inside(GOOD), region_id="good")
    assert r.status_code == 200, r.text
    assert r.json()["region"] == "good"


def test_the_orphan_sequence_upload_then_swap_then_proof(tmp_path, plates):
    """The real failure: the session was bound BEFORE the pull swapped the DEM."""
    good = _plate(tmp_path, "good", GOOD, GOOD)
    plates(good=good)
    sid = _upload(_gpx_inside(GOOD), region_id="good").json()["session"]
    _rewrite_dem(good.dir, SHIFTED)                      # the pull lands
    r = client.post("/api/proof", data={"session_id": sid, "x0": 10, "y0": 10,
                                        "x1": 60, "y1": 80})
    assert r.status_code == 503, r.text
    assert r.json()["detail"].startswith("Plate good can't render:")


def test_missing_dem_is_503_not_500(tmp_path, plates):
    _write_region(str(tmp_path), "nodem", GOOD, GOOD, crs=CRS, with_dem=False)
    plates(nodem=regions.Region("nodem", root=str(tmp_path)))
    r = _upload(_gpx_inside(GOOD), region_id="nodem")
    assert r.status_code == 503, r.text
    assert "DEM is missing" in r.json()["detail"]
```

Step 2: Run the tests to verify they fail

```bash
./.venv/bin/python -m pytest -q tests/test_geometry_gate.py
```

Expected: `test_healthy_plate_still_uploads` PASSES (it is the regression guard). The other three FAIL: the explicit and orphan-sequence tests get 200 instead of 503, the missing-DEM test gets a 500 or a 200.

Step 3: Write the gate

In `app/main.py`, replace `_region_or_404`:

```python
def _not_ready_detail(report: dict) -> str:
    """One humanized sentence per Region.readiness() failure. The prefix is a contract
    the studio's truth line and the tests both read; keep it."""
    rid = report.get("id", "?")
    fix = " Run scripts/verify_regions.py, then the orphan repair in CLAUDE.md."
    if not report.get("dem_present"):
        return f"Plate {rid} can't render: its DEM is missing on this machine.{fix}"
    if report.get("error"):
        return (f"Plate {rid} can't render: its DEM could not be opened "
                f"({report['error']}).{fix}")
    if not report.get("crs_match", True):
        return (f"Plate {rid} can't render: the DEM on disk is in a different CRS than "
                f"region.json, so it is not the DEM this plate was built with.{fix}")
    return (f"Plate {rid} can't render: the DEM on disk drifts "
            f"{report.get('bounds_drift_m', 0.0):.2f} m from region.json, so it is not "
            f"the DEM this plate was built with.{fix}")

def _ready_or_503(region):
    """The DEM geometry gate. A plate is handed to a verb only when its DEM on disk
    matches its region.json (Region.readiness(): present, bounds within 1.5 px, same
    CRS). The failure this catches is the pull orphan (CLAUDE.md § Known local
    failures): a rebuilt plate ships region.json to main while the gitignored DEM stays
    behind, and the old terrain paints under the new bounds with no error. /readyz has
    reported it since v1; nothing refused on it until now. Deliberately no override --
    unlike a rebuilt-plate hash mismatch, a misregistered DEM has no honest render.
    Runs per request: readiness() reads one GeoTIFF header, milliseconds against a
    proof, and a stat-keyed memo can come later if a profile ever shows it."""
    rep = region.readiness()
    if rep.get("ready"):
        return region
    log.warning("event=plate.not_ready region=%s report=%s", region.id, rep)
    raise HTTPException(503, _not_ready_detail(rep))

def _region_or_404(rid):
    if rid not in REGIONS:
        raise HTTPException(404, f"Unknown region {rid!r}")
    return _ready_or_503(REGIONS[rid])
```

Step 4: Run the tests to verify they pass

```bash
./.venv/bin/python -m pytest -q tests/test_geometry_gate.py tests/test_readyz.py tests/test_main.py -x
```

Expected: all PASS. `test_main.py` exercises upload, proof, and final on the real plates, whose synthetic or real DEMs match their bounds exactly, so nothing there should change. If anything in `test_main.py` turns 503, a plate on this Mac is drifted for real: run `./.venv/bin/python scripts/verify_regions.py` and stop.

Step 5: Commit

```bash
git add app/main.py tests/test_geometry_gate.py
git commit -m "gate: a plate whose DEM drifts from region.json refuses to render

The pull orphan (a rebuilt plate's region.json arrives, the gitignored DEM
does not) has painted a misregistered poster with no error three times
since July. Region.readiness() already knew; only /readyz asked. Now
_region_or_404 asks on every verb that hands a plate to a render, and a
503 names the plate, the drift in metres, and the repair. No override:
a misregistered DEM has no honest render."
```

---

### Task 2: The two `_resolve_region` branches that bypass `_region_or_404`

Files:
- Modify: `app/main.py` (`_best_region` around line 315, `_resolve_region` around line 369)
- Modify: `tests/test_geometry_gate.py`

Step 1: Write the failing tests

Append to `tests/test_geometry_gate.py`:

```python
def test_auto_detect_into_a_drifted_plate_is_the_drift_503_not_a_no_region_422(tmp_path, plates):
    """Two plates, the tracks land in the drifted one. The winner must be gated: the
    operator needs 'this plate drifted', not 'tracks fall in no region'."""
    plates(orphan=_plate(tmp_path, "orphan", GOOD, SHIFTED),
           far=_plate(tmp_path, "far", FAR, FAR))
    r = _upload(_gpx_inside(GOOD))                       # no region_id -> auto-detect
    assert r.status_code == 503, r.text
    assert r.json()["detail"].startswith("Plate orphan can't render:")


def test_single_plate_branch_is_gated(tmp_path, plates):
    plates(orphan=_plate(tmp_path, "orphan", GOOD, SHIFTED))
    r = _upload(_gpx_inside(GOOD))                       # one plate -> the sole-plate branch
    assert r.status_code == 503, r.text
    assert r.json()["detail"].startswith("Plate orphan can't render:")


def test_auto_recovery_into_a_drifted_plate_is_gated(tmp_path, plates):
    """Operator picked 'far', the tracks are really in 'orphan': recovery switches to
    the drifted plate and must refuse there, not paint."""
    plates(orphan=_plate(tmp_path, "orphan", GOOD, SHIFTED),
           far=_plate(tmp_path, "far", FAR, FAR))
    r = _upload(_gpx_inside(GOOD), region_id="far")
    assert r.status_code == 503, r.text
    assert r.json()["detail"].startswith("Plate orphan can't render:")
```

Step 2: Run the tests to verify they fail

```bash
./.venv/bin/python -m pytest -q tests/test_geometry_gate.py -k "auto_detect or single_plate or auto_recovery"
```

Expected: all three FAIL with status 200.

Step 3: Gate the winner and the sole plate

In `_best_region`, change the final return:

```python
    if stats is not None and best_stats:
        for k, v in best_stats.items():
            stats[k] = stats.get(k, 0) + v
    if best is not None:
        _ready_or_503(best)      # only the winner is gated: losers are never painted
    return best, best_tracks
```

In `_resolve_region`, the single-plate branch:

```python
    if len(REGIONS) == 1:
        region = _ready_or_503(next(iter(REGIONS.values())))
```

Step 4: Run the tests to verify they pass

```bash
./.venv/bin/python -m pytest -q tests/test_geometry_gate.py tests/test_main.py -x
```

Expected: all PASS.

Step 5: Commit

```bash
git add app/main.py tests/test_geometry_gate.py
git commit -m "gate: auto-detect and the sole-plate branch hand a plate to the gate too

_resolve_region reaches a plate three ways, and two of them never passed
through _region_or_404. The auto-detect winner and the single built plate
now go through _ready_or_503 as well, so a drifted plate that holds the
tracks refuses with the drift, not with a misleading no-region 422."
```

---

### Task 3: Reprint and continue

Files:
- Modify: `app/main.py` (`_manifest_region_or_422` around line 1536)
- Modify: `tests/test_geometry_gate.py`

Step 1: Write the failing test

Append to `tests/test_geometry_gate.py`:

```python
def test_manifest_region_gate_refuses_a_drifted_plate_before_the_pack_check(tmp_path, plates):
    """Reprint and continue resolve their plate here. Geometry is checked BEFORE the
    pack-version comparison, so allow_plate_mismatch can never walk past an orphan."""
    from types import SimpleNamespace
    plates(orphan=_plate(tmp_path, "orphan", GOOD, SHIFTED))
    spec = SimpleNamespace(region_id="orphan", labels=False, biome=False, dry_lakes=False)
    with pytest.raises(HTTPException) as ei:
        main._manifest_region_or_422(spec, "reprinted", manifest=None,
                                     allow_plate_mismatch=True)
    assert ei.value.status_code == 503
    assert ei.value.detail.startswith("Plate orphan can't render:")
```

Step 2: Run the test to verify it fails

```bash
./.venv/bin/python -m pytest -q tests/test_geometry_gate.py -k manifest_region_gate
```

Expected: FAIL with `DID NOT RAISE`.

Step 3: Gate after the 422

In `_manifest_region_or_422`, directly after the `if region is None:` block and before `if file_pv:`:

```python
    _ready_or_503(region)     # geometry first: the pack override below must not bypass it
```

Step 4: Run the tests to verify they pass

```bash
./.venv/bin/python -m pytest -q tests/test_geometry_gate.py tests/test_provenance.py tests/test_editions.py -x
```

Expected: PASS. `test_provenance.py` and `test_editions.py` hold the reprint and continue tests on the real plates; they must stay green.

Step 5: Commit

```bash
git add app/main.py tests/test_geometry_gate.py
git commit -m "gate: reprint and continue check the plate's geometry before its pack version

The pack-version mismatch is a warning with an override, because a rebuilt
plate still has an honest reprint. A drifted DEM does not, so it is
checked first and allow_plate_mismatch cannot reach past it."
```

---

### Task 4: The geometry row in `verify_regions.py`

Files:
- Modify: `scripts/verify_regions.py`
- Create: `tests/test_verify_regions.py`

Step 1: Write the failing tests

```python
# tests/test_verify_regions.py
# verify_regions.py separates the two kinds of DEM drift. A hash mismatch alone is a
# REBUILT plate (four of five on this Mac, deliberate, CLAUDE.md § Known local
# failures). A geometry mismatch is the pull ORPHAN, and it is the only kind that needs
# repair. Before this row the script printed the same DRIFT line for both.
import json
import os

from scripts import verify_regions as vr
from tests.test_readyz import _write_region

GOOD = (600000.0, 4400000.0, 610000.0, 4410000.0)
SHIFTED = (605000.0, 4405000.0, 615000.0, 4415000.0)


def _with_sidecar(root, rid, cfg_bounds, dem_bounds, with_dem=True):
    """A plate plus a sources.json that records region.json truthfully and the DEM
    with a deliberately wrong hash -- the rebuilt-plate shape."""
    d = _write_region(root, rid, cfg_bounds, dem_bounds, with_dem=with_dem)
    src = {"assets": {"region.json": {
        "sha256": vr._sha256_file(os.path.join(d, "region.json")),
        "bytes": os.path.getsize(os.path.join(d, "region.json"))}}}
    if with_dem:
        src["assets"]["dem.tif"] = {"sha256": "0" * 64, "bytes": 1}
    with open(os.path.join(d, "sources.json"), "w") as f:
        json.dump(src, f)
    return d


def test_geometry_ok_when_dem_matches(tmp_path):
    d = _with_sidecar(str(tmp_path), "rebuilt", GOOD, GOOD)
    verdict, detail = vr.geometry_verdict(d)
    assert verdict == "ok"
    assert "0.00 m" in detail


def test_geometry_orphan_when_dem_drifts(tmp_path):
    d = _with_sidecar(str(tmp_path), "orphan", GOOD, SHIFTED)
    verdict, detail = vr.geometry_verdict(d)
    assert verdict == "ORPHAN"
    assert "5000.00 m" in detail and "not this plate's" in detail


def test_geometry_missing_dem_is_not_orphan(tmp_path):
    d = _with_sidecar(str(tmp_path), "nodem", GOOD, GOOD, with_dem=False)
    verdict, _ = vr.geometry_verdict(d)
    assert verdict == "MISSING"


def test_main_prints_orphan_and_exits_1(tmp_path, capsys):
    _with_sidecar(str(tmp_path), "orphan", GOOD, SHIFTED)
    rc = vr.main(["--regions-root", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 1
    assert "ORPHAN geometry" in out
    assert "DRIFT  dem.tif" in out            # the hash row still prints beside it


def test_main_rebuilt_plate_reads_drift_but_not_orphan(tmp_path, capsys):
    _with_sidecar(str(tmp_path), "rebuilt", GOOD, GOOD)
    rc = vr.main(["--regions-root", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 1                            # the hash drift is still a finding
    assert "ORPHAN" not in out
    assert "ok     geometry" in out


def test_geometry_row_degrades_when_render_stack_is_absent(tmp_path, monkeypatch):
    """The script is stdlib-first by contract. Without app.regions it says so, once."""
    d = _with_sidecar(str(tmp_path), "any", GOOD, GOOD)
    monkeypatch.setattr(vr, "_readiness", None)
    verdict, detail = vr.geometry_verdict(d)
    assert verdict == "skip"
    assert "not checked" in detail
```

Step 2: Run the tests to verify they fail

```bash
./.venv/bin/python -m pytest -q tests/test_verify_regions.py
```

Expected: FAIL with `AttributeError: module ... has no attribute 'geometry_verdict'`, and `main()` failing on the argument list.

Step 3: Add the geometry row

In `scripts/verify_regions.py`:

3a. In the docstring, after the `* MISSING -> ...` bullet (line 28), add:

```
  * ORPHAN (the geometry row) -> the DEM on disk does not cover region.json's bounds
    or CRS. This is the pull orphan: a plate rebuilt elsewhere shipped its region.json
    to main and this machine's gitignored DEM stayed behind. Repair it (CLAUDE.md,
    the orphan repair). The engine refuses to render such a plate with a 503.

  The decisive rule: dem.tif DRIFT with geometry ok is a REBUILT plate, known and
  left alone. dem.tif DRIFT with geometry ORPHAN needs the repair.
```

3b. After the `from scripts.pack_region import _sha256_file` line, add the optional import:

```python
# The geometry row needs the render stack (rasterio via app.regions). The script stays
# stdlib-first: without it the row says "not checked" and everything else still runs.
try:
    from app.regions import Region as _Region   # noqa: E402
    def _readiness(region_dir: str) -> dict:
        root, rid = os.path.split(os.path.abspath(region_dir))
        return _Region(rid, root=root).readiness()
except Exception:                                # ImportError, or a broken venv
    _readiness = None


def geometry_verdict(region_dir: str) -> tuple[str, str]:
    """(verdict, detail) for the DEM's geometry against region.json.
    ok | ORPHAN | MISSING | skip. `skip` means the render stack is not installed here."""
    if _readiness is None:
        return ("skip", "not checked (render stack not installed; run from .venv)")
    if not os.path.exists(os.path.join(region_dir, "region.json")):
        return ("MISSING", "no region.json")
    rep = _readiness(region_dir)
    if not rep.get("dem_present"):
        return ("MISSING", "dem.tif absent")
    if rep.get("error"):
        return ("ORPHAN", f"DEM could not be opened: {rep['error']}")
    if rep.get("ready"):
        return ("ok", f"bounds drift {rep['bounds_drift_m']:.2f} m, CRS matches")
    why = (f"bounds drift {rep.get('bounds_drift_m', 0.0):.2f} m"
           if not rep.get("bounds_match", True) else "CRS differs from region.json")
    return ("ORPHAN", f"{why} -- the DEM on disk is not this plate's; "
                      f"run the orphan repair in CLAUDE.md")
```

3c. In `main()`, change the signature to `def main(argv=None) -> int:` and `args = ap.parse_args(argv)`. Then in the per-region loop, after the hash rows print, add the geometry row and count it:

```python
        verdict, detail = geometry_verdict(os.path.join(root, rid))
        if verdict == "ok":
            print(f"  ok     geometry  {detail}")
        elif verdict == "skip":
            print(f"  --     geometry  {detail}")
        else:
            print(f"  {verdict:<6} geometry  {detail}")
            bad += 1
```

3d. Update the closing message so the count reads right:

```python
    if bad:
        print(f"\n{bad} drifted, missing, or orphaned finding(s). This is a finding to "
              f"READ, not a failure to clear -- see this script's docstring for what "
              f"each kind means. ORPHAN is the one that needs repair. Do not re-stamp "
              f"a sidecar to make it quiet.")
```

Step 4: Run the tests to verify they pass

```bash
./.venv/bin/python -m pytest -q tests/test_verify_regions.py
./.venv/bin/python scripts/verify_regions.py
```

Expected: tests PASS. The script prints five plates; `lassen_ca` reads `7/7 ok` plus `ok     geometry  bounds drift 0.00 m`; the other four keep their `DRIFT  dem.tif` row and gain `ok     geometry  bounds drift 0.00 m`. No ORPHAN anywhere. Exit 1, as before, from the four known hash drifts.

Step 5: Commit

```bash
git add scripts/verify_regions.py tests/test_verify_regions.py
git commit -m "verify_regions: a geometry row tells a rebuilt plate from an orphan

Four of five plates carry a deliberate dem.tif hash drift, so the DRIFT
row is already red by design and a fresh pull orphan printed the same
line. The new row reads region.json against the DEM's own bounds and CRS
through Region.readiness(): ok is a rebuilt plate, ORPHAN needs the
repair. Stdlib-first stands -- without the render stack the row says
'not checked' and the hash audit runs as before."
```

---

### Task 5: The farm skips a drifted plate

Files:
- Modify: `scripts/render_asset_farm.py` (`_ensure_dem` around line 591, its caller around line 729)
- Create: `tests/test_asset_farm_gate.py`

Step 1: Write the failing test

```python
# tests/test_asset_farm_gate.py
# The farm paints marketing images from real terrain, and the deploy guard checks
# the DEM's provenance stamp -- but a DEM that is present, real, and ORPHANED
# (bounds no longer region.json's) would stamp cleanly and paint a misregistered
# poster. _ensure_dem must treat geometry drift as "no usable DEM", never as present.
from app import regions
from scripts.render_asset_farm import _ensure_dem
from tests.test_readyz import _write_region

GOOD = (600000.0, 4400000.0, 610000.0, 4410000.0)
SHIFTED = (605000.0, 4405000.0, 615000.0, 4415000.0)


def test_drifted_dem_is_skipped_with_its_own_reason(tmp_path, capsys):
    _write_region(str(tmp_path), "orphan", GOOD, SHIFTED)
    why = _ensure_dem(regions.Region("orphan", root=str(tmp_path)), allow_synthetic=False)
    assert why is not None and "5000.00 m" in why
    assert "orphan" in capsys.readouterr().out


def test_drifted_dem_is_not_papered_over_by_synthetic_mode(tmp_path):
    """--synthetic-dem hydrates a MISSING DEM only. A drifted real one still refuses."""
    _write_region(str(tmp_path), "orphan", GOOD, SHIFTED)
    why = _ensure_dem(regions.Region("orphan", root=str(tmp_path)), allow_synthetic=True)
    assert why is not None and "5000.00 m" in why


def test_healthy_dem_returns_none(tmp_path):
    _write_region(str(tmp_path), "good", GOOD, GOOD)
    assert _ensure_dem(regions.Region("good", root=str(tmp_path)), allow_synthetic=False) is None


def test_missing_dem_without_synthetic_is_the_old_reason(tmp_path):
    _write_region(str(tmp_path), "nodem", GOOD, GOOD, with_dem=False)
    why = _ensure_dem(regions.Region("nodem", root=str(tmp_path)), allow_synthetic=False)
    assert why is not None and "no DEM" in why
```

Step 2: Run the test to verify it fails

```bash
./.venv/bin/python -m pytest -q tests/test_asset_farm_gate.py
```

Expected: FAIL. `_ensure_dem` returns `True`/`False` today, so the `is None` and `"5000.00 m" in why` assertions break.

Step 3: Return a reason instead of a bool

Replace `_ensure_dem`:

```python
def _ensure_dem(region: Region, allow_synthetic: bool) -> str | None:
    """None when the plate can paint, else the reason it cannot (the farm records it
    and exits non-zero). Three refusals, in order:
      * DEM present but its geometry drifts from region.json -> the pull orphan.
        Refused even under --synthetic-dem: that flag stands in for a MISSING DEM and
        must never paper over a real one that is wrong.
      * DEM missing, no --synthetic-dem -> skip.
      * DEM missing, --synthetic-dem -> hydrate the test stand-in (preview only)."""
    ready = region.readiness()
    if ready.get("dem_present"):
        if ready.get("ready"):
            return None
        why = (f"DEM geometry drifts {ready.get('bounds_drift_m', 0.0):.2f} m from "
               f"region.json (orphaned DEM; run the orphan repair in CLAUDE.md)")
        print(f"  ! {region.id}: {why} -- skipping")
        return why
    if not allow_synthetic:
        print(f"  ! {region.id}: no DEM present -- skipping (pass --synthetic-dem for a preview)")
        return "no DEM (pass --synthetic-dem to stand one in)"
    import tests.conftest  # noqa: F401  -- importing hydrates every missing DEM synthetically
    print(f"  · {region.id}: hydrated a SYNTHETIC DEM (preview only, not real terrain)")
    if region.readiness().get("ready"):
        return None
    return "synthetic hydration did not produce a usable DEM"
```

And the caller in `main()`:

```python
        if needs_render:
            why = _ensure_dem(region, args.synthetic_dem)
            if why is not None:
                failed.append((rid, why))
                continue
```

Step 4: Run the tests to verify they pass

```bash
./.venv/bin/python -m pytest -q tests/test_asset_farm_gate.py tests/test_asset_farm_detail.py tests/test_asset_farm_frame.py tests/test_terrain_provenance.py
```

Expected: PASS.

Step 5: Commit

```bash
git add scripts/render_asset_farm.py tests/test_asset_farm_gate.py
git commit -m "farm: an orphaned DEM is not a DEM the farm may paint from

_ensure_dem answered 'present', and an orphaned DEM is present. It now
answers with the reason a plate cannot paint, and geometry drift is one:
the run records it and exits non-zero (6bf0160). --synthetic-dem still
stands in for a missing DEM only; it cannot paper over a wrong one."
```

---

### Task 6: One sentence in `CLAUDE.md`

Files:
- Modify: `CLAUDE.md` (lines 89 to 90)

Step 1: Edit

Find:

```
  `a6a93c2 → 5a0094e` re-orphaned it at 509.83 m drift. **After any pull touching
  `regions/`, run `regions.discover()` → `readiness()` before trusting a render.**
```

Replace with:

```
  `a6a93c2 → 5a0094e` re-orphaned it at 509.83 m drift. **After any pull touching
  `regions/`, run `regions.discover()` → `readiness()` before trusting a render.**
  Since 2026-09-01 the engine asks for you: every render verb refuses an orphaned
  plate with a 503 that names the drift (`_ready_or_503` in `app/main.py`, no
  override), the farm skips it, and `scripts/verify_regions.py` prints a geometry
  row whose `ORPHAN` verdict is the one finding that needs the repair below.
```

Step 2: Commit

```bash
git add CLAUDE.md
git commit -m "docs: the orphan is now refused, not merely detectable"
```

---

### Task 7: Full verification

Step 1: Run the whole suite

```bash
./.venv/bin/python -m pytest -q -n auto 2>&1 | tail -25
```

Expected: about 10 minutes. The failure set must be exactly the seven font-metric tests in `CLAUDE.md` § Known local failures, plus nothing. New tests: 8 in `test_geometry_gate.py`, 6 in `test_verify_regions.py`, 4 in `test_asset_farm_gate.py`.

Step 2: Prove the gate on the real registry

```bash
./.venv/bin/python -c "
import app.main as m
for r in m.REGIONS.values():
    print(r.id, m._ready_or_503(r).readiness()['bounds_drift_m'], 'm')
"
```

Expected: five lines, each `0.0 m` or within a pixel. A raised `HTTPException` here means a plate on this Mac is orphaned right now.

Step 3: Push

```bash
git push origin main
```

Expected: CI runs the full tier on push to `main` and stays green. The synthetic DEMs CI hydrates match their bounds exactly, so the gate is silent there.

Step 4: Log the session to Notion per `CLAUDE.md` § Session logging. Open a Decisions record: "DEM geometry drift is refused at the engine, 503, no override" with the context that the hash check was already red by design on four plates.

---

## What this does not do

- No git hook. The gate catches the orphan however it arrives; a hook would only add an earlier message on this Mac.
- No override flag. A misregistered DEM has no honest render.
- No readiness cache. One GeoTIFF header read per request. Add a stat-keyed memo only if a profile shows it on the proof loop.
- `/readyz` and `/api/reprint/inspect` are unchanged.
- No front-end change. `api.js` already surfaces `detail`.
