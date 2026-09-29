"""In-memory data store and the logical clock.

Storage is process-local Python dicts only. Nothing is seeded, preloaded or
hardcoded: every collection starts empty on every boot.
"""

import itertools
import uuid
from datetime import datetime, timezone

# The logical clock's startup value, per PRD 2.5. The service never reads
# wall-clock time.
CLOCK_START = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

COLLECTIONS = (
    "terminals",
    "drivers",
    "crashes",
    "driver_statements",
    "evidence_items",
    "review_cases",
    "committee_votes",
    "claims",
    "policy_layers",
    "demands",
    "negotiation_rounds",
    "disciplinary_actions",
    "subrogation_demands",
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.now = CLOCK_START
        for name in COLLECTIONS:
            setattr(self, name, {})
        self._counter = itertools.count(1)

    def next_seq(self):
        return next(self._counter)


db = Store()


def new_id():
    return str(uuid.uuid4())


def rows(collection):
    """All rows of a collection in insertion order."""
    return list(collection.values())


def ordered(collection_rows):
    """Default list ordering: created_at ascending, insertion order as tiebreak."""
    return sorted(collection_rows, key=lambda r: (r["created_at"], r["_seq"]))


def base_row(with_version=True):
    row = {"id": new_id(), "created_at": db.now, "_seq": db.next_seq()}
    if with_version:
        row["updated_at"] = db.now
        row["version"] = 1
    return row


def touch(row):
    """Record a mutation: refresh updated_at and bump version by exactly 1."""
    row["updated_at"] = db.now
    row["version"] = row["version"] + 1
