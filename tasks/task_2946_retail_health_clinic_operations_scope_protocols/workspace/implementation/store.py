"""In-memory data store and the logical clock.

Every byte of state lives in this process.  A fresh boot starts completely
empty: no entity is ever seeded, preloaded or hardcoded here.
"""

import itertools
import uuid
from datetime import datetime, timezone

# The logical clock's value before any client moves it (PRD section 2.4).
CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.state_rules = {}
        self.protocols = {}
        self.clinics = {}
        self.physicians = {}
        self.clinicians = {}
        self.patients = {}
        self.assignments = {}
        self.queue_entries = {}
        self.visits = {}
        self.assessments = {}
        self.prescriptions = {}
        self.chart_reviews = {}
        self.visit_summaries = {}
        self._seq = itertools.count(1)
        self.clock = CLOCK_EPOCH

    def next_seq(self):
        return next(self._seq)


db = Store()


def now():
    """The logical clock.  Business logic never reads wall-clock time."""
    return db.clock


def new_row():
    stamp = db.clock
    return {
        "id": str(uuid.uuid4()),
        "_seq": db.next_seq(),
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
    }


def touch(row):
    """Record a mutation: version += 1 and updated_at refreshed."""
    row["version"] = row["version"] + 1
    row["updated_at"] = db.clock
    return row


def sort_key(row):
    return (row["created_at"], row["_seq"])


def ordered(rows):
    """Default collection ordering: created_at ascending, stable by insertion."""
    return sorted(rows, key=sort_key)
