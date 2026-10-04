"""In-memory data store. Module-level dicts keyed by id.

The store starts EMPTY on every boot: no seeding, no preload, no files.
Internal record keys are prefixed with '_' and stripped at serialization.
"""
import uuid

import clock

STORES = {
    "bakeries": {},
    "territories": {},
    "distributors": {},
    "agreements": {},
    "financing_plans": {},
    "retail_accounts": {},
    "production_days": {},
    "orders": {},
    "stale_claims": {},
    "transfers": {},
}

_seq = {"n": 0}


def new_id():
    return str(uuid.uuid4())


def _next_seq():
    _seq["n"] += 1
    return _seq["n"]


def next_seq():
    """Public monotonic sequence (audit-entry tie-breaks, etc.)."""
    return _next_seq()


def insert(kind, record):
    """Stamp common system fields (PRD 2.5) and store the record."""
    record["id"] = new_id()
    record["created_at"] = clock.iso()
    record["updated_at"] = record["created_at"]
    record["version"] = 1
    record["_seq"] = _next_seq()
    STORES[kind][record["id"]] = record
    return record


def touch(record):
    """Every mutation advances version and refreshes updated_at (PRD 2.5)."""
    record["version"] += 1
    record["updated_at"] = clock.iso()


def get(kind, rid):
    return STORES[kind].get(rid)


def all_of(kind):
    return sorted(STORES[kind].values(), key=lambda r: (r["created_at"], r["_seq"]))
