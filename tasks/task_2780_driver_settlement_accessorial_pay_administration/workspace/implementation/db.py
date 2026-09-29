"""In-memory data store.

The store is EMPTY on every boot.  Nothing is seeded, preloaded or hardcoded;
every entity is created by an API call.
"""
import uuid

import clock

pay_packages = {}
pay_components = {}
drivers = {}
escrow_transactions = {}
loads = {}
accessorial_claims = {}
advances = {}
settlements = {}
settlement_lines = {}
disputes = {}
retro_corrections = {}

_seq = 0


def new_id():
    return str(uuid.uuid4())


def next_seq():
    """Monotonic insertion counter.

    The logical clock does not advance on its own, so `created_at` alone cannot
    order two rows written in the same logical instant.  This counter preserves
    insertion order as the stable realisation of "created_at ascending".
    """
    global _seq
    _seq += 1
    return _seq


def stamp_new(record):
    now = clock.now()
    record["id"] = new_id()
    record["created_at"] = now
    record["updated_at"] = now
    record["version"] = 1
    record["_seq"] = next_seq()
    return record


def stamp_log(record):
    """Append-only log rows carry only id and created_at (PRD section 2.4)."""
    record["id"] = new_id()
    record["created_at"] = clock.now()
    record["_seq"] = next_seq()
    return record


def touch(record, bump=1):
    record["updated_at"] = clock.now()
    record["version"] = record.get("version", 1) + bump
    return record


def ordered(collection):
    """Rows in created_at ascending order, insertion order as the tie-break."""
    return sorted(collection.values(), key=lambda r: (r["created_at"], r["_seq"]))


def reset():
    global _seq
    for store in (
        pay_packages,
        pay_components,
        drivers,
        escrow_transactions,
        loads,
        accessorial_claims,
        advances,
        settlements,
        settlement_lines,
        disputes,
        retro_corrections,
    ):
        store.clear()
    _seq = 0
    clock.reset()
