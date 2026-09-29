"""Shared low-level helpers: identifiers, instant parsing/formatting, integer maths."""

import random
import re
import string
import uuid
from datetime import datetime, timezone

# RFC-3339 UTC instant, must terminate with a literal Z (PRD 2.11 rank 7).
_INSTANT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(\.\d+)?[Zz]$")

_ALNUM = string.ascii_uppercase + string.digits


def new_id():
    """Server-minted id: a UUID string with no type prefix (PRD 2.4)."""
    return str(uuid.uuid4())


def new_request_id():
    """Request correlation id, prefixed 'req_' (PRD 2.2)."""
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def parse_instant(value):
    """Parse an RFC-3339 UTC instant ending in Z. Returns None when invalid."""
    if not isinstance(value, str):
        return None
    if not _INSTANT_RE.match(value):
        return None
    body = value[:-1]
    try:
        if "." in body:
            head, frac = body.split(".", 1)
            frac = (frac + "000000")[:6]
            dt = datetime.strptime(head, "%Y-%m-%dT%H:%M:%S")
            dt = dt.replace(microsecond=int(frac))
        else:
            dt = datetime.strptime(body, "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return None
    return dt.replace(tzinfo=timezone.utc)


def format_instant(dt):
    """ISO 8601 UTC with exactly three fractional-second digits (PRD 2.4)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def real_now():
    return datetime.now(timezone.utc)


def day_diff(start, end):
    """Whole days between two instants' calendar dates: (end.date - start.date)."""
    return (end.date() - start.date()).days


def ifloor(numerator, denominator):
    """Integer division discarding the remainder (rounds down)."""
    if denominator == 0:
        return 0
    return numerator // denominator


def iceil(numerator, denominator):
    """Integer division rounding up to the next whole unit."""
    if denominator == 0:
        return 0
    return -((-numerator) // denominator)


def is_int(value):
    """A JSON number with no fractional part. JSON booleans are not integers."""
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    if isinstance(value, float):
        return value.is_integer()
    return False


def as_int(value):
    return int(value)
