"""In-memory data store. Empty on every boot; no seeding, no persistence."""
import itertools
import uuid
from datetime import datetime, timezone

# id -> row (dict) per entity collection
store = {
    "active_ingredients": {},
    "products": {},
    "applications": {},
    "studies": {},
    "use_sites": {},
    "risk_assessments": {},
    "tolerances": {},
    "amendments": {},
    "certifications": {},
    "bulletins": {},
    "review_cases": {},
    "dcis": {},
    "proceedings": {},
    "state_registrations": {},
}

_seq = itertools.count(1)


def new_id():
    """Server-minted UUID with no type prefix (PRD 2.5)."""
    return str(uuid.uuid4())


def iso3(dt):
    """ISO 8601 UTC with exactly three fractional digits, e.g. 2025-05-24T10:30:00.123Z."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def wall_iso():
    """created_at/updated_at are wall-clock UTC with 3 fractional digits (PRD 2.5)."""
    return iso3(datetime.now(timezone.utc))


def new_row():
    """Common system-managed fields for every resource (PRD 2.5)."""
    ts = wall_iso()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next(_seq),
    }


def touch(row):
    """Every mutation refreshes updated_at and increments version (PRD 2.5),
    including mutations caused by system cascades."""
    row["updated_at"] = wall_iso()
    row["version"] += 1


def sort_key(row):
    """List ordering: created_at ascending; _seq breaks same-millisecond ties."""
    return (row["created_at"], row["_seq"])


def sorted_rows(rows):
    return sorted(rows, key=sort_key)
