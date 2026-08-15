"""Server logical clock (PRD §2.13). Starts at exactly 2026-08-01T00:00:00Z
and only moves when a SafetyOfficer sets it via /_clock/set_current_utc."""

from datetime import datetime, timezone

_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_current = _DEFAULT


def now():
    return _current


def set_current(dt):
    global _current
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    _current = dt.astimezone(timezone.utc)
    return _current
