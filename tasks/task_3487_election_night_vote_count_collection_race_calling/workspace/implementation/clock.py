"""Logical clock (PRD §2.4). Starts at exactly 2026-09-01T00:00:00Z; never
reads wall-clock time; moved only via POST /_clock/set_current_utc."""
from datetime import datetime, timezone


class LogicalClock:
    def __init__(self):
        self._now = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)

    def now(self):
        return self._now

    def set(self, dt):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        self._now = dt.astimezone(timezone.utc)


CLOCK = LogicalClock()


def now():
    return CLOCK.now()
