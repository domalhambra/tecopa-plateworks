# tests/test_plates.py
"""Plates become distributable artifacts: scripts/pack_region.py emits a byte-stable
.trailplate.zip whose copy of sources.json never lies (the drift gate), app.plates
installs one only after re-verifying every asset hash (zip-slip and tamper refused),
and verify_poster closes the loop -- a rendered final's region_pack block checks out
against the installed plate, and a mutated plate is named, never silently accepted."""
import hashlib
import io
import json
import os
import shutil
import zipfile

import pytest
from PIL import Image

from app.plates import PlateError, install_plate, verify_poster
from scripts.pack_region import DriftError, pack_region

SRC_REGION = "regions/lassen_ca"
DOS_EPOCH = (1980, 1, 1, 0, 0, 0)


def _region_copy(tmp_path, rid="lassen_ca"):
    """Copy the built lassen region into a tmp regions root. The copy carries the
    conftest synthetic DEM whose bytes do NOT match the sha256 the committed
    sources.json records for the real 3DEP raster -- exactly the drift the pack gate
    must catch (and --resync must repair in the zip's copy only)."""
    root = tmp_path / "regions"
    root.mkdir(exist_ok=True)
    dst = root / rid
    shutil.copytree(SRC_REGION, dst)
    if rid != "lassen_ca":
        for name in ("sources.json", "region.json"):
            with open(dst / name) as f:
                d = json.load(f)
            d["id"] = rid
            with open(dst / name, "w") as f:
                json.dump(d, f, indent=2)
    return str(root)


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ---- pack: determinism + the drift gate ----

def test_pack_twice_is_byte_identical_sorted_and_dos_dated(tmp_path):
    root = _region_copy(tmp_path)
    p1 = pack_region("lassen_ca", regions_root=root, out_dir=str(tmp_path / "out1"),
                     resync=True)
    p2 = pack_region("lassen_ca", regions_root=root, out_dir=str(tmp_path / "out2"),
                     resync=True)
    b1 = open(p1, "rb").read()
    assert b1 == open(p2, "rb").read()
    # the file names itself by its own zip hash
    assert os.path.basename(p1) == \
        f"lassen_ca-{hashlib.sha256(b1).hexdigest()[:12]}.trailplate.zip"
    with zipfile.ZipFile(io.BytesIO(b1)) as zf:
        names = zf.namelist()
        assert names == sorted(names)
        assert all(i.date_time == DOS_EPOCH for i in zf.infolist())
        with open(os.path.join(root, "lassen_ca", "sources.json")) as f:
            listed = json.load(f)["assets"]
        assert set(names) == {f"lassen_ca/{n}"
                              for n in list(listed) + ["sources.json", "PLATE.txt"]}


def test_drift_gate_refuses_by_default_naming_the_asset(tmp_path):
    root = _region_copy(tmp_path)     # synthetic DEM != recorded hash -> drifted
    with pytest.raises(DriftError) as ei:
        pack_region("lassen_ca", regions_root=root, out_dir=str(tmp_path / "out"))
    msg = str(ei.value)
    assert "dem.tif" in msg and "--resync" in msg
    assert not os.path.exists(tmp_path / "out")   # refused before emitting anything


def test_resync_packs_true_hashes_without_touching_the_source_dir(tmp_path):
    root = _region_copy(tmp_path)
    sidecar = os.path.join(root, "lassen_ca", "sources.json")
    before = open(sidecar, "rb").read()
    p = pack_region("lassen_ca", regions_root=root, out_dir=str(tmp_path / "out"),
                    resync=True)
    with zipfile.ZipFile(p) as zf:
        packed = json.loads(zf.read("lassen_ca/sources.json"))
    # the zip's COPY carries the TRUE disk hash of the (synthetic) DEM ...
    assert packed["assets"]["dem.tif"]["sha256"] == \
        _sha256(os.path.join(root, "lassen_ca", "dem.tif"))
    # ... and the source dir's sidecar is untouched, byte for byte
    assert open(sidecar, "rb").read() == before


# ---- install: happy path, refuse-then-replace ----

def test_install_happy_path_then_replace(tmp_path, capsys):
    root = _region_copy(tmp_path)
    p = pack_region("lassen_ca", regions_root=root, out_dir=str(tmp_path / "out"),
                    resync=True)
    dest = tmp_path / "installed"
    dest.mkdir()
    assert install_plate(p, root=str(dest)) == "lassen_ca"
    with zipfile.ZipFile(p) as zf:
        for n in zf.namelist():             # every member byte-equal to the pack
            assert open(os.path.join(dest, n), "rb").read() == zf.read(n)
    out = capsys.readouterr().out
    assert "lassen_ca" in out and "dem.tif" in out and "installed" in out
    with pytest.raises(PlateError) as ei:   # already installed -> refuse ...
        install_plate(p, root=str(dest))
    assert "--replace" in str(ei.value)
    assert install_plate(p, root=str(dest), replace=True) == "lassen_ca"  # ... unless asked
    assert (dest / "lassen_ca" / "region.json").exists()


def test_replace_leaves_no_phantom_region_dir(tmp_path):
    # --replace must not leave the old region as a sibling dir regions.discover()
    # would re-register (any root/<name>/region.json is a region to the registry) --
    # after the swap the root holds EXACTLY the installed region, nothing else.
    root = _region_copy(tmp_path)
    p = pack_region("lassen_ca", regions_root=root, out_dir=str(tmp_path / "out"),
                    resync=True)
    dest = tmp_path / "installed"
    dest.mkdir()
    install_plate(p, root=str(dest))
    install_plate(p, root=str(dest), replace=True)
    assert os.listdir(dest) == ["lassen_ca"]


def test_replace_restores_the_old_region_when_the_swap_fails(tmp_path, monkeypatch):
    # the docstring's guarantee: a failed install never leaves a half-region -- and
    # never a MISSING one. If the final rename into place dies (disk full, EPERM),
    # the old region must come back; --replace may not trade a working region for
    # nothing.
    root = _region_copy(tmp_path)
    p = pack_region("lassen_ca", regions_root=root, out_dir=str(tmp_path / "out"),
                    resync=True)
    dest = tmp_path / "installed"
    dest.mkdir()
    install_plate(p, root=str(dest))
    marker = dest / "lassen_ca" / "region.json"
    before = marker.read_bytes()
    real_replace = os.replace

    def failing(srcp, dstp):
        # fail ONLY the final swap: src is the extracted plate dir (basename == rid,
        # living outside the install root's top level), dst is the target.
        if (os.path.basename(srcp) == "lassen_ca"
                and os.path.dirname(srcp) != str(dest)):
            raise OSError("disk full")
        return real_replace(srcp, dstp)

    monkeypatch.setattr("app.plates.os.replace", failing)
    with pytest.raises(OSError):
        install_plate(p, root=str(dest), replace=True)
    monkeypatch.undo()
    assert os.listdir(dest) == ["lassen_ca"]      # the old region is back, alone
    assert marker.read_bytes() == before


def test_install_refuses_a_zip_whose_self_name_lies_about_its_hash(tmp_path):
    # the plate names itself <id>-<ziphash12>.trailplate.zip and that name rides the
    # download URL -- so an in-transit substitution (an internally consistent plate
    # whose own sources.json checks out) must be refused against the NAME's hash,
    # not discovered later as a confusing per-poster reprint mismatch.
    root = _region_copy(tmp_path)
    p_a = pack_region("lassen_ca", regions_root=root, out_dir=str(tmp_path / "outA"),
                      resync=True)
    # a second, internally consistent plate with different bytes: mutate one asset
    # and repack with --resync (the zip's sources.json copy stays truthful)
    with open(os.path.join(root, "lassen_ca", "hydro.json"), "ab") as f:
        f.write(b"\n")
    p_b = pack_region("lassen_ca", regions_root=root, out_dir=str(tmp_path / "outB"),
                      resync=True)
    assert os.path.basename(p_a) != os.path.basename(p_b)
    lying = tmp_path / os.path.basename(p_a)      # B's bytes under A's self-name
    shutil.copyfile(p_b, lying)
    dest = tmp_path / "installed"
    dest.mkdir()
    with pytest.raises(PlateError, match="sha256"):
        install_plate(str(lying), root=str(dest))
    assert os.listdir(dest) == []
    # the honest file under its own self-name still installs
    assert install_plate(p_a, root=str(dest)) == "lassen_ca"


def test_pack_identity_is_zlib_independent_members_stored(tmp_path):
    # the zip's sha256 IS the plate's published identity (the self-naming filename
    # and the committed index.json row). Deflate output is a property of the zlib
    # BUILD (zlib-ng and classic zlib emit different level-9 streams for the same
    # input), so a deflated plate's identity would silently fork across pack hosts.
    # Stored members keep the zip bytes a pure function of content + fixed metadata.
    root = _region_copy(tmp_path)
    p = pack_region("lassen_ca", regions_root=root, out_dir=str(tmp_path / "out"),
                    resync=True)
    with zipfile.ZipFile(p) as zf:
        assert all(i.compress_type == zipfile.ZIP_STORED for i in zf.infolist())


# ---- install: the refusals (zip-slip, allowlist, tamper) ----

def _write_zip(path, members):
    with zipfile.ZipFile(path, "w") as zf:
        for n, b in members.items():
            zf.writestr(n, b)
    return str(path)


def test_install_rejects_a_zip_slip_member(tmp_path):
    z = _write_zip(tmp_path / "evil.zip", {"../evil": b"x"})
    dest = tmp_path / "root"
    dest.mkdir()
    with pytest.raises(PlateError):
        install_plate(z, root=str(dest))
    assert os.listdir(dest) == []           # nothing extracted, temp cleaned

def test_install_rejects_a_member_outside_the_allowlist(tmp_path):
    z = _write_zip(tmp_path / "extra.zip",
                   {"aa/sources.json": b"{}", "aa/evil.bin": b"x"})
    dest = tmp_path / "root"
    dest.mkdir()
    with pytest.raises(PlateError) as ei:
        install_plate(z, root=str(dest))
    assert "evil.bin" in str(ei.value)
    assert os.listdir(dest) == []

def test_install_rejects_a_tampered_asset(tmp_path):
    root = _region_copy(tmp_path)
    p = pack_region("lassen_ca", regions_root=root, out_dir=str(tmp_path / "out"),
                    resync=True)
    tampered = tmp_path / "tampered.trailplate.zip"
    with zipfile.ZipFile(p) as zin, zipfile.ZipFile(tampered, "w") as zout:
        for n in zin.namelist():
            data = zin.read(n)
            if n.endswith("/dem.tif"):
                data = bytes([data[0] ^ 1]) + data[1:]   # one flipped bit
            zout.writestr(n, data)
    dest = tmp_path / "root"
    dest.mkdir()
    with pytest.raises(PlateError, match="corrupt or was tampered"):
        install_plate(str(tampered), root=str(dest))
    assert os.listdir(dest) == []           # tmp cleaned, target root untouched


# ---- plates/index.json ----

def test_index_is_deterministic_and_sorted(tmp_path):
    root = _region_copy(tmp_path)
    _region_copy(tmp_path, rid="aaa_alpha")
    out = tmp_path / "plates"
    p = pack_region("lassen_ca", regions_root=root, out_dir=str(out), resync=True)
    idx_path = out / "index.json"
    first = open(idx_path, "rb").read()
    pack_region("lassen_ca", regions_root=root, out_dir=str(out), resync=True)
    assert open(idx_path, "rb").read() == first       # repack -> identical index
    pack_region("aaa_alpha", regions_root=root, out_dir=str(out), resync=True)
    idx = json.loads(open(idx_path, "rb").read())
    assert idx["schema"] == 1
    assert [e["id"] for e in idx["plates"]] == ["aaa_alpha", "lassen_ca"]
    entry = idx["plates"][1]
    assert entry["file"] == os.path.basename(p)
    assert entry["sha256"] == _sha256(p) and entry["bytes"] == os.path.getsize(p)
    with zipfile.ZipFile(p) as zf:
        packed = json.loads(zf.read("lassen_ca/sources.json"))["assets"]
    assert entry["assets"] == {n: a["sha256"] for n, a in packed.items()}


# ---- verify: the poster checks its plate ----

def _client():
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)

def _crop(j, km_wide=40.0, ar=0.75):
    with open(os.path.join(SRC_REGION, "region.json")) as f:
        cfg = json.load(f)
    region_w = cfg["bounds"][2] - cfg["bounds"][0]
    ovw, ovh = j["overview_size"]
    cw = ovw * (km_wide * 1000.0 / region_w); ch = cw / ar
    x0 = ovw * 0.5 - cw / 2; y0 = ovh * 0.5 - ch / 2
    return {"x0": x0, "y0": y0, "x1": x0 + cw, "y1": y0 + ch}

def _final_png(c):
    files = [("files", ("a.gpx", open("tests/fixtures/sample.gpx", "rb").read(),
                        "application/gpx+xml"))]
    j = c.post("/api/upload", files=files).json()
    r = c.post("/api/proof", data={"session_id": j["session"], **_crop(j),
                                   "print_w": 6, "print_h": 8, "title": "Trip"})
    assert r.status_code == 200, r.text
    return c.post("/api/final", data={"session_id": j["session"], "format": "png"}).content


def test_verify_poster_verified_then_mismatch(tmp_path, capsys):
    poster = tmp_path / "poster.png"
    poster.write_bytes(_final_png(_client()))
    # install the SAME plate bytes into a fresh root: pack the live regions dir
    # (--resync: the committed sidecar records the real 3DEP DEM, the disk carries
    # the conftest synthetic one) and install the pack.
    p = pack_region("lassen_ca", regions_root="regions", out_dir=str(tmp_path / "out"),
                    resync=True)
    dest = tmp_path / "root"
    dest.mkdir()
    install_plate(p, root=str(dest))
    capsys.readouterr()
    assert verify_poster(str(poster), root=str(dest)) == 0
    assert "verified" in capsys.readouterr().out
    with open(dest / "lassen_ca" / "dem.tif", "ab") as f:
        f.write(b"\0")                       # the plate mutates under the poster
    assert verify_poster(str(poster), root=str(dest)) == 1
    out = capsys.readouterr().out
    assert "mismatch" in out and "dem.tif" in out


def test_verify_poster_refuses_an_out_of_root_region_id(tmp_path, capsys):
    from app import provenance
    # a region dir OUTSIDE the verify root, exactly where a traversal id points --
    # verify_poster must never join an untrusted region_id into a path (install and
    # the resurrection note both gate on [a-z0-9_]+; verify is the same door)
    victim = tmp_path / "victim"
    victim.mkdir()
    (victim / "region.json").write_text("{}")
    secret = b"out-of-root bytes the verifier must never hash"
    (victim / "dem.tif").write_bytes(secret)
    (victim / "sources.json").write_text(json.dumps(
        {"assets": {"dem.tif": {"sha256": hashlib.sha256(secret).hexdigest()}}}))
    manifest = {"manifest_version": 1,
                "spec": {"region_id": "../../victim"},
                "region_pack": {"pack_version": "0" * 12,
                                "assets": {"dem.tif": "0" * 64}}}
    from PIL import Image as _I
    buf = io.BytesIO()
    _I.new("RGB", (8, 8)).save(buf, "PNG",
                               pnginfo=provenance.manifest_pnginfo(manifest))
    poster = tmp_path / "evil.png"
    poster.write_bytes(buf.getvalue())
    root = tmp_path / "a" / "b"                     # ../../victim escapes this root
    root.mkdir(parents=True)
    assert verify_poster(str(poster), root=str(root)) == 1
    out = capsys.readouterr().out
    assert "region id" in out                       # named refusal, not a verdict
    # no out-of-root read: the victim asset's real hash never reaches the output
    assert hashlib.sha256(secret).hexdigest()[:12] not in out


def test_verify_poster_pre_pack_and_region_missing(tmp_path, capsys):
    from app import provenance
    # a pre-pack poster: manifest without a region_pack block -> soft, exit 0
    with open("tests/fixtures/manifest_v1.json") as f:
        m = json.load(f)
    spec = provenance.manifest_to_spec(m)
    manifest = provenance.build_manifest(spec, m.get("sources", []))
    assert "region_pack" not in manifest
    img = Image.new("RGB", (16, 16), (30, 40, 50))
    buf = io.BytesIO()
    img.save(buf, "PNG", pnginfo=provenance.manifest_pnginfo(manifest))
    prepack = tmp_path / "prepack.png"
    prepack.write_bytes(buf.getvalue())
    assert verify_poster(str(prepack), root=str(tmp_path)) == 0
    assert "unverifiable" in capsys.readouterr().out
    # a packed poster against a root where the region was never installed -> exit 1
    poster = tmp_path / "poster.png"
    poster.write_bytes(_final_png(_client()))
    empty = tmp_path / "empty"
    empty.mkdir()
    assert verify_poster(str(poster), root=str(empty)) == 1
    assert "not installed" in capsys.readouterr().out
