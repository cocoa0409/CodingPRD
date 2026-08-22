"""The facility's logical clock (PRD section 2.4).

Startup value is exactly 2026-08-01T00:00:00Z.  The server never falls back to
real wall-clock time; every timestamp it stamps and every deadline comparison
it makes reads this clock.
"""
from datetime import datetime, timezone

STARTUP_INSTANT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_now = STARTUP_INSTANT


def now():
    return _now


def set_now(dt):
    global _now
    _now = dt


def fmt(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def parse_iso(value):
    """Parse an ISO 8601 instant.  Returns None when the value is unusable."""
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
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def truncate_ms(dt):
    """Millisecond resolution, used by the created_at orderings of PRD 2.5."""
    if dt is None:
        return None
    return dt.replace(microsecond=(dt.microsecond // 1000) * 1000)


def truncate_s(dt):
    """Second resolution, used by the scheduling overlap tests of PRD 2.5."""
    if dt is None:
        return None
    return dt.replace(microsecond=0)
