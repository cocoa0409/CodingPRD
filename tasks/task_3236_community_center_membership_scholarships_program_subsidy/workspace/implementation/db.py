"""In-memory data store. The store starts empty on every boot; nothing is seeded."""
import uuid

from common import now_dt, format_dt, ApiError

STORES = {
    "associations": {},
    "branches": {},
    "categories": {},
    "members": {},
    "memberships": {},
    "drafts": {},
    "applications": {},
    "programs": {},
    "sessions": {},
    "registrations": {},
    "spaces": {},
    "reservations": {},
    "campaigns": {},
    "donations": {},
}


def new_record(store, fields):
    """Create and persist a record with common system fields."""
    now = now_dt()
    rec = {
        "id": str(uuid.uuid4()),
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    rec.update(fields)
    STORES[store][rec["id"]] = rec
    return rec


def touch(rec, bump=True):
    """Update timestamps and (optionally) increment version by exactly 1."""
    rec["updated_at"] = now_dt()
    if bump:
        rec["version"] = rec.get("version", 1) + 1


def get(store, rid, error_id="ERR_NOT_FOUND"):
    rec = STORES[store].get(rid)
    if rec is None:
        raise ApiError(error_id, f"Resource {rid} not found in {store}")
    return rec


def all_records(store):
    return sorted(STORES[store].values(), key=lambda r: (r["created_at"], r["id"]))


def serialize(rec, fields):
    """Serialize a record, converting datetime/date values to ISO strings."""
    out = {}
    for f in fields:
        val = rec.get(f)
        if f in ("created_at", "updated_at"):
            out[f] = format_dt(val)
        else:
            out[f] = val
    return out
