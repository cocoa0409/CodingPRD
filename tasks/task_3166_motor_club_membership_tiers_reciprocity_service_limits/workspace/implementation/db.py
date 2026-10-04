"""In-memory data store and logical clock for the Motor Club Reciprocity API.

The store starts completely empty on every boot -- no seeding of any entity.
The logical clock starts at exactly 2026-09-01T00:00:00Z per PRD section 2.4
and never falls back to wall-clock time.
"""

import uuid
from datetime import datetime, timezone

DEFAULT_CLOCK_ISO = "2026-09-01T00:00:00Z"


def parse_iso(value):
    """Parse an ISO-8601 timestamp (accepting trailing Z) into an aware datetime."""
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    s = str(value).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_ts(dt):
    """Format an aware datetime as ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def new_id():
    return str(uuid.uuid4())


class LogicalClock:
    """Monotonic logical clock shared by the whole application."""

    def __init__(self):
        self._now = parse_iso(DEFAULT_CLOCK_ISO)

    def now(self):
        return self._now

    def set(self, dt):
        self._now = dt
        return self._now


CLOCK = LogicalClock()


class Store:
    def __init__(self):
        self.clubs = {}
        self.tiers = {}
        self.memberships = {}
        self.household_members = {}
        self.membership_events = {}
        self.providers = {}
        self.truck_part_stock = {}
        self.service_calls = {}
        self.dispatches = {}
        self.settlement_periods = {}
        self.settlement_lines = {}
        self.ancillary_products = {}
        self.ancillary_sales = {}


DB = Store()

# Monotonic insertion counter. The logical clock produces identical
# timestamps for resources created within a single logical instant, so a
# secondary sequence number preserves creation order for sort stability
# (e.g. an audit trail whose entries are "appended" over time).
SEQ = [0]


def stamp_new(obj, with_version=True):
    now = CLOCK.now()
    obj["created_at"] = fmt_ts(now)
    if with_version:
        obj["updated_at"] = fmt_ts(now)
        obj["version"] = 1
    SEQ[0] += 1
    obj["_seq"] = SEQ[0]
    return obj


def touch(obj):
    obj["updated_at"] = fmt_ts(CLOCK.now())
    if "version" in obj:
        obj["version"] += 1
    return obj
