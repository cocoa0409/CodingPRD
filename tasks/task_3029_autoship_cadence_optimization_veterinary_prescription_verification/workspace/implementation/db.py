"""In-memory data store.

Storage is Python dicts keyed by entity id. Nothing is persisted to disk and
NOTHING is seeded here: every dict starts empty and every entity is created
through a declared API endpoint.
"""

import clock
from clock import iso, new_id

# --- collections (all empty at import time; never seeded) --------------------
PETS = {}
VETERINARIANS = {}
PHARMACY_SITES = {}
PRODUCTS = {}
AUTOSHIP_PLANS = {}
AUTOSHIP_ITEMS = {}
PRESCRIPTIONS = {}
ORDERS = {}
ORDER_LINES = {}
SHIPMENTS = {}
COLD_PACK_RESERVATIONS = {}
COMPASSIONATE_REVIEWS = {}

ALL_STORES = (
    PETS,
    VETERINARIANS,
    PHARMACY_SITES,
    PRODUCTS,
    AUTOSHIP_PLANS,
    AUTOSHIP_ITEMS,
    PRESCRIPTIONS,
    ORDERS,
    ORDER_LINES,
    SHIPMENTS,
    COLD_PACK_RESERVATIONS,
    COMPASSIONATE_REVIEWS,
)

# --- monotonic insertion order, used to break created_at ties ---------------
SEQ = {}
_seq = 0


def next_seq():
    global _seq
    _seq += 1
    return _seq


def mint(store, **fields):
    """Create a row: assign id, created_at/updated_at/version, then store it."""
    entity_id = new_id()
    stamp = iso(clock.current())
    row = {"id": entity_id}
    row.update(fields)
    row["created_at"] = stamp
    row["updated_at"] = stamp
    row["version"] = 1
    store[entity_id] = row
    SEQ[entity_id] = next_seq()
    return row


def touch(row):
    """A mutation refreshes updated_at and increments version (PRD SS2.4)."""
    row["updated_at"] = iso(clock.current())
    row["version"] = row.get("version", 1) + 1
    return row


def clear_all():
    """Reset every collection (fresh-process hygiene only)."""
    for store in ALL_STORES:
        store.clear()
    SEQ.clear()


# --- convenience lookups ----------------------------------------------------

def find(store, entity_id):
    return store.get(entity_id)


def items_of(store, key, value):
    return [row for row in store.values() if row.get(key) == value]


def ordered(rows):
    """Sort by created_at ascending, ties broken by insertion order."""
    return sorted(rows, key=lambda r: (r.get("created_at") or "", SEQ.get(r["id"], 0)))