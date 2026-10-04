"""In-memory storage (PRD: dicts keyed by id; empty at boot; no seeding).

Every record carries the four common properties of PRD section 2.4:
id (UUID, no prefix), created_at, updated_at (logical-clock timestamps,
3 fractional digits), version (starts at 1, +1 on every mutation including
cascade-driven ones). Internal bookkeeping fields are underscore-prefixed
and stripped before serialization.
"""
import itertools
import uuid

import logical_clock

STORE = {
    "care_stations": {},
    "tpas": {},
    "providers": {},
    "veterans": {},
    "assessments": {},
    "authorizations": {},
    "extension_requests": {},
    "appointments": {},
    "documentations": {},
    "claims": {},
    "urgent_care_visits": {},
    "rx_requests": {},
}

_seq = itertools.count(1)


def new_id():
    return str(uuid.uuid4())


def create(collection, fields):
    ts = logical_clock.now_iso()
    rec = {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next(_seq),
    }
    rec.update(fields)
    STORE[collection][rec["id"]] = rec
    return rec


def touch(rec):
    """Record one mutation of a resource: refresh updated_at, bump version."""
    rec["updated_at"] = logical_clock.now_iso()
    rec["version"] += 1


def get(collection, rid):
    return STORE[collection].get(rid)


def all_recs(collection):
    """Creation order: created_at ascending, insertion sequence as tiebreak
    (the logical clock can sit still across many creations)."""
    return sorted(
        STORE[collection].values(),
        key=lambda r: (r["created_at"], r["_seq"]),
    )


def public(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}
