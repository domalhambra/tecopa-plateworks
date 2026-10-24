# app/icc.py
"""Colour profiles: the sRGB profile every final embeds, and a soft proof through a
paper's profile.

Order modules import this, never app.main (plan decision P8): importing app.main starts
queues, caches and region discovery. Pillow bundles littlecms."""
from __future__ import annotations

import os

from PIL import Image, ImageCms

from app.papers import INTENTS

# Where a paper's profile is installed. `~` is expanded when a profile is looked up.
PROFILE_DIRS = ("/Library/ColorSync/Profiles", "~/Library/ColorSync/Profiles")

_INTENT = {
    "perceptual": ImageCms.Intent.PERCEPTUAL,
    "relative": ImageCms.Intent.RELATIVE_COLORIMETRIC,
}
assert set(_INTENT) == set(INTENTS)


def srgb_profile() -> bytes:
    """The sRGB ICC profile for a final, with one fixed creation date."""
    import struct
    profile = bytearray(ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes())
    # littlecms stamps the creation date and time, to the second, into header bytes
    # 24 to 35. The profile is built once per process, so two engine processes gave
    # the same final two different iCCP chunks and two hashes (invariant 3). One fixed
    # date makes the bytes the same in every process. It is a real date, not zeros:
    # Pillow raises on `creation_date` for year 0. The profile ID (bytes 84 to 99) is
    # zero, so no MD5 goes stale.
    profile[24:36] = struct.pack(">6H", 2026, 10, 12, 0, 0, 0)
    return bytes(profile)


def find_profile(name: str, dirs=PROFILE_DIRS) -> str | None:
    """The path of the profile called `name` in the first of `dirs` that holds it, or None."""
    for d in dirs:
        path = os.path.join(os.path.expanduser(d), name)
        if os.path.isfile(path):
            return path
    return None


def soft_proof(img: Image.Image, paper_profile: str, intent: str) -> Image.Image:
    """`img` (sRGB) as it would look printed on the paper whose profile is at
    `paper_profile`, shown on an sRGB screen. `intent` is one of INTENTS."""
    if intent not in _INTENT:
        raise ValueError(f"intent must be one of {INTENTS}, not {intent!r}")
    srgb = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB"))
    transform = ImageCms.buildProofTransform(
        srgb, srgb, paper_profile, "RGB", "RGB",
        renderingIntent=_INTENT[intent], proofRenderingIntent=_INTENT[intent],
        flags=ImageCms.Flags.SOFTPROOFING)
    return ImageCms.applyTransform(img.convert("RGB"), transform)
