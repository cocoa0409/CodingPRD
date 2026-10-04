"""In-memory storage, logical clock, identity generation, and mutation tracking.

Storage is plain dicts keyed by id (PRD: in-memory only, no seeding). The store
starts empty on every boot; every entity is created via API calls.

The logical clock (PRD 2.5) defaults to exactly 2026-09-01T00:00:00Z and never
falls back to wall-clock time. Wall clock is used only for created_at /
updated_at / api_request_timestamp, which PRD 2.5 does NOT list as
logical-clock consumers.

Version discipline (PRD 2.10): each entity mutated by a request — including
cascade targets — increments its version by exactly one per request and
refreshes updated_at. Entities created inside a request are born at version 1
and are not re-bumped within that same request. This is enforced through the
per-request `touched` registry held on flask.g.
"""

import uuid
from datetime import datetime, timezone

from flask import g

from constants import DEFAULT_CLOCK_ISO

# --- The store -------------------------------------------------------------
DB = {
    "facilities": {},
    "operators": {},
    "constraint_events": {},
    "forecasts": {},
    "tmis": {},
    "revisions": {},
    "flights": {},
    "slots": {},
    "transactions": {},
    "compression_runs": {},
    "ga_requests": {},
    "reroutes": {},
    "ledgers": {},
}

_SEQ = {"n": 0}


def next_seq():
    _SEQ["n"] += 1
    return _SEQ["n"]


def new_id():
    return str(uuid.uuid4())


def now_wall():
    return datetime.now(timezone.utc)


# --- Logical clock -----------------------------------------------------------
def _parse_default_clock():
    return datetime.strptime(DEFAULT_CLOCK_ISO, "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=timezone.utc
    )


_CLOCK = {"now": _parse_default_clock()}


def get_clock():
    return _CLOCK["now"]


def set_clock(dt):
    _CLOCK["now"] = dt


# --- Per-request mutation registry -------------------------------------------
def _touched():
    registry = getattr(g, "_touched_registry", None)
    if registry is None:
        registry = set()
        g._touched_registry = registry
    return registry


def touch(rec):
    """Bump version and refresh updated_at at most once per request per entity.

    Record-type entities (TMIRevision, SlotTransaction, CompressionRun,
    RerouteAssignment) have no version/updated_at and are never touched.
    """
    key = (rec["_collection"], rec["id"])
    registry = _touched()
    if key in registry:
        return
    registry.add(key)
    rec["version"] += 1
    rec["updated_at"] = get_clock()


def create_entity(collection, fields):
    """Create a mutable (common-fields) entity: id, created_at, updated_at,
    version=1. Newly created entities count as already-mutated this request so
    cascades in the same request do not bump them past version 1."""
    now = get_clock()
    rec = dict(fields)
    rec["id"] = new_id()
    rec["created_at"] = now
    rec["updated_at"] = now
    rec["version"] = 1
    rec["_seq"] = next_seq()
    rec["_collection"] = collection
    DB[collection][rec["id"]] = rec
    _touched().add((collection, rec["id"]))
    return rec


def create_record(collection, fields):
    """Create an append-only record type (id + created_at only; no updated_at,
    no version): TMIRevision, SlotTransaction, CompressionRun,
    RerouteAssignment."""
    rec = dict(fields)
    rec["id"] = new_id()
    rec["created_at"] = get_clock()
    rec["_seq"] = next_seq()
    rec["_collection"] = collection
    DB[collection][rec["id"]] = rec
    return rec
