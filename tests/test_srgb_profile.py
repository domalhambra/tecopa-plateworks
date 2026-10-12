# tests/test_srgb_profile.py
"""The sRGB profile in a final has the same bytes in every engine process.

littlecms stamps the creation date and time into the header of a profile it builds
(bytes 24 to 35), to the second. The engine builds its profile once at import, so two
engine processes embedded two different iCCP chunks and the same spec gave two PNG
files with identical pixels and different hashes. A reprint after a restart never
matched the original file. Invariant 3 promises identical bytes within a build.
"""
import datetime
import io
import os
import struct
import subprocess
import sys
import time

from PIL import Image, ImageCms

from app.main import SRGB_PROFILE

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# One engine process: import the app, print the profile and the hash of a small final.
_ENGINE = """
import hashlib, sys
from PIL import Image
from app.main import SRGB_PROFILE, _encode_final
png = _encode_final(Image.new("RGB", (8, 8), (200, 120, 40)), "png", {"k": "v"}, dpi=300)
sys.stdout.write(SRGB_PROFILE.hex() + " " + hashlib.sha256(png).hexdigest())
"""


def _engine_process(tmp_path, name):
    # its own stores: an import of app.main must never see another worker's blobs
    env = dict(os.environ,
               TECOPA_BLOBS=str(tmp_path / f"blobs-{name}"),
               TECOPA_UPLOADS=str(tmp_path / f"uploads-{name}"))
    out = subprocess.run([sys.executable, "-c", _ENGINE], cwd=REPO, env=env,
                         capture_output=True, text=True, check=True).stdout
    profile_hex, png_sha = out.split()
    return bytes.fromhex(profile_hex), png_sha


def test_two_engine_processes_embed_the_same_profile_bytes(tmp_path):
    first = _engine_process(tmp_path, "a")
    time.sleep(1.1)        # the header date has one-second resolution: cross a second
    second = _engine_process(tmp_path, "b")
    assert first[0] == second[0], "the sRGB profile differs between engine processes"
    assert first[1] == second[1], "the same final differs between engine processes"
    assert first[0] == SRGB_PROFILE


def test_the_profile_header_carries_one_fixed_creation_date():
    assert SRGB_PROFILE[24:36] == struct.pack(">6H", 2026, 10, 12, 0, 0, 0)
    # A date of all zeros is stable too, but it is not a date: Pillow raises on
    # `creation_date` for it (year 0). A reader must get a real one. Only the year is
    # held here, because Pillow 12.3 reads the month one too low (October as 9).
    profile = ImageCms.ImageCmsProfile(io.BytesIO(SRGB_PROFILE))
    created = profile.profile.creation_date
    assert isinstance(created, datetime.datetime) and created.year == 2026


def test_the_profile_has_no_id_that_the_fixed_date_makes_stale():
    # A profile ID is an MD5 over the profile, date included. littlecms writes none
    # today. If it starts to, the ID must be computed again after the date is set.
    assert SRGB_PROFILE[84:100] == bytes(16)


def test_the_profile_still_parses_as_srgb():
    profile = ImageCms.ImageCmsProfile(io.BytesIO(SRGB_PROFILE))
    assert "sRGB" in ImageCms.getProfileDescription(profile)
    assert profile.profile.xcolor_space.strip() == "RGB"
    assert profile.profile.connection_space.strip() == "XYZ"
    # ...and it still means sRGB: a transform to a fresh sRGB profile moves no colour
    ramp = Image.new("RGB", (256, 1))
    ramp.putdata([(i, 255 - i, (i * 7) % 256) for i in range(256)])
    back = ImageCms.profileToProfile(ramp, profile, ImageCms.createProfile("sRGB"))
    assert back.tobytes() == ramp.tobytes()


def test_a_png_final_carries_the_profile_byte_for_byte():
    from app.main import _encode_final
    png = _encode_final(Image.new("RGB", (8, 8), (200, 120, 40)), "png", dpi=300)
    assert Image.open(io.BytesIO(png)).info["icc_profile"] == SRGB_PROFILE
