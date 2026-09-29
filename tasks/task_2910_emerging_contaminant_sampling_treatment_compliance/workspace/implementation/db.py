"""In-memory data store.  Starts completely empty on every boot: nothing here
seeds, preloads or hardcodes any entity.
"""

import itertools
import uuid
from datetime import datetime, timezone

COLLECTIONS = (
    "contaminants",
    "laboratories",
    "entry_points",
    "samples",
    "lab_results",
    "determinations",
    "notifications",
    "evaluations",
    "pilots",
    "manifests",
    "projects",
    "applications",
    "claims",
)

DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, 0, tzinfo=timezone.utc)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.clock = DEFAULT_CLOCK
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)


store = Store()


def now():
    """The logical clock: the instant every request reads."""
    return store.clock


def new_id():
    return str(uuid.uuid4())


def insert(collection, row):
    stamp = now()
    row["id"] = new_id()
    row["created_at"] = stamp
    row["updated_at"] = stamp
    row["version"] = 1
    row["_seq"] = store.next_seq()
    getattr(store, collection)[row["id"]] = row
    return row


def touch(row):
    row["updated_at"] = now()
    row["version"] = row["version"] + 1
    return row


def public(row):
    return dict((k, v) for k, v in row.items() if not k.startswith("_"))


def sorted_rows(collection):
    rows = list(getattr(store, collection).values())
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return rows
