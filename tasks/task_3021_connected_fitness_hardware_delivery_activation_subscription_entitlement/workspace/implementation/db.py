"""In-memory data store, id minting and the hardware SKU price catalogue.

Storage is deliberately process-local: plain dictionaries keyed by id.  Nothing
is written to disk, nothing is cached outside the interpreter, and no row is
seeded at import time.  start.sh restarts the interpreter for every per-test
server, so every boot begins from a completely empty store.
"""

import uuid
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Hardware SKU catalogue
#
# The only SKU list price the specification ever needs is the one the
# refurbishment pricing rule reads: "resale_price_cents = 0.60 x
# source_device.hardware_sku list price for grade A, 0.50 x for grade B,
# 0.40 x for grade C" (scaffold section 1.2 RefurbBatch; PRD section 3.7).
# The scaffold never enumerates the list prices themselves.
# ---------------------------------------------------------------------------
SKU_LIST_PRICE_CENTS = {
    "BIKE": 250000,
    "TREAD": 350000,
    "ROWER": 300000,
    "REFURB_BIKE": 150000,
    "REFURB_TREAD": 210000,
}

LEGAL_SKUS = ("BIKE", "TREAD", "ROWER", "REFURB_BIKE", "REFURB_TREAD")

# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------
STORE = {
    "memberships": {},
    "household_users": {},
    "devices": {},
    "hardware_orders": {},
    "delivery_appointments": {},
    "financing_plans": {},
    "service_orders": {},
    "parts_inventory": {},
    "class_sessions": {},
    "class_enrollments": {},
    "refurb_batches": {},
}


class DBObject(object):
    """A stored row: a mutable field dict plus creation ordering."""

    __slots__ = ("entity", "f", "created_at")

    def __init__(self, entity, fields, created_at):
        self.entity = entity
        self.f = fields
        self.created_at = created_at

    def __getitem__(self, key):
        return self.f[key]

    def __setitem__(self, key, value):
        self.f[key] = value

    def get(self, key, default=None):
        return self.f.get(key, default)


def new_id():
    return str(uuid.uuid4())


def new_token():
    return "vt_" + uuid.uuid4().hex


def create(entity, fields):
    """Insert a row, minting id/created_at/updated_at/version.

    Server-managed common fields (PRD section 2.11): id is a server-minted
    UUID with no decoration, created_at and updated_at are ISO 8601 UTC at
    second precision, and version starts at its initial value.
    """
    from clock import now

    instant = now()
    row = dict(fields)
    row["id"] = new_id()
    row["created_at"] = instant
    row["updated_at"] = instant
    row["version"] = 0
    obj = DBObject(entity, row, instant)
    STORE[entity][row["id"]] = obj
    return obj


def get(entity, row_id):
    if row_id is None:
        return None
    return STORE[entity].get(row_id)


def require(entity, row_id, message=None):
    from errors import api_error

    obj = get(entity, row_id)
    if obj is None:
        raise api_error("ERR_RESOURCE_NOT_FOUND", message)
    return obj


def all_rows(entity):
    return list(STORE[entity].values())


def touch(obj, bump=True):
    """Refresh updated_at and increment version.

    PRD section 2.11: updated_at is refreshed by any change to the row's
    properties, including changes to derived or computed fields, and version
    is incremented by one on every mutation of the row.
    """
    from clock import now

    obj["updated_at"] = now()
    if bump:
        obj["version"] = obj["version"] + 1


def ordered(rows, sort_key="created_at", descending=False):
    """Sort rows by a first-seen-at timestamp, ties by creation sequence.

    PRD section 2.3: unless a specific endpoint says otherwise every list
    endpoint returns its resources ordered by creation timestamp ascending.
    """
    # Materialise once so transient equal keys still fall back to the stable
    # creation order rather than to comparison of DBObject instances.
    decorated = []
    for index, obj in enumerate(rows):
        value = obj.get(sort_key)
        if isinstance(value, str):
            value = _try_parse(value)
        if value is None:
            value = obj.created_at
        decorated.append(((value, index), obj))
    decorated.sort(key=lambda pair: pair[0], reverse=descending)
    return [obj for _, obj in decorated]


def _try_parse(text):
    try:
        candidate = text[:-1] + "+00:00" if text.endswith("Z") else text
        parsed = datetime.fromisoformat(candidate)
    except (ValueError, TypeError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Half-open interval arithmetic
#
# PRD section 2.9: every interval is half-open, so two windows that merely
# touch end-to-start do not overlap.
# ---------------------------------------------------------------------------
def intervals_overlap(a_start, a_end, b_start, b_end):
    if a_start is None or a_end is None or b_start is None or b_end is None:
        return False
    return a_start < b_end and b_start < a_end


# ---------------------------------------------------------------------------
# Membership-scoped lookups (derived from row data, never stored separately)
# ---------------------------------------------------------------------------
def child_rows(entity, membership_id):
    """Every row of `entity` whose membership_id is `membership_id`."""
    if membership_id is None:
        return []
    if entity == "household_users":
        return [r for r in STORE["household_users"].values()
                if r["membership_id"] == membership_id]
    if entity == "devices":
        return [r for r in STORE["devices"].values()
                if r["membership_id"] == membership_id]
    if entity == "hardware_orders":
        return [r for r in STORE["hardware_orders"].values()
                if r["membership_id"] == membership_id]
    if entity == "financing_plans":
        return [r for r in STORE["financing_plans"].values()
                if r["membership_id"] == membership_id]
    return []


def sessions_by_instructor_overlap(instructor_name, start_at, end_at, statuses):
    hits = []
    for session in STORE["class_sessions"].values():
        if session["instructor_name"] != instructor_name:
            continue
        if session["scheduled_status"] not in statuses:
            continue
        if intervals_overlap(start_at, end_at, session["starts_at"], session["ends_at"]):
            hits.append(session)
    return hits


def open_session_overlap_after_publish(instructor_name, start_at, end_at, exclude_id):
    """Sessions the instructor is already streaming through."""
    hits = []
    for session in STORE["class_sessions"].values():
        if session["id"] == exclude_id:
            continue
        if session["instructor_name"] != instructor_name:
            continue
        if session["scheduled_status"] != "PUBLISHED":
            continue
        if intervals_overlap(start_at, end_at, session["starts_at"], session["ends_at"]):
            hits.append(session)
    return hits


def crew_delivery_overlap(crew_code, start_at, end_at, statuses, exclude_id=None):
    hits = []
    for appt in STORE["delivery_appointments"].values():
        if appt["id"] == exclude_id:
            continue
        if appt["technician_crew_code"] != crew_code:
            continue
        if appt["status"] not in statuses:
            continue
        if intervals_overlap(start_at, end_at, appt["start_at"], appt["end_at"]):
            hits.append(appt)
    return hits


def crew_service_overlap(crew_code, start_at, end_at, statuses, exclude_id=None):
    if crew_code is None:
        # No crew is named on a repair booking, so no other order can share it.
        return []
    hits = []
    for order in STORE["service_orders"].values():
        if order["id"] == exclude_id:
            continue
        if order.get("technician_crew_code") != crew_code:
            continue
        if order["status"] not in statuses:
            continue
        if intervals_overlap(start_at, end_at,
                            order.get("scheduled_start_at"), order.get("scheduled_end_at")):
            hits.append(order)
    return hits


def device_certification_depth(device_id):
    """Follow the self-referential certification lineage.

    Returns (depth, cyclic).  depth(d) = 0 when d.certifying_device_id is null,
    else 1 + depth(d.certifying_device_id).
    """
    seen = set()
    current_id = device_id
    depth = 0
    while True:
        if current_id is None:
            return depth, False
        if current_id in seen:
            return depth, True
        seen.add(current_id)
        row = STORE["devices"].get(current_id)
        if row is None:
            return depth, False
        parent = row.get("certifying_device_id")
        if parent is None:
            return depth, False
        depth += 1
        current_id = parent