"""In-memory store, id minting, audit timestamps and the logical clock.

The store starts completely empty on every boot.  Nothing is ever seeded:
every row is created by a client through the declared endpoints.
"""

import uuid
from datetime import datetime, timedelta, timezone

# PRD 2.5: the logical clock starts at this fixed instant at server start and
# must never fall back to real wall-clock time.
LOGICAL_CLOCK_DEFAULT = "2026-08-01T00:00:00.000Z"

DT_OUT = "%Y-%m-%dT%H:%M:%S"


def _fmt(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD 2.2 / 2.4)."""
    dt = dt.astimezone(timezone.utc)
    return "%s.%03dZ" % (dt.strftime(DT_OUT), dt.microsecond // 1000)


def parse_dt(value):
    """Parse an ISO 8601 instant.  Returns None when unparseable."""
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    if raw.endswith("z") or raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def norm_dt(value):
    """Canonicalise a client-supplied instant to the response format."""
    dt = parse_dt(value)
    return None if dt is None else _fmt(dt)


def add_days(iso_value, days):
    dt = parse_dt(iso_value)
    if dt is None:
        return None
    return _fmt(dt + timedelta(days=days))


def day_span(start_iso, end_iso):
    """Whole days from start (inclusive) to end (exclusive)."""
    a, b = parse_dt(start_iso), parse_dt(end_iso)
    if a is None or b is None:
        return 0
    return (b - a).days


class Store:
    def __init__(self):
        self.programs = {}
        self.award_tiers = {}
        self.qualifiers = {}
        self.destinations = {}
        self.supplier_contracts = {}
        self.deposit_milestones = {}
        self.registrations = {}
        self.onsite_activities = {}
        self.activity_signups = {}
        self.tax_award_reports = {}
        self.logical_clock = LOGICAL_CLOCK_DEFAULT
        self._seq = 0

    # ------------------------------------------------------------------ util
    def next_seq(self):
        self._seq += 1
        return self._seq

    def now(self):
        """Audit clock (created_at / updated_at) - independent of the logical clock."""
        return _fmt(datetime.now(timezone.utc))

    def logical_now(self):
        return self.logical_clock

    def new_id(self):
        return str(uuid.uuid4())

    # --------------------------------------------------------------- helpers
    def stamp_new(self, row, versioned=True):
        row["id"] = self.new_id()
        row["created_at"] = self.now()
        if versioned:
            row["updated_at"] = row["created_at"]
            row["version"] = 1
        row["_seq"] = self.next_seq()
        return row

    def touch(self, row):
        """A named mutation: refresh updated_at and advance version by one."""
        row["updated_at"] = self.now()
        row["version"] = row.get("version", 0) + 1
        return row

    def ordered(self, table):
        """Rows sorted by created_at ascending (PRD 2.3), insertion-stable."""
        return sorted(table.values(), key=lambda r: (r["created_at"], r["_seq"]))


# Single process-wide store.  Empty at import time and never seeded.
db = Store()
