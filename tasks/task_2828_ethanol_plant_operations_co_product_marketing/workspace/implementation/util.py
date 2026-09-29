"""Numeric and temporal helpers.

All money/quantity arithmetic uses decimal.Decimal with ROUND_HALF_UP.
Never float.
"""
import re
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR, ROUND_CEILING
from datetime import datetime, timezone, timedelta

UTC = timezone.utc
MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def D(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(str(value))


def rhu(value, places):
    """Round half up to `places` decimal places."""
    q = Decimal(1).scaleb(-places)
    return D(value).quantize(q, rounding=ROUND_HALF_UP)


def dfloor(value):
    return int(D(value).to_integral_value(rounding=ROUND_FLOOR))


def dceil(value):
    return int(D(value).to_integral_value(rounding=ROUND_CEILING))


def fixed(value, places):
    """Decimal carrying exactly `places` decimal digits (no rounding surprises)."""
    return rhu(value, places)


def dec_places(value):
    if isinstance(value, int):
        return 0
    exp = D(value).as_tuple().exponent
    return -exp if exp < 0 else 0


def iso(dt):
    """ISO-8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(UTC)
    ms = dt.microsecond // 1000
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, ms)


def parse_instant(text):
    """Parse an ISO-8601 UTC instant. Raises ValueError when malformed."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError("not an instant")
    raw = text.strip()
    body = raw
    if body.endswith("Z") or body.endswith("z"):
        body = body[:-1] + "+00:00"
    dt = datetime.fromisoformat(body)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def at_second(dt):
    """Instants are compared at second resolution in UTC."""
    return dt.replace(microsecond=0)


def plus_minutes(dt, minutes):
    return dt + timedelta(minutes=int(minutes))


def is_month(text):
    return isinstance(text, str) and bool(MONTH_RE.match(text))
