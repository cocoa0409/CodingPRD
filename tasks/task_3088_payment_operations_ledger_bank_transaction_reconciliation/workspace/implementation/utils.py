"""Time, identifier and parsing helpers.

Every timestamp produced by this module is ISO 8601 UTC with exactly three
fractional digits (PRD S2.5).  All temporal rules in the system read the injected
logical clock, never the host clock (PRD S2.11).
"""

import datetime as _dt
import hashlib
import random
import string

try:  # pragma: no cover - stdlib on 3.9+
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None

VALID_TZ = {
    "America/New_York",
    "America/Chicago",
    "Europe/London",
}

_FALLBACK_OFFSET_MINUTES = {
    ("America/New_York", False): -300,
    ("America/New_York", True): -240,
    ("America/Chicago", False): -360,
    ("America/Chicago", True): -300,
    ("Europe/London", False): 0,
    ("Europe/London", True): 60,
}


class TimezoneError(Exception):
    pass


def _zone(name):
    if ZoneInfo is not None:
        try:
            return ZoneInfo(name)
        except Exception:
            pass
    return None


def is_dst(aware_dt, tz_name):
    if ZoneInfo is None:
        return False
    off = aware_dt.astimezone(_zone(tz_name)).utcoffset()
    return bool(off is not None and off.total_seconds() != _fallback_offset(tz_name, False))


def _fallback_offset(tz_name, dst):
    return _FALLBACK_OFFSET_MINUTES.get((tz_name, dst), 0)


def _fallback_zone(tz_name):
    class _Fixed(_dt.tzinfo):
        def utcoffset(self, dt):
            return _dt.timedelta(minutes=_fallback_offset(tz_name, False))

        def dst(self, dt):
            return _dt.timedelta(0)

        def tzname(self, dt):
            return tz_name

    return _Fixed()


def local_date_from_ms(ms, tz_name):
    """Calendar date of an instant, expressed in the institution's timezone."""
    utc = _dt.datetime.fromtimestamp(ms / 1000.0, _dt.timezone.utc)
    z = _zone(tz_name)
    if z is not None:
        return utc.astimezone(z).date()
    off = _fallback_offset(tz_name, is_dst(utc, tz_name))
    return (utc + _dt.timedelta(minutes=off)).date()


def local_time_from_ms(ms, tz_name):
    """Wall-clock time of an instant, expressed in the institution's timezone."""
    utc = _dt.datetime.fromtimestamp(ms / 1000.0, _dt.timezone.utc)
    z = _zone(tz_name)
    if z is not None:
        return utc.astimezone(z).time().replace(tzinfo=None)
    off = _fallback_offset(tz_name, is_dst(utc, tz_name))
    return (utc + _dt.timedelta(minutes=off)).time().replace(tzinfo=None)


def utc_ms_from_local(date, time, tz_name):
    """Convert a local wall-clock (date, time) in a timezone to a UTC epoch ms."""
    naive = _dt.datetime.combine(date, time)
    z = _zone(tz_name)
    if z is not None:
        aware = naive.replace(tzinfo=z)
        return int(aware.astimezone(_dt.timezone.utc).timestamp() * 1000)
    # crude fallback: assume the standard (non-DST) offset
    off = _fallback_offset(tz_name, False)
    utc = naive - _dt.timedelta(minutes=off)
    return int(utc.replace(tzinfo=_dt.timezone.utc).timestamp() * 1000)


def iso_from_ms(ms):
    dt = _dt.datetime.fromtimestamp(ms / 1000.0, _dt.timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (ms % 1000)


def parse_iso(value):
    """Parse an ISO 8601 instant to epoch milliseconds.  Raises ValueError."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("not an ISO 8601 instant")
    s = value.strip()
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    dt = _dt.datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_dt.timezone.utc)
    return int(dt.timestamp() * 1000)


def parse_date(value):
    """Parse a YYYY-MM-DD calendar date.  Raises ValueError."""
    if not isinstance(value, str):
        raise ValueError("not a date")
    return _dt.date.fromisoformat(value.strip())


def new_request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(18))


def sha256_hex(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def rounds_half_up(value, places):
    """Decimal ROUND_HALF_UP helper for the rare non-integer fee presentation."""
    from decimal import Decimal, ROUND_HALF_UP

    quant = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(quant, rounding=ROUND_HALF_UP)