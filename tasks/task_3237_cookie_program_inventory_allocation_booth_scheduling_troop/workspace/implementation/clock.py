"""Logical clock. Startup default is exactly 2026-09-01T00:00:00Z; never
falls back to wall-clock time."""
from datetime import datetime, timezone

DEFAULT_CLOCK = "2026-09-01T00:00:00Z"


class LogicalClock:
    def __init__(self):
        self._current = self._parse(DEFAULT_CLOCK)

    @staticmethod
    def _parse(s):
        txt = str(s).strip()
        if txt.endswith("Z"):
            txt = txt[:-1] + "+00:00"
        dt = datetime.fromisoformat(txt)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    def now(self):
        return self._current

    def set(self, s):
        self._current = self._parse(s)

    def now_iso(self):
        return self._current.strftime("%Y-%m-%dT%H:%M:%S.") + \
            f"{self._current.microsecond // 1000:03d}Z"

    def now_iso_seconds(self):
        """Seconds-precision ISO8601 UTC, matching the PRD-pinned clock
        representation (e.g. 2026-09-01T00:00:00Z)."""
        return self._current.strftime("%Y-%m-%dT%H:%M:%SZ")


clock = LogicalClock()


def parse_dt(s):
    return LogicalClock._parse(s)


def now_iso():
    """Timestamp used in created_at/updated_at and meta. ISO8601 UTC with
    three fractional digits, from the logical clock."""
    return clock.now_iso()
