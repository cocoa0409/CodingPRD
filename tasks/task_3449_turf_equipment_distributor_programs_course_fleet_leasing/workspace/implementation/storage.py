"""In-memory storage. Dicts only; the store starts empty on every boot.

No seeding, no preloading, no file/SQLite persistence. Every entity is built
through the declared API surface.
"""
import uuid

STORES = {
    "distributors": {},
    "technicians": {},
    "courses": {},
    "models": {},
    "parts": {},
    "orders": {},
    "leases": {},
    "units": {},
    "appraisals": {},
    "claims": {},
    "projects": {},
}

_seq = [0]


def new_id():
    return str(uuid.uuid4())


def next_seq():
    _seq[0] += 1
    return _seq[0]


def new_record(store, fields):
    """Create a record with the common system fields (PRD section 2.4)."""
    import clock
    now_s = clock.stamp()
    rec = {
        "id": new_id(),
        "created_at": now_s,
        "updated_at": now_s,
        "version": 1,
        "_seq": next_seq(),
        "_created_dt": clock.now(),
    }
    rec.update(fields)
    STORES[store][rec["id"]] = rec
    return rec


def touch(rec):
    """Refresh updated_at and bump version (every modification, incl. cascades)."""
    import clock
    rec["updated_at"] = clock.stamp()
    rec["version"] += 1


def public(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def sort_created(recs):
    """Default list sort: created_at ascending; creation order breaks ties."""
    return sorted(recs, key=lambda r: (r["created_at"], r["_seq"]))
