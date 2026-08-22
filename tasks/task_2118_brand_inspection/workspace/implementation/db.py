"""In-memory data store.

Every collection is a plain dict keyed by row id. The store starts completely
empty on every boot: no entity is ever seeded, preloaded or hardcoded here.
All state is produced by API calls.
"""

from datetime import datetime

from util import UTC, new_id

# The board's logical clock reads exactly this instant before any client sets it.
INITIAL_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)


class Store:
    def __init__(self):
        self.owners = {}
        self.territories = {}
        self.inspectors = {}
        self.applications = {}
        self.registrations = {}
        self.claims = {}
        self.orders = {}
        self.lots = {}
        self.bills = {}
        self.estrays = {}
        self.investigations = {}
        self.remittances = {}
        self.clock = INITIAL_CLOCK
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def now():
    """The logical clock. Nothing in this system reads the host's wall clock."""
    return db.clock


def base_row(common_fields=True):
    row = {"id": new_id(), "created_at": db.clock}
    if common_fields:
        row["updated_at"] = db.clock
        row["version"] = 1
    return row


def insert(collection, row):
    row["_seq"] = db.next_seq()
    collection[row["id"]] = row
    return row


def touch(row):
    """A mutation of a row: refresh updated_at and advance the version token."""
    row["updated_at"] = db.clock
    row["version"] = row.get("version", 1) + 1
    return row


def _order_key(row):
    # The logical clock is frozen between explicit moves, so created_at alone is
    # not a total order. Insertion sequence is the deterministic tie-break.
    return (row["created_at"], row["_seq"])


def by_created_at(rows):
    return sorted(rows, key=_order_key)


def public(row):
    if row is None:
        return None
    from util import iso
    out = {}
    for key, value in row.items():
        if key.startswith("_"):
            continue
        out[key] = iso(value) if isinstance(value, datetime) else value
    return out
