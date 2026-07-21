# tests/test_orphan_drill.py
"""The orphan drill -- the acceptance test of the whole continuity plan.

The promise ("What if you disappear?"): someone in 2035 holding NOTHING but one
poster PNG and the region's .trailplate.zip can resurrect the exact artwork on a
fresh machine. The PNG is its own save file (the zTXt manifest + the tEXt
resurrection note tell the finder so); the plate is the terrain it was painted on
(named by hash in the manifest's region_pack block); the engine is AGPL and public.

This module runs that story end to end, in-process:

  1. render a real final through the API against the live lassen_ca region;
  2. pack lassen_ca into a .trailplate.zip (scripts/pack_region.py, --resync: the
     committed sidecar records the real 3DEP DEM while this tree carries the
     conftest synthetic one -- exactly the drift a CI pack must repair in the
     zip's copy);
  3. install that plate into an EMPTY regions root (app.plates.install_plate) --
     the orphan machine, which never ran region_prep.py;
  4. point the app at the orphan root -- with the ORIGINAL region dir moved aside,
     so a reprint-path read that leaks back to the default root fails loudly
     instead of silently satisfying the byte comparison -- assert /readyz vouches
     for the installed plate (the installer's own output defers bounds checking
     there), then reprint the ORIGINAL final's bytes.

The reprint must be BYTE-IDENTICAL to the original download -- same plate bytes +
same spec + re-stamped identical manifest + identical note == identical file.
That byte equality IS the product claim; if this drill fails, the release doesn't
ship. Alongside it: /api/reprint/inspect must answer plate == "verified" on the
orphan server, and a server with NO regions at all must refuse with the honest
422 that names the plate the file wants."""
import json
import os

import pytest

from app import main, provenance, regions
from app.plates import install_plate
from scripts.pack_region import pack_region

REGION_DIR = "regions/lassen_ca"

# This drill moves the SHARED regions/lassen_ca dir aside for a few seconds (its
# defense against a reprint leaking to the default root). Under `pytest -n auto` that
# makes lassen briefly vanish for every other worker mid-render, so this test must run
# ALONE: CI runs `-m "not serial"` in parallel, then `-m serial` on its own.
pytestmark = pytest.mark.serial


def _client():
    from fastapi.testclient import TestClient
    return TestClient(main.app)


def _crop(j, km_wide=40.0, ar=0.75):
    cfg = json.load(open(os.path.join(REGION_DIR, "region.json")))
    region_w = cfg["bounds"][2] - cfg["bounds"][0]
    ovw, ovh = j["overview_size"]
    cw = ovw * (km_wide * 1000.0 / region_w); ch = cw / ar
    x0 = ovw * 0.5 - cw / 2; y0 = ovh * 0.5 - ch / 2
    return {"x0": x0, "y0": y0, "x1": x0 + cw, "y1": y0 + ch}


def _final_png(c):   # one small (6x8 in, 300 dpi) final: the drill's only slow render
    files = [("files", ("a.gpx", open("tests/fixtures/sample.gpx", "rb").read(),
                        "application/gpx+xml"))]
    j = c.post("/api/upload", files=files).json()
    r = c.post("/api/proof", data={"session_id": j["session"], **_crop(j),
                                   "print_w": 6, "print_h": 8, "title": "Trip"})
    assert r.status_code == 200, r.text
    return c.post("/api/final", data={"session_id": j["session"], "format": "png",
                                      "embed_spec": "true"}).content


def test_orphan_server_resurrects_the_poster_byte_identically(tmp_path, monkeypatch):
    # 1. the original: a real final off the live region, manifest + note embedded
    c = _client()
    final_png = _final_png(c)
    manifest = provenance.extract(final_png)
    file_pv = manifest["region_pack"]["pack_version"]

    # 2. + 3. pack the plate, install it into an EMPTY regions root (the orphan
    # machine: no region_prep run, no repo regions dir -- only the zip)
    plate = pack_region("lassen_ca", regions_root="regions",
                        out_dir=str(tmp_path / "plates"), resync=True)
    orphan_root = tmp_path / "orphan-regions"
    orphan_root.mkdir()
    assert install_plate(plate, root=str(orphan_root)) == "lassen_ca"

    # 4. the app now sees ONLY the installed plate (REGIONS is the import-time
    # registry; monkeypatch restores the real one after the test). The ORIGINAL
    # region dir is moved aside for the orphan steps: it holds byte-identical
    # assets to the plate, so leaving it in place would let any code path that
    # silently falls back to the default regions root satisfy the byte comparison
    # -- the drill must FAIL loudly if a reprint read escapes the orphan root,
    # exactly as a real 2035 machine (no repo regions/ dir at all) would.
    monkeypatch.setattr(main, "REGIONS", regions.discover(str(orphan_root)))
    assert list(main.REGIONS) == ["lassen_ca"]
    aside = REGION_DIR + ".orphan-drill-aside"    # same fs: a plain rename suffices
    os.rename(REGION_DIR, aside)
    try:
        # the installer defers bounds verification to /readyz ("installed — /readyz
        # will confirm bounds"): hold it to that. Hash consistency alone can't catch
        # a dem.tif/region.json bounds disagreement packed with --resync, so the
        # orphan server must ALSO report the installed plate render-ready.
        r = c.get("/readyz")
        assert r.status_code == 200, r.text
        report = r.json()
        assert report["ready"] is True
        (entry,) = report["regions"]
        assert entry["id"] == "lassen_ca"
        assert entry["ready"] is True and entry["bounds_match"] is True

        # the orphan server vouches for the plate before rendering anything
        body = c.post("/api/reprint/inspect",
                      files={"file": ("poster.png", final_png, "image/png")}).json()
        assert body["plate"] == "verified"
        assert body["plate_file"] == file_pv and body["plate_server"] == file_pv

        # ... and the resurrection: the reprint IS the original file, byte for byte
        # (same plate bytes -> same pixels; re-stamped manifest + note identical ->
        # identical chunks -> identical PNG). Full equality on purpose: pixel-only
        # equality would let a chunk-order or metadata regression ship silently.
        r = c.post("/api/reprint",
                   files={"file": ("poster.png", final_png, "image/png")})
        assert r.status_code == 200, r.text
        assert r.content == final_png

        # a server with no regions at all: the honest 422 names the plate the file
        # wants, so the finder knows exactly what to install
        bare_root = tmp_path / "bare-regions"
        bare_root.mkdir()
        monkeypatch.setattr(main, "REGIONS", regions.discover(str(bare_root)))
        r = c.post("/api/reprint",
                   files={"file": ("poster.png", final_png, "image/png")})
        assert r.status_code == 422
        detail = r.json()["detail"]
        assert "lassen_ca" in detail and file_pv in detail
    finally:
        os.rename(aside, REGION_DIR)
