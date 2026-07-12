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

Share twins: the same frames also encode as WebP (encode_webp) and MP4 (encode_mp4,
optional extra) for the surfaces that flatten an APNG to its first frame -- lossy,
manifest-less BY CONSTRUCTION (the encoders take none), exactly the posture of an
embed_spec=false share poster. The archival film stays the APNG above.
"""
from __future__ import annotations
import io
import json
import os
import shutil

from PIL import Image

from app import provenance, render
from app.spec import CompositionSpec

# MP4 is an OPTIONAL extra (requirements-share.txt): imageio-ffmpeg bundles an ffmpeg
# binary, which would break the core lock's "native wheels, no system deps" property.
# Gate on availability (the PDF-format posture: honest refusal, never an ImportError
# mid-render) instead of importing unconditionally. Import success alone is NOT
# availability: the binary resolves lazily in get_ffmpeg_exe(), which can fail long
# after import (an sdist install bundles no binary; a stale IMAGEIO_FFMPEG_EXE comes
# back UNTESTED on the pinned 0.6.0) -- so probe the actual exe here, once, and let
# the API's pre-enqueue 422 gate read the honest answer.
try:
    import imageio_ffmpeg
except ImportError:                                        # pragma: no cover
    imageio_ffmpeg = None


def _ffmpeg_exe() -> str | None:
    """The ffmpeg binary imageio-ffmpeg would actually run, or None if there isn't a
    runnable one. get_ffmpeg_exe() raises when nothing resolves and returns an
    IMAGEIO_FFMPEG_EXE override without testing it (both verified against the pinned
    0.6.0), so check the result too -- shutil.which handles the absolute bundled path
    and the bare 'ffmpeg' PATH fallback alike."""
    if imageio_ffmpeg is None:                             # pragma: no cover
        return None
    try:
        exe = imageio_ffmpeg.get_ffmpeg_exe()
    except RuntimeError:        # "No ffmpeg exe could be found" -- e.g. an sdist install
        return None
    return exe if shutil.which(exe) else None


MP4_AVAILABLE = _ffmpeg_exe() is not None

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


def _durations(n: int, step_ms: int, hold_ms: int, leader_ms: int) -> list:
    """The per-frame display times for an n-frame film: a beat on the bare-terrain
    leader, `step_ms` per reveal, the long `hold_ms` on the complete poster (n == 1:
    just held). Pinned HERE, once -- every encoder (the archival APNG and the share
    twins) consumes this list, so the pacing can never drift between formats."""
    durations = [step_ms] * n
    if n > 1:
        durations[0] = leader_ms      # the bare-terrain leader gets a beat
    durations[-1] = hold_ms           # the complete poster gets a long hold (n==1: held)
    return durations


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
    durations = _durations(len(frames), step_ms, hold_ms, leader_ms)
    buf = io.BytesIO()
    kw = dict(save_all=True, append_images=frames[1:], duration=durations, loop=0)
    if manifest is not None:
        kw["pnginfo"] = provenance.manifest_pnginfo(manifest)
    if icc_profile:
        kw["icc_profile"] = icc_profile
    frames[0].save(buf, "PNG", **kw)
    return buf.getvalue()


def encode_webp(frames, step_ms: int = DEFAULT_STEP_MS, hold_ms: int = DEFAULT_HOLD_MS,
                leader_ms: int = DEFAULT_LEADER_MS,
                icc_profile: bytes | None = None) -> bytes:
    """The film's WebP share twin: the same frames and pacing as the APNG, lossy, for
    the surfaces that flatten an APNG to its first frame. A share twin carries NO
    manifest BY CONSTRUCTION -- there is no parameter to pass one, exactly the posture
    of an `embed_spec=false` share poster. A single frame degrades to a static WebP
    (no leader/hold ambiguity), same as encode_apng.

    Verified against the pinned Pillow: the per-frame durations read back faithfully
    (`info["duration"]` fills on frame *load*, not seek), and the encode is
    byte-deterministic (both asserted in tests)."""
    frames = list(frames)
    if not frames:
        raise ValueError("no frames to encode")
    buf = io.BytesIO()
    kw = dict(save_all=True, append_images=frames[1:],
              duration=_durations(len(frames), step_ms, hold_ms, leader_ms),
              loop=0, quality=80, method=4)
    if icc_profile:
        kw["icc_profile"] = icc_profile
    frames[0].save(buf, "WEBP", **kw)
    return buf.getvalue()


# the MP4 twin's constant frame rate: video has no per-frame durations, so frames are
# emitted at 25 fps (40 ms ticks) and each film frame repeats round(duration/40) ticks.
MP4_BASE_FPS = 25


def encode_mp4(frames, step_ms: int = DEFAULT_STEP_MS, hold_ms: int = DEFAULT_HOLD_MS,
               leader_ms: int = DEFAULT_LEADER_MS) -> bytes:
    """The film's MP4 (H.264) share twin, for the platforms that only speak video.
    Like every share twin it carries NO manifest by construction; a video container has
    no place for an ICC profile either, so this one carries nothing at all.

    Needs the optional share extra (imageio-ffmpeg, requirements-share.txt) -- the API
    gates on MP4_AVAILABLE with an honest 422 before this is ever called; a direct
    caller gets the same sentence as a RuntimeError.

    Geometry: H.264 yuv420p subsamples chroma 2x2, so BOTH dimensions must be even --
    and the wallpaper presets are odd (e.g. iPhone 1179x2556). Pad the right/bottom
    edge by replicating the last pixel row/col: never crop a composed poster (the
    cartouche sits flush against the edge), and one replicated line is invisible.

    Pacing: the leader/step/hold durations (the shared _durations list) survive as
    frame repeats on the constant-rate pipe, quantized to the 40 ms tick.

    Color: the RGB->YUV conversion is pinned to BT.709 and the stream tagged to match,
    because untagged HD video decodes as 709 on real players while swscale converts
    with 601 by default -- left alone, the twin's hues would drift from the APNG.

    Determinism: bitexact mux+codec flags, metadata stripped, single-threaded x264,
    fixed crf/preset. Byte-determinism verified against the pinned imageio-ffmpeg
    (asserted in tests); if a future ffmpeg breaks it, downgrade that assert to
    structural (ftyp magic + decoded frame count) and name what varied."""
    # resolve the binary BEFORE materializing frames: `frames` is usually the live
    # render generator, and a whole film render must never be spent discovering that
    # the exe vanished between import and now (a stale IMAGEIO_FFMPEG_EXE, say).
    exe = require_ffmpeg()
    frames = list(frames)
    if not frames:
        raise ValueError("no frames to encode")
    tick_ms = 1000 // MP4_BASE_FPS
    durations = _durations(len(frames), step_ms, hold_ms, leader_ms)
    return _mp4_stream(exe, frames[0].size,
                       ((img, max(1, round(dur / tick_ms)))
                        for img, dur in zip(frames, durations)))


def require_ffmpeg() -> str:
    """The one honest gate for MP4 encoding: the resolved ffmpeg binary, or the same
    sentence the API's 422 speaks. Shared by the film twin and the mockup videos so
    the refusal never drifts between surfaces."""
    exe = _ffmpeg_exe() if MP4_AVAILABLE else None
    if exe is None:
        raise RuntimeError("MP4 export needs the share extra — "
                           "pip install -r requirements-share.txt")
    return exe


def _pad_even(img):
    """H.264 yuv420p needs even dimensions; replicate the last row/col (never crop --
    a composed sheet sits flush against its edges, and one replicated line is
    invisible)."""
    import numpy as np
    a = np.asarray(img)
    if a.shape[0] % 2:
        a = np.concatenate([a, a[-1:, :, :]], axis=0)       # replicate the bottom row
    if a.shape[1] % 2:
        a = np.concatenate([a, a[:, -1:, :]], axis=1)       # replicate the right col
    return a


def _mp4_stream(exe, size, ticks) -> bytes:
    """The MP4 twin's exact encoder invocation, extracted so every MP4 this repo emits
    (the film twin, the mockup videos) shares ONE bitexact/BT.709 posture. `ticks` is
    an iterable of (RGB frame, repeat_count) pairs consumed lazily -- one raw frame in
    flight at a time, so a 300-tick mockup video never holds a gigabyte of frames."""
    import subprocess
    import tempfile
    w, h = size
    even_w, even_h = w + (w % 2), h + (h % 2)
    fd, out_path = tempfile.mkstemp(suffix=".mp4")
    os.close(fd)
    try:
        cmd = [exe, "-y",
               "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{even_w}x{even_h}",
               "-r", str(MP4_BASE_FPS), "-i", "pipe:0", "-an",
               "-c:v", "libx264", "-preset", "medium", "-crf", "23",
               # color fidelity: swscale's RGB->YUV default is BT.601, but players
               # assume BT.709 for untagged video -- so CONVERT with 709 explicitly
               # (the scale filter, full-range RGB in, limited-range 709 out) and TAG
               # the stream to match, or the twin's hues drift from the APNG/poster.
               # bitexact never suppressed these tags; they were simply never set.
               "-vf", ("scale=in_range=full:out_range=limited:out_color_matrix=bt709,"
                       "format=yuv420p"),
               "-color_primaries", "bt709", "-color_trc", "bt709",
               "-colorspace", "bt709", "-color_range", "tv",
               # determinism: one x264 thread (threading reorders rate-control state),
               # one filter thread (slice order), bitexact mux + codec, and no
               # metadata (no encoder tag, no timestamps)
               "-x264-params", "threads=1", "-filter_threads", "1",
               "-fflags", "+bitexact", "-flags:v", "+bitexact", "-map_metadata", "-1",
               # +faststart fronts the moov atom so the film streams on the social
               # surfaces this twin exists for; it makes the mp4 muxer need a SEEKABLE
               # output, hence a temp file instead of a stdout pipe.
               "-movflags", "+faststart",
               "-f", "mp4", out_path]
        with tempfile.TemporaryFile() as errf:             # never PIPE: stderr must drain
            proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                    stdout=subprocess.DEVNULL, stderr=errf)
            try:
                # stream frame-by-frame (one raw frame in flight, repeats reuse its
                # bytes) -- a 40-frame film becomes ~200 piped frames, never one blob
                for img, repeats in ticks:
                    raw = _pad_even(img).tobytes()
                    for _ in range(repeats):
                        proc.stdin.write(raw)
                proc.stdin.close()
            except BrokenPipeError:
                pass                                       # the returncode check reports it
            if proc.wait() != 0:
                errf.seek(0)
                tail = errf.read()[-2000:].decode(errors="replace")
                raise RuntimeError(f"ffmpeg failed encoding the MP4 film: {tail}")
        with open(out_path, "rb") as f:
            return f.read()
    finally:
        os.unlink(out_path)


def animation_meta(max_frames: int, step_ms: int, hold_ms: int, leader_ms: int,
                   dpi: float) -> dict:
    """The manifest `animation` block: the pacing + render dpi that, with the spec,
    fully reproduce the film. Ints where the inputs are ints; dpi may be a device ppi."""
    return {"max_frames": int(max_frames), "step_ms": int(step_ms),
            "hold_ms": int(hold_ms), "leader_ms": int(leader_ms), "dpi": dpi}
