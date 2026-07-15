# app/solar.py
"""Solar position + the journey's "signature moment" -- the engine behind Journey Light.

Pure Python (stdlib `math`/`datetime` only, no new dependency) and DETERMINISTIC: every
function is a pure function of its inputs, no clock and no RNG, so a spec built from a
given journey always resolves to the same sun (invariant 3). The resolved azimuth/
altitude are stamped onto the CompositionSpec at proof time and thereafter ride the
manifest -- the GPX timestamps themselves never leave the session (privacy + a lean
reprint manifest).

`solar_position` is the NOAA/Meeus low-accuracy ephemeris (the algorithm behind NOAA's
solar-calculator spreadsheet); ~0.01 deg on altitude, far finer than lighting needs.
Reference: verified against the NREL SPA canonical point in tests/test_solar.py.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

# The default "signature moment": ~1 h before sunset, the warm raking light a hike
# finishes in. Chosen as the DESCENDING crossing of this solar altitude on the anchor
# day. The 8 deg floor (STYLE_BOUNDS["sun_altitude_deg"]) is the hard clamp below.
GOLDEN_ALT_TARGET = 12.0
ALT_FLOOR = 8.0
ALT_CEIL = 80.0
_DAY_SECONDS = 86400.0


def _iso_to_unix(s: str) -> float:
    """ISO-19 UTC string (ingest._iso19) -> unix seconds."""
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc).timestamp()


def _julian_day(dt: datetime) -> float:
    """Julian Day (Gregorian) for a UTC datetime."""
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    a = (14 - dt.month) // 12
    y = dt.year + 4800 - a
    m = dt.month + 12 * a - 3
    jdn = (dt.day + (153 * m + 2) // 5 + 365 * y + y // 4 - y // 100 + y // 400 - 32045)
    frac = (dt.hour - 12) / 24.0 + dt.minute / 1440.0 + dt.second / 86400.0
    return jdn + frac


def solar_position(dt_utc: datetime, lat_deg: float, lon_deg: float) -> tuple[float, float]:
    """(azimuth_deg clockwise from north, altitude_deg above horizon) of the sun at a UTC
    instant and a geographic point (lon east-positive). NOAA/Meeus low-accuracy series."""
    jd = _julian_day(dt_utc)
    t = (jd - 2451545.0) / 36525.0                          # Julian centuries since J2000
    # geometric mean longitude + anomaly of the sun
    l0 = (280.46646 + t * (36000.76983 + 0.0003032 * t)) % 360.0
    m = 357.52911 + t * (35999.05029 - 0.0001537 * t)
    mr = math.radians(m)
    e = 0.016708634 - t * (0.000042037 + 0.0000001267 * t)
    # equation of center -> true, then apparent longitude
    c = (math.sin(mr) * (1.914602 - t * (0.004817 + 0.000014 * t))
         + math.sin(2 * mr) * (0.019993 - 0.000101 * t)
         + math.sin(3 * mr) * 0.000289)
    true_long = l0 + c
    omega = 125.04 - 1934.136 * t
    app_long = true_long - 0.00569 - 0.00478 * math.sin(math.radians(omega))
    # obliquity of the ecliptic (corrected)
    eps0 = 23.0 + (26.0 + (21.448 - t * (46.815 + t * (0.00059 - t * 0.001813))) / 60.0) / 60.0
    eps = eps0 + 0.00256 * math.cos(math.radians(omega))
    epsr = math.radians(eps)
    app_r = math.radians(app_long)
    # declination
    decl = math.asin(math.sin(epsr) * math.sin(app_r))
    # equation of time (minutes)
    y = math.tan(epsr / 2.0) ** 2
    l0r = math.radians(l0)
    eot = 4.0 * math.degrees(
        y * math.sin(2 * l0r) - 2 * e * math.sin(mr)
        + 4 * e * y * math.sin(mr) * math.cos(2 * l0r)
        - 0.5 * y * y * math.sin(4 * l0r) - 1.25 * e * e * math.sin(2 * mr))
    # true solar time (minutes), then hour angle (deg)
    dt = dt_utc.astimezone(timezone.utc) if dt_utc.tzinfo else dt_utc
    minutes = dt.hour * 60.0 + dt.minute + dt.second / 60.0
    tst = (minutes + eot + 4.0 * lon_deg) % 1440.0
    ha = tst / 4.0 - 180.0
    if ha < -180.0:
        ha += 360.0
    har = math.radians(ha)
    latr = math.radians(lat_deg)
    # zenith -> altitude
    cos_zen = (math.sin(latr) * math.sin(decl)
               + math.cos(latr) * math.cos(decl) * math.cos(har))
    cos_zen = max(-1.0, min(1.0, cos_zen))
    zenith = math.acos(cos_zen)
    altitude = 90.0 - math.degrees(zenith)
    # azimuth clockwise from north
    sin_zen = math.sin(zenith)
    if sin_zen < 1e-9:
        azimuth = 0.0
    else:
        cos_az = (math.sin(latr) * cos_zen - math.sin(decl)) / (math.cos(latr) * sin_zen)
        cos_az = max(-1.0, min(1.0, cos_az))
        az = math.degrees(math.acos(cos_az))
        azimuth = (az + 180.0) % 360.0 if ha > 0 else (540.0 - az) % 360.0
    return azimuth, altitude


def _clamp_alt(alt: float) -> float:
    return max(ALT_FLOOR, min(ALT_CEIL, alt))


def _local_offset_seconds(lon_deg: float) -> float:
    """Local SOLAR-time offset from UTC (labelled as solar time in the UI): lon/15 hours.
    Not civil timezone/DST -- deliberately, so it needs no tz database and is honest about
    what it is (the sun's own clock at that longitude)."""
    return lon_deg / 15.0 * 3600.0


def track_anchor(tracks) -> dict | None:
    """Aggregate the journey's geography + timing into the small dict the sun functions
    read, or None when NO track carries a timestamp (Journey Light is then unavailable).

    Reads the ingest.Track fields added for this feature: `lonlat` (lon, lat centroid),
    `coords_t` (per-vertex unix seconds, NaN unknown), and `summit_t`/`summit_ele` (the
    full-resolution highest point that carries a time). Pure function of the tracks."""
    lons, lats = [], []
    tmin = tmax = None
    summit_ele = None
    summit_unix = None
    days = set()
    for tr in tracks or []:
        ll = getattr(tr, "lonlat", None)
        if ll is not None:
            lons.append(float(ll[0]))
            lats.append(float(ll[1]))
        ct = getattr(tr, "coords_t", None)
        if ct is not None:
            for tv in ct:
                if tv is None or not math.isfinite(tv):
                    continue
                tv = float(tv)
                tmin = tv if tmin is None else min(tmin, tv)
                tmax = tv if tmax is None else max(tmax, tv)
                days.add(datetime.fromtimestamp(tv, timezone.utc).date().isoformat())
        st, se = getattr(tr, "summit_t", None), getattr(tr, "summit_ele", None)
        if st is not None and se is not None and (summit_ele is None or se > summit_ele):
            summit_ele = float(se)
            summit_unix = _iso_to_unix(st)
    if tmin is None or not lons:
        return None
    return {"lon": sum(lons) / len(lons), "lat": sum(lats) / len(lats),
            "tmin_unix": tmin, "tmax_unix": tmax, "summit_unix": summit_unix,
            "days": sorted(days)}


def golden_hour_utc(anchor: dict, day_iso: str | None = None) -> datetime:
    """The default signature moment as a UTC datetime: the DESCENDING crossing of
    GOLDEN_ALT_TARGET on `day_iso` (default: the journey's last dated day), scanned at
    minute resolution in local solar time. Falls back to solar noon (the day's highest
    sun) when the sun never reaches the target (deep winter / high latitude)."""
    lat, lon = anchor["lat"], anchor["lon"]
    day = day_iso or anchor["days"][-1]
    y, m, d = (int(x) for x in day.split("-"))
    # local-solar midnight of that day, expressed in UTC
    off = _local_offset_seconds(lon)
    base = datetime(y, m, d, tzinfo=timezone.utc) - timedelta(seconds=off)
    best_noon = base
    best_alt = -90.0
    prev_alt = None
    crossing = None
    for minute in range(0, 24 * 60 + 1):
        when = base + timedelta(minutes=minute)
        _, alt = solar_position(when, lat, lon)
        if alt > best_alt:
            best_alt, best_noon = alt, when
        if (prev_alt is not None and crossing is None
                and prev_alt >= GOLDEN_ALT_TARGET > alt and minute > 60):
            crossing = when                       # descending crossing = evening golden hour
        prev_alt = alt
    return crossing or best_noon


def _hour_local_of(when: datetime, lon: float) -> float:
    """Local-solar hour-of-day (0..24) of a UTC instant, for the UI scrubber default."""
    off = _local_offset_seconds(lon)
    local = when + timedelta(seconds=off)
    return local.hour + local.minute / 60.0 + local.second / 3600.0


def _utc_for_hour_local(day_iso: str, hour_local: float, lon: float) -> datetime:
    y, m, d = (int(x) for x in day_iso.split("-"))
    off = _local_offset_seconds(lon)
    return (datetime(y, m, d, tzinfo=timezone.utc)
            + timedelta(hours=hour_local) - timedelta(seconds=off))


def journey_sun(anchor: dict, hour_local: float | None = None) -> dict:
    """Resolve the still poster's sun from the journey.

    Default moment: SUMMIT LIGHT -- the sun as it stood when the journey reached its
    highest point -- falling back to golden hour of the last dated day when no elevation
    is present. `hour_local` (the UI time-of-day scrubber, local solar hours) overrides
    the time on the anchor day. Altitude is clamped into STYLE_BOUNDS so a scrub into the
    night can never yield an under-horizon sun. Returns the resolved angles plus the
    moment's local hour (the scrubber's default position)."""
    lat, lon = anchor["lat"], anchor["lon"]
    day = anchor["days"][-1]
    if hour_local is not None:
        when = _utc_for_hour_local(day, float(hour_local), lon)
    elif anchor.get("summit_unix") is not None:
        when = datetime.fromtimestamp(anchor["summit_unix"], timezone.utc)
    else:
        when = golden_hour_utc(anchor)
    az, alt = solar_position(when, lat, lon)
    return {"azimuth_deg": az % 360.0, "altitude_deg": _clamp_alt(alt),
            "hour_local": round(_hour_local_of(when, lon), 3)}


def sun_schedule(anchor: dict, n_frames: int, motion: str = "auto") -> list[tuple[float, float]]:
    """One clamped (az, alt) per film frame -- the sun that travels with the hike. Pure
    function of (anchor, n_frames, motion).

    - "diurnal": the sun walks the journey's own hours (tmin..tmax) -- sunrise-band to
      sunset-band as a single long day-hike draws.
    - "seasonal": the sun is taken at a fixed evening hour on each successive dated day,
      so the light drifts across the season as a multi-day / multi-year archive fills in.
    - "auto": diurnal when the whole trip spans <= ~1 day, else seasonal.
    """
    n = max(1, int(n_frames))
    lat, lon = anchor["lat"], anchor["lon"]
    span = anchor["tmax_unix"] - anchor["tmin_unix"]
    mode = motion
    if mode == "auto":
        mode = "diurnal" if span <= _DAY_SECONDS else "seasonal"
    out = []
    if mode == "seasonal" and len(anchor["days"]) > 1:
        days = anchor["days"]
        for k in range(n):
            frac = k / (n - 1) if n > 1 else 1.0
            day = days[min(len(days) - 1, round(frac * (len(days) - 1)))]
            when = golden_hour_utc(anchor, day)
            az, alt = solar_position(when, lat, lon)
            out.append((az % 360.0, _clamp_alt(alt)))
        return out
    # diurnal (also the degenerate single-day seasonal case)
    lo, hi = anchor["tmin_unix"], anchor["tmax_unix"]
    if hi <= lo:
        hi = lo + 3600.0
    for k in range(n):
        frac = k / (n - 1) if n > 1 else 1.0
        when = datetime.fromtimestamp(lo + frac * (hi - lo), timezone.utc)
        az, alt = solar_position(when, lat, lon)
        out.append((az % 360.0, _clamp_alt(alt)))
    return out
