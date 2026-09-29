"""Money, basis point and temporal helpers."""

import re
import uuid
import random
import string
from datetime import datetime, timezone, date, timedelta
from decimal import Decimal, ROUND_HALF_UP


# ---------------------------------------------------------------- money / bps

def round_half_up(value):
    """Round a Decimal/int/str half-up to the nearest whole unit, returning int."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def apply_bps(amount_cents, bps):
    """amount * bps / 10000, rounded half up to whole cents."""
    return round_half_up(Decimal(int(amount_cents)) * Decimal(int(bps)) / Decimal(10000))


def ratio_bps(numerator_cents, denominator_cents):
    """numerator * 10000 / denominator, rounded half up to whole bps."""
    if int(denominator_cents) == 0:
        return 0
    return round_half_up(
        Decimal(int(numerator_cents)) * Decimal(10000) / Decimal(int(denominator_cents))
    )


# ------------------------------------------------------------------ identity

def new_uuid():
    return str(uuid.uuid4())


_ALNUM = string.ascii_uppercase + string.digits


def new_request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


# ------------------------------------------------------------------ temporal

_DT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d{1,9}))?)?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)
_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def parse_datetime(value):
    """Parse an ISO 8601 instant into an aware UTC datetime. None when invalid."""
    if not isinstance(value, str):
        return None
    m = _DT_RE.match(value.strip())
    if not m:
        return None
    year, month, day, hour, minute = (int(m.group(i)) for i in range(1, 6))
    second = int(m.group(6) or 0)
    frac = m.group(7) or ""
    micro = int((frac + "000000")[:6]) if frac else 0
    tz = m.group(8)
    try:
        naive = datetime(year, month, day, hour, minute, second, micro)
    except ValueError:
        return None
    if tz in (None, "Z", "z"):
        return naive.replace(tzinfo=timezone.utc)
    sign = 1 if tz[0] == "+" else -1
    body = tz[1:].replace(":", "")
    offset = timedelta(hours=int(body[:2]), minutes=int(body[2:4]))
    return (naive - sign * offset).replace(tzinfo=timezone.utc)


def parse_date(value):
    """Parse a strict YYYY-MM-DD calendar date. None when invalid."""
    if not isinstance(value, str):
        return None
    m = _DATE_RE.match(value.strip())
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def format_datetime(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, dt.microsecond // 1000,
    )


def format_date(d):
    if d is None:
        return None
    return "%04d-%02d-%02d" % (d.year, d.month, d.day)


def midnight(d):
    """The UTC instant at the start of the given calendar date."""
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


def day_diff(later, earlier):
    """Whole UTC calendar days between two dates or datetimes (later - earlier)."""
    return (_as_date(later) - _as_date(earlier)).days


def _as_date(value):
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).date()
    return value
