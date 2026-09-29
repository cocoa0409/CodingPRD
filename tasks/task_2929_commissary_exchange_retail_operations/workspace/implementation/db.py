"""In-memory data store, id minting, the record clock and the logical clock.

The store starts completely empty on every boot: nothing is seeded, preloaded
or hardcoded.  Every entity is created through the declared API surface.
"""

import datetime
import threading
import uuid

# The logical clock's startup value is exactly 2026-08-01T00:00:00Z (PRD 2.5).
LOGICAL_CLOCK_DEFAULT = datetime.datetime(2026, 8, 1, 0, 0, 0)

# One global lock serialises request handling so cascades stay atomic.
LOCK = threading.RLock()


class Database(object):
    def __init__(self):
        self.stores = {}
        self.patrons = {}
        self.delegations = {}
        self.products = {}
        self.assortments = {}
        self.sales = {}
        self.sale_lines = {}
        self.ledger = {}
        self.projects = {}
        self.programs = {}
        self.special_orders = {}
        self.logical_clock = LOGICAL_CLOCK_DEFAULT
        self._seq = 0
        self._last_instant = None

    def next_seq(self):
        self._seq += 1
        return self._seq

    def next_instant(self):
        """Monotone, millisecond-resolution wall-clock instant for created_at /
        updated_at.  Strictly increasing so every created_at ordering is total."""
        now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
        now = now.replace(microsecond=(now.microsecond // 1000) * 1000)
        if self._last_instant is not None and now <= self._last_instant:
            now = self._last_instant + datetime.timedelta(milliseconds=1)
        self._last_instant = now
        return now


db = Database()


def new_id():
    """A UUID string with no type prefix of any kind (PRD 2.4)."""
    return str(uuid.uuid4())


def clock_now():
    return db.logical_clock


def new_record(with_version=True):
    """Common fields for a freshly created record."""
    stamp = db.next_instant()
    record = {"id": new_id(), "created_at": stamp, "_seq": db.next_seq()}
    if with_version:
        record["updated_at"] = stamp
        record["version"] = 1
    return record


def touch(record):
    """Register a mutation: refresh updated_at and advance version by exactly 1."""
    record["updated_at"] = db.next_instant()
    record["version"] = record.get("version", 1) + 1
    return record


def sorted_records(collection):
    """Every list defaults to created_at ascending (PRD 2.3)."""
    return sorted(collection.values(), key=lambda r: (r["created_at"], r["_seq"]))
