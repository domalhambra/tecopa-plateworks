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
  mockup_<v>_<size>.jpg the poster staged as a physical object (the embossed Plate, the
                        matted Frame) on the gallery wall -- Instagram-ready stills
  mockup_<v>_<size>.mp4 the same objects with the film inking itself inside them while
                        the object subtly yaws (share-class like the film twins: lossy,
                        no manifest; needs the share extra)
  mockup_plate.glb      the orbitable plate for the landing page's <model-viewer> --
                        the poster's pixels on a relief-displaced disc
  lightsweep.mp4        (--only lightsweep; slow) the turntable: the sun walks the
                        azimuth circle and only the land relights -- the terrain itself
                        reads as 3D

The rendered deliverables (poster, wallpapers, film, editions) go through the real final
path (`provenance.build_final_spec` -> `render.rasterize` -> embedded manifest), so a
full run doubles as an end-to-end smoke test of the engine's own outputs. The mockup,
model, and lightsweep tiers are share-class and exercise none of that path: the mockups
and the GLB restage an already-rendered final's pixels, and the lightsweep re-renders
but carries no manifest.

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

def _synth_tracks(region: Region, n_days: int = 7, seed: int = 7) -> list:
    """A detailed multi-day trip inside one region, generated in projected metres so it
    works for any region from its bounds alone. A shared approach corridor is retraced
    every day (so density reads a worn path); each day pushes a densely-sampled,
    switchbacked leg to its own destination, and the legs reach FARTHER and wander MORE
    as the trip accumulates -- so a progressive reveal grows like a real many-hour,
    multi-day journey rather than a few straight lines snapping in. Each day carries
    hundreds of points; the whole trip is thousands."""
    w, s, e, n = region.cfg["bounds"]
    cx, cy = (w + e) / 2.0, (s + n) / 2.0
    span = min(e - w, n - s)
    R = span * 0.24                              # keep destinations well inside the frame
    rng = np.random.default_rng(seed)
    ang0 = rng.uniform(0, 2 * np.pi)

    def _leg(x0, y0, x1, y1, npts, amp, harmonics, switch, rng):
        """A densely-sampled path A->B: a low-frequency meander, plus optional
        high-frequency switchbacks that tighten toward the destination (a climb to a
        pass or summit). Tapered to its anchored endpoints."""
        t = np.linspace(0, 1, npts)
        xs, ys = x0 + (x1 - x0) * t, y0 + (y1 - y0) * t
        off = np.zeros_like(t)
        for k in range(1, harmonics + 1):
            off += (amp / k) * np.sin(2 * np.pi * k * t + rng.uniform(0, 2 * np.pi))
        if switch:
            off += amp * 0.55 * np.sin(2 * np.pi * switch * t) * np.clip((t - 0.4) / 0.6, 0, 1)
        off *= np.sin(np.pi * t) ** 0.5
        perp = np.arctan2(y1 - y0, x1 - x0) + np.pi / 2
        return np.column_stack([xs + np.cos(perp) * off, ys + np.sin(perp) * off])

    # the shared approach: trailhead -> base camp, retraced every day
    thx, thy = cx - R * 0.75 * np.cos(ang0), cy - R * 0.75 * np.sin(ang0)
    bcx, bcy = cx + R * 0.12 * np.cos(ang0), cy + R * 0.12 * np.sin(ang0)
    approach = _leg(thx, thy, bcx, bcy, 170, R * 0.10, 5, 0, np.random.default_rng(seed + 1))

    tracks = []
    d0 = date(2024, 6, 1)
    for i in range(n_days):
        frac = (i + 1) / n_days                  # later days push farther and wander more
        ang = ang0 + rng.uniform(-1.2, 1.2)
        reach = R * (0.45 + 0.75 * frac) * rng.uniform(0.9, 1.1)
        dx, dy = bcx + reach * np.cos(ang), bcy + reach * np.sin(ang)
        leg = _leg(bcx, bcy, dx, dy, int(200 + 240 * frac), R * 0.07 * (0.6 + frac),
                   4, switch=int(3 + 5 * frac), rng=rng)
        path = leg
        if rng.random() < 0.65:                  # many days add a summit spur from the end
            sang = ang + rng.uniform(-1.5, 1.5)
            sr = reach * rng.uniform(0.18, 0.34)
            spur = _leg(dx, dy, dx + sr * np.cos(sang), dy + sr * np.sin(sang),
                        int(70 + 90 * frac), R * 0.04, 3, 0, rng)
            path = np.vstack([leg, spur[1:], spur[::-1][1:]])          # out-and-back spur
        # the full day: approach in, explore, and retrace approach back to the trailhead
        day_path = np.vstack([approach, path[1:], path[::-1][1:], approach[::-1][1:]])
        day_path = day_path + rng.normal(0, 5.0, day_path.shape)       # GPS jitter
        day = (d0 + timedelta(days=i * 6)).isoformat()
        tracks.append(Track(track_id=f"day-{i + 1}", coords=day_path, day=day))
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


def _mockups(region, tracks, spots, out_dir):
    """Instagram-ready object mockups of the composition (share-class: no manifest,
    like the film twins). The STILLS (plate/frame JPEGs) restage the already-rendered
    poster.png -- the engine's own pixels -- and need no terrain. The MOTION MP4s
    render a SMOOTH progressive reveal (timelapse.progressive_frames): the trip draws
    itself point by point while the object gently yaws, so they need the DEM and are
    skipped, with a message, when it isn't present (e.g. --only mockups on a machine
    holding only yesterday's poster.png)."""
    from scripts.render_mockups import (MOCKUP_FRAMES, MOCKUP_HOLD_MS, MOCKUP_MOTION_PX,
                                        MOCKUP_STEP_MS, SIZES, VARIANTS, load_final,
                                        render_mockup, render_mockup_video, write_jpeg)
    made = []
    poster = os.path.join(out_dir, "poster.png")
    manifest = None
    if os.path.exists(poster):
        img_frames, _durs, manifest = load_final(poster)
        for variant in VARIANTS:
            for w, h in SIZES:
                out = os.path.join(out_dir, f"mockup_{variant}_{w}x{h}.jpg")
                write_jpeg(render_mockup(img_frames[0], manifest, variant, (w, h)), out)
                made.append((out, (w, h)))
    else:
        print(f"  ! no poster.png in {out_dir} — render the poster first (mockup JPEGs skipped)")
    if not tracks:
        print("  ! mockup MP4s render the reveal from the terrain — skipped (no DEM/tracks here)")
        return made
    if not timelapse.MP4_AVAILABLE:
        print("  ! mockup MP4s need the share extra (pip install -r requirements-share.txt) — skipped")
        return made
    spec = _base_spec(region, tracks, spots)
    mdpi = MOCKUP_MOTION_PX / min(spec.print_w_in, spec.print_h_in)
    n_frames = int(os.environ.get("TRAILPRINT_MOCKUP_FRAMES", MOCKUP_FRAMES))
    frames = list(timelapse.progressive_frames(spec, mdpi, region.dir, region.cfg,
                                               n_frames=n_frames))
    durations = [MOCKUP_STEP_MS] * (len(frames) - 1) + [MOCKUP_HOLD_MS]
    for variant in VARIANTS:
        for w, h in SIZES:
            out = os.path.join(out_dir, f"mockup_{variant}_{w}x{h}.mp4")
            with open(out, "wb") as f:
                f.write(render_mockup_video(frames, durations, manifest, variant, (w, h)))
            made.append((out, (w, h)))
    return made


def _model(out_dir):
    """The orbitable plate: a GLB of the poster's pixels on a displaced disc, for the
    landing page's <model-viewer> (share-class, no manifest)."""
    from scripts.render_mockups import load_final
    from scripts.render_model import build_plate_glb
    poster = os.path.join(out_dir, "poster.png")
    if not os.path.exists(poster):
        print(f"  ! no poster.png in {out_dir} — render the poster first (model skipped)")
        return []
    frames, _durs, _m = load_final(poster)
    out = os.path.join(out_dir, "mockup_plate.glb")
    data = build_plate_glb(frames[0])   # build fully before touching disk: a failure
    with open(out, "wb") as f:          # must not leave a truncated GLB the landing
        f.write(data)                   # page would fetch by exact name
    return [out]


def _lightsweep(region, tracks, spots, out_dir):
    """The turntable: the composition re-rendered around the azimuth circle (the
    terrain itself reads as 3D -- only the light moves). Needs the DEM; minutes on
    real terrain, which is why --quick skips it unless explicitly asked for."""
    if not timelapse.MP4_AVAILABLE:
        print("  ! lightsweep needs the share extra (pip install -r requirements-share.txt) — skipped")
        return []
    from scripts.render_lightsweep import TARGET_PX, sweep_mp4
    spec = _base_spec(region, tracks, spots)
    dpi = TARGET_PX / max(spec.print_w_in, spec.print_h_in)
    out = os.path.join(out_dir, "lightsweep.mp4")
    data = sweep_mp4(spec, dpi, region.dir, region.cfg)  # encode fully first: the
    with open(out, "wb") as f:                           # farm's slowest job must not
        f.write(data)                                    # die into a 0-byte "asset"
    return [out]


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
    ap.add_argument("--only", nargs="*",
                    choices=["poster", "wallpapers", "film", "editions",
                             "mockups", "lightsweep", "model"],
                    help="render only these deliverables (default: all but lightsweep)")
    ap.add_argument("--quick", action="store_true",
                    help="fast smoke: low dpi, no film (wiring check, not final quality)")
    ap.add_argument("--synthetic-dem", action="store_true",
                    help="hydrate the test suite's synthetic DEM when a real one is absent")
    args = ap.parse_args()

    if args.quick:
        args.dpi = min(args.dpi, 96.0); args.film_dpi = min(args.film_dpi, 80.0)

    regions = discover()
    ids = args.regions or list(regions)
    # lightsweep re-renders ~60 frames per region (minutes on real DEMs), so it is
    # opt-in via --only; everything else ships by default
    want = set(args.only) if args.only else {"poster", "wallpapers", "film", "editions",
                                             "mockups", "model"}
    if args.quick:
        # quick drops the slow renders -- unless they were EXPLICITLY asked for
        for slow in ("film", "lightsweep"):
            if not (args.only and slow in args.only):
                want.discard(slow)

    index = {}
    for rid in ids:
        region = regions.get(rid)
        if region is None:
            print(f"! unknown region {rid!r} (built: {', '.join(regions)})"); continue
        print(f"\n=== {rid} — {region.name} ===")
        # mockups + model stage already-rendered finals: they need no DEM and no
        # tracks, so --only mockups works on any machine with yesterday's assets
        needs_render = bool(want - {"mockups", "model"})
        if needs_render and not _ensure_dem(region, args.synthetic_dem):
            continue
        out_dir = os.path.join(args.out, rid); os.makedirs(out_dir, exist_ok=True)
        tracks = _synth_tracks(region) if needs_render else []
        spots = _annotate(hotspots(tracks, tuple(region.cfg["bounds"])), out_dir) \
            if needs_render else []
        if needs_render:
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
            if "mockups" in want:
                for p, sz in _mockups(region, tracks, spots, out_dir):
                    print(f"  mockup      {sz[0]}x{sz[1]}  {p}"); made.append(p)
            if "model" in want:
                for p in _model(out_dir):
                    print(f"  model       plate glb  {p}"); made.append(p)
            if "lightsweep" in want:
                for p in _lightsweep(region, tracks, spots, out_dir):
                    print(f"  lightsweep  {p}"); made.append(p)
            if "editions" in want:
                for p, sz in _editions(region, tracks, spots, out_dir, args.dpi):
                    print(f"  {os.path.basename(p):11s} {sz[0]}x{sz[1]}  {p}"); made.append(p)
        except Exception as ex:
            print(f"  ! {rid} failed: {type(ex).__name__}: {ex}")
            continue
        if made:
            # a region whose every wanted deliverable was skipped gets no entry:
            # an empty "assets": [] would read as a rendered region
            index[rid] = {"name": region.name,
                          "assets": [os.path.relpath(p) for p in made]}

    if index:
        idx_path = os.path.join(args.out, "index.json")
        os.makedirs(args.out, exist_ok=True)
        total = sum(len(v["assets"]) for v in index.values())
        # merge into yesterday's index, never overwrite it: --only mockups on a dir
        # from an earlier full run must keep the poster/wallpaper/film records whose
        # files still sit on disk (and every other region's entry, untouched)
        prior = {}
        if os.path.exists(idx_path):
            try:
                with open(idx_path) as f:
                    prior = json.load(f)
            except (OSError, ValueError):
                prior = {}
        for rid, entry in index.items():
            old = prior.get(rid)
            if isinstance(old, dict):
                kept = [p for p in old.get("assets", [])
                        if p not in entry["assets"] and os.path.exists(p)]
                entry["assets"] = kept + entry["assets"]
        with open(idx_path, "w") as f:
            json.dump({**prior, **index}, f, indent=2)
        print(f"\nwrote {total} assets across {len(index)} region(s) -> {idx_path}")
    else:
        print("\nno assets rendered")


if __name__ == "__main__":
    main()
