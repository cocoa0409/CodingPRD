"""In-memory data store.  Empty on every boot -- nothing is ever seeded."""
import itertools
import uuid

import clock

COLLECTIONS = (
    "events",
    "benchmarks",
    "venues",
    "entries",
    "inspections",
    "rfps",
    "proposals",
    "evaluations",
    "counters",
    "contracts",
    "steps",
    "installments",
    "reports",
    "reviews",
)


class Store(object):
    def __init__(self):
        self._seq = itertools.count(1)
        for name in COLLECTIONS:
            setattr(self, name, {})

    def next_seq(self):
        return next(self._seq)


db = Store()


def new_id():
    return str(uuid.uuid4())


def base_row(versioned=True):
    """Common system fields (PRD section 2.4)."""
    stamp = clock.now()
    row = {"id": new_id(), "created_at": stamp, "_seq": db.next_seq()}
    if versioned:
        row["updated_at"] = stamp
        row["version"] = 1
    return row


def touch(row):
    """A mutation: refresh updated_at and advance version by exactly one."""
    if row is None:
        return
    if "version" in row:
        row["updated_at"] = clock.now()
        row["version"] = row["version"] + 1


def ordered(rows):
    """Default ordering: created_at ascending, insertion order breaking ties."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
