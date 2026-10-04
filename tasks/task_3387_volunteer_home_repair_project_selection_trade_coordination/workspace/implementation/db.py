"""In-memory data store and logical clock.

Storage is dicts keyed by id. The store starts completely empty on every
boot: no seeding, no preloading, no file persistence.
"""
import itertools
import uuid

STORES = {
    "funding_cycles": {},
    "selection_runs": {},
    "sponsors": {},
    "commitments": {},
    "applications": {},
    "assessments": {},
    "scope_items": {},
    "projects": {},
    "events": {},
    "volunteers": {},
    "enrollments": {},
    "contractors": {},
    "work_orders": {},
    "material_orders": {},
    "warranty_claims": {},
}

_seq = itertools.count(1)

DEFAULT_CLOCK = "2026-09-01T00:00:00Z"
_clock = {"current": DEFAULT_CLOCK}


def get_clock():
    return _clock["current"]


def set_clock(value):
    _clock["current"] = value


def next_seq():
    return next(_seq)


def new_id():
    return str(uuid.uuid4())


def new_record(store, fields, now_iso, common=True):
    """Create a record with system fields. ScopeItem passes common=False
    (it carries only id + created_at; no updated_at / version)."""
    rec = dict(fields)
    rec["id"] = new_id()
    ts = now_iso()
    rec["created_at"] = ts
    rec["_seq"] = next_seq()
    if common:
        rec["updated_at"] = ts
        rec["version"] = 1
    STORES[store][rec["id"]] = rec
    return rec
