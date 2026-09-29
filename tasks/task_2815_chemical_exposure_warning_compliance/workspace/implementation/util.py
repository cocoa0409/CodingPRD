"""Numeric and temporal helpers.

Rounding in this system is always round half up (PRD 2.5); money is integer
cents and every "floor" step truncates toward zero.
"""
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_DOWN, ROUND_FLOOR

from errors import fail

ISO_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}[Tt ]\d{2}:\d{2}:\d{2}(\.\d+)?([Zz]|[+-]\d{2}:?\d{2})?$"
)


def D(value):
    """Decimal from anything numeric, never through binary float arithmetic."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        return Decimal(int(value))
    if value is None:
        return None
    return Decimal(str(value))


def rhu(value, places):
    """Round half up to `places` decimals."""
    if value is None:
        return None
    q = Decimal(1).scaleb(-places)
    return D(value).quantize(q, rounding=ROUND_HALF_UP)


def floor_cents(value):
    """Truncate toward zero to a whole number."""
    return int(D(value).quantize(Decimal(1), rounding=ROUND_DOWN))


def out_num(value):
    """Render a Decimal for JSON without binary-float surprises."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            iv = int(value)
            return iv if abs(D(iv) - value) == 0 else float(value)
        return float(value)
    return value


def parse_dt(raw, field="timestamp"):
    if not isinstance(raw, str) or not ISO_RE.match(raw.strip()):
        fail("ERR_INVALID_REQUEST", "%s is not an ISO 8601 timestamp" % field)
    text = raw.strip().replace(" ", "T").replace("t", "T")
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        fail("ERR_INVALID_REQUEST", "%s is not an ISO 8601 timestamp" % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional-second digits (PRD 2.4)."""
    if dt is None:
        return None
    if not isinstance(dt, datetime):
        return dt
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def days(n):
    return timedelta(seconds=n * 86400)


def whole_days_between(start, end):
    """Elapsed seconds divided by 86400, taken as a floor to a whole number."""
    delta = end - start
    seconds = D(delta.days) * D(86400) + D(delta.seconds) + D(delta.microseconds) / D(10 ** 6)
    return int((seconds / D(86400)).to_integral_value(rounding=ROUND_FLOOR))
