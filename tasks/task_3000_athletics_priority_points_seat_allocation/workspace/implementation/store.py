"""Purely in-memory data store.

Every collection is a plain dict keyed by the row's UUID string.  Nothing is
seeded, preloaded or persisted: a fresh process starts with every collection
empty, and no state survives a restart.
"""
import itertools
import uuid

import clock
from errors import err


class Store(object):
    def __init__(self):
        self.donors = {}
        self.gifts = {}
        self.ledger_entries = {}
        self.recalculations = {}
        self.disputes = {}
        self.transfers = {}
        self.sections = {}
        self.seats = {}
        self.assignments = {}
        self.events = {}
        self.slots = {}
        self.requests = {}
        self._counter = itertools.count(1)

    def next_seq(self):
        return next(self._counter)


DB = Store()


def new_id():
    return str(uuid.uuid4())


def new_row(with_version=True, **fields):
    """Create a row carrying the common system fields.

    id is a bare UUID string, created_at/updated_at are logical-clock instants
    and version starts at 1.  Point-ledger entries pass with_version=False
    because they are append-only and carry neither updated_at nor version.
    """
    instant = clock.now()
    row = {"id": new_id(), "created_at": instant, "_seq": DB.next_seq()}
    if with_version:
        row["updated_at"] = instant
        row["version"] = 1
    row.update(fields)
    return row


def touch(row):
    """Refresh updated_at and advance version by exactly 1."""
    row["updated_at"] = clock.now()
    row["version"] = int(row.get("version", 0)) + 1
    return row


def order_key(row):
    """created_at ascending, with the insertion sequence as a stable tie-break.

    The logical clock does not advance on its own, so two rows written without
    a clock move share an instant; the insertion sequence preserves the
    chronological intent of 'created_at ASC' without ever letting id influence
    an ordering decision.
    """
    return (row["created_at"], row["_seq"])


def by_created_at(rows):
    return sorted(rows, key=order_key)


# ---------------------------------------------------------------------------
# Path-parameter resolution (PRD section 2.7): each collection has its own
# not-found code and path ids are resolved strictly left to right.
# ---------------------------------------------------------------------------
_COLLECTIONS = {
    "donor": ("donors", "ERR_DONOR_NOT_FOUND"),
    "gift": ("gifts", "ERR_GIFT_NOT_FOUND"),
    "recalculation": ("recalculations", "ERR_RECALCULATION_NOT_FOUND"),
    "ledger_entry": ("ledger_entries", "ERR_LEDGER_ENTRY_NOT_FOUND"),
    "dispute": ("disputes", "ERR_DISPUTE_NOT_FOUND"),
    "transfer": ("transfers", "ERR_TRANSFER_NOT_FOUND"),
    "section": ("sections", "ERR_SECTION_NOT_FOUND"),
    "seat": ("seats", "ERR_SEAT_NOT_FOUND"),
    "assignment": ("assignments", "ERR_SEAT_ASSIGNMENT_NOT_FOUND"),
    "event": ("events", "ERR_SELECTION_EVENT_NOT_FOUND"),
    "slot": ("slots", "ERR_SELECTION_SLOT_NOT_FOUND"),
    "request": ("requests", "ERR_RELOCATION_REQUEST_NOT_FOUND"),
}


def get_path(kind, row_id):
    """Resolve a path identifier or raise the collection's own 404."""
    attr, error_id = _COLLECTIONS[kind]
    row = getattr(DB, attr).get(row_id)
    if row is None:
        raise err(error_id, "%s '%s' was not found" % (kind.replace("_", " "), row_id))
    return row


def get_body_ref(kind, row_id):
    """Resolve an identifier supplied inside a request body (PRD section 2.7)."""
    attr, _ = _COLLECTIONS[kind]
    row = getattr(DB, attr).get(row_id)
    if row is None:
        raise err("ERR_REFERENCED_ENTITY_NOT_FOUND",
                  "referenced %s '%s' does not exist" % (kind.replace("_", " "), row_id))
    return row


def find(kind, row_id):
    attr, _ = _COLLECTIONS[kind]
    return getattr(DB, attr).get(row_id)


def check_version(row, expected, label="resource"):
    """Optimistic concurrency control against a parent row's current version."""
    if int(row.get("version", 0)) != int(expected):
        raise err("ERR_STALE_VERSION",
                  "expected %s version %s but the current version is %s"
                  % (label, expected, row.get("version")))
