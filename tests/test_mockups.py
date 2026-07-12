# tests/test_mockups.py
"""The social-preview suite: mockup stills stage the final's OWN pixels as a physical
object (deterministically -- same input, byte-identical JPEG), the film APNG routes to
the yawing video twin, the lightsweep relights the real terrain, and the GLB plate is
a structurally sound model. Share-class assets: nothing here carries a manifest."""
import io
import json
import math
import os
import struct

import numpy as np
import pytest
from PIL import Image, ImageDraw
from PIL.PngImagePlugin import PngInfo

from scripts.render_mockups import (
    MockupError, PAPER, SIZES, VARIANTS, WALL, caption_text, expected_video_ticks,
    load_final, render_mockup, write_depth_map, write_jpeg, yaw_at_tick, _wall,
    _yaw_quad,
)

REGION_DIR = "regions/lassen_ca"


def _final_png(tmp_path, name="final.png", size=(320, 420), manifest=None):
    """A cheap stand-in final: two-axis gradient + dark blobs (enough luminance
    structure for the emboss), optionally carrying a real zTXt manifest."""
    w, h = size
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float64)
    base = 90 + 100 * (xx / w) + 40 * (yy / h)
    img = Image.fromarray(np.dstack([base, base * 0.9, base * 0.7]
                                    ).astype(np.uint8), "RGB")
    d = ImageDraw.Draw(img)
    d.ellipse((40, 60, 120, 140), fill=(40, 45, 30))
    d.ellipse((180, 240, 290, 350), fill=(60, 50, 35))
    path = str(tmp_path / name)
    kw = {}
    if manifest is not None:
        info = PngInfo()
        info.add_text("trailprint", json.dumps(manifest), zip=True)
        kw["pnginfo"] = info
    img.save(path, "PNG", **kw)
    return path


MANIFEST = {"manifest_version": 1, "region_id": "lassen_ca",
            "spec": {"title_text": "Lassen Volcanic", "region_id": "lassen_ca",
                     "edition": 2}}


def _apng(tmp_path, name="film.png", n=2, size=(200, 200)):
    frames = []
    for i in range(n):
        a = np.full((size[1], size[0], 3), 60 + 60 * i, dtype=np.uint8)
        frames.append(Image.fromarray(a, "RGB"))
    path = str(tmp_path / name)
    frames[0].save(path, "PNG", save_all=True, append_images=frames[1:],
                   duration=[120] * n, loop=0)
    return path


# ---- stills ----

def test_two_runs_byte_equal(tmp_path):
    p = _final_png(tmp_path, manifest=MANIFEST)
    frames, _, m = load_final(p)
    for variant in VARIANTS:
        a, b = str(tmp_path / "a.jpg"), str(tmp_path / "b.jpg")
        write_jpeg(render_mockup(frames[0], m, variant, (1080, 1080)), a)
        write_jpeg(render_mockup(frames[0], m, variant, (1080, 1080)), b)
        assert open(a, "rb").read() == open(b, "rb").read(), variant


def test_sizes_exact_and_jpeg_magic(tmp_path):
    p = _final_png(tmp_path)
    frames, _, m = load_final(p)
    for variant in VARIANTS:
        for size in SIZES:
            out = str(tmp_path / f"{variant}_{size[0]}x{size[1]}.jpg")
            write_jpeg(render_mockup(frames[0], m, variant, size), out)
            raw = open(out, "rb").read()
            assert raw[:3] == b"\xff\xd8\xff"
            im = Image.open(io.BytesIO(raw))
            assert im.size == size and im.mode == "RGB"


def test_plate_reads_as_disc(tmp_path):
    frames, _, m = load_final(_final_png(tmp_path))
    scene = render_mockup(frames[0], m, "plate", (1080, 1080), caption=False)
    wall = _wall((1080, 1080))
    for xy in ((4, 4), (1075, 4), (4, 1075), (1075, 1075)):
        assert scene.getpixel(xy) == wall.getpixel(xy), xy   # corners: bare wall
    cx = scene.getpixel((540, 500))
    assert cx != wall.getpixel((540, 500))                    # center: the plate


def test_plate_bevel_is_directional(tmp_path):
    # a uniform mid-gray final isolates dome+bevel: the rim's upper-left must catch
    # the light and the lower-right must fall away from it
    img = Image.new("RGB", (300, 300), (128, 128, 128))
    path = str(tmp_path / "gray.png")
    img.save(path, "PNG")
    frames, _, m = load_final(path)
    scene = np.asarray(render_mockup(frames[0], m, "plate", (1080, 1080),
                                     caption=False).convert("L"), dtype=np.float64)
    d = round(0.62 * 1080)
    cx, cy = 540, round(0.47 * 1080)
    r_out, r_in = d / 2, d / 2 - 0.035 * d / 2 - 8
    yy, xx = np.mgrid[0:1080, 0:1080]
    rr = np.hypot(xx - cx, yy - cy)
    band = (rr < r_out - 2) & (rr > r_in)
    ul = band & (xx < cx) & (yy < cy)
    lr = band & (xx > cx) & (yy > cy)
    assert scene[ul].mean() > scene[lr].mean() + 2


def test_frame_has_mat(tmp_path):
    frames, _, m = load_final(_final_png(tmp_path))
    scene = np.asarray(render_mockup(frames[0], m, "frame", (1080, 1080),
                                     caption=False, sheen=False))
    paper = np.array(PAPER)
    wall = np.asarray(_wall((1080, 1080)))
    near_paper = (np.abs(scene.astype(int) - paper).max(axis=2) <= 6).sum()
    off_wall = (np.abs(scene.astype(int) - wall.astype(int)).max(axis=2) > 24).sum()
    assert near_paper > 20_000          # the mat band exists
    assert off_wall > 60_000            # and the artwork sits inside it


def test_apng_routes_to_video_mode(tmp_path):
    frames, durations, m = load_final(_apng(tmp_path, n=3))
    assert len(frames) == 3
    assert durations == [120, 120, 120]
    assert m is None


def test_refuses_non_png(tmp_path):
    j = tmp_path / "x.jpg"
    Image.new("RGB", (10, 10)).save(str(j), "JPEG")
    with pytest.raises(MockupError):
        load_final(str(j))
    t = tmp_path / "x.txt"
    t.write_text("not an image")
    with pytest.raises(MockupError):
        load_final(str(t))


def test_caption_from_manifest_and_absent(tmp_path):
    frames, _, m = load_final(_final_png(tmp_path, manifest=MANIFEST))
    assert caption_text(m) == "LASSEN VOLCANIC — EDITION 2"
    frames2, _, m2 = load_final(_final_png(tmp_path, name="bare.png"))
    assert m2 is None and caption_text(m2) is None
    render_mockup(frames2[0], m2, "plate", (1080, 1080))     # still succeeds


def test_caption_drops_on_malformed_manifest(tmp_path):
    # the manifest is untrusted input (any crafted PNG reaches here): a malformed
    # field type drops the caption -- never a traceback
    for bad in ({"spec": {"title_text": "X", "edition": "second"}},
                {"spec": ["not", "a", "dict"]},
                {"spec": {"title_text": 5}},
                {"spec": {}, "region_id": 7},
                {"spec": {"title_text": "X", "edition": {}}}):
        assert caption_text(bad) is None, bad
    # and the render itself survives such a PNG end to end
    frames, _, m = load_final(_final_png(
        tmp_path, name="crafted.png",
        manifest={"spec": {"title_text": "X", "edition": "second"}}))
    render_mockup(frames[0], m, "plate", (1080, 1080))


def test_caption_font_never_comes_from_host(tmp_path, monkeypatch):
    # the determinism contract ("no machine state") covers caption glyphs: the
    # placard face must be Pillow's own bundled font, never a host-installed TTF
    from PIL import ImageFont
    real_truetype = ImageFont.truetype

    def _no_host_fonts(font=None, *a, **k):
        if isinstance(font, (str, os.PathLike)):    # load_default passes a BytesIO
            raise AssertionError("caption font must not come from host TTFs")
        return real_truetype(font, *a, **k)

    monkeypatch.setattr(ImageFont, "truetype", _no_host_fonts)
    frames, _, m = load_final(_final_png(tmp_path, manifest=MANIFEST))
    render_mockup(frames[0], m, "plate", (1080, 1080))


def test_portrait_and_landscape_fit(tmp_path):
    for size_in in ((300, 420), (420, 300)):
        frames, _, m = load_final(_final_png(tmp_path, name=f"{size_in[0]}.png",
                                             size=size_in))
        for size in SIZES:
            scene = np.asarray(render_mockup(frames[0], m, "frame", size,
                                             caption=False, sheen=False))
            wall = np.asarray(_wall(size))
            diff = np.abs(scene.astype(int) - wall.astype(int)).max(axis=2) > 24
            ys, xs = np.nonzero(diff)
            margin = 8
            assert xs.min() >= margin and xs.max() < size[0] - margin
            assert ys.min() >= margin and ys.max() < size[1] - margin


# ---- video ----

def test_video_byte_equal_and_frame_count(tmp_path):
    pytest.importorskip("imageio_ffmpeg")
    from scripts.render_mockups import render_mockup_video
    frames, durations, m = load_final(_apng(tmp_path, n=2))
    a = render_mockup_video(frames, durations, m, "plate", (240, 240))
    b = render_mockup_video(frames, durations, m, "plate", (240, 240))
    assert a == b
    assert a[4:8] == b"ftyp"
    import imageio_ffmpeg
    import subprocess
    exe = imageio_ffmpeg.get_ffmpeg_exe()
    path = str(tmp_path / "v.mp4")
    open(path, "wb").write(a)
    out = subprocess.run([exe, "-i", path, "-f", "null", "-"],   # decode: emits frame=
                         capture_output=True, text=True)
    import re
    counts = re.findall(r"frame=\s*(\d+)", out.stderr)
    assert counts and int(counts[-1]) == expected_video_ticks(len(frames), durations)


def test_yaw_pure_and_seamless():
    period = round(4.0 * 25)
    assert yaw_at_tick(0) == pytest.approx(yaw_at_tick(period), abs=1e-9)
    assert _yaw_quad(100, 100, yaw_at_tick(0)) != _yaw_quad(100, 100, yaw_at_tick(7))
    assert yaw_at_tick(13) == yaw_at_tick(13)                # pure function of tick


def test_video_unavailable_is_honest(tmp_path, monkeypatch):
    from app import timelapse
    from scripts.render_mockups import render_mockup_video
    monkeypatch.setattr(timelapse, "MP4_AVAILABLE", False)
    frames, durations, m = load_final(_apng(tmp_path, n=2))
    with pytest.raises(RuntimeError, match="requirements-share.txt"):
        render_mockup_video(frames, durations, m, "plate", (240, 240))


# (encode_mp4's own pinned tests in tests/test_timelapse.py guard the writer refactor)


# ---- depth map ----

def test_depth_map(tmp_path):
    frames, _, m = load_final(_final_png(tmp_path))
    out = str(tmp_path / "depth.png")
    write_depth_map(frames[0], out)
    im = Image.open(out)
    assert im.size == frames[0].size and im.mode.startswith("I;16")
    write_depth_map(frames[0], str(tmp_path / "depth2.png"))
    assert open(out, "rb").read() == open(str(tmp_path / "depth2.png"), "rb").read()


# ---- lightsweep ----

def _lightsweep_spec():
    from app.regions import discover
    from app.density import hotspots
    from scripts.render_asset_farm import _synth_tracks, _base_spec
    region = discover("regions")["lassen_ca"]
    tracks = _synth_tracks(region)
    spots = hotspots(tracks, region.cfg["bounds"])
    return _base_spec(region, tracks, spots), region


def test_lightsweep_starts_home_and_counts():
    # the sweep is anchored at the region's own light azimuth, so frame 0 is
    # pixel-equal to the plain render -- the honesty of the effect: only the
    # light moves, never the artwork
    from scripts.render_lightsweep import sweep_frames, AZ_STEPS
    from app import render
    spec, region = _lightsweep_spec()
    frames = list(sweep_frames(spec, 24, region.dir, region.cfg))
    assert len(frames) == AZ_STEPS
    direct = render.rasterize(spec, dpi=24, region_dir=region.dir, cfg=region.cfg)
    assert np.array_equal(np.asarray(frames[0]), np.asarray(direct))


def test_lightsweep_two_runs_byte_equal(tmp_path):
    pytest.importorskip("imageio_ffmpeg")
    from scripts.render_lightsweep import sweep_mp4
    spec, region = _lightsweep_spec()
    a = sweep_mp4(spec, 16, region.dir, region.cfg)
    b = sweep_mp4(spec, 16, region.dir, region.cfg)
    assert a == b and a[4:8] == b"ftyp"


def test_lightsweep_cli_refuses_non_png(tmp_path, capsys):
    # a JPEG export must get an honest "not a PNG", not the embed_spec wild-goose
    # chase (no toggle will ever put a zTXt manifest in a JPEG)
    from scripts.render_lightsweep import main
    junk = tmp_path / "junk.png"
    junk.write_text("not an image")
    rc = main([str(junk), "--region-dir", REGION_DIR])
    err = capsys.readouterr().err
    assert rc == 2
    assert "not a PNG" in err
    assert "embed_spec" not in err


# ---- GLB ----

def test_glb_structure(tmp_path):
    from scripts.render_model import build_plate_glb, DISC_SEGMENTS, DISC_RINGS
    frames, _, _m = load_final(_final_png(tmp_path))
    glb = build_plate_glb(frames[0])
    assert glb[:4] == b"glTF"
    version, total = struct.unpack("<II", glb[4:12])
    assert version == 2 and total == len(glb)
    jlen, jtype = struct.unpack("<II", glb[12:20])
    assert jtype == 0x4E4F534A                       # 'JSON'
    doc = json.loads(glb[20:20 + jlen])
    assert doc["asset"]["version"] == "2.0"
    top = 1 + DISC_RINGS * DISC_SEGMENTS             # center + rings
    expected = 2 * top + 2 * DISC_SEGMENTS           # top + back + rim wall pair
    pos_acc = doc["accessors"][doc["meshes"][0]["primitives"][0]["attributes"]["POSITION"]]
    assert pos_acc["count"] == expected
    from scripts.render_model import DISC_THICKNESS, DISPLACE_MAX
    # displacement applied for a textured plate: z-range exceeds the bare thickness
    zs = pos_acc["max"][2] - pos_acc["min"][2]
    assert zs > DISC_THICKNESS + 0.25 * DISPLACE_MAX
    # ...and absent for uniform gray: z-range is the disc thickness alone
    flat = build_plate_glb(Image.new("RGB", (64, 64), (128, 128, 128)))
    fdoc = json.loads(flat[20:20 + struct.unpack("<II", flat[12:20])[0]])
    facc = fdoc["accessors"][fdoc["meshes"][0]["primitives"][0]["attributes"]["POSITION"]]
    assert facc["max"][2] - facc["min"][2] == pytest.approx(DISC_THICKNESS, abs=1e-6)


def test_glb_deterministic(tmp_path):
    from scripts.render_model import build_plate_glb
    frames, _, _m = load_final(_final_png(tmp_path))
    assert build_plate_glb(frames[0]) == build_plate_glb(frames[0])


# ---- farm integration ----

def test_farm_integration(tmp_path, monkeypatch):
    pytest.importorskip("imageio_ffmpeg")
    import sys
    import scripts.render_asset_farm as farm
    monkeypatch.setattr(sys, "argv",
                        ["render_asset_farm.py", "--regions", "lassen_ca",
                         "--only", "poster", "film", "mockups", "model",
                         "--quick", "--dpi", "32", "--film-dpi", "32",
                         "--film-frames", "4", "--synthetic-dem",
                         "--out", str(tmp_path)])
    farm.main()
    out = tmp_path / "lassen_ca"
    expect = [f"mockup_{v}_{w}x{h}.jpg" for v in VARIANTS for w, h in SIZES]
    expect += [f"mockup_{v}_{w}x{h}.mp4" for v in VARIANTS for w, h in SIZES]
    expect += ["mockup_plate.glb"]
    for name in expect:
        assert (out / name).exists(), name
    index = json.loads((tmp_path / "index.json").read_text())
    listed = json.dumps(index["lassen_ca"]["assets"])
    assert "mockup_plate.glb" in listed and "mockup_plate_1080x1080.jpg" in listed


def test_farm_failed_model_leaves_no_truncated_glb(tmp_path, monkeypatch):
    # a mid-build failure must not leave a 0-byte mockup_plate.glb that the landing
    # page's <model-viewer> would fetch by exact name and render broken
    import scripts.render_model as rm
    from scripts.render_asset_farm import _model
    _final_png(tmp_path, name="poster.png")

    def _boom(img):
        raise RuntimeError("boom")

    monkeypatch.setattr(rm, "build_plate_glb", _boom)
    with pytest.raises(RuntimeError):
        _model(str(tmp_path))
    assert not (tmp_path / "mockup_plate.glb").exists()


def test_farm_failed_lightsweep_leaves_no_truncated_mp4(tmp_path, monkeypatch):
    # same guarantee for the farm's slowest job: an ffmpeg death mid-encode must
    # not leave a 0-byte lightsweep.mp4 that reads as a finished asset
    import scripts.render_lightsweep as ls
    import scripts.render_asset_farm as farm
    from app.regions import discover

    def _boom(spec, dpi, region_dir, cfg):
        raise RuntimeError("ffmpeg died")

    monkeypatch.setattr(ls, "sweep_mp4", _boom)
    monkeypatch.setattr(farm.timelapse, "MP4_AVAILABLE", True)
    region = discover("regions")["lassen_ca"]
    with pytest.raises(RuntimeError):
        farm._lightsweep(region, [], [], str(tmp_path))
    assert not (tmp_path / "lightsweep.mp4").exists()


def test_farm_all_skipped_run_leaves_index_alone(tmp_path, monkeypatch):
    # --only mockups model with nothing staged: three honest skip lines and NO
    # index.json -- an entry with "assets": [] would read as a rendered region
    import sys
    import scripts.render_asset_farm as farm
    monkeypatch.setattr(sys, "argv",
                        ["render_asset_farm.py", "--regions", "lassen_ca",
                         "--only", "mockups", "model", "--out", str(tmp_path)])
    farm.main()
    assert not (tmp_path / "index.json").exists()


def test_farm_index_merge_keeps_prior_assets(tmp_path, monkeypatch):
    # the "works on any machine with yesterday's assets" mode must not overwrite a
    # full-run index with a mockup-only one while the real files still sit on disk
    import sys
    import scripts.render_asset_farm as farm
    base = ["render_asset_farm.py", "--regions", "lassen_ca", "--quick",
            "--dpi", "32", "--synthetic-dem", "--out", str(tmp_path)]
    monkeypatch.setattr(sys, "argv", base + ["--only", "poster"])
    farm.main()
    first = json.loads((tmp_path / "index.json").read_text())
    assert any("poster.png" in a for a in first["lassen_ca"]["assets"])
    monkeypatch.setattr(sys, "argv", base + ["--only", "model"])
    farm.main()
    index = json.loads((tmp_path / "index.json").read_text())
    listed = index["lassen_ca"]["assets"]
    assert any("poster.png" in a for a in listed)        # yesterday's asset survives
    assert any("mockup_plate.glb" in a for a in listed)  # today's is added
    assert len(listed) == len(set(listed))               # and nothing is doubled
