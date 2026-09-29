"""The server-held logical clock (PRD 2.4).

Before any operator sets it, the logical clock reads exactly 2026-08-01T00:00:00Z
and it never falls back to real time.
"""

from datetime import datetime, timezone

DEFAULT_INSTANT = datetime(2026, 8, 1, 0, 0, 0, 0, tzinfo=timezone.utc)


class LogicalClock(object):
    def __init__(self):
        self._now = DEFAULT_INSTANT

    def now(self):
        return self._now

    def set(self, instant):
        previous = self._now
        self._now = instant
        return previous

    def reset(self):
        self._now = DEFAULT_INSTANT


clock = LogicalClock()


def now():
    return clock.now()


def iso(dt):
    """Render an aware datetime as ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)
    millis = dt.microsecond // 1000
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, millis,
    )
