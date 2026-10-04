"""In-memory data store and logical clock.

Storage is process-local dicts only. No SQLite, no file persistence, no /tmp
cache. Every boot starts with an empty store; the implementation encodes the
system, never the data.
"""

from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

# PRD §2.4: before any clock-setting call, the logical clock reads exactly
# 2026-09-01T00:00:00Z and never falls back to wall-clock time.
INITIAL_CLOCK_ISO = "2026-09-01T00:00:00Z"


def _parse_iso(value):
    """Parse an ISO8601 string into an aware UTC datetime."""
    if isinstance(value, str):
        v = value.strip()
        if v.endswith("Z"):
            v = v[:-1] + "+00:00"
        dt = datetime.fromisoformat(v)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    raise ValueError("not an ISO8601 string")


class LogicalClock:
    def __init__(self):
        self._now = _parse_iso(INITIAL_CLOCK_ISO)

    def now(self):
        return self._now

    def set(self, value):
        self._now = value


clock = LogicalClock()


def now():
    return clock.now()


def format_ts(dt):
    """ISO 8601 UTC with three fractional digits, e.g. 2026-09-01T00:00:00.000Z"""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % ms


def now_iso():
    return format_ts(now())


def parse_iso(value):
    return _parse_iso(value)


# ---------------------------------------------------------------------------
# Entity stores (dicts keyed by id) — start empty on every boot.
# ---------------------------------------------------------------------------

stations = {}
drivers = {}
screenings = {}
vehicles = {}
blocks = {}
offers = {}
assignments = {}
packages = {}
rating_events = {}
pay_statements = {}
appeals = {}
