"""Position families, staffing plans and shift blocks."""

from flask import Blueprint

import calc
import services as svc
from core import (
    ALL_ROLES,
    all_rows,
    auth,
    bad_window,
    body_dict,
    conflict,
    db,
    err,
    invalid,
    lookup,
    minutes_between,
    new_record,
    now,
    pagination,
    q_bool,
    q_enum,
    q_str,
    req_dt,
    req_enum,
    req_int,
    req_str,
    respond,
    respond_array,
    respond_list,
    touch,
    update,
    v_bool,
    v_enum_list,
    v_int,
    v_num,
    v_str,
    MISSING,
)
from serialize import position_type_json, shift_bid_json, staffing_plan_json, position_slot_json

bp = Blueprint("staffing", __name__)

POSITION_CODES = ("USHER", "TICKET_TAKER", "ELEVATOR_OPERATOR", "GUEST_SERVICES_REP")
CERT_TYPES = (
    "ACCESSIBILITY_SERVICES",
    "EVACUATION_PROCEDURES",
    "CODE_OF_CONDUCT",
    "ELEVATOR_OPERATION",
)
PLAN_VARIANTS = ("FORECAST_BASED", "HISTORICAL_ACTUAL")
PLAN_STATUSES = ("DRAFT", "ACTIVE", "SUPERSEDED", "LOCKED", "VOIDED")
SLOT_STATUSES = (
    "OPEN",
    "PARTIALLY_FILLED",
    "FILLED",
    "UNDERSTAFFED_ESCALATED",
    "CLOSED",
)
PLAN_WRITABLE = ("DRAFT", "ACTIVE")

READ_ROLES = ("GuestExperienceDirector", "StaffingCoordinator", "GuestServicesSupervisor")


# ---------------------------------------------------------------------------
# position types
# ---------------------------------------------------------------------------

@bp.post("/position-types")
def create_position_type():
    auth("StaffingCoordinator")
    body = body_dict()
    code = req_enum(body, "code", POSITION_CODES)
    display_name = req_str(body, "display_name")
    rate = req_int(body, "base_hourly_rate_cents", minimum=0)
    ratio = body.get("attendance_ratio_per_1000", MISSING)
    if ratio is MISSING:
        raise invalid("attendance_ratio_per_1000 is required.")
    ratio = v_num(ratio, "attendance_ratio_per_1000", exclusive_minimum=0)
    min_headcount = req_int(body, "min_headcount", minimum=0)
    certs = body.get("required_certifications", MISSING)
    if certs is MISSING:
        raise invalid("required_certifications is required.")
    certs = v_enum_list(certs, "required_certifications", CERT_TYPES)
    tip = body.get("is_tip_eligible", MISSING)
    tip = False if tip is MISSING else v_bool(tip, "is_tip_eligible")
    contracted = body.get("is_contracted_position", MISSING)
    contracted = (
        False if contracted is MISSING else v_bool(contracted, "is_contracted_position")
    )
    row = new_record(
        "position_types",
        {
            "code": code,
            "display_name": display_name,
            "base_hourly_rate_cents": rate,
            "attendance_ratio_per_1000": ratio,
            "min_headcount": min_headcount,
            "required_certifications": certs,
            "is_tip_eligible": tip,
            "is_contracted_position": contracted,
        },
    )
    return respond(position_type_json(row), 201)


@bp.get("/position-types/<type_id>")
def read_position_type(type_id):
    auth(*READ_ROLES)
    return respond(position_type_json(lookup("position_types", type_id)))


@bp.get("/position-types")
def list_position_types():
    auth(*READ_ROLES)
    code = q_enum("code", POSITION_CODES)
    tip = q_bool("is_tip_eligible")
    limit, offset = pagination()
    rows = all_rows("position_types")
    if code is not None:
        rows = [r for r in rows if r["code"] == code]
    if tip is not None:
        rows = [r for r in rows if r["is_tip_eligible"] is tip]
    rows = sorted(rows, key=lambda r: r["code"])
    window = rows[offset:offset + limit]
    return respond_list(
        [position_type_json(r) for r in window], limit, offset, len(rows)
    )


@bp.patch("/position-types/<type_id>")
def update_position_type(type_id):
    auth("StaffingCoordinator")
    body = body_dict()
    changes = {}
    if "display_name" in body:
        changes["display_name"] = v_str(body["display_name"], "display_name")
    if "base_hourly_rate_cents" in body:
        changes["base_hourly_rate_cents"] = v_int(
            body["base_hourly_rate_cents"], "base_hourly_rate_cents", minimum=0
        )
    if "attendance_ratio_per_1000" in body:
        changes["attendance_ratio_per_1000"] = v_num(
            body["attendance_ratio_per_1000"],
            "attendance_ratio_per_1000",
            exclusive_minimum=0,
        )
    if "min_headcount" in body:
        changes["min_headcount"] = v_int(
            body["min_headcount"], "min_headcount", minimum=0
        )
    if "required_certifications" in body:
        changes["required_certifications"] = v_enum_list(
            body["required_certifications"], "required_certifications", CERT_TYPES
        )
    if "is_tip_eligible" in body:
        changes["is_tip_eligible"] = v_bool(body["is_tip_eligible"], "is_tip_eligible")
    if "is_contracted_position" in body:
        changes["is_contracted_position"] = v_bool(
            body["is_contracted_position"], "is_contracted_position"
        )
    row = lookup("position_types", type_id)
    # No retroactive repricing: slots and plans are deliberately left untouched.
    if not update(row, **changes):
        touch(row)
    return respond(position_type_json(row))


# ---------------------------------------------------------------------------
# staffing plans
# ---------------------------------------------------------------------------

def _basis_for(event, variant):
    if variant == "FORECAST_BASED":
        return event["expected_attendance"]
    return event["historical_actual_attendance"]


@bp.post("/staffing-plans")
def create_staffing_plan():
    auth("StaffingCoordinator")
    body = body_dict()
    event_id = req_str(body, "event_id")
    variant = req_enum(body, "plan_variant", PLAN_VARIANTS)
    event = lookup("events", event_id)
    basis = _basis_for(event, variant)
    if basis is None:
        raise conflict(
            "ERR_HISTORICAL_ATTENDANCE_MISSING",
            "The event has no historical_actual_attendance to plan against.",
        )
    revision = 1 + len(svc.plans_of_event(event))
    row = new_record(
        "staffing_plans",
        {
            "event_id": event_id,
            "plan_variant": variant,
            "revision_number": revision,
            "status": "DRAFT",
            "basis_attendance": basis,
            "basis_attendance_tier": calc.attendance_tier(basis)[0],
            "total_required_headcount": 0,
            "base_labor_cost_cents": 0,
            "accessibility_surcharge_cents": 0,
            "projected_labor_cost_cents": 0,
            "activated_at": None,
        },
    )
    return respond(staffing_plan_json(row), 201)


@bp.get("/staffing-plans/<plan_id>")
def read_staffing_plan(plan_id):
    auth(*READ_ROLES)
    return respond(staffing_plan_json(lookup("staffing_plans", plan_id)))


@bp.get("/staffing-plans")
def list_staffing_plans():
    auth(*READ_ROLES)
    event_id = q_str("event_id")
    status = q_enum("status", PLAN_STATUSES)
    variant = q_enum("plan_variant", PLAN_VARIANTS)
    limit, offset = pagination()
    rows = all_rows("staffing_plans")
    if event_id is not None:
        rows = [r for r in rows if r["event_id"] == event_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if variant is not None:
        rows = [r for r in rows if r["plan_variant"] == variant]
    window = rows[offset:offset + limit]
    return respond_list(
        [staffing_plan_json(r) for r in window], limit, offset, len(rows)
    )


@bp.post("/staffing-plans/<plan_id>/activate")
def activate_staffing_plan(plan_id):
    auth("StaffingCoordinator")
    body = body_dict()
    expected = req_int(body, "expected_event_version")
    plan = lookup("staffing_plans", plan_id)
    event = svc.event_of_plan(plan)
    # rung 9: the version guard sits before any status check and mutates nothing.
    if expected != event["version"]:
        raise err(
            "ERR_STALE_EVENT_VERSION",
            412,
            "expected_event_version %s does not match the event version %s."
            % (expected, event["version"]),
        )
    if plan["status"] != "DRAFT":
        raise conflict(
            "ERR_PLAN_STATE_INVALID",
            "Only a DRAFT plan can be activated (this one is %s)." % plan["status"],
        )
    if event["status"] not in ("FORECAST", "PLANNED"):
        raise conflict(
            "ERR_EVENT_STATE_INVALID",
            "An event in %s can no longer take an activation." % event["status"],
        )

    for other in svc.plans_of_event(event):
        if other["id"] != plan["id"] and other["status"] == "ACTIVE":
            svc.supersede_plan(other)

    update(plan, status="ACTIVE", activated_at=now())
    svc.recost_plan(plan)

    if event["status"] == "FORECAST":
        event["status"] = "PLANNED"
    touch(event)
    return respond(staffing_plan_json(plan))


# ---------------------------------------------------------------------------
# position slots
# ---------------------------------------------------------------------------

def _override(body, name="required_headcount_override"):
    value = body.get(name, MISSING)
    if value is MISSING or value is None:
        return value
    return v_int(value, name, minimum=1)


def _plan_writable(plan):
    if plan["status"] not in PLAN_WRITABLE:
        raise conflict(
            "ERR_PLAN_STATE_INVALID",
            "A %s plan does not accept shift-block writes." % plan["status"],
        )


@bp.post("/position-slots")
def create_position_slot():
    auth("StaffingCoordinator")
    body = body_dict()
    plan_id = req_str(body, "plan_id")
    position_type_id = req_str(body, "position_type_id")
    zone_code = req_str(body, "zone_code")
    shift_start = req_dt(body, "shift_start")
    shift_end = req_dt(body, "shift_end")
    override = _override(body)
    if override is MISSING:
        override = None
    if shift_end <= shift_start:
        raise bad_window("shift_end must be strictly after shift_start.")
    plan = lookup("staffing_plans", plan_id)
    position_type = lookup("position_types", position_type_id)
    _plan_writable(plan)

    computed = svc.slot_computed(plan, position_type, override, shift_start, shift_end)
    fields = {
        "plan_id": plan_id,
        "position_type_id": position_type_id,
        "zone_code": zone_code,
        "shift_start": shift_start,
        "shift_end": shift_end,
        "required_headcount_override": override,
        "filled_headcount": 0,
        "status": "OPEN",
    }
    fields.update(computed)
    row = new_record("position_slots", fields)
    svc.recost_plan(plan)
    return respond(position_slot_json(row), 201)


@bp.get("/position-slots/<slot_id>")
def read_position_slot(slot_id):
    auth(*ALL_ROLES)
    return respond(position_slot_json(lookup("position_slots", slot_id)))


@bp.get("/position-slots")
def list_position_slots():
    auth(*ALL_ROLES)
    plan_id = q_str("plan_id")
    position_type_id = q_str("position_type_id")
    status = q_enum("status", SLOT_STATUSES)
    zone_code = q_str("zone_code")
    limit, offset = pagination()
    rows = all_rows("position_slots")
    if plan_id is not None:
        rows = [r for r in rows if r["plan_id"] == plan_id]
    if position_type_id is not None:
        rows = [r for r in rows if r["position_type_id"] == position_type_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if zone_code is not None:
        rows = [r for r in rows if r["zone_code"] == zone_code]
    window = rows[offset:offset + limit]
    return respond_list(
        [position_slot_json(r) for r in window], limit, offset, len(rows)
    )


@bp.patch("/position-slots/<slot_id>")
def update_position_slot(slot_id):
    auth("StaffingCoordinator")
    body = body_dict()
    zone_code = MISSING
    if "zone_code" in body:
        zone_code = v_str(body["zone_code"], "zone_code")
    shift_start = MISSING
    if "shift_start" in body:
        shift_start = req_dt(body, "shift_start")
    shift_end = MISSING
    if "shift_end" in body:
        shift_end = req_dt(body, "shift_end")
    override = _override(body)
    if (
        shift_start is not MISSING
        and shift_end is not MISSING
        and shift_end <= shift_start
    ):
        raise bad_window("shift_end must be strictly after shift_start.")

    slot = lookup("position_slots", slot_id)
    start = slot["shift_start"] if shift_start is MISSING else shift_start
    end = slot["shift_end"] if shift_end is MISSING else shift_end
    if end <= start:
        raise bad_window("shift_end must be strictly after shift_start.")
    plan = svc.plan_of_slot(slot)
    _plan_writable(plan)
    if slot["status"] == "CLOSED":
        raise conflict(
            "ERR_SLOT_STATE_INVALID", "A CLOSED shift block can no longer be revised."
        )

    effective_override = (
        slot["required_headcount_override"] if override is MISSING else override
    )
    position_type = svc.position_type_of_slot(slot)
    changes = svc.slot_computed(plan, position_type, effective_override, start, end)
    changes["shift_start"] = start
    changes["shift_end"] = end
    changes["required_headcount_override"] = effective_override
    if zone_code is not MISSING:
        changes["zone_code"] = zone_code
    if slot["status"] != "UNDERSTAFFED_ESCALATED":
        changes["status"] = svc.derived_status(
            slot["filled_headcount"], changes["required_headcount"]
        )
    if not update(slot, **changes):
        touch(slot)
    svc.recost_plan(plan)
    return respond(position_slot_json(slot))


@bp.delete("/position-slots/<slot_id>")
def delete_position_slot(slot_id):
    auth("StaffingCoordinator")
    slot = lookup("position_slots", slot_id)
    plan = svc.plan_of_slot(slot)
    if plan["status"] != "DRAFT":
        raise conflict(
            "ERR_PLAN_STATE_INVALID",
            "Only a DRAFT plan allows a shift block to be removed.",
        )
    for assignment in svc.assignments_of_slot(slot):
        if assignment["attendance_status"] in svc.LIVE_ATTENDANCE:
            raise conflict(
                "ERR_SLOT_STATE_INVALID",
                "A live assignment still references this shift block.",
            )
    for bid in svc.bids_of_slot(slot):
        if bid["status"] in svc.LIVE_BID:
            raise conflict(
                "ERR_SLOT_STATE_INVALID",
                "A live bid still references this shift block.",
            )
    del db.position_slots[slot["id"]]
    svc.recost_plan(plan)
    return respond({}, 204)


@bp.post("/position-slots/<slot_id>/run-bid-award")
def run_bid_award(slot_id):
    auth("StaffingCoordinator")
    slot = lookup("position_slots", slot_id)
    if slot["status"] == "CLOSED":
        raise conflict(
            "ERR_SLOT_STATE_INVALID",
            "A CLOSED shift block cannot be adjudicated.",
        )
    plan = svc.plan_of_slot(slot)
    if plan["status"] != "ACTIVE":
        raise conflict(
            "ERR_PLAN_STATE_INVALID",
            "Bid adjudication requires the owning plan to stand in ACTIVE.",
        )
    position_type = svc.position_type_of_slot(slot)

    candidates = [b for b in svc.bids_of_slot(slot) if b["status"] in svc.LIVE_BID]
    eligible = []
    declined = []
    for bid in candidates:
        member = db.staff_members[bid["staff_member_id"]]
        # a worker already holding a live assignment on this very block trips the
        # rest check inside batch_eligibility_reason, which is the only decline
        # reason the batch vocabulary offers for that case.
        reason = svc.batch_eligibility_reason(member, slot, position_type)
        if reason is None:
            eligible.append((bid, member))
        else:
            declined.append((bid, reason))

    eligible.sort(
        key=lambda pair: (
            -pair[1]["reliability_score"],
            pair[1]["seniority_date"],
            pair[0]["created_at"],
            pair[0]["_seq"],
        )
    )

    touched = []
    for bid, member in eligible:
        was_waitlisted = bid["status"] == "WAITLISTED"
        if svc.has_capacity(slot):
            svc.create_assignment(slot, member, "BID_AWARD", shift_bid_id=bid["id"])
            update(
                bid,
                rank_score=member["reliability_score"],
                status="AWARDED",
                decision_reason=(
                    "AUTO_AWARD_RERUN" if was_waitlisted else "MANUAL_AWARD"
                ),
            )
        else:
            update(
                bid,
                rank_score=member["reliability_score"],
                status="WAITLISTED",
                decision_reason="CAPACITY_EXHAUSTED",
            )
        touched.append(bid)

    for bid, reason in declined:
        update(bid, status="DECLINED_BY_SYSTEM", decision_reason=reason)
        touched.append(bid)

    return respond_array([shift_bid_json(b) for b in touched])
