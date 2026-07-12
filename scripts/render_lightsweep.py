#!/usr/bin/env python3
"""The light-sweep turntable -- tier 1 of the social-preview suite.

The same composition rendered AZ_STEPS times with the sun's azimuth walking a full
circle, encoded as a seamless MP4 loop: shadows wheel around the ranges and the
terrain itself reads as three-dimensional relief. Nothing is mocked up -- the
poster's tracks, labels, and halos are lighting-independent, so ONLY the land
relights. This is the product's own DEM doing the 3D, which is the point.

The sweep is anchored at the region's own light azimuth: frame 0 is pixel-equal to
the ordinary poster render (asserted in tests), and the 360-degree wrap makes the
loop free. Deterministic end to end: fixed azimuth grid, deterministic renders, the
MP4 twin's bitexact encoder. Share-class: no manifest aboard.

Needs the region's terrain on disk (this re-renders), unlike the object mockups
(scripts/render_mockups.py) which stage a final's own pixels and need nothing.
"""
from __future__ import annotations
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import provenance, render, timelapse  # noqa: E402
from scripts.render_mockups import PNG_MAGIC  # noqa: E402

AZ_STEPS     = 60          # azimuth samples around the circle (6 degrees apart)
TICKS_PER_AZ = 5           # 25 fps ticks each azimuth holds -> a 12 s seamless loop
TARGET_PX    = 1080        # long-edge target for the default dpi choice


def sweep_frames(spec, dpi, region_dir, cfg):
    """Yield AZ_STEPS renders, azimuth walking (home + i*step) % 360. The cfg
    override rides the same seam the asset farm already uses (rasterize(cfg=...));
    everything but the relief lighting is identical frame to frame."""
    home = float(cfg.get("light_azimuth", 315))
    step = 360.0 / AZ_STEPS
    for i in range(AZ_STEPS):
        az = (home + i * step) % 360.0
        yield render.rasterize(spec, dpi=dpi, region_dir=region_dir,
                               watermark=False, cfg={**cfg, "light_azimuth": az})


def sweep_mp4(spec, dpi, region_dir, cfg) -> bytes:
    """The full turntable as MP4 bytes, streamed through the twin's bitexact
    encoder -- one rendered frame in flight at a time."""
    exe = timelapse.require_ffmpeg()
    frames = sweep_frames(spec, dpi, region_dir, cfg)
    first = next(frames)

    def _ticks():
        yield first, TICKS_PER_AZ
        for f in frames:
            yield f, TICKS_PER_AZ

    return timelapse._mp4_stream(exe, first.size, _ticks())


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("final", help="a TrailPrint final PNG whose manifest names the composition")
    ap.add_argument("--region-dir", required=True,
                    help="the plate directory (dem.tif etc.) -- the sweep re-renders")
    ap.add_argument("-o", "--out", default=None)
    ap.add_argument("--dpi", type=float, default=0.0,
                    help="render dpi (default: sized so the long edge ~ 1080 px)")
    args = ap.parse_args(argv)
    with open(args.final, "rb") as f:
        data = f.read()
    if not data.startswith(PNG_MAGIC):
        # a wrong file gets an honest refusal -- no embed_spec toggle will ever
        # put a manifest in a JPEG export
        print(f"not a PNG: {os.path.basename(args.final)} — the sweep takes a "
              "TrailPrint final", file=sys.stderr)
        return 2
    manifest = provenance.extract(data)
    if manifest is None:
        print("this PNG carries no manifest — the sweep re-renders from the recipe, "
              "so it needs a reprintable final (embed_spec on)", file=sys.stderr)
        return 2
    try:
        spec = provenance.spec_from_manifest(manifest)     # the one untrusted door
    except Exception as e:
        print(str(e), file=sys.stderr)
        return 2
    with open(os.path.join(args.region_dir, "region.json")) as f:
        cfg = json.load(f)
    dpi = args.dpi or TARGET_PX / max(spec.print_w_in, spec.print_h_in)
    out = args.out or os.path.join(
        os.path.dirname(os.path.abspath(args.final)) or ".",
        os.path.splitext(os.path.basename(args.final))[0] + "_lightsweep.mp4")
    try:
        data = sweep_mp4(spec, dpi, args.region_dir, cfg)
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        return 2
    with open(out, "wb") as f:
        f.write(data)
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
