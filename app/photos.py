# app/photos.py
"""Read a customer's photo: where it was taken, when, and its upright size.

Photos are customer data. This module only reads them; the work JPEG it writes goes
wherever the caller points it (the order folder), never into ``in/``.
"""
from __future__ import annotations

import calendar
import io
import math
import os
import time
from dataclasses import dataclass

from PIL import ExifTags, Image, ImageCms, ImageOps

try:  # HEIC/HEIF needs pillow-heif (requirements.txt); JPEG, PNG etc. do not.
    import pillow_heif
    pillow_heif.register_heif_opener()
except ImportError:  # pragma: no cover - the dependency is declared
    pillow_heif = None

PHOTO_EXTS = (".jpg", ".jpeg", ".png", ".heic", ".heif", ".tif", ".tiff", ".webp", ".gif",
              ".dng")
WORK_JPEG_QUALITY = 92
_SWAPS_AXES = {5, 6, 7, 8}   # EXIF orientations that turn the picture a quarter


@dataclass(frozen=True)
class PhotoMeta:
    name: str
    lonlat: tuple | None
    taken_utc: float | None
    size_px: tuple


def _deg(value, ref) -> float | None:
    """EXIF (degrees, minutes, seconds) rationals and an N/S/E/W ref -> signed degrees."""
    try:
        d, m, s = (float(x) for x in value)
        deg = d + m / 60.0 + s / 3600.0
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    if not math.isfinite(deg):
        return None
    if isinstance(ref, bytes):
        ref = ref.decode("ascii", "ignore")
    return -deg if str(ref).strip().upper() in ("S", "W") else deg


def _lonlat(exif) -> tuple | None:
    gps = exif.get_ifd(ExifTags.IFD.GPSInfo)
    if not gps:
        return None
    lat = _deg(gps.get(2), gps.get(1)) if 2 in gps and 1 in gps else None
    lon = _deg(gps.get(4), gps.get(3)) if 4 in gps and 3 in gps else None
    if lat is None or lon is None or abs(lat) > 90 or abs(lon) > 180:
        return None
    return (lon, lat)


def _taken_utc(exif) -> float | None:
    """Unix seconds UTC, only when the photo states its UTC offset (spec section 5)."""
    sub = exif.get_ifd(ExifTags.IFD.Exif)
    taken = sub.get(ExifTags.Base.DateTimeOriginal)
    offset = sub.get(ExifTags.Base.OffsetTimeOriginal)
    if not taken or not offset:
        return None
    try:
        local = calendar.timegm(time.strptime(str(taken).strip(), "%Y:%m:%d %H:%M:%S"))
        off = str(offset).strip()
        sign = -1 if off[0] == "-" else 1
        hh, mm = off.lstrip("+-").split(":")
        return float(local - sign * (int(hh) * 3600 + int(mm) * 60))
    except (ValueError, IndexError):
        return None


def read_meta(path: str) -> PhotoMeta:
    with Image.open(path) as im:
        exif = im.getexif()
        w, h = im.size
        if exif.get(ExifTags.Base.Orientation) in _SWAPS_AXES:
            w, h = h, w
        return PhotoMeta(os.path.basename(path), _lonlat(exif), _taken_utc(exif), (w, h))


_SRGB = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB"))


def _to_srgb(im: Image.Image, icc: bytes | None) -> Image.Image:
    """``im`` as sRGB RGB. A photo tagged with another profile (an iPhone's Display P3) is
    converted, perceptual intent: the poster composites in sRGB, so an unconverted P3
    photo would print desaturated (ruling RB3). An untagged or sRGB-tagged photo, or one
    whose profile cannot be used, is only converted to RGB."""
    if icc:
        try:
            profile = ImageCms.ImageCmsProfile(io.BytesIO(icc))
            if "srgb" not in ImageCms.getProfileDescription(profile).lower():
                mode = im.mode if im.mode in ("RGB", "CMYK", "L") else "RGB"
                return ImageCms.profileToProfile(
                    im.convert(mode), profile, _SRGB,
                    renderingIntent=ImageCms.Intent.PERCEPTUAL, outputMode="RGB")
        except (ImageCms.PyCMSError, OSError, ValueError):
            pass            # a broken or mismatched profile: the pixels as they are
    return im.convert("RGB")


def write_work_jpeg(src: str, dst: str, max_px: int = 4000) -> tuple:
    """Write an upright sRGB JPEG of ``src``, long side at most ``max_px``; return its size."""
    with Image.open(src) as im:
        icc = im.info.get("icc_profile")
        im = _to_srgb(ImageOps.exif_transpose(im), icc)
        if max(im.size) > max_px:
            im.thumbnail((max_px, max_px), Image.LANCZOS)
        im.save(dst, "JPEG", quality=WORK_JPEG_QUALITY)
        return im.size
