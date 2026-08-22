"""In-memory data store.

Every collection is a plain dict keyed by id and starts EMPTY on every boot --
nothing is ever seeded, preloaded or hardcoded here. Test clients build all
state through the declared endpoints.

Keys beginning with an underscore are internal bookkeeping (insertion sequence,
parsed datetimes, exact Fractions) and are stripped from API responses.
"""

import itertools
import uuid

from flask import g

import clock

clients = {}
projects = {}
briefs = {}
composers = {}
demos = {}
musicians = {}
studio_rooms = {}
session_calls = {}
bookings = {}
license_deals = {}
reuse_extensions = {}
deliverables = {}
cue_entries = {}
library_tracks = {}

_seq = itertools.count(1)


def new_id():
    return str(uuid.uuid4())


def create(collection, fields):
    """Mint a row with the four common properties of PRD 2.4."""
    stamp = clock.now_iso()
    record = {
        "id": new_id(),
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
        "_seq": next(_seq),
    }
    record.update(fields)
    collection[record["id"]] = record
    touched = getattr(g, "touched", None)
    if touched is not None:
        # Creation is the row's first mutation and is already reflected in
        # version 1; a cascade later in the same request must not bump it.
        touched.add(record["id"])
    return record


def touch(record):
    """Register a mutation: refresh updated_at and bump version by exactly 1.

    A row mutated several times inside one request is still one mutation, so
    the bump is idempotent per request.
    """
    touched = getattr(g, "touched", None)
    if touched is not None:
        if record["id"] in touched:
            return record
        touched.add(record["id"])
    record["updated_at"] = clock.now_iso()
    record["version"] += 1
    return record


def by_created(rows):
    """created_at ascending, insertion sequence as the deterministic tie-break."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def serialize(record):
    return {k: v for k, v in record.items() if not k.startswith("_")}


def serialize_many(rows):
    return [serialize(r) for r in rows]
