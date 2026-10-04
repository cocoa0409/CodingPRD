"""Logical clock. Before any set, reads exactly 2026-09-01T00:00:00Z.
Never falls back to wall-clock time."""
from datetime import datetime, timezone

_DEFAULT = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)
_current = _DEFAULT


def now():
    return _current


def set_now(dt):
    global _current
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    _current = dt.astimezone(timezone.utc)
    return _current


def reset():
    global _current
    _current = _DEFAULT
