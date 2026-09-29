"""In-memory data store and the logical laboratory clock (PRD section 2.5).

Nothing is seeded here: every dict below starts empty on every boot and tests
build all state through the declared endpoints.
"""
import uuid
from datetime import datetime

from util import UTC

CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, 0, tzinfo=UTC)

TABLES = (
    "analysts",
    "methods",
    "cases",
    "evidence_items",
    "examination_requests",
    "assignments",
    "review_records",
    "proficiency_tests",
    "vendors",
    "vendor_engagements",
    "nonconformances",
    "court_events",
)


class Store(object):
    def __init__(self):
        self.clock = CLOCK_EPOCH
        self._seq = 0
        for table in TABLES:
            setattr(self, table, {})

    # -- clock ------------------------------------------------------------
    def now(self):
        """The logical clock. The server never reads wall-clock time here."""
        return self.clock

    def set_clock(self, moment):
        self.clock = moment

    # -- identity ---------------------------------------------------------
    def next_seq(self):
        self._seq += 1
        return self._seq

    def new_id(self):
        return str(uuid.uuid4())


db = Store()


def new_row(with_audit=True):
    """A fresh row carrying the system-sourced identity and audit stamps."""
    row = {
        "id": db.new_id(),
        "_seq": db.next_seq(),
        "created_at": db.now(),
    }
    if with_audit:
        row["updated_at"] = db.now()
        row["version"] = 1
    return row


def touch(row):
    """Record a mutation: refresh updated_at and increment version by one."""
    row["updated_at"] = db.now()
    row["version"] = row.get("version", 1) + 1
    return row


def by_created(rows):
    """created_at ascending, stable on insertion sequence."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
