"""In-memory data store for the water-heater manufacturing service.

The store is ALWAYS empty at boot: no seeding, no preloading, no persistence.
Every entity is created through the declared API surface.
"""

import itertools
import re
import threading
import uuid
from datetime import datetime, timezone

# PRD 2.5: the logical clock starts at exactly this instant on every boot.
CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_TS_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt](\d{2}):(\d{2}):(\d{2})(\.\d{1,9})?[Zz]$"
)


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.reset()

    def reset(self):
        # Logical UTC clock -- never the host wall clock.
        self.clock = CLOCK_DEFAULT
        self.suppliers = {}
        self.component_lots = {}
        self.furnaces = {}
        self.batches = {}
        self.tank_lots = {}
        self.inspections = {}
        self.models = {}
        self.test_cells = {}
        self.tests = {}
        self.certifications = {}
        self.units = {}
        self.claims = {}
        self.campaigns = {}
        self.notices = {}
        self._counter = itertools.count(1)

    def next_seq(self):
        return next(self._counter)

    def now(self):
        return self.clock


db = Store()


def new_id():
    return str(uuid.uuid4())


def fmt_ts(dt):
    """ISO 8601 UTC with exactly three fractional-second digits and a Z suffix."""
    if dt is None:
        return None
    d = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        d.year,
        d.month,
        d.day,
        d.hour,
        d.minute,
        d.second,
        d.microsecond // 1000,
    )


def parse_ts(value):
    """Parse an ISO 8601 UTC instant with a trailing Z. Returns None when invalid."""
    if not isinstance(value, str):
        return None
    m = _TS_RE.match(value.strip())
    if not m:
        return None
    frac = m.group(7) or ".0"
    micro = int(round(float(frac) * 1000000))
    if micro >= 1000000:
        micro = 999999
    try:
        return datetime(
            int(m.group(1)),
            int(m.group(2)),
            int(m.group(3)),
            int(m.group(4)),
            int(m.group(5)),
            int(m.group(6)),
            micro,
            tzinfo=timezone.utc,
        )
    except ValueError:
        return None


def period_of(dt):
    """Production period key YYYY-MM derived from a logical-clock instant."""
    d = dt.astimezone(timezone.utc)
    return "%04d-%02d" % (d.year, d.month)


def period_compact(period):
    return period.replace("-", "")


def make_row(fields, mutable=True):
    """Create a new entity row carrying the system-managed common fields."""
    now = db.now()
    row = {
        "id": new_id(),
        "created_at": now,
        "_seq": db.next_seq(),
    }
    if mutable:
        row["updated_at"] = now
        row["version"] = 1
    row.update(fields)
    return row


def touch(row):
    """Record an accepted mutation: bump version by exactly 1 and stamp updated_at."""
    row["version"] = row.get("version", 1) + 1
    row["updated_at"] = db.now()
    return row


def ordered(rows):
    """created_at ascending, with insertion order as a stable tiebreaker."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
