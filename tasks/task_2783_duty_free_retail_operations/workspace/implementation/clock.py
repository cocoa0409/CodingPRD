"""The server-held logical clock (PRD section 2.4).

Nothing in this service reads the host wall clock.  The clock starts at exactly
2026-08-01T00:00:00Z on every boot and only moves when a TerminalAdmin drives it
through POST /_clock/set_current_utc.
"""
from datetime import datetime, timedelta, timezone

START = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_current = START


def now():
    """Current logical instant as an aware UTC datetime (millisecond resolution)."""
    return _current


def set_now(value):
    global _current
    _current = value


def reset():
    global _current
    _current = START


def fmt(value):
    """ISO 8601 UTC with exactly three fractional digits."""
    if value is None:
        return None
    value = value.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        value.year, value.month, value.day,
        value.hour, value.minute, value.second,
        value.microsecond // 1000,
    )


def now_iso():
    return fmt(_current)


def parse(text):
    """Parse an ISO 8601 timestamp into an aware UTC datetime truncated to ms.

    Raises ValueError when the value is not a usable timestamp.
    """
    if not isinstance(text, str):
        raise ValueError("timestamp must be a string")
    raw = text.strip()
    if not raw:
        raise ValueError("empty timestamp")
    candidate = raw
    if candidate.endswith("Z") or candidate.endswith("z"):
        candidate = candidate[:-1] + "+00:00"
    parsed = datetime.fromisoformat(candidate)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    parsed = parsed.astimezone(timezone.utc)
    return parsed.replace(microsecond=(parsed.microsecond // 1000) * 1000)


def parse_stored(text):
    """Parse a timestamp this server previously stored (always well formed)."""
    return parse(text)


def plus_hours(value, hours):
    return value + timedelta(hours=hours)


def plus_days(value, days):
    return value + timedelta(days=days)
