"""Reading a customer's photo: place, time and upright size (order-photos Task 1)."""
from __future__ import annotations

import calendar
import io

import pytest
from PIL import ExifTags, Image

from app import photos

_IFD = ExifTags.IFD


def _gps_ifd(lat, lat_ref, lon, lon_ref):
    def dms(v):
        d = int(v)
        m = int((v - d) * 60)
        s = round(((v - d) * 60 - m) * 60 * 10000)
        return ((d, 1), (m, 1), (s, 10000))
    return {1: lat_ref, 2: tuple(float(x[0]) / x[1] for x in dms(lat)),
            3: lon_ref, 4: tuple(float(x[0]) / x[1] for x in dms(lon))}


def _make(path, size=(60, 40), *, gps=None, taken=None, offset=None, orientation=None):
    im = Image.new("RGB", size, (30, 120, 60))
    exif = Image.Exif()
    if orientation:
        exif[ExifTags.Base.Orientation] = orientation
    if gps:
        exif[ExifTags.Base.GPSInfo] = None
        exif.get_ifd(_IFD.GPSInfo).update(_gps_ifd(*gps))
    if taken or offset:
        sub = exif.get_ifd(_IFD.Exif)
        if taken:
            sub[ExifTags.Base.DateTimeOriginal] = taken
        if offset:
            sub[ExifTags.Base.OffsetTimeOriginal] = offset
    im.save(path, exif=exif)
    return str(path)


def test_gps_becomes_lon_lat(tmp_path):
    p = _make(tmp_path / "a.jpg", gps=(36.25, "N", 116.75, "W"))
    m = photos.read_meta(p)
    assert m.name == "a.jpg"
    lon, lat = m.lonlat
    assert lon == pytest.approx(-116.75, abs=1e-4)
    assert lat == pytest.approx(36.25, abs=1e-4)


def test_southern_eastern_hemisphere_signs(tmp_path):
    p = _make(tmp_path / "s.jpg", gps=(33.5, "S", 151.25, "E"))
    lon, lat = photos.read_meta(p).lonlat
    assert lon == pytest.approx(151.25, abs=1e-4)
    assert lat == pytest.approx(-33.5, abs=1e-4)


def test_time_is_unix_utc_with_its_offset(tmp_path):
    p = _make(tmp_path / "t.jpg", taken="2026:10:03 09:30:00", offset="-07:00")
    want = calendar.timegm((2026, 10, 3, 16, 30, 0))
    assert photos.read_meta(p).taken_utc == want


def test_time_needs_its_offset(tmp_path):
    p = _make(tmp_path / "t.jpg", taken="2026:10:03 09:30:00")
    assert photos.read_meta(p).taken_utc is None


def test_no_exif_is_all_none_but_the_size(tmp_path):
    p = tmp_path / "n.jpg"
    Image.new("RGB", (50, 30)).save(p)
    m = photos.read_meta(str(p))
    assert (m.lonlat, m.taken_utc, m.size_px) == (None, None, (50, 30))


def test_sideways_photo_reports_its_upright_size(tmp_path):
    p = _make(tmp_path / "r.jpg", size=(60, 40), orientation=6)
    assert photos.read_meta(p).size_px == (40, 60)
    q = _make(tmp_path / "u.jpg", size=(60, 40), orientation=1)
    assert photos.read_meta(q).size_px == (60, 40)


def test_heic_is_read(tmp_path):
    pillow_heif = pytest.importorskip("pillow_heif")
    pillow_heif.register_heif_opener()
    src = tmp_path / "h.heic"
    try:
        exif = Image.Exif()
        exif.get_ifd(_IFD.GPSInfo).update(_gps_ifd(36.25, "N", 116.75, "W"))
        Image.new("RGB", (64, 48), (9, 9, 9)).save(src, exif=exif)
    except Exception as e:  # pragma: no cover - encoder missing
        pytest.skip(f"pillow-heif cannot write a fixture: {e}")
    m = photos.read_meta(str(src))
    assert m.size_px == (64, 48)
    assert m.lonlat[1] == pytest.approx(36.25, abs=1e-3)


def test_work_jpeg_is_upright_and_capped(tmp_path):
    p = _make(tmp_path / "w.jpg", size=(300, 200), orientation=6)
    dst = tmp_path / "out.jpg"
    size = photos.write_work_jpeg(p, str(dst), max_px=100)
    assert size == (67, 100)
    with Image.open(dst) as im:
        assert im.size == size and im.mode == "RGB" and im.format == "JPEG"


def test_work_jpeg_never_enlarges(tmp_path):
    p = _make(tmp_path / "w.jpg", size=(60, 40))
    assert photos.write_work_jpeg(p, str(tmp_path / "o.jpg"), max_px=4000) == (60, 40)


def test_ordernew_keeps_using_the_moved_photo_exts():
    from app import ordernew
    assert ordernew.PHOTO_EXTS is photos.PHOTO_EXTS


# --- RB3: a wide-gamut photo is converted to sRGB before the poster composites it ------

def _rgb_matrix_icc(desc, red, green, blue, gamma=2.2):
    """A minimal ICC v2 display profile: RGB primaries (D50 XYZ) and one gamma curve.
    Built by hand, so the test needs no profile file (Pillow only makes sRGB)."""
    import struct

    def s15(v):
        return struct.pack(">i", round(v * 65536))

    def xyz(v):
        return b"XYZ \0\0\0\0" + b"".join(s15(c) for c in v)

    text = desc.encode("ascii") + b"\0"
    desc_tag = (b"desc\0\0\0\0" + struct.pack(">I", len(text)) + text
                + struct.pack(">II", 0, 0) + struct.pack(">HB", 0, 0) + b"\0" * 67)
    curve = b"curv\0\0\0\0" + struct.pack(">IH", 1, round(gamma * 256)) + b"\0\0"
    d50 = (0.9642, 1.0, 0.8249)
    blocks = [(b"desc", desc_tag), (b"wtpt", xyz(d50)), (b"rXYZ", xyz(red)),
              (b"gXYZ", xyz(green)), (b"bXYZ", xyz(blue)), (b"rTRC", curve)]
    shared = {b"gTRC": b"rTRC", b"bTRC": b"rTRC"}
    count = len(blocks) + len(shared)
    offset = 128 + 4 + 12 * count
    table, data, where = b"", b"", {}
    for sig, body in blocks:
        body += b"\0" * (-len(body) % 4)
        where[sig] = (offset + len(data), len(body))
        data += body
    for sig in [s for s, _ in blocks] + list(shared):
        table += sig + struct.pack(">II", *where[shared.get(sig, sig)])
    size = offset + len(data)
    header = (struct.pack(">I", size) + b"\0" * 4 + struct.pack(">I", 0x02100000)
              + b"mntrRGB XYZ " + b"\0" * 12 + b"acsp" + b"\0" * 24
              + struct.pack(">I", 0) + b"".join(s15(c) for c in d50) + b"\0" * 48)
    assert len(header) == 128
    return header + struct.pack(">I", count) + table + data


# Display P3's primaries, adapted to D50 (the iPhone's camera profile)
P3 = dict(red=(0.5151, 0.2412, -0.0011), green=(0.2920, 0.6922, 0.0419),
          blue=(0.1571, 0.0666, 0.7841))


def _pixel(path):
    with Image.open(path) as im:
        return im.convert("RGB").getpixel((10, 10))


def test_work_jpeg_converts_a_wide_gamut_photo_to_srgb(tmp_path):
    from PIL import ImageCms
    icc = _rgb_matrix_icc("Display P3 (test)", **P3)
    assert ImageCms.getProfileDescription(ImageCms.ImageCmsProfile(io.BytesIO(icc)))
    src = tmp_path / "p3.jpg"
    Image.new("RGB", (40, 40), (190, 120, 110)).save(src, icc_profile=icc, quality=100)
    photos.write_work_jpeg(str(src), str(tmp_path / "out.jpg"))
    r, g, b = _pixel(tmp_path / "out.jpg")
    # the same colour in sRGB's smaller gamut: the red reaches further, the green less
    assert r >= 190 + 8 and g <= 120 - 2 and b <= 110 - 2, (r, g, b)
    with Image.open(tmp_path / "out.jpg") as im:
        assert im.mode == "RGB"


def test_work_jpeg_leaves_an_srgb_or_untagged_photo_alone(tmp_path):
    from PIL import ImageCms
    srgb = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    for name, kw in (("srgb.jpg", {"icc_profile": srgb}), ("plain.jpg", {})):
        src = tmp_path / name
        Image.new("RGB", (40, 40), (190, 120, 110)).save(src, quality=100, **kw)
        photos.write_work_jpeg(str(src), str(tmp_path / ("out-" + name)))
        got = _pixel(tmp_path / ("out-" + name))
        assert all(abs(a - b) <= 2 for a, b in zip(got, (190, 120, 110))), (name, got)
