"""In-memory data stores, the logical clock, and entity field helpers.

The store starts empty on every boot — no seeding. The server is relaunched
per test, so module-level dicts are the entire database.
"""
import uuid
from datetime import datetime, timezone

import constants

# One dict per entity collection, keyed by entity id. Insertion order is the
# creation order and is preserved by Python dicts.
DB = {
    "factories": {},
    "models": {},
    "components": {},
    "lots": {},
    "runs": {},
    "reports": {},
    "orders": {},
    "claims": {},
    "docs": {},
    "workers": {},
    "enrollments": {},
    "allocations": {},
    "contracts": {},
}

# The logical clock (PRD 2.4): starts at exactly 2026-09-01T00:00:00Z and only
# moves when a PlatformAdmin sets it. `dt` is the comparable instant; `raw` is
# the canonical string re-used for received_at / substantiated_at / published_at
# and echoed as current_utc.
CLOCK = {
    "dt": datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc),
    "raw": constants.DEFAULT_CLOCK_RAW,
}

# Global monotonic sequence used as a stable tie-breaker when two resources
# share a created_at timestamp (millisecond resolution).
_SEQ = {"n": 0}


def new_id():
    """A server-minted UUID with no type prefix (PRD 2.5)."""
    return str(uuid.uuid4())


def now_iso_ms():
    """Wall-clock UTC with three fractional digits, e.g. 2026-10-02T12:34:56.789Z."""
    n = datetime.now(timezone.utc)
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + "{:03d}Z".format(n.microsecond // 1000)


def base_fields():
    """The common system-managed fields every resource carries (PRD 2.5)."""
    _SEQ["n"] += 1
    ts = now_iso_ms()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": _SEQ["n"],
    }


def touch(ent):
    """Refresh updated_at and bump version by exactly 1 (PRD 2.5)."""
    ent["updated_at"] = now_iso_ms()
    ent["version"] += 1


def clock_raw():
    return CLOCK["raw"]


def clock_date_str():
    """Current logical-clock date as YYYY-MM-DD (for evidence freshness)."""
    return CLOCK["dt"].date().isoformat()


def sorted_items(coll):
    """List-endpoint ordering: created_at ascending, creation order on ties."""
    return sorted(coll.values(), key=lambda e: (e["created_at"], e["_seq"]))
