# scripts/render_asset_farm.py
"""Render the Phase-0 marketing asset farm (see docs/marketing.md).

The marketing plan's "do first": turn each curated region into a spread of finished
deliverables so the landing page, the Show HN post, and the social drops all have real
imagery to use. This script drives the render engine DIRECTLY (no server needed) and
produces, per region:

  poster.png            a full-region print, with named/iconed hotspots and a pinned
                        photo -- carrying its own provenance manifest (the file is the
                        artwork)
  wallpaper_<device>.png one screen-native wallpaper per requested preset
  film.png              a time-lapse APNG: the journeys ink themselves in day order,
                        ending on the finished poster (the "watch the year draw itself"
                        beat)
  film.webp / film.mp4  the film's share twins for the social columns (mp4 only when
                        the share extra is installed) -- lossy, no manifest aboard
  edition_1/2/3.png     the same composition as three growing editions -- the "magic
                        trick": one frame, more ink, the cartouche climbing Edition 1->3

Every deliverable goes through the real final path (`provenance.build_final_spec` ->
`render.rasterize` -> embedded manifest), so this doubles as an end-to-end smoke test of
every output the product ships.

Usage:
    ./.venv/bin/python scripts/render_asset_farm.py                    # all regions, real DEMs
    ./.venv/bin/python scripts/render_asset_farm.py --regions lassen_ca --quick
    ./.venv/bin/python scripts/render_asset_farm.py --synthetic-dem    # local preview, no real DEM

Real 3DEP DEMs are gitignored (see region_prep.py). On a machine that has them, this
renders true terrain. Without them, pass --synthetic-dem to hydrate the same tiny
synthetic DEMs the test suite uses -- fine for wiring/preview, not for a real poster.
Outputs land under assets/<region_id>/ (override with --out).
"""
from __future__ import annotations
import argparse
import json
import os
import sys
from datetime import date, timedelta

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.regions import discover, Region
from app.ingest import Track
from app.density import hotspots
from app.spec import CompositionSpec
from app import render, provenance, timelapse, wallpaper

NATIVE_FLOOR_DPI = 300          # the zoom cap is judged at print dpi: 10 m/px at 300 dpi
HOTSPOT_LABELS = ["Base Camp", "The Notch", "North Shore", "South Fork", "The Marina",
                  "Trailhead", "High Overlook", "Cold Spring"]
HOTSPOT_ICONS = ["camp", "peak", "water", "flag", "camera", "star", "dot", "water"]


# ---- synthetic-but-plausible tracks, generated per region in its own CRS ----

def _synth_tracks(region: Region, n_days: int = 5, seed: int = 7) -> list:
    """A season of day-trips inside one region: a shared meandering corridor every day
    retraces (so density reads a worn path), each day branching off to its own spot, with
    light GPS jitter and a distinct date. Generated directly in the region's projected
    metres -- no lon/lat round-trip -- so it works for any region from its bounds alone."""
    w, s, e, n = region.cfg["bounds"]
    cx, cy = (w + e) / 2.0, (s + n) / 2.0
    span = min(e - w, n - s)
    R = span * 0.28                              # keep well inside the frame (off-DEM safe)
    rng = np.random.default_rng(seed)
    ang0 = rng.uniform(0, 2 * np.pi)

    def _meander(x0, y0, x1, y1, npts, amp, harmonics, rng):
        t = np.linspace(0, 1, npts)
        xs, ys = x0 + (x1 - x0) * t, y0 + (y1 - y0) * t
        off = np.zeros_like(t)
        for k in range(1, harmonics + 1):
            off += (amp / k) * np.sin(2 * np.pi * k * t + rng.uniform(0, 2 * np.pi))
        off *= np.sin(np.pi * t) ** 0.5           # taper to the anchored endpoints
        perp = np.arctan2(y1 - y0, x1 - x0) + np.pi / 2
        return np.column_stack([xs + np.cos(perp) * off, ys + np.sin(perp) * off])

    x0, y0 = cx - R * 0.6 * np.cos(ang0), cy - R * 0.6 * np.sin(ang0)
    x1, y1 = cx + R * 0.3 * np.cos(ang0), cy + R * 0.3 * np.sin(ang0)
    corridor = _meander(x0, y0, x1, y1, 130, R * 0.12, 5, np.random.default_rng(seed + 1))

    tracks = []
    d0 = date(2024, 6, 1)
    for i in range(n_days):
        ang = ang0 + rng.uniform(-0.9, 0.9)
        r = R * rng.uniform(0.4, 0.85)
        sx, sy = x1 + r * np.cos(ang), y1 + r * np.sin(ang)
        branch = _meander(x1, y1, sx, sy, 60, R * 0.05, 3, rng)
        route = np.vstack([corridor, branch[1:]])
        out_back = np.vstack([route, route[::-1][1:]])                  # out-and-back retrace
        out_back = out_back + rng.normal(0, 6.0, out_back.shape)        # GPS jitter
        out_back += np.array([(i - n_days // 2) * 14.0, 0.0])           # per-day lateral offset
        day = (d0 + timedelta(days=i * 9)).isoformat()
        tracks.append(Track(track_id=f"day-{i}", coords=out_back, day=day))
    return tracks


# ---- specs + the real final path ----

def _frame(region: Region):
    """Frame the whole region as the poster, with a print size that lands the crop
    exactly on the data floor (300 dpi == native_resolution_m per pixel)."""
    b = region.cfg["bounds"]; floor = region.cfg["native_resolution_m"]
    pw = (b[2] - b[0]) / (floor * NATIVE_FLOOR_DPI)
    ph = (b[3] - b[1]) / (floor * NATIVE_FLOOR_DPI)
    return (b[0], b[1], b[2], b[3]), pw, ph


def _annotate(spots: list, out_dir: str) -> list:
    """Name + icon each hotspot and pin one synthetic photo, so the poster shows the
    marker/photo furniture the product is about (the photo embeds into the manifest)."""
    for k, s in enumerate(spots):
        s["label"] = HOTSPOT_LABELS[k % len(HOTSPOT_LABELS)]
        s["icon"] = HOTSPOT_ICONS[k % len(HOTSPOT_ICONS)]
    if spots:
        demo = Image.new("RGB", (240, 180)); px = demo.load()
        for yy in range(180):
            for xx in range(240):
                t = yy / 180.0
                px[xx, yy] = (int(150 + 60 * t), int(170 - 40 * t), int(190 - 120 * t))
        os.makedirs(out_dir, exist_ok=True)
        photo = os.path.join(out_dir, "_demo_photo.png"); demo.save(photo)
        spots[0]["photo"] = photo
    return spots


def _base_spec(region: Region, tracks: list, spots: list, edition: int = 1) -> CompositionSpec:
    crop, pw, ph = _frame(region)
    return CompositionSpec(
        region_id=region.id, crs=region.cfg["crs"], crop=crop,
        print_w_in=pw, print_h_in=ph, native_resolution_m=region.cfg["native_resolution_m"],
        tracks=[t.coords for t in tracks], track_days=[t.day for t in tracks],
        hotspots=spots, seed=7, title_text=region.name.upper(),
        contours=True, edition=edition)


def _write_final(spec: CompositionSpec, region: Region, dpi: float, out_path: str,
                 sources=None, lineage=None) -> tuple:
    """The real final path: embed photos, rasterize, embed the provenance manifest, save."""
    box = max(24, round(spec.photo_box_in * dpi))
    espec = provenance.build_final_spec(spec, box)
    img = render.rasterize(espec, dpi=dpi, region_dir=region.dir, watermark=False, cfg=region.cfg)
    manifest = provenance.build_manifest(espec, sources or [], lineage,
                                         region_pack=provenance.region_pack_block(
                                             region.dir, labels=espec.labels, biome=espec.biome))
    img.save(out_path, "PNG", pnginfo=provenance.manifest_pnginfo(manifest))
    return out_path, img.size


# ---- deliverables ----

def _poster(region, tracks, spots, out_dir, dpi):
    spec = _base_spec(region, tracks, spots)
    return _write_final(spec, region, dpi, os.path.join(out_dir, "poster.png"))


def _wallpapers(region, tracks, spots, out_dir, preset_ids):
    made = []
    base = _base_spec(region, tracks, spots)
    for pid in preset_ids:
        preset = wallpaper.PRESETS.get(pid)
        if preset is None:
            print(f"  ! unknown wallpaper preset {pid!r}, skipping"); continue
        try:
            wspec = wallpaper.spec_for_preset(base, preset, tuple(region.cfg["bounds"]))
        except Exception as ex:
            print(f"  ! {pid}: region can't satisfy this device ({ex})"); continue
        out = os.path.join(out_dir, f"wallpaper_{pid}.png")
        made.append(_write_final(wspec, region, wspec.final_dpi(), out))
    return made


def _film(region, tracks, spots, out_dir, dpi, max_frames):
    """The film + its share twins for the social columns: render the frames ONCE, encode
    thrice -- film.png (the archival APNG, manifest aboard), film.webp (always), and
    film.mp4 (when the share extra is installed). The twins carry no manifest, by
    construction (their encoders take none)."""
    spec = _base_spec(region, tracks, spots)
    spec = provenance.build_final_spec(spec, max(24, round(spec.photo_box_in * dpi)))  # embed photo, as the real worker does
    plan = timelapse.frame_plan(spec, max_frames)
    frames = list(timelapse.render_frames(spec, dpi=dpi, region_dir=region.dir, plan=plan))
    anim = timelapse.animation_meta(max_frames=max_frames, step_ms=timelapse.DEFAULT_STEP_MS,
                                    hold_ms=timelapse.DEFAULT_HOLD_MS,
                                    leader_ms=timelapse.DEFAULT_LEADER_MS, dpi=dpi)
    manifest = provenance.build_manifest(spec, [], animation=anim,
                                         region_pack=provenance.region_pack_block(
                                             region.dir, labels=spec.labels, biome=spec.biome))
    pace = dict(step_ms=anim["step_ms"], hold_ms=anim["hold_ms"],
                leader_ms=anim["leader_ms"])
    outs = [(os.path.join(out_dir, "film.png"),
             timelapse.encode_apng(frames, manifest=manifest, **pace)),
            (os.path.join(out_dir, "film.webp"), timelapse.encode_webp(frames, **pace))]
    if timelapse.MP4_AVAILABLE:
        outs.append((os.path.join(out_dir, "film.mp4"),
                     timelapse.encode_mp4(frames, **pace)))
    for out, data in outs:
        with open(out, "wb") as f:
            f.write(data)
    return [out for out, _ in outs], len(plan)


def _editions(region, tracks, spots, out_dir, dpi):
    """The lineage set: the same frame rendered as three growing editions (add journeys
    each year), the cartouche climbing Edition 1 -> 3, lineage chained in the manifest."""
    made, lineage = [], []
    steps = [max(1, len(tracks) // 3), max(2, 2 * len(tracks) // 3), len(tracks)]
    for ed, upto in enumerate(steps, start=1):
        sub = tracks[:upto]
        subspots = _annotate(hotspots(sub, tuple(region.cfg["bounds"])), out_dir)
        spec = _base_spec(region, sub, subspots, edition=ed)
        out = os.path.join(out_dir, f"edition_{ed}.png")
        made.append(_write_final(spec, region, dpi, out, lineage=list(lineage)))
        # next edition's lineage points at this one (a plausible ancestor hash)
        lineage.append({"sha256": f"{'0'*63}{ed}", "edition": ed})
    return made


# ---- driver ----

def _ensure_dem(region: Region, allow_synthetic: bool) -> bool:
    ready = region.readiness()
    if ready.get("dem_present"):
        return True
    if not allow_synthetic:
        print(f"  ! {region.id}: no DEM present -- skipping (pass --synthetic-dem for a preview)")
        return False
    import tests.conftest  # noqa: F401  -- importing hydrates every missing DEM synthetically
    print(f"  · {region.id}: hydrated a SYNTHETIC DEM (preview only, not real terrain)")
    return region.readiness().get("dem_present", False)


def main():
    ap = argparse.ArgumentParser(description="Render the Phase-0 marketing asset farm.")
    ap.add_argument("--regions", nargs="*", help="region ids (default: all built regions)")
    ap.add_argument("--out", default="assets", help="output root (default: assets/)")
    ap.add_argument("--dpi", type=float, default=float(NATIVE_FLOOR_DPI), help="poster/edition dpi")
    ap.add_argument("--film-dpi", type=float, default=110.0, help="time-lapse frame dpi")
    ap.add_argument("--film-frames", type=int, default=24, help="max time-lapse frames")
    ap.add_argument("--wallpapers", nargs="*", default=["iphone", "desktop_4k"],
                    help="wallpaper preset ids")
    ap.add_argument("--only", nargs="*", choices=["poster", "wallpapers", "film", "editions"],
                    help="render only these deliverables (default: all)")
    ap.add_argument("--quick", action="store_true",
                    help="fast smoke: low dpi, no film (wiring check, not final quality)")
    ap.add_argument("--synthetic-dem", action="store_true",
                    help="hydrate the test suite's synthetic DEM when a real one is absent")
    args = ap.parse_args()

    if args.quick:
        args.dpi = min(args.dpi, 96.0); args.film_dpi = min(args.film_dpi, 80.0)

    regions = discover()
    ids = args.regions or list(regions)
    want = set(args.only) if args.only else {"poster", "wallpapers", "film", "editions"}
    if args.quick:
        want.discard("film")

    index = {}
    for rid in ids:
        region = regions.get(rid)
        if region is None:
            print(f"! unknown region {rid!r} (built: {', '.join(regions)})"); continue
        print(f"\n=== {rid} — {region.name} ===")
        if not _ensure_dem(region, args.synthetic_dem):
            continue
        out_dir = os.path.join(args.out, rid); os.makedirs(out_dir, exist_ok=True)
        tracks = _synth_tracks(region)
        spots = _annotate(hotspots(tracks, tuple(region.cfg["bounds"])), out_dir)
        print(f"  tracks={len(tracks)}  hotspots={len(spots)}")
        made = []
        try:
            if "poster" in want:
                p, sz = _poster(region, tracks, spots, out_dir, args.dpi)
                print(f"  poster      {sz[0]}x{sz[1]}  {p}"); made.append(p)
            if "wallpapers" in want:
                for p, sz in _wallpapers(region, tracks, spots, out_dir, args.wallpapers):
                    print(f"  wallpaper   {sz[0]}x{sz[1]}  {p}"); made.append(p)
            if "film" in want:
                ps, nf = _film(region, tracks, spots, out_dir, args.film_dpi, args.film_frames)
                for p in ps:
                    print(f"  film        {nf} frames  {p}"); made.append(p)
            if "editions" in want:
                for p, sz in _editions(region, tracks, spots, out_dir, args.dpi):
                    print(f"  {os.path.basename(p):11s} {sz[0]}x{sz[1]}  {p}"); made.append(p)
        except Exception as ex:
            print(f"  ! {rid} failed: {type(ex).__name__}: {ex}")
            continue
        index[rid] = {"name": region.name, "assets": [os.path.relpath(p) for p in made]}

    if index:
        idx_path = os.path.join(args.out, "index.json")
        os.makedirs(args.out, exist_ok=True)
        with open(idx_path, "w") as f:
            json.dump(index, f, indent=2)
        total = sum(len(v["assets"]) for v in index.values())
        print(f"\nwrote {total} assets across {len(index)} region(s) -> {idx_path}")
    else:
        print("\nno assets rendered")


if __name__ == "__main__":
    main()
