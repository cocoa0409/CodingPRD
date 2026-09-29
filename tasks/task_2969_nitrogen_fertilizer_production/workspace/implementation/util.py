"""Numeric / temporal primitives.

All rounding in this service is round-half-up (PRD 2.6); all instants are
emitted through a single canonical formatter so every timestamp field in every
response carries exactly three fractional digits (PRD 2.4).
"""
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

ZERO = Decimal("0")


def D(v):
    """Coerce to Decimal without dragging binary float noise along."""
    if isinstance(v, Decimal):
        return v
    if isinstance(v, bool):
        raise ValueError("bool is not a number")
    if isinstance(v, int):
        return Decimal(v)
    if isinstance(v, float):
        return Decimal(repr(v))
    return Decimal(str(v))


def rhu(value, places):
    """Round half up to `places` decimals -- a midpoint rounds away from zero."""
    if value is None:
        return None
    q = Decimal(1).scaleb(-places)
    return D(value).quantize(q, rounding=ROUND_HALF_UP)


def clamp(value, lo, hi):
    if value < lo:
        return lo
    if value > hi:
        return hi
    return value


# --------------------------------------------------------------------------
# Instants
# --------------------------------------------------------------------------
_DT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})"
    r"(?:[Tt ](\d{2}):(\d{2})(?::(\d{2}))?(\.\d+)?"
    r"(Z|z|[+-]\d{2}:?\d{2})?)?$"
)


def parse_dt(value):
    """Parse an ISO-8601 instant into an aware UTC datetime, or raise ValueError."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    m = _DT_RE.match(value.strip())
    if not m:
        raise ValueError("not an ISO-8601 instant")
    year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
    hour = int(m.group(4) or 0)
    minute = int(m.group(5) or 0)
    second = int(m.group(6) or 0)
    frac = m.group(7)
    micro = 0
    if frac:
        digits = (frac[1:] + "000000")[:6]
        micro = int(digits)
    offset = m.group(8)
    tz = timezone.utc
    if offset and offset not in ("Z", "z"):
        sign = 1 if offset[0] == "+" else -1
        body = offset[1:].replace(":", "")
        tz = timezone(sign * timedelta(hours=int(body[:2]), minutes=int(body[2:4])))
    dt = datetime(year, month, day, hour, minute, second, micro, tzinfo=tz)
    return dt.astimezone(timezone.utc)


def fmt_dt(dt):
    """The single canonical instant formatter: YYYY-MM-DDTHH:MM:SS.mmmZ."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def year_month(dt):
    """The UTC year-and-month of an instant, as the `YYYY-MM` string hedge lots use."""
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d" % (dt.year, dt.month)


_MONTH_RE = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")


def valid_delivery_month(value):
    return isinstance(value, str) and bool(_MONTH_RE.match(value))


def whole_days(later, earlier):
    """Elapsed whole days, truncated toward zero."""
    return int((later - earlier).total_seconds() / 86400)
