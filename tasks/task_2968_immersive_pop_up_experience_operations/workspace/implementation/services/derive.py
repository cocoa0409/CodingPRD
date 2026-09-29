"""Shared lookups, derived states and cascades.

Rows carry their parsed temporal values under keys prefixed with '_' so the
public serialisation echoes the caller's own literal while comparisons stay
exact.
"""

from decimal import Decimal

from db import db, iso, now, ordered, touch
from errors import ApiError
from services import calc

# --------------------------------------------------------------------------
# lookups (ladder rungs 3 and 5)
# --------------------------------------------------------------------------

_NOT_FOUND = {
    "venues": "ERR_VENUE_NOT_FOUND",
    "agreements": "ERR_AGREEMENT_NOT_FOUND",
    "submissions": "ERR_SUBMISSION_NOT_FOUND",
    "runs": "ERR_RUN_NOT_FOUND",
    "rooms": "ERR_ROOM_NOT_FOUND",
    "slots": "ERR_SLOT_NOT_FOUND",
    "guests": "ERR_GUEST_NOT_FOUND",
    "orders": "ERR_ORDER_NOT_FOUND",
    "staff": "ERR_STAFF_NOT_FOUND",
    "shifts": "ERR_SHIFT_NOT_FOUND",
    "inspections": "ERR_INSPECTION_NOT_FOUND",
    "kits": "ERR_KIT_NOT_FOUND",
    "statements": "ERR_STATEMENT_NOT_FOUND",
}


def fetch(collection, row_id, error_id=None):
    table = getattr(db, collection)
    row = table.get(row_id) if isinstance(row_id, str) else None
    if row is None:
        raise ApiError(error_id or _NOT_FOUND[collection])
    return row


def venue(vid, error_id=None):
    return fetch("venues", vid, error_id)


def agreement(aid, error_id=None):
    return fetch("agreements", aid, error_id)


def submission(sid, error_id=None):
    return fetch("submissions", sid, error_id)


def run(rid, error_id=None):
    return fetch("runs", rid, error_id)


def room(rid, error_id=None):
    return fetch("rooms", rid, error_id)


def slot(sid, error_id=None):
    return fetch("slots", sid, error_id)


def guest(gid, error_id=None):
    return fetch("guests", gid, error_id)


def order(oid, error_id=None):
    return fetch("orders", oid, error_id)


def staff(sid, error_id=None):
    return fetch("staff", sid, error_id)


def shift(sid, error_id=None):
    return fetch("shifts", sid, error_id)


def inspection(iid, error_id=None):
    return fetch("inspections", iid, error_id)


def kit(kid, error_id=None):
    return fetch("kits", kid, error_id)


def statement(sid, error_id=None):
    return fetch("statements", sid, error_id)


# --------------------------------------------------------------------------
# child collections
# --------------------------------------------------------------------------

def rooms_of(run_row):
    return ordered([r for r in db.rooms.values() if r["run_id"] == run_row["id"]])


def slots_of(run_row):
    return ordered([s for s in db.slots.values() if s["run_id"] == run_row["id"]])


def orders_of_run(run_row):
    return ordered([o for o in db.orders.values() if o["run_id"] == run_row["id"]])


def orders_of_slot(slot_row):
    return ordered([o for o in db.orders.values() if o["slot_id"] == slot_row["id"]])


def staff_of(run_row):
    return ordered([s for s in db.staff.values() if s["run_id"] == run_row["id"]])


def shifts_of_run(run_row):
    return ordered([s for s in db.shifts.values() if s["run_id"] == run_row["id"]])


def shifts_of_member(member):
    return ordered([s for s in db.shifts.values()
                    if s["staff_member_id"] == member["id"]])


def submissions_of_run(run_row):
    return ordered([s for s in db.submissions.values()
                    if s["run_id"] == run_row["id"]])


def submissions_of_agreement(agreement_row):
    return ordered([s for s in db.submissions.values()
                    if s["license_agreement_id"] == agreement_row["id"]])


def runs_of_venue(venue_row):
    return ordered([r for r in db.runs.values() if r["venue_id"] == venue_row["id"]])


def runs_of_agreement(agreement_row):
    return ordered([r for r in db.runs.values()
                    if r["license_agreement_id"] == agreement_row["id"]])


def inspections_of_run(run_row):
    return ordered([i for i in db.inspections.values()
                    if i["run_id"] == run_row["id"]])


def statements_of_run(run_row):
    return ordered([s for s in db.statements.values()
                    if s["run_id"] == run_row["id"]])


# --------------------------------------------------------------------------
# run_effective_capacity (calculation 5)
# --------------------------------------------------------------------------

def compute_effective_capacity(run_row, rooms=None, tolerate_empty=False):
    """The tightest of the four ceilings.

    A roomless run is an error, not a zero (PRD §3.3) — except on the
    CONDITIONAL inspection branch, which may not surface ERR_RUN_HAS_NO_ROOMS,
    where the run's stored figure (necessarily 0) simply stands.
    """
    rooms = rooms_of(run_row) if rooms is None else rooms
    if not rooms:
        if tolerate_empty:
            return None
        raise ApiError("ERR_RUN_HAS_NO_ROOMS")
    venue_row = venue(run_row["venue_id"])
    egress_ceiling = calc.egress_capacity(venue_row["egress_width_cm"])
    room_floor = min(r["throughput_per_slot"] for r in rooms)
    base = min(venue_row["permitted_occupancy_load"], egress_ceiling, room_floor)
    cap = run_row.get("effective_capacity_cap") or 0
    if cap > 0:
        return min(base, cap)
    return base


def refresh_effective_capacity(run_row, tolerate_empty=False):
    value = compute_effective_capacity(run_row, tolerate_empty=tolerate_empty)
    if value is None:
        return run_row["effective_capacity"]
    run_row["effective_capacity"] = value
    return value


def require_rooms(run_row):
    """Raise ERR_RUN_HAS_NO_ROOMS when a capacity figure is needed but none can
    be derived."""
    if not rooms_of(run_row):
        raise ApiError("ERR_RUN_HAS_NO_ROOMS")


# --------------------------------------------------------------------------
# run clearance gate (PRD §3.3)
# --------------------------------------------------------------------------

REQUIRED_CRAFTS = ("PERFORMER", "AMBASSADOR", "TECHNICIAN")


def clearance_gate_holds(run_row):
    agreement_row = db.agreements.get(run_row["license_agreement_id"])
    if agreement_row is None:
        return False
    approved_scopes = set(
        s["scope"] for s in db.submissions.values()
        if s["run_id"] == run_row["id"] and s["status"] == "APPROVED"
    )
    for scope in agreement_row["approval_scopes"]:
        if scope not in approved_scopes:
            return False
    cleared_crafts = set(
        m["staff_role"] for m in db.staff.values()
        if m["run_id"] == run_row["id"] and m["status"] == "CLEARED"
    )
    for craft in REQUIRED_CRAFTS:
        if craft not in cleared_crafts:
            return False
    return True


def rederive_clearance(run_row):
    """Re-evaluate the CLEARED/UNCLEARED gate.

    A SUSPENDED clearance is a separate, sticky standing: only
    lift-suspension leaves it, so the gate never overwrites it.
    """
    if run_row["clearance_status"] == "SUSPENDED":
        return
    target = "CLEARED" if clearance_gate_holds(run_row) else "UNCLEARED"
    if run_row["clearance_status"] != target:
        run_row["clearance_status"] = target
        touch(run_row)


# --------------------------------------------------------------------------
# slot seat bookkeeping
# --------------------------------------------------------------------------

def recompute_available(slot_row):
    slot_row["available_capacity"] = (slot_row["released_capacity"]
                                      - slot_row["held_capacity"]
                                      - slot_row["sold_capacity"])
    return slot_row["available_capacity"]


# --------------------------------------------------------------------------
# slot_overlap_admission_load (calculation 12)
# --------------------------------------------------------------------------

OVERLAP_PEER_STATUSES = ("DRAFT", "OPEN", "SOLD_OUT", "HELD_FOR_BUYOUT", "SUSPENDED")


def check_slot_overlap_load(run_row, start, end, base_capacity, effective_capacity,
                            exclude_id=None):
    peers = [s for s in db.slots.values()
             if s["run_id"] == run_row["id"]
             and s["status"] in OVERLAP_PEER_STATUSES
             and s["id"] != exclude_id]
    peers.sort(key=lambda s: (s["_start"], s["created_at"], s["_seq"]))
    load = int(base_capacity)
    for peer in peers:
        # half-open windows: adjacency is admissible, both comparisons strict
        if start < peer["_end"] and peer["_start"] < end:
            load += peer["base_capacity"]
    if load > effective_capacity:
        raise ApiError("ERR_SLOT_OVERLAP_CAPACITY")


# --------------------------------------------------------------------------
# staff_shift_occupation_window (calculation 11)
# --------------------------------------------------------------------------

def check_shift_geometry(member, start, end):
    from datetime import timedelta
    buffer_delta = timedelta(minutes=calc.REST_BUFFER_MIN)
    for existing in shifts_of_member(member):
        if existing["status"] != "SCHEDULED":
            continue
        buffered_start = existing["_start"] - buffer_delta
        buffered_end = existing["_end"] + buffer_delta
        # closed intervals on both sides: touching endpoints collide
        if start <= buffered_end and buffered_start <= end:
            raise ApiError("ERR_SHIFT_OVERLAP")
    # length is only examined once the collision sweep has cleared
    if (end - start) > timedelta(minutes=calc.MAX_SHIFT_MINUTES):
        raise ApiError("ERR_SHIFT_TOO_LONG")


# --------------------------------------------------------------------------
# accessibility (ladder rung 14)
# --------------------------------------------------------------------------

SENSORY_BYPASS_LEVEL = 4


def check_accommodations(run_row, slot_row, accommodations, wheelchair_party_count):
    wanted = set(accommodations or ())
    rooms = rooms_of(run_row)
    if "WHEELCHAIR" in wanted:
        if any(not r["wheelchair_accessible"] for r in rooms):
            raise ApiError("ERR_WHEELCHAIR_ROUTE_UNAVAILABLE")
    if "QUIET_ROUTE" in wanted:
        for r in rooms:
            if r["sensory_intensity_level"] >= SENSORY_BYPASS_LEVEL and not r["has_quiet_bypass"]:
                raise ApiError("ERR_QUIET_ROUTE_UNAVAILABLE")
    if "ASL_INTERPRETER" in wanted:
        staffed = any(m["staff_role"] == "AMBASSADOR" and m["status"] == "CLEARED"
                      for m in staff_of(run_row))
        if not staffed:
            raise ApiError("ERR_ASL_NOT_STAFFED")
    if (slot_row["wheelchair_sold"] + int(wheelchair_party_count)
            > slot_row["wheelchair_positions"]):
        raise ApiError("ERR_WHEELCHAIR_POSITIONS_EXHAUSTED")


# --------------------------------------------------------------------------
# staff readiness refresh
# --------------------------------------------------------------------------

def refresh_readiness(member):
    coverage = calc.dec(member["cert_coverage_pct"])
    preflight = calc.readiness_score(
        member["training_score"], coverage,
        member["completed_rehearsal_count"] + member["scheduled_rehearsal_count"],
        member["incident_count"])
    audit = calc.readiness_score(
        member["training_score"], coverage,
        member["completed_rehearsal_count"], member["incident_count"])
    member["readiness_score_preflight"] = float(preflight)
    member["readiness_score_audit"] = float(audit)


def cancel_scheduled_shifts(member):
    """Every SCHEDULED shift of this member is cancelled, each with its own
    version bump and timestamp."""
    for row in shifts_of_member(member):
        if row["status"] == "SCHEDULED":
            row["status"] = "CANCELLED"
            touch(row)
