"""The logical clock (PRD 2.4). The server never falls back to wall-clock time."""
from datetime import datetime, timezone

from util import fmt_ts

DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"


class LogicalClock:
    def __init__(self):
        self._dt = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

    def now(self) -> datetime:
        return self._dt

    def now_iso(self) -> str:
        return fmt_ts(self._dt)

    def today(self):
        return self._dt.date()

    def set(self, dt: datetime):
        self._dt = dt


CLOCK = LogicalClock()
