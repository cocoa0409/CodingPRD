"""Server-maintained logical clock (PRD section 2.4).

All time-dependent behavior reads this clock, never the wall clock. Startup
default is exactly 2026-09-01T00:00:00Z. The clock endpoint lives OUTSIDE the
/gfoa prefix: POST /_clock/set_current_utc.
"""

from datetime import datetime, timezone

CLOCK_START_ISO = "2026-09-01T00:00:00Z"


def parse_iso(value):
    """Parse an ISO 8601 string into an aware UTC datetime. Raises ValueError."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    v = value.strip()
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    dt = datetime.fromisoformat(v)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_iso(dt):
    """Canonical ISO 8601 UTC with exactly three fractional digits (PRD 2.5)."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


class LogicalClock:
    def __init__(self):
        self._dt = parse_iso(CLOCK_START_ISO)
        self._raw = CLOCK_START_ISO

    def now(self):
        return self._dt

    def now_iso(self):
        return fmt_iso(self._dt)

    def set(self, raw):
        """Advance the clock. Returns the raw string as supplied (echoed back)."""
        dt = parse_iso(raw)  # raises ValueError on malformed input
        self._dt = dt
        self._raw = raw
        return raw

    def raw(self):
        return self._raw


clock = LogicalClock()
