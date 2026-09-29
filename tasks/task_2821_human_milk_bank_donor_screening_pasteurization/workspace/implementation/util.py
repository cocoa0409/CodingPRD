"""Shared primitives: ids, ISO-8601 formatting, calendar arithmetic, rounding.

Timestamp format is fixed by PRD 2.2 / 2.4: ISO 8601 UTC with exactly three
fractional digits.  Money is whole cents and every rounding step is
round-half-up (PRD 2.6), so Decimal is used everywhere a fraction can appear.
"""

import random
import re
import string
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

UTC = timezone.utc

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_INSTANT_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}[Tt ]\d{2}:\d{2}(:\d{2})?(\.\d+)?"
    r"(([Zz])|([+-]\d{2}:?\d{2}))?$"
)

_ALNUM = string.ascii_uppercase + string.digits


def new_id():
    """Server-minted UUID with no type prefix (PRD 2.4)."""
    return str(uuid.uuid4())


def new_request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def now_wall():
    return datetime.now(tz=UTC)


def fmt_instant(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(UTC)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def parse_instant(value):
    """Parse an ISO-8601 instant into an aware UTC datetime, or None."""
    if not isinstance(value, str) or not _INSTANT_RE.match(value.strip()):
        return None
    text = value.strip()
    if text[-1] in ("Z", "z"):
        text = text[:-1] + "+00:00"
    text = text.replace(" ", "T")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def parse_date(value):
    """Strict YYYY-MM-DD -> date, else None."""
    if not isinstance(value, str) or not _DATE_RE.match(value):
        return None
    try:
        return date(int(value[0:4]), int(value[5:7]), int(value[8:10]))
    except ValueError:
        return None


def fmt_date(d):
    if d is None:
        return None
    return "%04d-%02d-%02d" % (d.year, d.month, d.day)


def add_days(d, n):
    """Exact calendar addition; leap days count (PRD 2.4)."""
    return d + timedelta(days=int(n))


def days_between(start, end):
    """Whole number of calendar days from start to end."""
    return (end - start).days


def dec(value):
    """Decimal from an int/float/str/Decimal without binary-float noise."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def round_half_up(value, places=0):
    """Round half away from zero to `places` decimals (PRD 2.6)."""
    quantum = Decimal(1).scaleb(-int(places))
    return dec(value).quantize(quantum, rounding=ROUND_HALF_UP)


def cents(value):
    """Round a Decimal amount half-up to a whole number of cents."""
    return int(round_half_up(value, 0))


def ceil_units(volume_ml, unit_ml):
    """Billable unit count: volume / unit rounded UP to the next whole unit."""
    q, r = divmod(int(volume_ml), int(unit_ml))
    return q + (1 if r else 0)


def num_out(value):
    """JSON representation for a decimal quantity."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value
