"""In-memory data store. Every byte of state vanishes on process restart.

The store starts empty on every boot: no seeding, no preloading, no
hardcoded entity data. All data arrives via API calls.
"""
from __future__ import annotations

import itertools
import uuid

from clock import format_ts, now

STORE = {
    "beneficiaries": {},
    "rate_schedules": {},
    "enrollment_periods": {},
    "enrollments": {},
    "employer_coverages": {},
    "penalties": {},
    "tax_records": {},
    "determinations": {},
    "appeals": {},
    "arrangements": {},
    "invoices": {},
    "payer_records": {},
    "elections": {},
    "relief_cases": {},
}

# Insertion sequence: deterministic tie-break after created_at (the logical
# clock may tie across several creations in one request).
_seq = itertools.count(1)


def new_id() -> str:
    return str(uuid.uuid4())


def make_entity(store_name: str, fields: dict) -> dict:
    ts = format_ts(now())
    ent = {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    ent.update(fields)
    ent["_seq"] = next(_seq)
    STORE[store_name][ent["id"]] = ent
    return ent


def touch(ent: dict) -> None:
    """Refresh updated_at and increment the OCC version on a mutation."""
    ent["updated_at"] = format_ts(now())
    ent["version"] = int(ent.get("version", 1)) + 1


def public(ent: dict) -> dict:
    """Strip internal (underscore-prefixed) bookkeeping keys."""
    return {k: v for k, v in ent.items() if not k.startswith("_")}


def get(store_name: str, ent_id):
    return STORE[store_name].get(ent_id)


def all_of(store_name: str):
    return list(STORE[store_name].values())


def find(store_name: str, pred):
    return [e for e in STORE[store_name].values() if pred(e)]


def find_one(store_name: str, pred):
    for e in STORE[store_name].values():
        if pred(e):
            return e
    return None


def remove(store_name: str, ent_id) -> None:
    STORE[store_name].pop(ent_id, None)


def sort_entities(ents):
    """created_at ASC, insertion order as the deterministic tie-break."""
    return sorted(ents, key=lambda e: (e["created_at"], e["_seq"]))
