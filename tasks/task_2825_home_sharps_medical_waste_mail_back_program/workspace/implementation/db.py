"""In-memory data store.

The store starts completely empty on every boot; no entity is ever seeded,
preloaded or hardcoded. Tests build every precondition through the API.
"""
import copy
import uuid

import clock

COLLECTIONS = (
    "state_rules",
    "packaging_specs",
    "treatment_facilities",
    "sponsors",
    "programs",
    "patients",
    "enrollments",
    "kits",
    "return_labels",
    "shipments",
    "nonconformance_events",
    "certificates",
    "ledger_entries",
    "autoship_runs",
)


def _fresh():
    data = {name: {} for name in COLLECTIONS}
    data["_insert_seq"] = 0
    return data


data = _fresh()


def reset():
    global data
    data = _fresh()
    clock.clock.reset()


def snapshot():
    return copy.deepcopy(data)


def restore(snap):
    global data
    data = snap


def coll(name):
    return data[name]


def next_insert_seq():
    data["_insert_seq"] += 1
    return data["_insert_seq"]


def new_id():
    return str(uuid.uuid4())


def touch(row):
    """Refresh updated_at on a mutated row that carries the common fields."""
    if "updated_at" in row:
        row["updated_at"] = clock.now_iso()


def bump(row):
    """Refresh updated_at and increment version by exactly 1."""
    if "updated_at" in row:
        row["updated_at"] = clock.now_iso()
    if "version" in row:
        row["version"] = row["version"] + 1


def insert(name, row):
    row["_seq"] = next_insert_seq()
    data[name][row["id"]] = row
    return row


def create_row(name, fields, common=True):
    row = dict(fields)
    row["id"] = new_id()
    row["created_at"] = clock.now_iso()
    if common:
        row["updated_at"] = row["created_at"]
        row["version"] = 1
    return insert(name, row)


def ordered(name, predicate=None):
    """Rows in created_at ascending order (insertion order breaks ties)."""
    rows = list(data[name].values())
    if predicate is not None:
        rows = [r for r in rows if predicate(r)]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return rows


def get(name, row_id):
    if not isinstance(row_id, str):
        return None
    return data[name].get(row_id)
