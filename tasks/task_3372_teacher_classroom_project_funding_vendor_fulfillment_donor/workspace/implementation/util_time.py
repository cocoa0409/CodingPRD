"""Timestamp helpers: ISO-8601 UTC formatting and parsing.

All business-logic timestamps are compared at second precision.
"""
from datetime import datetime, timezone


def iso_ms(dt):
    """Format a datetime as ISO 8601 UTC with three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "{:03d}Z".format(dt.microsecond // 1000)


def iso_sec(dt):
    """Format a datetime as ISO 8601 UTC at whole-second precision (clock echo)."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_dt(value):
    """Parse an ISO 8601 string (Z or offset) into an aware UTC datetime
    truncated to second precision. Returns None when unparseable."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(microsecond=0)
