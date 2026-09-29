"""In-memory store.  Empty on every boot: nothing is ever seeded or preloaded."""
import itertools
import uuid

import clock

_seq = itertools.count(1)

terminals = {}
brands = {}
allowance_rules = {}
grants = {}
products = {}
stock_items = {}
movements = {}
itineraries = {}
sales = {}
sale_lines = {}
sealed_bags = {}
pre_orders = {}
agreements = {}
audits = {}

ALL_STORES = (
    terminals, brands, allowance_rules, grants, products, stock_items, movements,
    itineraries, sales, sale_lines, sealed_bags, pre_orders, agreements, audits,
)


def new_id():
    return str(uuid.uuid4())


def base(versioned=True):
    """Common system fields (PRD section 2.5)."""
    stamp = clock.now_iso()
    record = {"id": new_id(), "created_at": stamp}
    if versioned:
        record["updated_at"] = stamp
        record["version"] = 1
    record["_seq"] = next(_seq)
    return record


def touch(record):
    """Refresh updated_at and increment version by exactly 1."""
    record["updated_at"] = clock.now_iso()
    record["version"] = record.get("version", 0) + 1


def public(record):
    if record is None:
        return None
    return {key: value for key, value in record.items() if not key.startswith("_")}


def sort_key(record):
    return (record["created_at"], record["_seq"])


def ordered(store, predicate=None):
    """Every collection is sorted by created_at ascending (creation order ties)."""
    rows = [r for r in store.values() if predicate is None or predicate(r)]
    rows.sort(key=sort_key)
    return rows
