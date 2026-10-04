"""Logical clock (PRD §2.4).

Startup default is exactly 2026-09-01T00:00:00Z; never falls back to
wall-clock time. Advanced only via POST /_clock/set_current_utc.
"""

import threading
from datetime import datetime, timezone

_LOCK = threading.Lock()

# Fixed startup default: 2026-09-01T00:00:00Z.
_current = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)


def now():
    """Return the current logical-clock instant (timezone-aware UTC)."""
    with _LOCK:
        return _current


def set_current(dt):
    """Advance/set the logical clock to the given aware datetime (UTC)."""
    global _current
    with _LOCK:
        _current = dt.astimezone(timezone.utc)


def iso(dt):
    """Serialize a datetime as ISO 8601 UTC with three fractional digits.

    Format per PRD §2.5: e.g. 2026-09-01T00:00:00.000Z
    """
    dt = dt.astimezone(timezone.utc)
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ms:03d}Z"
