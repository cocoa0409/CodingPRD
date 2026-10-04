"""Server-side logical clock (PRD §2.4).

Starts at exactly 2026-09-01T00:00:00Z on every fresh boot and never falls
back to wall-clock time. Advanced only via POST /_clock/set_current_utc.
"""

from datetime import datetime, timezone

from constants import CLOCK_DEFAULT_ISO


def _parse_default():
    return datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)


# Module-level state; a fresh process always starts at the default.
assert CLOCK_DEFAULT_ISO == "2026-09-01T00:00:00Z"
_current = _parse_default()


def now():
    """Current logical-clock instant (timezone-aware UTC)."""
    return _current


def set_now(value):
    """Advance the logical clock to the supplied instant."""
    global _current
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    _current = value.astimezone(timezone.utc)
