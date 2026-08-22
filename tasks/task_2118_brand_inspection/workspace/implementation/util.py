"""Shared low-level helpers: identifiers, ISO-8601 handling, rounding."""

import random
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

UTC = timezone.utc

_REQ_ALPHABET = string.ascii_uppercase + string.digits


def new_id():
    """Opaque UUID identifier; no type prefix, never supplied by clients."""
    return str(uuid.uuid4())


def new_request_id():
    return "req_" + "".join(random.choice(_REQ_ALPHABET) for _ in range(20))


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits, e.g. 2026-08-01T00:00:00.000Z."""
    if dt is None:
        return None
    if not isinstance(dt, datetime):
        return dt
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    dt = dt.astimezone(UTC)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, dt.microsecond // 1000,
    )


def parse_dt(value):
    """Parse a client-supplied instant. Returns None when the value is unusable."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
            try:
                parsed = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
        else:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def days(n):
    return timedelta(days=n)


def minutes(n):
    return timedelta(minutes=n)


def round_half_up(value):
    """Half-up rounding to whole cents. Never uses float arithmetic."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def whole_days_between(start, end):
    """Whole elapsed days from start to end; any partial day is discarded (floor).

    timedelta normalises so that ``seconds`` and ``microseconds`` are always
    non-negative, therefore integer floor division reproduces mathematical floor.
    """
    delta = end - start
    return (delta.days * 86400 + delta.seconds) // 86400
