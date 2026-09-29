"""In-memory data store.

Every collection starts empty on every boot: nothing is seeded, preloaded or
hardcoded here. Tests build all state through the declared API surface.
"""
import itertools
import uuid

from flask import g, has_request_context

import clock

COLLECTIONS = (
    "rental_accounts",
    "service_sites",
    "placement_permits",
    "asset_units",
    "rental_contracts",
    "quote_lines",
    "routes",
    "service_schedules",
    "service_visits",
    "disposal_sites",
    "waste_manifests",
    "charge_events",
    "unit_deployments",
)


class Store(object):
    def __init__(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)


db = Store()


def new_id():
    return str(uuid.uuid4())


def insert(collection, fields, common_fields=True):
    """Create a row with the server-managed common properties (PRD 2.9)."""
    row = dict(fields)
    row["id"] = new_id()
    row["created_at"] = clock.now_iso()
    if common_fields:
        row["updated_at"] = row["created_at"]
        row["version"] = 1
    row["_seq"] = db.next_seq()
    getattr(db, collection)[row["id"]] = row
    return row


def touch(row):
    """Refresh updated_at and bump version once per request per row."""
    if "version" not in row:
        # QuoteLine carries neither updated_at nor version (PRD 2.9).
        return row
    row["updated_at"] = clock.now_iso()
    if has_request_context():
        touched = getattr(g, "touched_rows", None)
        if touched is None:
            touched = set()
            g.touched_rows = touched
        if row["id"] in touched:
            return row
        touched.add(row["id"])
    row["version"] += 1
    return row


def order_key(row):
    return (row["created_at"], row["_seq"])


def ordered(rows):
    """created_at ascending, with the server-minted sequence as tie-break."""
    return sorted(rows, key=order_key)


def all_rows(collection):
    return ordered(getattr(db, collection).values())


def serialize(row):
    return {k: v for k, v in row.items() if not k.startswith("_")}


def serialize_all(rows):
    return [serialize(r) for r in rows]


def get(collection, row_id):
    if not isinstance(row_id, str):
        return None
    return getattr(db, collection).get(row_id)
