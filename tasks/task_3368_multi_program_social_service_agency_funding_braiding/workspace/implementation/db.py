"""In-memory data store.

Every collection starts empty on each boot and lives only in this process:
no SQLite file, no JSON dump, no /tmp cache. Re-invoking start.sh therefore
wipes every byte of state. No entity is ever seeded or preloaded here.
"""

import uuid
from datetime import datetime

import clock

COLLECTIONS = [
    "funders",
    "programs",
    "grants",
    "clients",
    "intake_assessments",
    "eligibility_screens",
    "enrollments",
    "service_authorizations",
    "service_deliveries",
    "cost_allocations",
    "in_kind_donations",
    "outcome_reports",
]

store = {name: {} for name in COLLECTIONS}

_counters = {"row": 0, "delivery_seq": 0}


def new_id():
    """Server-minted UUID as a bare string: no type prefix, no embedded meaning."""
    return str(uuid.uuid4())


def create(collection, fields):
    _counters["row"] += 1
    row = {
        "id": new_id(),
        "created_at": clock.now(),
        "updated_at": clock.now(),
        "version": 1,
        "_seq": _counters["row"],
    }
    row.update(fields)
    store[collection][row["id"]] = row
    return row


def get(collection, row_id):
    if row_id is None:
        return None
    return store[collection].get(str(row_id))


def rows(collection):
    return list(store[collection].values())


def touch(row):
    """Every mutation refreshes updated_at and increments version by one."""
    row["updated_at"] = clock.now()
    row["version"] = row.get("version", 1) + 1
    return row


def next_delivery_seq():
    """Strictly increasing, never reused, never derived from the row id."""
    _counters["delivery_seq"] += 1
    return _counters["delivery_seq"]


def serialize(value):
    if isinstance(value, datetime):
        return clock.iso(value)
    if isinstance(value, dict):
        return {k: serialize(v) for k, v in value.items() if not k.startswith("_")}
    if isinstance(value, list):
        return [serialize(v) for v in value]
    return value


def public(row):
    return serialize(row)


def ordered(collection, rows_in=None):
    """Default list order: creation timestamp ascending."""
    items = list(rows_in) if rows_in is not None else rows(collection)
    return sorted(items, key=lambda r: (r["created_at"], r["_seq"]))


def find(collection, **filters):
    out = []
    for row in rows(collection):
        ok = True
        for key, value in filters.items():
            if value is None:
                continue
            if row.get(key) != value:
                ok = False
                break
        if ok:
            out.append(row)
    return out
