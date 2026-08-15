"""Logical clock. Starts at 2026-08-01T00:00:00Z; never falls back to wall clock."""

from datetime import datetime, timezone

DEFAULT_NOW = "2026-08-01T00:00:00Z"

_current = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


def now() -> datetime:
    return _current


def set_now(dt: datetime) -> datetime:
    global _current
    _current = dt
    return _current
