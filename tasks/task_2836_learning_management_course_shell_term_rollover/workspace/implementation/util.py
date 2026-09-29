"""Datetime / numeric primitives.

PRD 2.2: api_request_timestamp is an ISO 8601 UTC timestamp with three
fractional digits.  PRD 2.4: created_at / updated_at use the same shape.
PRD 2.6: every decimal figure carries exactly two decimal places and rounds
half away from zero (ROUND_HALF_UP).
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR, ROUND_CEILING, localcontext
from fractions import Fraction

UTC = timezone.utc
EPOCH_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)

TWO = Decimal("0.01")


class BadValue(Exception):
    """Raised when an input value cannot be coerced into the declared type."""


def wall_now():
    return datetime.now(UTC)


def fmt_ms(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD 2.2 / 2.4)."""
    if dt is None:
        return None
    dt = dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def fmt_dt(dt):
    """ISO 8601 UTC.  Sub-second digits appear only when the instant carries
    them; PRD 3.1/3.6 quote whole-second instants such as
    2027-01-10T23:59:59Z and 2026-10-17T12:00:00Z."""
    if dt is None:
        return None
    dt = dt.astimezone(UTC)
    if dt.microsecond == 0:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return fmt_ms(dt)


def parse_dt(value):
    """Tolerant ISO 8601 parser returning a tz-aware UTC datetime."""
    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)
    if not isinstance(value, str):
        raise BadValue("not a timestamp")
    text = value.strip()
    if not text:
        raise BadValue("empty timestamp")
    if text[-1] in ("Z", "z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        for pattern in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(text, pattern)
                break
            except ValueError:
                continue
        else:
            raise BadValue("unparseable timestamp")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def to_decimal(value):
    """Coerce a JSON scalar to Decimal.  Numeric strings are accepted so that a
    client sending money as a quoted literal is not rejected."""
    if isinstance(value, bool):
        raise BadValue("boolean is not a number")
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(repr(value))
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise BadValue("empty number")
        try:
            return Decimal(text)
        except Exception:
            raise BadValue("unparseable number")
    raise BadValue("not a number")


def to_int(value):
    if isinstance(value, bool):
        raise BadValue("boolean is not an integer")
    if isinstance(value, int):
        return value
    dec = to_decimal(value)
    if dec != dec.to_integral_value():
        raise BadValue("not an integer")
    return int(dec)


def to_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        low = value.strip().lower()
        if low in ("true", "1", "yes"):
            return True
        if low in ("false", "0", "no"):
            return False
    raise BadValue("not a boolean")


def q2(value):
    """Quantise to two decimal places, rounding half away from zero."""
    if value is None:
        return None
    if not isinstance(value, Decimal):
        value = to_decimal(value)
    return value.quantize(TWO, rounding=ROUND_HALF_UP)


def pct(numerator, denominator):
    """round_half_up(numerator / denominator * 100, 2); 0.00 on a zero
    denominator (PRD 3.8)."""
    numerator = to_decimal(numerator)
    denominator = to_decimal(denominator)
    if denominator == 0:
        return q2(Decimal(0))
    with localcontext() as ctx:
        ctx.prec = 60
        raw = numerator / denominator * Decimal(100)
    return q2(raw)


def floor_dec(value):
    if not isinstance(value, Decimal):
        value = to_decimal(value)
    return int(value.to_integral_value(rounding=ROUND_FLOOR))


def ceil_dec(value):
    if not isinstance(value, Decimal):
        value = to_decimal(value)
    return int(value.to_integral_value(rounding=ROUND_CEILING))


def round_half_up_int(value):
    """Round an exact rational to the nearest whole number, halves upward."""
    if isinstance(value, Fraction):
        return (value.numerator * 2 + value.denominator) // (value.denominator * 2)
    if not isinstance(value, Decimal):
        value = to_decimal(value)
    return int(value.to_integral_value(rounding=ROUND_HALF_UP))


def add_days(dt, days):
    return dt + timedelta(days=days)


def add_seconds(dt, seconds):
    return dt + timedelta(seconds=seconds)


def day_end(dt):
    """The 23:59:59 UTC boundary of the calendar day dt falls on (PRD 3.1)."""
    return dt.replace(hour=23, minute=59, second=59, microsecond=0)
