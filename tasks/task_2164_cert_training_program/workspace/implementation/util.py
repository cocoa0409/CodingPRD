"""Time, rounding and formatting helpers.

Every domain datetime in this system lives on the server's *logical clock*
timeline (PRD 2.4).  created_at / updated_at are therefore stamped from the
logical clock, not from wall-clock time, because the refresher-currency window
[term_start_on, logical_now) aggregates rows by their updated_at.
"""
from __future__ import annotations

import datetime as _dt
import random
import string
from decimal import Decimal, ROUND_HALF_UP

UTC = _dt.timezone.utc

# PRD 2.4: startup value of the logical clock.
CLOCK_DEFAULT_ISO = "2026-08-01T00:00:00Z"


def parse_iso(value):
    """Parse an ISO 8601 UTC datetime.  Raises ValueError when malformed."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    text = value.strip()
    if not text:
        raise ValueError("empty")
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = _dt.datetime.fromisoformat(text)
    except Exception:
        raise ValueError("malformed ISO 8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def fmt_iso(dt):
    """ISO 8601 UTC with exactly three fractional-second digits (PRD 2.4)."""
    if dt is None:
        return None
    dt = dt.astimezone(UTC)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def wall_now_iso():
    return fmt_iso(_dt.datetime.now(tz=UTC))


def request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


# --------------------------------------------------------------------------
# Decimal helpers.  Money is integer cents; hours 1dp; ratios 4dp; scores 2dp.
# All rounding is ROUND_HALF_UP (PRD 2.9) — never Python's banker's round().
# --------------------------------------------------------------------------
def D(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def round_half_up(value, places):
    quant = Decimal(1).scaleb(-places)
    return D(value).quantize(quant, rounding=ROUND_HALF_UP)


def dec_out(value, places):
    """Serialise a Decimal as a JSON number rounded to `places` decimals."""
    if value is None:
        return None
    return float(round_half_up(value, places))


def hours_out(value):
    return dec_out(value, 1)


def has_max_decimals(value, places):
    try:
        exp = D(value).normalize().as_tuple().exponent
    except Exception:
        return False
    if not isinstance(exp, int):
        return False
    return exp >= -places


def add_days(dt, days):
    return dt + _dt.timedelta(days=days)


def add_minutes(dt, minutes):
    return dt + _dt.timedelta(minutes=float(minutes))


def whole_days_between(a, b):
    """Whole (floored) days between two instants."""
    delta = b - a
    return int(delta.total_seconds() // 86400)


def utc_date(dt):
    return dt.date()
