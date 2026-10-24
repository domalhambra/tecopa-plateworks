"""Reading a customer's photo: place, time and upright size (order-photos Task 1)."""
from __future__ import annotations

import calendar

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
