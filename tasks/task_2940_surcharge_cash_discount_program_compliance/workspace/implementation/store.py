"""In-memory data store and the server's logical clock.

Storage is process-local only: plain dicts keyed by uuid.  A fresh process
therefore starts completely empty -- nothing is seeded, preloaded or
hardcoded here or anywhere else in the implementation.
"""

import itertools
import uuid
from datetime import datetime, timedelta, timezone

# The logical clock's startup default (PRD 2.5).
CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        self.jurisdictions = {}
        self.merchants = {}
        self.cost_documentations = {}
        self.programs = {}
        self.rate_rules = {}
        self.registrations = {}
        self.artifacts = {}
        self.terminals = {}
        self.transactions = {}
        self.complaint_cases = {}
        self.refunds = {}
        self.clock = CLOCK_DEFAULT
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)

    def now(self):
        return self.clock


db = Store()


def new_id():
    return str(uuid.uuid4())


def fmt_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits and a trailing Z."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, dt.microsecond // 1000,
    )


def add_days(dt, days):
    """Day arithmetic is exact multiples of 24 hours (PRD 2.5)."""
    return dt + timedelta(seconds=86400 * days)


def base_row(kind_common=True):
    """Fresh common fields: id / created_at / updated_at / version."""
    now = db.now()
    row = {
        "id": new_id(),
        "_seq": db.next_seq(),
        "created_at": now,
    }
    if kind_common:
        row["updated_at"] = now
        row["version"] = 1
    return row


def touch(row):
    """A mutation: version += 1 and updated_at refreshed to the logical clock."""
    row["version"] = row.get("version", 1) + 1
    row["updated_at"] = db.now()


def sort_rows(rows):
    """Default list ordering: created_at ascending (insertion order breaks ties)."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
