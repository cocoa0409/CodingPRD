"""In-memory data store and the server's logical clock.

The store starts completely empty on every boot; no entity is ever seeded here.
"""
import itertools
import uuid
from datetime import datetime, timezone

from util import fmt_ts

CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

COLLECTIONS = (
    "employees", "claims", "providers", "restriction_sets", "supervisors",
    "training_records", "jobs", "placements", "directives",
    "progression_reviews", "audits", "wage_entries", "reinjury_reports",
    "case_reviews", "votes",
)


class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.clock = CLOCK_DEFAULT
        self._seq = itertools.count(1)

    def seq(self):
        return next(self._seq)

    def now_iso(self):
        return fmt_ts(self.clock)

    def today(self):
        return self.clock.date()

    def new_id(self):
        return str(uuid.uuid4())


db = Store()


def stamp_new(row, versioned=True):
    """Attach id / created_at (/ updated_at / version) to a brand-new row."""
    row["id"] = db.new_id()
    row["_seq"] = db.seq()
    row["created_at"] = db.now_iso()
    if versioned:
        row["updated_at"] = row["created_at"]
        row["version"] = 1
    return row


def touch(row):
    """Record a mutation: refresh updated_at and raise version by exactly 1."""
    if "version" in row:
        row["version"] = row["version"] + 1
        row["updated_at"] = db.now_iso()
    return row


def ordered(rows):
    """Default list order: created_at ASC, ties broken by insertion order."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
