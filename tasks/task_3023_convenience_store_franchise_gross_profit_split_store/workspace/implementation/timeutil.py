"""Logical clock and timestamp helpers (PRD §2.9, §2.5)."""

from datetime import datetime, timezone

DEFAULT_CLOCK = "2026-09-01T00:00:00Z"


def parse_utc(value):
    """Parse an ISO 8601 UTC instant; returns an aware datetime or None."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            return None
    else:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def required_utc(value):
    dt = parse_utc(value)
    if dt is None:
        from errors import fail
        fail("ERR_INVALID_REQUEST")
    return dt


def fmt(dt):
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def fmt_naive_style(dt):
    """Render a datetime so the wall-clock part is what the clock was set to."""
    return fmt(dt)


def overlaps(start_a, end_a, start_b, end_b):
    """Half-open [start, end) overlap test."""
    return start_a < end_b and start_b < end_a


def iso_utc(value):
    """Accept either a datetime or a raw string and normalise to our format."""
    return fmt(required_utc(value))