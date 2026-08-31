"""Student registrations, the teacher supplemental programme, and the clock."""
from datetime import timedelta

from flask import Blueprint

import calc
import derive
import find
import response as resp
import validators as v
from db import base_record, db, iso, now, sort_records, touch
from errors import ApiError
from middleware import (ALL_ROLES, PROGRAM_DIRECTOR, SCHOOL_LIAISON,
                        WAREHOUSE_LEAD, auth, school_scope)

bp = Blueprint("students", __name__)


# --------------------------------------------------------------------------
# StudentRegistration
# --------------------------------------------------------------------------
@bp.post("/student-registrations")
def create_registration():
    user_id, role = auth([SCHOOL_LIAISON])
    data = v.body()
    event_id = v.req_id(data, "distribution_event_id")
    student_reference = v.req_str(data, "student_reference", 1, 40)
    grade_band = v.req_enum(data, "grade_band", v.GRADE_BANDS)
    guardian_name = v.req_str(data, "guardian_name")
    free_lunch = v.opt_bool(data, "free_lunch_eligible", False)
    income_verified = v.opt_bool(data, "income_verified", False)

    event = find.distribution_event(event_id)
    school_scope(role, user_id, event["school_id"])

    # 9 — the event must be PUBLISHED.
    if event["status"] != "PUBLISHED":
        raise ApiError("ERR_INVALID_EVENT_STATE")

    # 19 — cadence-dependent registration lead time.
    cycle = db.drive_cycles.get(event["drive_cycle_id"])
    cadence = cycle["cadence"] if cycle else "BACK_TO_SCHOOL"
    lead_hours = calc.LEAD_TIME_HOURS[cadence]
    if event["window_start"] - now() < timedelta(hours=lead_hours):
        raise ApiError("ERR_REGISTRATION_LEAD_TIME")

    # 22 — uniqueness among non-WITHDRAWN registrations of the event.
    for reg in derive.registrations_of_event(event["id"]):
        if (reg["student_reference"] == student_reference
                and reg["eligibility_status"] != "WITHDRAWN"):
            raise ApiError("ERR_DUPLICATE_STUDENT_REGISTRATION")

    # 23 — grade-band agreement.
    if grade_band != event["grade_band"]:
        raise ApiError("ERR_GRADE_BAND_MISMATCH")

    rec = base_record()
    rec.update({
        "distribution_event_id": event["id"],
        "student_reference": student_reference,
        "grade_band": grade_band,
        "guardian_name": guardian_name,
        "free_lunch_eligible": free_lunch,
        "income_verified": income_verified,
        "eligibility_status": "PENDING",
        "verified_at": None,
        "reserved_unit_count": 0,
        "_reserved_lines": [],
    })
    db.student_registrations[rec["id"]] = rec

    event["provisional_fill_pct"] = derive.provisional_fill(event)
    touch(event)
    return resp.ok(rec, 201)


@bp.get("/student-registrations/<registration_id>")
def read_registration(registration_id):
    auth(ALL_ROLES)
    return resp.ok(find.registration(registration_id))


REG_FROM_STATES = {
    "VERIFIED": ("PENDING",),
    "REJECTED": ("PENDING",),
    "CONFIRMED": ("VERIFIED", "WAITLISTED"),
    "WAITLISTED": ("VERIFIED", "CONFIRMED"),
    "FULFILLED": ("CONFIRMED",),
    "NO_SHOW": ("CONFIRMED",),
    "WITHDRAWN": ("PENDING", "VERIFIED", "CONFIRMED", "WAITLISTED"),
}
REG_EVENT_STATES = {
    "VERIFIED": ("PUBLISHED",),
    "CONFIRMED": ("PUBLISHED",),
    "WAITLISTED": ("PUBLISHED",),
    "FULFILLED": ("PUBLISHED", "LOCKED"),
    "NO_SHOW": ("PUBLISHED", "LOCKED"),
}


@bp.post("/student-registrations/<registration_id>/transitions")
def move_registration(registration_id):
    user_id, role = auth([SCHOOL_LIAISON, PROGRAM_DIRECTOR])
    data = v.body()
    target = v.target_status(data)
    expected_version = v.req_int(data, "expected_distribution_event_version")

    reg = find.registration(registration_id)
    event = db.distribution_events.get(reg["distribution_event_id"])
    school_scope(role, user_id, event["school_id"] if event else None)
    school = db.schools.get(event["school_id"]) if event else None
    cycle = db.drive_cycles.get(event["drive_cycle_id"]) if event else None
    current = reg["eligibility_status"]

    # 9 — the registration's own from-state is judged first...
    if target not in v.REGISTRATION_STATUSES or target not in REG_FROM_STATES:
        raise ApiError("ERR_INVALID_REGISTRATION_STATE")
    if current not in REG_FROM_STATES[target]:
        raise ApiError("ERR_INVALID_REGISTRATION_STATE")
    # ...only then the governing event's status precondition.
    allowed_event_states = REG_EVENT_STATES.get(target)
    if allowed_event_states is not None:
        if event is None or event["status"] not in allowed_event_states:
            raise ApiError("ERR_INVALID_EVENT_STATE")

    # 10 — optimistic concurrency on the governing distribution event.
    if event is None or expected_version != event["version"]:
        raise ApiError("ERR_STALE_EVENT_VERSION")

    if target == "VERIFIED":
        # 24 — eligibility evidence.
        if not (reg["free_lunch_eligible"] or reg["income_verified"]):
            raise ApiError("ERR_ELIGIBILITY_NOT_MET")
        reg["eligibility_status"] = "VERIFIED"
        reg["verified_at"] = now()
        touch(reg)
        touch(event)
    elif target == "REJECTED":
        reg["eligibility_status"] = "REJECTED"
        touch(reg)
        touch(event)
    elif target == "CONFIRMED":
        # 25 — seat capacity, then 28 — inventory coverage.
        if event["confirmed_count"] >= event["seat_capacity"]:
            raise ApiError("ERR_EVENT_CAPACITY_FULL")
        if not derive.inventory_covers(event):
            raise ApiError("ERR_INSUFFICIENT_INVENTORY")
        reg["eligibility_status"] = "CONFIRMED"
        derive.reserve_units(reg, event)
        touch(reg)
        derive.recompute_event_counters(event)
        touch(event)
        if cycle is not None:
            derive.recompute_cycle_inventory(cycle)
        if school is not None:
            derive.recompute_school(school)
    elif target == "WAITLISTED":
        was_confirmed = current == "CONFIRMED"
        reg["eligibility_status"] = "WAITLISTED"
        if was_confirmed:
            derive.release_units(reg, event)
        touch(reg)
        derive.recompute_event_counters(event)
        touch(event)
        if was_confirmed:
            if cycle is not None:
                derive.recompute_cycle_inventory(cycle)
                touch(cycle)
            if school is not None:
                derive.recompute_school(school)
    elif target == "FULFILLED":
        reg["eligibility_status"] = "FULFILLED"
        derive.distribute_units(reg, event)
        touch(reg)
        derive.recompute_event_counters(event)
        touch(event)
        if cycle is not None:
            derive.recompute_cycle_inventory(cycle)
        if school is not None:
            derive.recompute_school(school)
    elif target == "NO_SHOW":
        reg["eligibility_status"] = "NO_SHOW"
        derive.release_units(reg, event)
        touch(reg)
        derive.recompute_event_counters(event)
        touch(event)
        if cycle is not None:
            derive.recompute_cycle_inventory(cycle)
        if school is not None:
            derive.recompute_school(school)
    else:  # WITHDRAWN
        was_confirmed = current == "CONFIRMED"
        reg["eligibility_status"] = "WITHDRAWN"
        if was_confirmed:
            derive.release_units(reg, event)
        touch(reg)
        derive.recompute_event_counters(event)
        touch(event)
        if was_confirmed and cycle is not None:
            derive.recompute_cycle_inventory(cycle)
        if school is not None:
            derive.recompute_school(school)

    return resp.ok(reg)


# --------------------------------------------------------------------------
# TeacherRequest
# --------------------------------------------------------------------------
@bp.post("/teacher-requests")
def create_teacher_request():
    user_id, role = auth([SCHOOL_LIAISON])
    data = v.body()
    school_id = v.req_id(data, "school_id")
    cycle_id = v.req_id(data, "drive_cycle_id")
    item_id = v.req_id(data, "supply_item_id")
    teacher_name = v.req_str(data, "teacher_name")
    qty_requested = v.req_int(data, "qty_requested", minimum=1)
    justification = v.req_str(data, "justification")

    school = find.school(school_id)
    cycle = find.cycle(cycle_id)
    item = find.supply_item(item_id)
    school_scope(role, user_id, school["id"])

    if not item["catalog_active"]:
        raise ApiError("ERR_ITEM_INACTIVE")

    rec = base_record()
    rec.update({
        "school_id": school["id"],
        "drive_cycle_id": cycle["id"],
        "supply_item_id": item["id"],
        "teacher_name": teacher_name,
        "qty_requested": qty_requested,
        "justification": justification,
        "request_cost_cents": qty_requested * item["unit_cost_cents"],
        "status": "SUBMITTED",
        "approved_at": None,
    })
    db.teacher_requests[rec["id"]] = rec
    return resp.ok(rec, 201)


@bp.get("/teacher-requests/<request_id>")
def read_teacher_request(request_id):
    auth(ALL_ROLES)
    return resp.ok(find.teacher_request(request_id))


@bp.get("/teacher-requests")
def list_teacher_requests():
    auth(ALL_ROLES)
    limit, offset = v.pagination()
    school_id = v.query_id("school_id")
    cycle_id = v.query_id("drive_cycle_id")
    item_id = v.query_id("supply_item_id")
    status = v.query_enum("status", v.TEACHER_REQUEST_STATUSES)
    rows = list(db.teacher_requests.values())
    if school_id:
        rows = [r for r in rows if r["school_id"] == school_id]
    if cycle_id:
        rows = [r for r in rows if r["drive_cycle_id"] == cycle_id]
    if item_id:
        rows = [r for r in rows if r["supply_item_id"] == item_id]
    if status:
        rows = [r for r in rows if r["status"] == status]
    return resp.listing(sort_records(rows), limit, offset)


def _active_partner_count():
    count = 0
    for school in db.schools.values():
        if school["partnership_status"] != "ACTIVE":
            continue
        if any(s["status"] == "PUBLISHED"
               for s in derive.specs_of_school(school["id"])):
            count += 1
    return count


@bp.post("/teacher-requests/<request_id>/transitions")
def move_teacher_request(request_id):
    user_id, role = auth([PROGRAM_DIRECTOR, WAREHOUSE_LEAD])
    data = v.body()
    target = v.target_status(data)
    if target in ("APPROVED", "DENIED") and role != PROGRAM_DIRECTOR:
        raise ApiError("ERR_UNAUTHORIZED")
    if target == "FULFILLED" and role != WAREHOUSE_LEAD:
        raise ApiError("ERR_UNAUTHORIZED")

    req = find.teacher_request(request_id)
    school = db.schools.get(req["school_id"])
    cycle = db.drive_cycles.get(req["drive_cycle_id"])
    current = req["status"]

    if target not in v.TEACHER_REQUEST_STATUSES:
        raise ApiError("ERR_INVALID_TEACHER_REQUEST_STATE")

    if target == "APPROVED":
        if current != "SUBMITTED":
            raise ApiError("ERR_INVALID_TEACHER_REQUEST_STATE")
        if school is None or school["partnership_status"] != "ACTIVE":
            raise ApiError("ERR_SCHOOL_PARTNERSHIP_INACTIVE")
        if cycle is None or cycle["status"] not in (
                "COLLECTING", "SORTING", "DISTRIBUTION"):
            raise ApiError("ERR_CYCLE_PHASE_INVALID")
        cap = cycle["supplemental_cap_cents"]
        approved_spend = sum(t["request_cost_cents"]
                             for t in derive.requests_of_cycle(cycle["id"])
                             if t["status"] in ("APPROVED", "FULFILLED"))
        if approved_spend + req["request_cost_cents"] > cap:
            raise ApiError("ERR_SUPPLEMENTAL_CAP_EXCEEDED")
        if _active_partner_count() >= calc.SCHOOL_SUBCAP_MIN_PARTNERS:
            school_cap = calc.school_share_cap(cap)
            school_spend = sum(t["request_cost_cents"]
                               for t in derive.requests_of_cycle(cycle["id"])
                               if t["school_id"] == req["school_id"]
                               and t["status"] in ("APPROVED", "FULFILLED"))
            if school_spend + req["request_cost_cents"] > school_cap:
                raise ApiError("ERR_SCHOOL_SUBCAP_EXCEEDED")
        req["status"] = "APPROVED"
        req["approved_at"] = now()
        touch(req)
    elif target == "DENIED":
        if current != "SUBMITTED":
            raise ApiError("ERR_INVALID_TEACHER_REQUEST_STATE")
        req["status"] = "DENIED"
        touch(req)
    elif target == "FULFILLED":
        if current != "APPROVED":
            raise ApiError("ERR_INVALID_TEACHER_REQUEST_STATE")
        pos = derive.get_position(req["drive_cycle_id"], req["supply_item_id"])
        on_hand = pos["on_hand_qty"] if pos else 0
        if on_hand < req["qty_requested"]:
            raise ApiError("ERR_INSUFFICIENT_INVENTORY")
        pos["on_hand_qty"] -= req["qty_requested"]
        pos["distributed_qty"] += req["qty_requested"]
        touch(pos)
        req["status"] = "FULFILLED"
        touch(req)
        if cycle is not None:
            derive.recompute_cycle_inventory(cycle)
            touch(cycle)
    else:
        raise ApiError("ERR_INVALID_TEACHER_REQUEST_STATE")

    return resp.ok(req)


# --------------------------------------------------------------------------
# Logical clock (PRD §2.5)
# --------------------------------------------------------------------------
@bp.post("/_clock/set_current_utc")
def set_clock():
    auth([PROGRAM_DIRECTOR])
    data = v.body()
    if "to_iso8601" not in data or data["to_iso8601"] is None:
        raise ApiError("ERR_INVALID_REQUEST", "Missing required field 'to_iso8601'.")
    parsed = v.parse_dt(data["to_iso8601"], "to_iso8601")
    db.clock = parsed
    return resp.raw({"current_utc": iso(parsed)})
