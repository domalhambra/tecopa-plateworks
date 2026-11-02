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
  detail.png            a 1:1 crop of the poster at print resolution -- the landing
                        page's "actual print pixels" proof (web pages downscale the
                        poster into a blur; this is what the sheet really holds)
  coin.webp / coin.mp4  the coin spin: the GLB's own plate mesh turning once under a
                        spotlight, as a looping social video (mp4 needs the share
                        extra) -- the feed-postable twin of the orbitable plate
  poster_journey.png    (journey tier) the poster again, lit by the sun the plate's
                        story names (light_mode "journey"); only the four light fields
                        differ from poster.png. Plates whose story has a `journey`
                        table only (Zion)
  story_<n>.png         (stories tier) a 1:1 crop of print pixels for section n of the
                        plate's story, at the window marketing/stories.toml gives
                        (crop_center_m + crop_in, or crop_anchor "profile" + crop_in,
                        centred on the elevation strip); cut at the dpi the sheet
                        was rendered at, never resized. A poster_journey section writes story_<n>.png
                        from poster_journey.png and story_<n>_before.png from
                        poster.png, the same window. A section with no window fails
                        the plate, naming its heading, before anything renders. A
                        plate with no story writes none (`detail` serves it)
  relief/               the Ghost landing page's relief-viewer images, from
                        scripts/export_relief.py: coin.webp + coin-h.png, the poster
                        pair, wall.webp, detail.webp -- and, for a plate with a story,
                        story-<n>.webp, journey-before/after.webp, edition-<n>.webp
                        and film.mp4. Refused, and skipped, for a region with no real
                        terrain record (invariant 11)
  lightsweep.mp4        (--only lightsweep; slow) the turntable: the sun walks the
                        azimuth circle and only the land relights -- the terrain itself
                        reads as 3D

A plate with a story in marketing/stories.toml renders every image with the plate's own
`look` over the customer's (`_plate_spec`), so the page shows one look per plate. The
`stories` tier restages sheets, so it runs with `--only` on any machine holding them; it
runs after `poster`, `journey` and `editions` and before `relief`, which reads its crops.

The rendered deliverables (poster, wallpapers, film, editions) go through the real final
path (`provenance.build_final_spec` -> `render.rasterize` -> embedded manifest), so a
full run doubles as an end-to-end smoke test of the engine's own outputs. The mockup,
model, and lightsweep tiers are share-class and exercise none of that path: the mockups
and the GLB restage an already-rendered final's pixels, and the lightsweep re-renders
but carries no manifest.

One plate's whole story, in the order the exporter needs it (the real plates need their
windows in marketing/stories.toml first; Task 7 of the Pick-a-plate plan sets them):
    ./.venv/bin/python scripts/render_asset_farm.py --regions zion_ut \
        --only poster journey editions stories relief
`film` joins the list for a plate whose story has a film section (Eastern Sierra).

Usage (run from the REPO ROOT -- `regions/`, `cache/networks/` and the default
`assets/` output root all resolve relative to the current directory):
    ./.venv/bin/python scripts/render_asset_farm.py                    # all regions, real DEMs
    ./.venv/bin/python scripts/render_asset_farm.py --regions lassen_ca --quick
    ./.venv/bin/python scripts/render_asset_farm.py --synthetic-dem    # local preview, no real DEM
    ./.venv/bin/python scripts/render_asset_farm.py --synthetic-tracks # ignore the network cache

Demo journeys come from the OSM network cache at `cache/networks/<region_id>.json`
when one is present (see scripts/fetch_track_network.py), so markers carry the real
summits and lakes the routes reached. The cache is gitignored; without it -- a fresh
clone, CI -- the farm falls back to the synthetic track generator and renders exactly
what it always did. `--synthetic-tracks` forces that fallback even when a cache exists.

Real 3DEP DEMs are gitignored (see region_prep.py). On a machine that has them, this
renders true terrain. Without them, pass --synthetic-dem to hydrate the same tiny
synthetic DEMs the test suite uses -- fine for wiring/preview, not for a real poster.
Outputs land under assets/<region_id>/ (override with --out).

`assets/index.json` records, per region, the assets made AND the DEM they were rendered
from ("terrain": {synthetic, sha256, bytes}). That stamp is what marketing/build_deploy.py
refuses to publish without: a synthetic stand-in renders cleanly, so the picture cannot
betray itself and the record is the only thing that can. See marketing/DEPLOY.md.
"""
from __future__ import annotations
import argparse
import calendar
import hashlib
import json
import os
import sys
from dataclasses import replace
from datetime import date, timedelta

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.geo import RegionGeo, crs_to_overview_px
from app.regions import discover, Region
from app.ingest import Track
from app.density import hotspots
from app.spec import CompositionSpec
from app import render, provenance, timelapse, wallpaper
from app.orderspec import order_look
from scripts.story_config import StoryError, story_for
from scripts.track_network import PinError, load_network, network_tracks

NATIVE_FLOOR_DPI = 300          # the zoom cap is judged at print dpi: 10 m/px at 300 dpi
HOTSPOT_LABELS = ["Base Camp", "The Notch", "North Shore", "South Fork", "The Marina",
                  "Trailhead", "High Overlook", "Cold Spring"]
HOTSPOT_ICONS = ["camp", "peak", "water", "flag", "camera", "star", "dot", "water"]
NETWORK_CACHE = os.path.join("cache", "networks")
# The detail crop's ink scan. INK_TOL is the per-channel distance from TRACK_INK that
# still reads as route: wide enough for the antialiased edges and the grain, tight
# enough that warm terrain doesn't outvote a route (at 60 the lassen_ca scan picks a
# bare sunlit slope over the journeys). INK_BLOCK is the cell the mask is summed into.
INK_TOL = 24
INK_BLOCK = 32
# What a plain run renders. lightsweep re-renders ~60 frames per region (minutes on
# real DEMs), so it is opt-in via --only.
DEFAULT_TIERS = frozenset({"poster", "wallpapers", "film", "editions", "mockups",
                           "model", "detail", "coin", "relief", "stories", "journey"})
# Tiers that restage already-rendered finals: no DEM, no tracks, so --only <these>
# works on any machine holding yesterday's assets. `stories` is one (it cuts crops from
# poster.png and poster_journey.png); `journey` is not (it renders the poster again).
RESTAGE_TIERS = frozenset({"mockups", "model", "detail", "coin", "relief", "stories"})
# The story sections that cut a crop, and the sheets each cuts it from: (output, source)
# pairs in write order. `film` and `editions` sections show whole files and need no window.
CROP_VARIANTS = {
    "poster": (("story_{n}.png", "poster.png"),),
    "poster_journey": (("story_{n}_before.png", "poster.png"),
                       ("story_{n}.png", "poster_journey.png")),
}


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
    """Frame the renderable region as the poster, with a print size that lands the
    crop exactly on the data floor (300 dpi == native_resolution_m per pixel).

    "Renderable" is the region bounds shrunk to the DEM's finite-data envelope: a
    corridor-scale plate's UTM rectangle bulges past its 4326 fetch bbox, leaving
    nodata strips along the frame edges (elko_bonneville: ~4%, north and south), and
    the engine's off-DEM guard rightly refuses to paint them. Full-coverage plates
    trim nothing -- their frame is their bounds, unchanged."""
    b = tuple(region.cfg["bounds"]); floor = region.cfg["native_resolution_m"]
    crop = _finite_envelope(region, b)
    pw = (crop[2] - crop[0]) / (floor * NATIVE_FLOOR_DPI)
    ph = (crop[3] - crop[1]) / (floor * NATIVE_FLOOR_DPI)
    return crop, pw, ph


def _finite_envelope(region: Region, bounds: tuple) -> tuple:
    """Shrink `bounds` to the largest edge-trimmed rectangle of finite DEM data.

    Reads a downsampled mask (cheap at any plate size) and peels edge rows/columns
    whose finite fraction is under 99.5% until all four edges are clean, then pads
    one native pixel inward so resampling at the crop edge never touches the void.
    Interior nodata (none in practice) is left alone -- the guard still owns it."""
    import rasterio
    dem = os.path.join(region.dir, region.cfg.get("dem_path", "dem.tif"))
    if not os.path.exists(dem):
        return bounds
    with rasterio.open(dem) as ds:
        scale = max(1, ds.width // 1200, ds.height // 1200)
        h, w = ds.height // scale, ds.width // scale
        a = ds.read(1, out_shape=(h, w))
        finite = np.isfinite(a) if ds.nodata is None or np.isnan(ds.nodata) \
            else np.isfinite(a) & (a != ds.nodata)
        top, bot, left, right = 0, h, 0, w
        ok = 0.995
        while top < bot and left < right:
            # peel the WORST edge each pass -- a fixed order lets one bad column
            # contaminate every row and eat the frame from the top
            edges = [(finite[top, left:right].mean(), "top"),
                     (finite[bot - 1, left:right].mean(), "bot"),
                     (finite[top:bot, left].mean(), "left"),
                     (finite[top:bot, right - 1].mean(), "right")]
            frac, worst = min(edges)
            if frac >= ok:
                break
            if worst == "top":
                top += 1
            elif worst == "bot":
                bot -= 1
            elif worst == "left":
                left += 1
            else:
                right -= 1
        if (top, bot, left, right) == (0, h, 0, w):
            return bounds                        # full coverage: byte-identical frame
        pad = region.cfg["native_resolution_m"]
        wld = ds.transform * (left * scale, top * scale)      # px -> world, upper-left
        wrd = ds.transform * (right * scale, bot * scale)
        crop = (max(bounds[0], wld[0] + pad), max(bounds[1], wrd[1] + pad),
                min(bounds[2], wrd[0] - pad), min(bounds[3], wld[1] - pad))
    print(f"  frame: trimmed to the DEM's finite-data envelope "
          f"({100 * (1 - (crop[2]-crop[0]) * (crop[3]-crop[1]) / ((bounds[2]-bounds[0]) * (bounds[3]-bounds[1]))):.1f}% off)")
    return crop


def _annotate(spots: list, out_dir: str, story: dict | None = None) -> list:
    """Name + icon each hotspot and pin the story's photo, if it has one (the photo
    embeds into the manifest).

    A plate with no story pins nothing. A story's `photo_at` names the spot that carries
    the photo (a label that matches no spot is a PinError), and no `photo_at` pins
    nothing. Its `photo_file`, a path under the gitignored marketing/photos/, makes that
    photo a real photograph; without one a painted gradient stands in, and `--ship-check`
    stops it shipping. A `photo_file` that does not exist is a PinError too.

    A spot that ALREADY carries a label or icon keeps both: network journeys arrive
    named after the real summit/lake they reached, and carrying the glyph that matches
    that kind (track_network.KIND_ICONS). Overwriting "Antelope Mountain" with
    "Base Camp" would throw away the whole point of routing over real terrain, and
    re-cycling the icon positionally is worse than generic -- it contradicts the name
    printed beside it, putting a tent on a lake and a camera on a summit. Only
    density-derived spots (which carry neither) get them from the invented lists.

    Guarding the icon also makes a destination's glyph STABLE across the three
    editions: the positional cycle re-indexed on each subset, so a summit could
    change marker between Edition 1 and Edition 3 of the same lineage."""
    for k, s in enumerate(spots):
        if "label" not in s:
            s["label"] = HOTSPOT_LABELS[k % len(HOTSPOT_LABELS)]
        if "icon" not in s:
            s["icon"] = HOTSPOT_ICONS[k % len(HOTSPOT_ICONS)]
    target = None
    if story and story.get("photo_at"):
        target = next((s for s in spots if s["label"] == story["photo_at"]), None)
        if target is None:
            raise PinError(f"story photo_at is not a spot on this plate: {story['photo_at']}")
    if target is not None:
        real = story.get("photo_file")
        if real:
            if not os.path.isfile(real):
                raise PinError(f"story photo_file not found: {real}")
            target["photo"] = real
            return spots
        demo = Image.new("RGB", (240, 180)); px = demo.load()
        for yy in range(180):
            for xx in range(240):
                t = yy / 180.0
                px[xx, yy] = (int(150 + 60 * t), int(170 - 40 * t), int(190 - 120 * t))
        os.makedirs(out_dir, exist_ok=True)
        photo = os.path.join(out_dir, "_demo_photo.png"); demo.save(photo)
        target["photo"] = photo
    return spots


def _demo_journeys(region, out_dir: str, force_synthetic: bool = False):
    """Tracks + spots for a region: journeys routed over the cached OSM network
    when cache/networks/<id>.json exists, else the synthetic generator. The
    fallback keeps the farm runnable on a fresh clone and in CI.

    A cache that exists but cannot be read falls back too, loudly. This is the
    one place the farm does file I/O per region, and it sits OUTSIDE main()'s
    per-region try/except -- so an unreadable cache raising here would abort the
    whole run, taking down every LATER region including ones with no cache that
    would have rendered fine. A truncated half-written JSON is exactly what an
    interrupted Overpass fetch leaves on disk, so this is the expected failure,
    not an exotic one. The catch is deliberately narrow (read/parse/shape
    errors); anything else is a real bug and should still surface.

    That includes a plate's story. A PinError, or a broken marketing/stories.toml,
    fails the run: the story's captions name these places, and a plate that quietly
    drew synthetic squiggles under them would be worse than no plate."""
    cache = os.path.join(NETWORK_CACHE, f"{region.id}.json")
    if not force_synthetic and os.path.exists(cache):
        story = story_for(region.id)
        try:
            tracks, spots = network_tracks(region, load_network(cache), story=story)
        except (OSError, ValueError, KeyError) as ex:
            print(f"  ! cache unreadable, falling back to synthetic tracks "
                  f"({type(ex).__name__}: {ex})")
        else:
            print(f"  tracks: routed over {cache} (OSM, ODbL)")
            return tracks, _annotate(spots, out_dir, story)
    else:
        why = "forced by --synthetic-tracks" if force_synthetic else f"no cache at {cache}"
        print(f"  tracks: synthetic ({why})")
    tracks = _synth_tracks(region)
    return tracks, _annotate(hotspots(tracks, tuple(region.cfg["bounds"])), out_dir)


def _edition_spots(sub: list, spots: list, region, out_dir: str,
                   story: dict | None = None) -> list:
    """Spots for an edition's track subset. Network journeys carry their
    destination in track_id ("<kind>:<name>"): the edition shows the real
    destinations its ink has reached, weights recounted for the subset.
    Synthetic tracks (ids like "day-1") keep the density-hotspot path.

    The story's pin rule carries through. An edition that has not yet reached the
    `photo_at` spot pins nothing and does not raise: only the full poster raises
    PinError for a `photo_at` that matches no spot."""
    names = [t.track_id.split(":", 1)[1] for t in sub if ":" in t.track_id]
    if names:
        # drop any inherited "photo" pin -- _annotate re-pins by the same rule as the
        # poster (the `photo_at` spot, if the story has one), so an
        # edition carries ONE pinned photo like the poster, not two. The strip is
        # defensive rather than load-bearing under today's caller, and costs
        # nothing. Not tested, because no reachable state produces a double pin.
        #
        # `names.count` likewise always returns 1 today: destination_pool dedupes
        # by name and select_destinations removes each pick, so one trip per
        # destination. Written as a count rather than a literal 1 so that a
        # future generator which DOES revisit a place gets the right weight
        # (marker size is weight-driven) instead of a silently flat one.
        eds = [{k: v for k, v in dict(s, weight=names.count(s["label"])).items()
                if k != "photo"}
               for s in spots if s.get("label") in names]
        if story and story.get("photo_at") and not any(
                s["label"] == story["photo_at"] for s in eds):
            story = {k: v for k, v in story.items() if k != "photo_at"}
        return _annotate(eds, out_dir, story)
    return _annotate(hotspots(sub, tuple(region.cfg["bounds"])), out_dir)


def _base_spec(region: Region, tracks: list, spots: list, edition: int = 1,
               look: dict | None = None) -> CompositionSpec:
    """The farm's spec: the customer's look for these tracks (orderspec.order_look), so
    the marketing images show what an order ships. `look` overrides single fields of it
    for one plate."""
    crop, pw, ph = _frame(region)
    coords, days = [t.coords for t in tracks], [t.day for t in tracks]
    return CompositionSpec(
        region_id=region.id, crs=region.cfg["crs"], crop=crop,
        print_w_in=pw, print_h_in=ph, native_resolution_m=region.cfg["native_resolution_m"],
        tracks=coords, track_days=days,
        hotspots=spots, seed=7, title_text=region.name.upper(),
        contours=True, edition=edition, **{**order_look(coords, days), **(look or {})})


def _plate_spec(region: Region, tracks: list, spots: list,
                edition: int = 1) -> CompositionSpec:
    """_base_spec with the plate's own look. A plate with a story tunes the look the way
    Dom would tune a customer's poster on that ground (more haze on a basin plate, say),
    and every image of the plate renders with it, so the page shows one look per plate.
    A plate with no story gets the plain order look."""
    story = story_for(region.id)
    return _base_spec(region, tracks, spots, edition=edition,
                      look=(story or {}).get("look"))


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
    spec = _plate_spec(region, tracks, spots)
    return _write_final(spec, region, dpi, os.path.join(out_dir, "poster.png"))


def _journey(region, tracks, spots, out_dir, dpi, story):
    """poster_journey.png: the poster again, same spec, lit by the sun the story's
    `journey` table names (`sun_azimuth_deg`, `sun_altitude_deg`, `golden_strength`)
    instead of the archival light. The pair differs in those four fields and nothing
    else, so a crop of the same window from each shows only what the light does. A
    plate with no story, or a story with no `journey` table, has no pair: returns []."""
    sun = (story or {}).get("journey")
    if not sun:
        return []
    for key in ("sun_azimuth_deg", "sun_altitude_deg", "golden_strength"):
        if key not in sun:
            raise StoryError(f"{story.get('name', region.id)}: the journey table has no {key}")
    spec = replace(_plate_spec(region, tracks, spots), light_mode="journey",
                   sun_azimuth_deg=float(sun["sun_azimuth_deg"]),
                   sun_altitude_deg=float(sun["sun_altitude_deg"]),
                   golden_strength=float(sun["golden_strength"]))
    path, _size = _write_final(spec, region, dpi, os.path.join(out_dir, "poster_journey.png"))
    return [path]


def _wallpapers(region, tracks, spots, out_dir, preset_ids):
    """One wallpaper per preset, each re-cropped from the poster's frame to the
    device's aspect.

    The roam box is `base.crop` -- the finite-data envelope `_frame` already
    computed -- NOT `region.cfg["bounds"]`. Bounds were the bug: a preset is allowed
    to re-crop anywhere inside the box it is given, and elko_bonneville's bounds
    include the nodata strips its UTM rectangle bulges into (~3.8% of the plate,
    north and south edges). Landscape presets stayed wide and got away with it;
    every portrait and square preset extended vertically into the void and the
    off-DEM guard refused all ten at 3.14%. Handing over the envelope keeps every
    preset inside real elevation data -- 18/18 render on elko. Reusing base.crop
    also costs nothing: no second DEM read.

    A preset that cannot be satisfied skips ITSELF, never the region. The render is
    inside the try for the same reason the spec build is: an OffDemError escaping
    here used to kill the whole region *after* its poster was written, and main()
    then discarded a correct 132 MB file and left the terrain record unstamped."""
    made = []
    base = _plate_spec(region, tracks, spots)
    roam = tuple(base.crop)
    for pid in preset_ids:
        preset = wallpaper.PRESETS.get(pid)
        if preset is None:
            print(f"  ! unknown wallpaper preset {pid!r}, skipping"); continue
        out = os.path.join(out_dir, f"wallpaper_{pid}.png")
        try:
            wspec = wallpaper.spec_for_preset(base, preset, roam)
            made.append(_write_final(wspec, region, wspec.final_dpi(), out))
        except Exception as ex:
            print(f"  ! wallpaper {pid} skipped ({type(ex).__name__}: {ex})")
    return made


def _film(region, tracks, spots, out_dir, dpi, max_frames):
    """The film + its share twins for the social columns: render the frames ONCE, encode
    thrice -- film.png (the archival APNG, manifest aboard), film.webp (always), and
    film.mp4 (when the share extra is installed). The twins carry no manifest, by
    construction (their encoders take none)."""
    spec = _plate_spec(region, tracks, spots)
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


def _years_later(day: str | None, years: int) -> str | None:
    """An ISO date `years` years on, month and day kept. 29 February lands on 28 February
    in a year with no leap day. Anything that does not start with a year comes back as
    it was: the farm's demo days are ISO dates, but a missing one is None."""
    if not years or not day or not (day[:4].isascii() and day[:4].isdigit()):
        return day
    year = int(day[:4]) + years
    rest = day[4:]
    if rest[:6] == "-02-29" and not calendar.isleap(year):
        rest = "-02-28" + rest[6:]
    return f"{year:04d}{rest}"


def _dated_by_edition(tracks: list, steps: list) -> list:
    """Copies of the tracks for the editions path, dated so the editions read as years.
    A trip first added in Edition 2 is a year later than the demo date, one first added
    in Edition 3 two years later; Edition 1's trips keep theirs. `steps` are the editions'
    track counts. The caller's tracks are not touched: the poster, the film and every
    other tier read them with their own dates."""
    firsts = [0] + list(steps[:-1])
    out = []
    for i, t in enumerate(tracks):
        ed = sum(1 for first in firsts if first <= i)          # the edition that adds it
        out.append(replace(t, day=_years_later(t.day, ed - 1)))
    return out


def _editions(region, tracks, spots, out_dir, dpi):
    """The lineage set: the same frame rendered as three growing editions (add journeys
    each year), the cartouche climbing Edition 1 -> 3, lineage chained in the manifest.

    A plate with a story dates each edition's new trips a year after the last (the demo
    trips are all one year, and the page says "the same ground three years running"), so
    the cartouche reads Edition 2 as 2024-2025 and Edition 3 as 2024-2026. A plate with
    no story keeps its days."""
    made, lineage = [], []
    # the story only governs network journeys; synthetic tracks keep today's pin
    plate_story = story_for(region.id)
    story = plate_story if any(":" in t.track_id for t in tracks) else None
    steps = [max(1, len(tracks) // 3), max(2, 2 * len(tracks) // 3), len(tracks)]
    if plate_story is not None:
        tracks = _dated_by_edition(tracks, steps)
    for ed, upto in enumerate(steps, start=1):
        sub = tracks[:upto]
        subspots = _edition_spots(sub, spots, region, out_dir, story)
        spec = _plate_spec(region, sub, subspots, edition=ed)
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
    spec = _plate_spec(region, tracks, spots)
    mdpi = MOCKUP_MOTION_PX / min(spec.print_w_in, spec.print_h_in)
    n_frames = int(os.environ.get("TECOPA_MOCKUP_FRAMES", MOCKUP_FRAMES))
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


def _ink_window(img, cw, ch, block=INK_BLOCK, tol=INK_TOL):
    """Top-left corner of the cw x ch window of `img` carrying the most route ink, or
    None when the sheet holds none. The mask is built full-res (a hairline route is one
    or two pixels wide -- resampling the picture first would blend it into the terrain
    and lose it), row-band by row-band, then summed down into `block`-sized cells; the
    window scan runs over that coarse grid, so it is a few thousand adds, not millions.
    Candidate offsets are the grid pitch, clamped to keep the window inside the sheet."""
    ink = np.array(render.TRACK_INK, np.int16)
    w, h = img.size
    gw, gh = -(-w // block), -(-h // block)
    grid = np.zeros((gh, gw), np.int32)
    src = img if img.mode == "RGB" else img.convert("RGB")   # convert copies 100+ MB
    for top in range(0, h, block * 8):                      # bands, to cap peak memory
        bh = min(block * 8, h - top)
        band = np.asarray(src.crop((0, top, w, top + bh)), np.int16)
        mask = np.abs(band - ink).max(axis=2) <= tol
        pad_y, pad_x = -(-bh // block) * block - bh, gw * block - w
        if pad_y or pad_x:
            mask = np.pad(mask, ((0, pad_y), (0, pad_x)))
        rows = mask.reshape(mask.shape[0] // block, block,
                            gw, block).sum(axis=(1, 3))
        grid[top // block:top // block + rows.shape[0]] = rows
    if not grid.any():
        return None
    # window sums over the coarse grid, via its integral image
    ii = np.pad(grid.cumsum(0).cumsum(1), ((1, 0), (1, 0)))
    kw, kh = max(1, cw // block), max(1, ch // block)
    sums = (ii[kh:, kw:] - ii[:-kh, kw:] - ii[kh:, :-kw] + ii[:-kh, :-kw])
    gy, gx = np.unravel_index(int(np.argmax(sums)), sums.shape)
    return (min(int(gx) * block, w - cw), min(int(gy) * block, h - ch))


def _detail(out_dir):
    """The 1:1 detail crop: actual print pixels cut from the freshly rendered poster,
    so the landing page can show what 300 dpi looks like instead of a downscaled blur.

    The window is chosen by ink CONTENT, from the poster's own pixels alone (this tier
    stages an already-rendered final: no DEM, no tracks, no spec). Journeys route over
    the real OSM network and are spread across the whole plate deliberately, so the
    centre is now typically the emptiest part of a sheet -- a centre crop lands on bare
    terrain and the landing page's "look close at the labels" copy points at nothing.
    Picking the densest ink window lands on labels too: every destination marker sits at
    the end of a route with its name beside it. Falls back to the centre crop when the
    sheet carries no ink -- a poster rendered with no tracks, the one case it was right."""
    poster = os.path.join(out_dir, "poster.png")
    if not os.path.exists(poster):
        print(f"  ! no poster.png in {out_dir} — render the poster first (detail skipped)")
        return []
    img = Image.open(poster)
    w, h = img.size
    cw, ch = min(1400, w), min(1050, h)
    at = _ink_window(img, cw, ch)
    if at is None:
        print("  · detail: no route ink found on the sheet — centre crop")
    x0, y0 = at if at is not None else ((w - cw) // 2, (h - ch) // 2)
    out = os.path.join(out_dir, "detail.png")
    img.crop((x0, y0, x0 + cw, y0 + ch)).save(out, "PNG")
    return [out]


def crop_window(center_m, size_in, crop, image_size, dpi, anchor=None, strip=None):
    """The pixel window (x0, y0, x1, y1) of a story crop: `size_in` printed inches at
    `dpi`, centred on the ground point `center_m` (region CRS metres), cut from a sheet
    of `image_size` pixels that was rendered from the ground window `crop`.

    The ground to pixel step is app/geo.py's (invariant 5), the same linear map the
    painter uses: the farm's sheet has no bleed and no margin, so its canvas IS the
    crop, and a point's pixel is `crs_to_overview_px` over (crop, image_size).

    The window is exactly round(size_in * dpi) pixels per side, and the sheet's pixels
    are never resampled: what the page shows is what prints. A window that would cross
    the sheet's edge slides inward and keeps its size. A window bigger than the sheet,
    or a centre off the sheet, raises StoryError (a window that quietly slid would show
    the wrong country).

    `anchor="profile"` centres the window on the elevation-profile strip instead,
    `strip` being its pixel rectangle (`_profile_strip`), and ignores `center_m`. The
    strip sits above the cartouche and compass stack, not in the sheet's corner, so no
    corner window finds it. A window that does not hold the whole strip raises
    StoryError."""
    wpx, hpx = round(size_in[0] * dpi), round(size_in[1] * dpi)
    W, H = image_size
    if wpx > W or hpx > H:
        raise StoryError(f"a {size_in[0]} x {size_in[1]} in window is {wpx} x {hpx} px at "
                         f"{dpi:g} dpi, bigger than the {W} x {H} px sheet")
    if anchor is not None:
        if anchor != "profile":
            raise StoryError(f"crop_anchor {anchor!r} is not one the farm knows (profile)")
        if strip is None:
            raise StoryError("crop_anchor 'profile' needs the strip's rectangle, and this "
                             "sheet's spec draws none")
        sx0, sy0, sx1, sy1 = strip
        x0 = min(max(round((sx0 + sx1) / 2 - wpx / 2), 0), W - wpx)
        y0 = min(max(round((sy0 + sy1) / 2 - hpx / 2), 0), H - hpx)
        if not (x0 <= sx0 and sx1 <= x0 + wpx and y0 <= sy0 and sy1 <= y0 + hpx):
            raise StoryError(f"a {wpx} x {hpx} px window does not hold the whole "
                             f"{sx1 - sx0} x {sy1 - sy0} px elevation strip -- widen crop_in")
        return (x0, y0, x0 + wpx, y0 + hpx)
    geo = RegionGeo(crs="", bounds=tuple(crop), overview_size=(W, H))
    px, py = crs_to_overview_px(geo, center_m[0], center_m[1])
    if not (0 <= px <= W and 0 <= py <= H):
        raise StoryError(f"the window's centre {tuple(center_m)} is off the sheet "
                         f"(pixel {px:.0f}, {py:.0f} on {W} x {H})")
    x0 = min(max(round(px - wpx / 2), 0), W - wpx)
    y0 = min(max(round(py - hpx / 2), 0), H - hpx)
    return (x0, y0, x0 + wpx, y0 + hpx)


def _section_label(story: dict, n: int, section: dict) -> str:
    return f'{story.get("name", "story")}: section {n} "{section.get("heading", "?")}"'


def check_story_windows(story: dict | None) -> None:
    """Raise StoryError, naming the section's heading, for any section that crops and
    has no usable window: `crop_in` plus `crop_center_m` (or `crop_anchor`), and a
    variant the farm knows. `film` and `editions` sections need no window. Config only,
    no files: main() runs it before any render, so a plate whose windows are not set
    yet costs no poster."""
    for n, section in enumerate((story or {}).get("sections", []), start=1):
        variant = section.get("variant")
        if variant in ("film", "editions"):
            continue
        label = _section_label(story, n, section)
        if variant not in CROP_VARIANTS:
            raise StoryError(f"{label} has variant {variant!r}; the farm crops "
                             f"{', '.join(CROP_VARIANTS)}")
        size = section.get("crop_in")
        if not (isinstance(size, (list, tuple)) and len(size) == 2):
            raise StoryError(f"{label} has no crop_in = [width, height] in inches")
        if "crop_anchor" in section:
            if section["crop_anchor"] != "profile":
                raise StoryError(f"{label} has crop_anchor {section['crop_anchor']!r}; the "
                                 f"farm knows \"profile\"")
        elif not (isinstance(section.get("crop_center_m"), (list, tuple))
                  and len(section["crop_center_m"]) == 2):
            raise StoryError(f"{label} has no crop window: give crop_center_m = [x, y] "
                             f"(CRS metres), or crop_anchor = \"profile\"")


def _sheet_spec(path: str, region) -> CompositionSpec:
    """The spec a sheet was rendered from: its own manifest, through the one untrusted
    door (provenance.spec_from_manifest), else the plate's spec as the farm would build
    it now. The manifest comes first because a restage-only run opens no DEM, and
    `_frame` trims the bounds to the DEM's finite envelope only when it can read one."""
    from app import provenance
    from app.spec import SpecError
    try:
        with open(path, "rb") as f:
            manifest = provenance.extract(f.read())
        if manifest:
            return provenance.spec_from_manifest(manifest)
    except (OSError, SpecError):
        pass
    return _plate_spec(region, [], [])


def _sheet_dpi(spec: CompositionSpec, image_size: tuple) -> float:
    """The dpi a sheet was rendered at, read from the sheet: its pixel width over the
    spec's printed width. A whole-number dpi that reproduces the width exactly wins over
    the raw quotient, which wobbles by the pixel rounding. A window cut at the wrong dpi
    would show other pixels than the ones named, so `--dpi` is never trusted."""
    est = image_size[0] / spec.print_w_in
    clean = float(round(est))
    return clean if clean > 0 and round(spec.print_w_in * clean) == image_size[0] else est


def _profile_strip(spec: CompositionSpec, image_size: tuple, dpi: float) -> tuple | None:
    """(x0, y0, x1, y1) in sheet pixels of the elevation-profile strip, from the
    painter's own geometry (render._profile_rect, never a copy), or None when the spec
    draws no strip."""
    from PIL import ImageDraw
    if not spec.profile:
        return None
    return tuple(render._profile_rect(spec, ImageDraw.Draw(Image.new("RGB", (1, 1))),
                                      (0, 0, image_size[0], image_size[1]), dpi))


def _stories(out_dir, region, story, dpi=None):
    """story_<n>.png for each cropping section of the plate's story: a 1:1 window of
    print pixels from the poster, at the window the config gives. A `poster_journey`
    section writes two, story_<n>_before.png from the plain poster and story_<n>.png
    from the lit one, the same window from both. Nothing is resized.

    Restages poster.png and poster_journey.png, so no DEM is needed. The window's pixel
    size and place come from the sheet itself (its manifest's spec and its own width),
    not from `dpi`, which is only the run's expectation: a sheet at another dpi (a
    --quick poster cut by a default-dpi run) says so and is cut at its own. A section
    with no window raises StoryError naming its heading, before anything is read or
    written. A plate with no story writes nothing; the `detail` tier still serves it."""
    if not story:
        return []
    check_story_windows(story)
    jobs = []
    for n, section in enumerate(story.get("sections", []), start=1):
        for out_name, src_name in CROP_VARIANTS.get(section.get("variant"), ()):
            jobs.append((n, section, out_name.format(n=n), src_name))
    missing = sorted({src for *_, src in jobs
                      if not os.path.exists(os.path.join(out_dir, src))})
    if missing:
        print(f"  ! no {', '.join(missing)} in {out_dir} — render the poster"
              f"{' and the journey' if 'poster_journey.png' in missing else ''} first "
              f"(stories skipped)")
        return []
    sheets, windows = {}, []
    for n, section, out_name, src_name in jobs:     # judge every window before any write
        label = _section_label(story, n, section)
        if src_name not in sheets:
            path = os.path.join(out_dir, src_name)
            with Image.open(path) as im:
                size = im.size
            spec = _sheet_spec(path, region)
            if spec.bleed_in:
                raise StoryError(f"{label}: {src_name} was rendered with bleed, and a "
                                 f"story window is placed on a sheet with none")
            sheet_dpi = _sheet_dpi(spec, size)
            if dpi and abs(sheet_dpi - dpi) > 0.01 * dpi:
                print(f"  · {src_name} was rendered at {sheet_dpi:g} dpi, not {dpi:g}: "
                      f"cutting its windows at {sheet_dpi:g}")
            sheets[src_name] = (path, size, spec, sheet_dpi)
        path, size, spec, sheet_dpi = sheets[src_name]
        anchor = section.get("crop_anchor")
        try:
            box = crop_window(section.get("crop_center_m"), section["crop_in"], spec.crop,
                              size, sheet_dpi, anchor=anchor,
                              strip=_profile_strip(spec, size, sheet_dpi)
                              if anchor == "profile" else None)
        except StoryError as ex:
            raise StoryError(f"{label}: {ex}") from None
        windows.append((out_name, src_name, box))
    made = []
    for out_name, src_name, box in windows:
        with Image.open(sheets[src_name][0]) as img:
            out = os.path.join(out_dir, out_name)
            img.crop(box).save(out, "PNG")
            made.append(out)
    return made


def _coin(out_dir):
    """The coin spin: the plate (the GLB's own mesh) turning once under a spotlight,
    as a looping social video. Restages poster.png like the model tier -- no DEM
    needed. WebP always; MP4 twin when the share extra is installed."""
    from scripts.render_coinspin import COIN_FRAMES, COIN_PX, coin_mp4, coin_webp
    poster = os.path.join(out_dir, "poster.png")
    if not os.path.exists(poster):
        print(f"  ! no poster.png in {out_dir} — render the poster first (coin skipped)")
        return []
    img = Image.open(poster).convert("RGB")
    n_frames = int(os.environ.get("TECOPA_COIN_FRAMES", COIN_FRAMES))
    made = []
    for name, encode in (("coin.webp", coin_webp), ("coin.mp4", coin_mp4)):
        if name.endswith(".mp4") and not timelapse.MP4_AVAILABLE:
            print("  ! coin.mp4 needs the share extra (pip install -r requirements-share.txt) — skipped")
            continue
        out = os.path.join(out_dir, name)
        data = encode(img, n_frames, COIN_PX)   # encode fully before touching disk
        with open(out, "wb") as f:
            f.write(data)
        made.append(out)
    return made


def _relief(out_dir, rid, index):
    """The relief viewer's web images, into <out_dir>/relief/ (the farm's coin.webp
    is the coin-spin film, so the exporter's own coin.webp must not land beside it).
    Restages poster.png and detail.png like the model tier -- no DEM needed.

    `index` is what the terrain gate reads: this run's stamp merged over the prior
    index (_gate_index). A refusal skips the tier with a message rather than failing
    the region: a --synthetic-dem preview renders everything else and is correctly
    denied marketing images. A story image the exporter cannot make (a missing
    story_<n>.png, edition or film, or a crop too small to export without upscaling)
    raises instead, and main() counts the region as failed."""
    from scripts.export_relief import ReliefError, StorySourceError, export_region
    try:
        return export_region(out_dir, os.path.join(out_dir, "relief"), rid, index,
                             story=story_for(rid))
    except StorySourceError:
        raise                       # the page shows every story image: a run that cannot
                                    # export them all failed, as the exporter CLI says
    except ReliefError as ex:
        print(f"  ! relief skipped: {ex}")
        return []


def _gate_index(prior: dict, rid: str, terrain: dict | None) -> dict:
    """The index as the relief gate must see it mid-run: the farm writes index.json
    only after every region, so a first render has no record on disk yet. Same rules
    as the file the run will write (_merge_index): a DEM this run opened wins, and a
    restage-only run carries the prior record forward."""
    fresh = {"assets": []}
    if terrain:
        fresh["terrain"] = terrain
    return _merge_index({rid: fresh}, prior)


def _lightsweep(region, tracks, spots, out_dir):
    """The turntable: the composition re-rendered around the azimuth circle (the
    terrain itself reads as 3D -- only the light moves). Needs the DEM; minutes on
    real terrain, which is why --quick skips it unless explicitly asked for."""
    if not timelapse.MP4_AVAILABLE:
        print("  ! lightsweep needs the share extra (pip install -r requirements-share.txt) — skipped")
        return []
    from scripts.render_lightsweep import TARGET_PX, sweep_mp4
    spec = _plate_spec(region, tracks, spots)
    dpi = TARGET_PX / max(spec.print_w_in, spec.print_h_in)
    out = os.path.join(out_dir, "lightsweep.mp4")
    data = sweep_mp4(spec, dpi, region.dir, region.cfg)  # encode fully first: the
    with open(out, "wb") as f:                           # farm's slowest job must not
        f.write(data)                                    # die into a 0-byte "asset"
    return [out]


# ---- driver ----

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
               f"region.json (orphaned DEM; see Repair an orphaned DEM in "
               f"docs/changing-things.md)")
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


def _terrain_record(dem_path: str) -> dict | None:
    """Provenance for the DEM this run is about to paint from, or None if there is none.

    Stamped HERE, where the DEM is actually opened, and never re-derived at deploy time.
    A synthetic stand-in renders cleanly -- right hillshade, right palette, right labels
    -- so the picture cannot betray itself, and reading `regions/<id>/dem.tif` later
    answers the wrong question: a machine can render from a stand-in and obtain the real
    DEM afterwards, at which point the disk says "real" while the posters are still
    invented. (That is the lassen_ca orphan bug's shape, from the other side.) The record
    describes the bytes the render consumed, so it stays true however the plate moves.

    Three answers, because they mean three different things:

      None                     no DEM was consulted at all — the honest answer for the
                               restage tiers, and the only one _merge_index may let a
                               prior record survive.
      {"synthetic": None, …}   a DEM WAS consulted and could not be characterized. It
                               must overwrite any prior record: the earlier claim of
                               real terrain describes different bytes than the ones
                               these pixels came from, and inheriting it would attach a
                               stale promise to an unknown file. The deploy guard reads
                               a non-bool `synthetic` as unverified and refuses.
      {"synthetic": bool, …}   the real thing.

    Never fabricate the third from the second.
    """
    if not os.path.exists(dem_path):
        return None
    import rasterio
    try:
        with rasterio.open(dem_path) as ds:
            synthetic = ds.tags().get("synthetic") == "1"   # tests/conftest.py's mark
    except Exception as ex:                                 # present, but uncharacterized
        print(f"  ! could not read terrain provenance from {dem_path} "
              f"({type(ex).__name__}: {ex}) — recording it as unverified")
        return {"synthetic": None, "sha256": None, "bytes": os.path.getsize(dem_path)}
    h = hashlib.sha256()
    with open(dem_path, "rb") as f:                         # chunked: these run to 700 MB
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return {"synthetic": synthetic, "sha256": h.hexdigest(),
            "bytes": os.path.getsize(dem_path)}


def _merge_index(fresh: dict, prior: dict) -> dict:
    """Fold this run's entries into yesterday's index rather than overwriting it.

    Assets: a run that rendered only some tiers keeps the earlier tiers' records whose
    files still sit on disk (and every other region's entry, untouched).

    Terrain: a restage-only run (--only mockups/model/detail/coin) opens no DEM and so
    stamps nothing — it must carry the prior record forward. Clobbering a known-good
    record with silence would demote a verified region to an unverified one at the next
    deploy, which is worse than never having recorded it. A run that DID open a DEM
    always wins: its record describes the terrain the new pixels actually came from.
    """
    merged = dict(prior)
    for rid, entry in fresh.items():
        entry = dict(entry)
        old = prior.get(rid)
        if isinstance(old, dict):
            kept = [p for p in old.get("assets", [])
                    if p not in entry.get("assets", []) and os.path.exists(p)]
            entry["assets"] = kept + entry.get("assets", [])
            if "terrain" not in entry and isinstance(old.get("terrain"), dict):
                entry["terrain"] = old["terrain"]
        merged[rid] = entry
    return merged


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
                             "mockups", "lightsweep", "model", "detail", "coin",
                             "relief", "stories", "journey"],
                    help="render only these deliverables (default: all but lightsweep)")
    ap.add_argument("--quick", action="store_true",
                    help="fast smoke: low dpi, no film (wiring check, not final quality)")
    ap.add_argument("--synthetic-dem", action="store_true",
                    help="hydrate the test suite's synthetic DEM when a real one is absent")
    ap.add_argument("--synthetic-tracks", action="store_true",
                    help="force the synthetic track generator even when a "
                         "network cache exists (parity with --synthetic-dem)")
    args = ap.parse_args()

    if args.quick:
        args.dpi = min(args.dpi, 96.0); args.film_dpi = min(args.film_dpi, 80.0)

    regions = discover()
    ids = args.regions or list(regions)
    want = set(args.only) if args.only else set(DEFAULT_TIERS)
    if args.quick:
        # quick drops the slow renders -- unless they were EXPLICITLY asked for
        for slow in ("film", "lightsweep"):
            if not (args.only and slow in args.only):
                want.discard(slow)

    index = {}
    idx_path = os.path.join(args.out, "index.json")
    prior = {}
    if os.path.exists(idx_path):
        try:
            with open(idx_path) as f:
                prior = json.load(f)
        except (OSError, ValueError):
            prior = {}
    if not isinstance(prior, dict):
        prior = {}
    # Every region that was ASKED FOR and did not render, with why. The farm used to
    # print "! <rid> failed:" and then exit 0, so a run that lost a whole plate was
    # indistinguishable from a clean one to anything reading the status code -- which
    # is how elko_bonneville stayed unrendered while the run looked successful. The
    # deploy caught it downstream (no terrain record), but a guard two steps away is
    # not a substitute for the exit code being true.
    failed: list[tuple[str, str]] = []
    for rid in ids:
        region = regions.get(rid)
        if region is None:
            print(f"! unknown region {rid!r} (built: {', '.join(regions)})")
            failed.append((rid, "unknown region")); continue
        print(f"\n=== {rid} — {region.name} ===")
        story = story_for(rid)
        if "stories" in want:
            try:
                check_story_windows(story)      # before any render, so a bare story costs none
            except StoryError as ex:
                print(f"  ! {rid} failed: {ex}")
                failed.append((rid, str(ex)))
                continue
        needs_render = bool(want - RESTAGE_TIERS)
        terrain = None
        if needs_render:
            why = _ensure_dem(region, args.synthetic_dem)
            if why is not None:
                failed.append((rid, why))
                continue
            # stamp the DEM we are about to paint from, before painting from it
            terrain = _terrain_record(
                os.path.join(region.dir, region.cfg.get("dem_path", "dem.tif")))
            if terrain and terrain["synthetic"]:
                print("  · terrain: SYNTHETIC stand-in — these renders are not real "
                      "country and the deploy will refuse them")
        out_dir = os.path.join(args.out, rid); os.makedirs(out_dir, exist_ok=True)
        tracks, spots = _demo_journeys(region, out_dir, args.synthetic_tracks) \
            if needs_render else ([], [])
        if needs_render:
            print(f"  tracks={len(tracks)}  hotspots={len(spots)}")
        made = []
        try:
            if "poster" in want:
                p, sz = _poster(region, tracks, spots, out_dir, args.dpi)
                print(f"  poster      {sz[0]}x{sz[1]}  {p}"); made.append(p)
            if "journey" in want:
                for p in _journey(region, tracks, spots, out_dir, args.dpi, story):
                    print(f"  journey     lit poster  {p}"); made.append(p)
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
            if "mockups" in want:
                for p, sz in _mockups(region, tracks, spots, out_dir):
                    print(f"  mockup      {sz[0]}x{sz[1]}  {p}"); made.append(p)
            if "model" in want:
                for p in _model(out_dir):
                    print(f"  model       plate glb  {p}"); made.append(p)
            if "detail" in want:
                for p in _detail(out_dir):
                    print(f"  detail      1:1 crop   {p}"); made.append(p)
            if "coin" in want:
                for p in _coin(out_dir):
                    print(f"  coin        turntable  {p}"); made.append(p)
            if "stories" in want:
                for p in _stories(out_dir, region, story, args.dpi):
                    print(f"  story       1:1 crop   {p}"); made.append(p)
            if "relief" in want:
                for p in _relief(out_dir, rid, _gate_index(prior, rid, terrain)):
                    print(f"  relief      web image  {p}"); made.append(p)
            if "lightsweep" in want:
                for p in _lightsweep(region, tracks, spots, out_dir):
                    print(f"  lightsweep  {p}"); made.append(p)
        except Exception as ex:
            print(f"  ! {rid} failed: {type(ex).__name__}: {ex}")
            failed.append((rid, f"{type(ex).__name__}: {ex}"))
            continue
        if made:
            # a region whose every wanted deliverable was skipped gets no entry:
            # an empty "assets": [] would read as a rendered region
            index[rid] = {"name": region.name,
                          "assets": [os.path.relpath(p) for p in made]}
            if terrain:
                index[rid]["terrain"] = terrain

    if index:
        os.makedirs(args.out, exist_ok=True)
        total = sum(len(v["assets"]) for v in index.values())
        with open(idx_path, "w") as f:
            json.dump(_merge_index(index, prior), f, indent=2)
        print(f"\nwrote {total} assets across {len(index)} region(s) -> {idx_path}")
    else:
        print("\nno assets rendered")

    if failed:
        print(f"\n{len(failed)} of {len(ids)} region(s) did NOT render:")
        for rid, why in failed:
            print(f"  ! {rid}: {why}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
