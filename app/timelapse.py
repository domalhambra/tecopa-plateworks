# app/timelapse.py
"""Time-lapse render: the poster as a film.

The spec already carries time (`track_days` drives journey grouping), and rendering is
deterministic, so an animation is not a new kind of output -- it is ONE spec painted
many times, each frame a prefix of the journeys in day order, over a terrain base that
holds still. The final frame is the complete poster, pixel-identical to `/api/final`
(the master invariant, which the tests assert directly).

Cost: the static base (relief / contours / hydro / labels) is painted ONCE via
`render._paint_base`; each frame re-inks only the route for its prefix onto that base
(`render._paint_journey` copies the base, so it is never mutated) and re-applies the
static overlays. A film therefore costs ~one full render plus N cheap route passes.

Self-describing (the file is the artwork): the deliverable is an APNG -- a PNG -- so
the provenance manifest embeds in the same zTXt chunk as any still, and the film
inspects and re-renders from the file alone. The manifest's `animation` block records
the pacing + render dpi so the film is fully reproducible.
"""
from __future__ import annotations
import io
import json
import os

from PIL import Image

from app import provenance, render
from app.spec import CompositionSpec

# Pacing defaults. None of these is a picture decision (they never change a frame's
# pixels, only how many prefixes are cut and how long each shows), so they ride the
# manifest's `animation` block, NOT the spec.
DEFAULT_MAX_FRAMES = 40
DEFAULT_STEP_MS = 220        # a journey-reveal frame
DEFAULT_HOLD_MS = 2500       # the long hold on the complete poster
DEFAULT_LEADER_MS = 700      # the beat on the bare-terrain leader frame

# Bounds the API enforces (also clamped here so a direct caller can't cut an absurd
# film): frame count and per-frame durations.
FRAMES_BOUNDS = (2, 120)
DURATION_MS_BOUNDS = (40, 10000)


def _group_day(spec: CompositionSpec, group) -> str | None:
    """The ISO day of a journey group (the first dated segment), or None if none of its
    segments carry a date. _journey_groups already clusters by day, so a group is either
    all one day or a single day-less segment."""
    days = list(spec.track_days or [])
    days += [None] * (len(spec.tracks) - len(days))
    for i in group:
        if 0 <= i < len(days) and days[i]:
            return days[i]
    return None


def frame_plan(spec: CompositionSpec, max_frames: int = DEFAULT_MAX_FRAMES) -> list:
    """The list of journey-group prefixes to paint, oldest journey first:

    - a leader frame (the empty prefix -> bare terrain), always first;
    - then cumulative prefixes as journeys accumulate in day order (day-less journeys
      last, ties by canonical order), binned to at most `max_frames` frames total;
    - the final prefix is EVERY journey, emitted in `_journey_groups` canonical order,
      so the last frame is byte-identical to `render.rasterize` (coverage is summed
      per group and float addition order is load-bearing at the ULP level).

    A pure function of the spec (no clock, no RNG), so the same spec yields the same
    plan and thus the same film (invariant 3)."""
    groups = render._journey_groups(spec)
    n = len(groups)
    if n == 0:
        return [[]]                          # no journeys to reveal: a single bare frame
    # reveal schedule: dated journeys first (ISO dates sort chronologically as text),
    # day-less journeys last, ties broken by canonical index (stable).
    order = sorted(range(n), key=lambda gi: (_group_day(spec, groups[gi]) is None,
                                             _group_day(spec, groups[gi]) or "", gi))
    max_frames = max(FRAMES_BOUNDS[0], min(int(max_frames), FRAMES_BOUNDS[1]))
    reveal_slots = max_frames - 1            # frames after the leader
    if n <= reveal_slots:
        counts = list(range(1, n + 1))       # one journey per frame
    else:
        # evenly spaced cumulative counts over reveal_slots frames, always ending at n
        counts = sorted({max(1, round(n * k / reveal_slots))
                         for k in range(1, reveal_slots + 1)})
        if counts[-1] != n:
            counts.append(n)
    plan = [[]]                              # leader: bare terrain, a beat before frame 1
    for c in counts:
        revealed = set(order[:c])
        # emit in CANONICAL order (not reveal order): the SET is the c oldest journeys,
        # but at c == n the list is exactly _journey_groups(spec) -> the last frame is
        # pixel-equal to the still poster. Order within a frame is visually irrelevant.
        plan.append([groups[gi] for gi in range(n) if gi in revealed])
    return plan


def render_frames(spec: CompositionSpec, dpi: int, region_dir: str, cfg=None,
                  hydro=None, labels=None, plan=None):
    """Yield each film frame as a PIL RGB image: the static base is painted ONCE, then
    every prefix re-inks the route onto it and re-applies the overlays. The base is
    never mutated (`_paint_journey` copies it), so frames are independent and
    deterministic. Memory holds the base + one frame at a time (the encoder consumes
    this generator)."""
    spec.validate(dpi)
    if cfg is None:
        with open(os.path.join(region_dir, "region.json")) as f:
            cfg = json.load(f)
    out_w, out_h = spec.pixel_size(dpi)
    base_rgb, lum = render._paint_base(spec, dpi, region_dir, cfg, hydro=hydro,
                                       labels=labels)
    if plan is None:
        plan = frame_plan(spec)
    for groups in plan:
        img = render._paint_journey(base_rgb, spec, out_w, out_h, dpi, groups=groups)
        yield render._paint_overlays(img, spec, lum, out_w, out_h, dpi, watermark=False)


def encode_apng(frames, manifest: dict | None = None, step_ms: int = DEFAULT_STEP_MS,
                hold_ms: int = DEFAULT_HOLD_MS, leader_ms: int = DEFAULT_LEADER_MS,
                icc_profile: bytes | None = None) -> bytes:
    """Encode frames as one looping APNG: a beat on the leader, `step_ms` per reveal, a
    long `hold_ms` on the complete poster. The manifest embeds as a compressed zTXt
    chunk (verified: Pillow writes text chunks with save_all=True), so the animated file
    is self-describing and reprintable exactly like a still."""
    frames = list(frames)
    if not frames:
        raise ValueError("no frames to encode")
    n = len(frames)
    durations = [step_ms] * n
    if n > 1:
        durations[0] = leader_ms      # the bare-terrain leader gets a beat
    durations[-1] = hold_ms           # the complete poster gets a long hold (n==1: held)
    buf = io.BytesIO()
    kw = dict(save_all=True, append_images=frames[1:], duration=durations, loop=0)
    if manifest is not None:
        kw["pnginfo"] = provenance.manifest_pnginfo(manifest)
    if icc_profile:
        kw["icc_profile"] = icc_profile
    frames[0].save(buf, "PNG", **kw)
    return buf.getvalue()


def animation_meta(max_frames: int, step_ms: int, hold_ms: int, leader_ms: int,
                   dpi: float) -> dict:
    """The manifest `animation` block: the pacing + render dpi that, with the spec,
    fully reproduce the film. Ints where the inputs are ints; dpi may be a device ppi."""
    return {"max_frames": int(max_frames), "step_ms": int(step_ms),
            "hold_ms": int(hold_ms), "leader_ms": int(leader_ms), "dpi": dpi}
