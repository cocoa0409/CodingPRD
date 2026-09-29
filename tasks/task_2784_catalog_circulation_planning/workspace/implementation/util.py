"""Primitive helpers: ids, exact half-up integer arithmetic, timestamp handling."""

import itertools
import random
import string
import uuid
from datetime import datetime, timezone

_SEQ = itertools.count(1)

_REQ_ALPHABET = string.ascii_uppercase + string.digits


def next_seq():
    """Monotonic insertion counter used as the final deterministic tie-break."""
    return next(_SEQ)


def new_id():
    return str(uuid.uuid4())


def request_id():
    return "req_" + "".join(random.choice(_REQ_ALPHABET) for _ in range(20))


def rhu_div(numerator, denominator):
    """Exact integer half-up division.

    A value exactly halfway between two whole units rounds away from zero to the
    larger magnitude.  Implemented on integers so no float or Decimal context
    precision limit can ever perturb the result.
    """
    n = int(numerator)
    d = int(denominator)
    if d == 0:
        raise ZeroDivisionError("half-up division by zero")
    if d < 0:
        n, d = -n, -d
    if n >= 0:
        return (2 * n + d) // (2 * d)
    return -((-2 * n + d) // (2 * d))


def floor_div(numerator, denominator):
    """Truncation toward the lower whole unit (floor)."""
    n = int(numerator)
    d = int(denominator)
    if d == 0:
        raise ZeroDivisionError("floor division by zero")
    if d < 0:
        n, d = -n, -d
    return n // d


def utcnow():
    return datetime.now(timezone.utc)


def fmt_dt(value):
    """ISO 8601 UTC with exactly three fractional digits and a trailing Z."""
    if value is None:
        return None
    dt = value.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year,
        dt.month,
        dt.day,
        dt.hour,
        dt.minute,
        dt.second,
        dt.microsecond // 1000,
    )


def parse_dt(value):
    """Parse an ISO 8601 instant into an aware UTC datetime, or None if invalid."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def whole_days(earlier, later):
    """Whole elapsed days from `earlier` to `later` (floor of the day difference)."""
    return int((later - earlier).total_seconds() // 86400)
