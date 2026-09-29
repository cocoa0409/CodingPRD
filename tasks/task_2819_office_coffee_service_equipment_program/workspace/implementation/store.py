"""In-memory store, logical clock and green-coffee market quote.

Nothing is persisted anywhere and nothing is ever seeded: a freshly booted server
has empty collections, and every entity is created through a declared endpoint.
"""
import copy
import uuid
from datetime import datetime

from timeutil import UTC

INITIAL_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)  # PRD 2.5
INITIAL_GREEN_INDEX_MICROS = 2000000                       # PRD 2.5

COLLECTION_NAMES = (
    "accounts", "sites", "routes", "equipment_models", "equipment_assets",
    "equipment_placements", "product_items", "par_levels", "service_visits",
    "work_orders", "invoices", "invoice_lines", "price_adjustments",
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        for name in COLLECTION_NAMES:
            setattr(self, name, {})
        self.current_utc = INITIAL_CLOCK
        self.green_index_micros = INITIAL_GREEN_INDEX_MICROS
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def now():
    return db.current_utc


def new_id():
    return str(uuid.uuid4())


def insert(collection, fields, common_fields=True):
    """Create a row: server-minted UUID id, created_at, and (optionally) the
    updated_at / version common members of PRD 2.4."""
    row = {"id": new_id()}
    row.update(fields)
    row["created_at"] = now()
    if common_fields:
        row["updated_at"] = now()
        row["version"] = 1
    row["_seq"] = db.next_seq()
    collection[row["id"]] = row
    return row


def snapshot(row):
    """Comparable copy of a row's business members (version/updated_at excluded)."""
    return copy.deepcopy({
        k: v for k, v in row.items()
        if not k.startswith("_") and k not in ("updated_at", "version")
    })


def touch(row, before):
    """PRD 2.4 / 2.10: refresh updated_at and increment version by exactly 1 when
    the row's fields actually changed."""
    if snapshot(row) != before:
        if "version" in row:
            row["version"] += 1
        if "updated_at" in row:
            row["updated_at"] = now()
        return True
    return False


def bump(row):
    """Unconditional mutation stamp, for the operations PRD declares always bump."""
    if "version" in row:
        row["version"] += 1
    if "updated_at" in row:
        row["updated_at"] = now()


def ordered(rows):
    """Default list ordering of PRD 2.3: created_at ascending, oldest first."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def ordered_desc(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]), reverse=True)
