"""In-memory entity store (PRD §2.4 common fields).

The store starts empty on every boot. No entity is ever seeded at startup;
every resource is constructed through the declared API surface.
"""

import uuid

import clock

territories = {}
wholesalers = {}
agreements = {}
transfers = {}
allocation_events = {}
accounts = {}
audits = {}
pos_grants = {}
reviews = {}
plans = {}
programs = {}


def new_id():
    return str(uuid.uuid4())


def stamped():
    """Common system-managed fields for a freshly created primary resource."""
    ts = clock.now_iso()
    return {"id": new_id(), "created_at": ts, "updated_at": ts, "version": 1}


def touch(entity):
    """Refresh updated_at and increment version on a mutation (PRD §2.4)."""
    entity["updated_at"] = clock.now_iso()
    entity["version"] += 1


def active_agreements_of(wholesaler_id):
    """The wholesaler's ACTIVE agreements, earliest-created first."""
    rows = [a for a in agreements.values()
            if a["wholesaler_id"] == wholesaler_id and a["status"] == "ACTIVE"]
    rows.sort(key=lambda a: a["created_at"])  # stable: ties keep insertion order
    return rows


def brand_in_scope(wholesaler_id, brand_code):
    """True when brand_code appears in one of the wholesaler's ACTIVE agreements."""
    return any(brand_code in (a["brand_scope"] or [])
               for a in active_agreements_of(wholesaler_id))
