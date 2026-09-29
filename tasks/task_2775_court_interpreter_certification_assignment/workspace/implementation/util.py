"""Time, id, and numeric helpers.

Every timestamp the API emits is an ISO 8601 UTC instant with exactly three
fractional-second digits (PRD 2.2 / 2.4).  All temporal reasoning runs against
the server-held logical clock (PRD 2.5), never wall-clock time.
"""
import random
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

# The logical clock reads exactly this instant before any client sets it.
CLOCK_DEFAULT = "2026-08-01T00:00:00.000Z"

_ALNUM = string.ascii_uppercase + string.digits


def new_uuid():
    """Server-minted UUID with no type prefix and no embedded semantics."""
    return str(uuid.uuid4())


def new_request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def fmt_date(d):
    if d is None:
        return None
    return "%04d-%02d-%02d" % (d.year, d.month, d.day)


def parse_dt(value):
    """Parse an ISO 8601 datetime.  Returns None when malformed."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value):
    """Parse a plain YYYY-MM-DD date.  Returns None when malformed."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if len(text) != 10:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def add_days(d, n):
    """Whole-day arithmetic on a calendar date (PRD 2.5)."""
    return d + timedelta(days=int(n))


def day_start(d):
    """Midnight UTC on a calendar date."""
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


def dec(value):
    """Decimal from an int/float/str without binary float error."""
    if isinstance(value, Decimal):
        return value
    if value is None:
        return Decimal(0)
    return Decimal(str(value))


def round_half_up_cents(value):
    """Round a Decimal amount to whole cents, half away from zero."""
    return int(dec(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_2(value):
    """Round to two decimal places, half up; returned as a float."""
    return float(dec(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def num_out(value):
    """Emit a numeric value as int when integral, else float."""
    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            return int(value)
        return float(value)
    return value


def hours_two_dp(value):
    """billable_hours carried to two decimal places."""
    return float(dec(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
