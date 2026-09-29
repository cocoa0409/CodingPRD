"""In-memory store.

Nothing is ever seeded here: every collection starts empty on every boot and
tests build all state through the declared endpoints.
"""

from datetime import datetime, timezone

from util import fmt_dt, utcnow

# PRD section 2.6: the logical clock reads exactly this instant at startup and
# must never fall back to real wall-clock time.
CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

COLLECTIONS = (
    "landowners",
    "parcels",
    "setback_rules",
    "consents",
    "curative_items",
    "options",
    "payments",
    "corridors",
    "crossings",
    "bookings",
    "leases",
    "invoices",
)


class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.clock = CLOCK_EPOCH
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def now():
    """Current logical clock value (business instants only)."""
    return db.clock


def sort_key(row):
    """Collections are ordered by created_at ascending, never by id."""
    return (row["created_at"], row["_seq"])


def ordered(rows):
    return sorted(rows, key=sort_key)


def all_of(collection):
    return ordered(getattr(db, collection).values())


def insert(collection, row, common_fields=True):
    """Insert a row, minting id / created_at / updated_at / version."""
    from util import new_id

    stamp = utcnow()
    row["id"] = new_id()
    row["_seq"] = db.next_seq()
    row["created_at"] = stamp
    if common_fields:
        row["updated_at"] = stamp
        row["version"] = 1
    getattr(db, collection)[row["id"]] = row
    return row


def touch(row):
    """Refresh updated_at and increment version by exactly 1."""
    row["updated_at"] = utcnow()
    row["version"] = int(row.get("version", 0)) + 1
    return row


def iso(dt):
    return fmt_dt(dt)
