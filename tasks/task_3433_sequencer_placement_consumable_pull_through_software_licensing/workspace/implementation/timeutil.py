"""ISO-8601 parsing/formatting helpers.

All timestamps serialize as ISO 8601 UTC with three fractional digits and a
trailing Z, e.g. 2026-09-01T00:00:00.000Z.
"""

from datetime import datetime, timezone


def parse_dt(value):
    """Parse an ISO-8601 string into an aware UTC datetime; None on failure."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso(dt):
    """Serialize an aware datetime as ISO 8601 UTC with 3 fractional digits."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_date_to_dt(value):
    """Parse a date ('YYYY-MM-DD') or datetime string into a UTC datetime at
    midnight of that date; None on failure."""
    if not isinstance(value, str):
        return None
    dt = parse_dt(value)
    if dt is None:
        return None
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


def date_str(dt):
    """Serialize a datetime as a plain YYYY-MM-DD date string."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%d")
