"""In-memory data store, logical clock, and entity lifecycle helpers.

All state is in-memory only. The store starts completely empty on every boot;
no entity is ever seeded, preloaded, or registered at startup.
"""

import uuid
from datetime import datetime, timezone, date as date_type


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

class LogicalClock:
    """Server-side logical clock. Startup default is exactly
    2026-09-01T00:00:00Z; never falls back to wall-clock time."""

    def __init__(self):
        self._now = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)

    def now(self):
        return self._now

    def today(self):
        return self._now.date()

    def set(self, dt):
        self._now = dt


CLOCK = LogicalClock()


def fmt_ts(dt):
    """ISO 8601 UTC timestamp with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now_ts():
    return fmt_ts(CLOCK.now())


def parse_datetime(s):
    """Parse an ISO 8601 timestamp (accepts trailing Z or offset)."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(s):
    """Parse an ISO date (YYYY-MM-DD); also tolerates full ISO datetimes by
    taking their UTC date portion."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    t = s.strip()
    try:
        return date_type.fromisoformat(t)
    except ValueError:
        pass
    return parse_datetime(t).date()


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------

class Store:
    def __init__(self):
        self.terms = {}
        self.programs = {}
        self.state_auths = {}
        self.staff = {}
        self.applicants = {}
        self.applications = {}
        self.tces = {}
        self.enrollments = {}
        self.sections = {}
        self.packages = {}
        self.alerts = {}
        self.outreaches = {}
        self._seq = 0

    def next_seq(self):
        """Monotonic creation sequence; refines created_at tie-breaks."""
        self._seq += 1
        return self._seq


STORE = Store()


def new_entity(fields):
    """Create a resource dict with the standard system-managed fields."""
    e = dict(fields)
    e["id"] = str(uuid.uuid4())
    ts = now_ts()
    e["created_at"] = ts
    e["updated_at"] = ts
    e["version"] = 1
    e["_seq"] = STORE.next_seq()
    return e


def bump(e):
    """Every mutation of a resource increments its version by exactly 1 and
    refreshes updated_at."""
    e["version"] += 1
    e["updated_at"] = now_ts()
