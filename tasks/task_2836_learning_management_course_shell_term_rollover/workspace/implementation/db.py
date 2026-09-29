"""In-memory data store.

The store is empty on every boot: no entity is seeded, preloaded or hardcoded.
Every record is created by a caller through a declared endpoint.

PRD 2.5: the logical clock reads exactly 2026-08-01T00:00:00Z on startup and
never falls back to real time.
"""

import itertools
import uuid

from flask import g

from util import EPOCH_DEFAULT, wall_now

COLLECTIONS = (
    "terms",
    "people",
    "shells",
    "enrollments",
    "batches",
    "merges",
    "items",
    "jobs",
    "tools",
    "reviews",
    "placements",
    "passbacks",
    "disputes",
    "windows",
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        # grade records keyed by (enrollment_id, content_item_id)
        self.grade_records = {}
        self.clock = EPOCH_DEFAULT
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)


db = Store()


def now():
    """The logical clock (PRD 2.5)."""
    return db.clock


def new_record(**fields):
    stamp = wall_now()
    record = {
        "id": str(uuid.uuid4()),
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
        "_seq": db.next_seq(),
    }
    record.update(fields)
    created = getattr(g, "_created_ids", None)
    if created is None:
        created = set()
        g._created_ids = created
    created.add(record["id"])
    return record


def new_immutable(**fields):
    """A ToolReview carries id and created_at only (PRD 2.4)."""
    record = {
        "id": str(uuid.uuid4()),
        "created_at": wall_now(),
        "_seq": db.next_seq(),
    }
    record.update(fields)
    created = getattr(g, "_created_ids", None)
    if created is None:
        created = set()
        g._created_ids = created
    created.add(record["id"])
    return record


def mark(record):
    """Flag a record as mutated by this request.  PRD 2.4/2.8: every mutated
    record has updated_at refreshed and version advanced once the request
    settles."""
    if record is None:
        return
    pending = getattr(g, "_dirty", None)
    if pending is None:
        pending = {}
        g._dirty = pending
    pending[id(record)] = record


def set_field(record, field, value):
    """Assign and flag as mutated only when the stored value actually moves."""
    if record.get(field) != value:
        record[field] = value
        mark(record)
        return True
    return False


def flush():
    """Settle mutation bookkeeping for every record this request touched."""
    pending = getattr(g, "_dirty", None)
    if not pending:
        return
    created = getattr(g, "_created_ids", set())
    stamp = wall_now()
    for record in list(pending.values()):
        if record.get("id") in created:
            continue
        if "version" in record:
            record["version"] = record["version"] + 1
        if "updated_at" in record:
            record["updated_at"] = stamp
    g._dirty = {}


def by_created(records):
    """Cascade ordering: created_at ascending, never identifier order
    (PRD 2.8).  The monotonic insertion sequence breaks exact ties."""
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
