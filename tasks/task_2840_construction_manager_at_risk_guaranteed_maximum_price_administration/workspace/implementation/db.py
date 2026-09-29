"""In-memory data store.  Empty on every boot; no seeding of any kind."""
import uuid

import clock

STORES = (
    "projects",
    "estimates",
    "proposals",
    "qualification_items",
    "work_packages",
    "bids",
    "subcontracts",
    "change_events",
    "draws",
    "cost_reports",
)


class Store(object):
    def __init__(self):
        for name in STORES:
            setattr(self, name, {})
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def new_id():
    return str(uuid.uuid4())


def new_record(fields):
    stamp = clock.real_now()
    record = {
        "id": new_id(),
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
        "_seq": db.next_seq(),
    }
    record.update(fields)
    return record


def touch(record):
    """Register a mutation: bump the concurrency counter and the update stamp."""
    record["version"] = record["version"] + 1
    record["updated_at"] = clock.real_now()
    return record


def sorted_rows(rows):
    """Default sort: creation timestamp ascending (insertion order breaks ties)."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def all_rows(collection):
    return sorted_rows(list(collection.values()))
