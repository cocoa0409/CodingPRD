"""The logical clock, events, payout runs and the two computed event reads."""

from flask import Blueprint

import calc
import services as svc
from core import (
    ALL_ROLES,
    all_rows,
    auth,
    body_dict,
    conflict,
    db,
    err,
    fmt_dt,
    invalid,
    lookup,
    new_record,
    now,
    ordered,
    pagination,
    q_enum,
    q_str,
    req_dt,
    req_enum,
    req_int,
    req_str,
    respond,
    respond_array,
    respond_list,
    set_clock,
    touch,
    update,
    v_int,
    MISSING,
    bad_window,
)
from serialize import event_json, satisfaction_response_json

bp = Blueprint("events", __name__)

EVENT_STATUSES = ("FORECAST", "PLANNED", "IN_PROGRESS", "CLOSED", "CANCELLED")
READ_ONLY_EVENT_STATES = ("IN_PROGRESS", "CLOSED", "CANCELLED")
PAYOUT_PHASES = ("GRATUITY_ALLOCATION", "PAYROLL")


# ---------------------------------------------------------------------------
# logical clock (§2.4)
# ---------------------------------------------------------------------------

@bp.post("/_clock/set_current_utc")
def set_current_utc():
    auth(*ALL_ROLES)
    body = body_dict()
    instant = req_dt(body, "current_utc")
    set_clock(instant)
    return respond({"current_utc": fmt_dt(instant)})


# ---------------------------------------------------------------------------
# events
# ---------------------------------------------------------------------------

def _optional_attendance(body, name, current=MISSING):
    value = body.get(name, MISSING)
    if value is MISSING:
        return current
    if value is None:
        return None
    return v_int(value, name, minimum=0)


@bp.post("/events")
def create_event():
    auth("GuestExperienceDirector")
    body = body_dict()
    name = req_str(body, "name")
    event_date = req_dt(body, "event_date")
    doors_open_at = req_dt(body, "doors_open_at")
    doors_close_at = req_dt(body, "doors_close_at")
    expected_attendance = req_int(body, "expected_attendance", minimum=0)
    historical = _optional_attendance(body, "historical_actual_attendance", None)
    budget = body.get("refund_budget_total_cents", MISSING)
    budget = 100000 if budget is MISSING else v_int(
        budget, "refund_budget_total_cents", minimum=0
    )
    gratuity = body.get("gratuity_pool_cents", MISSING)
    gratuity = 0 if gratuity is MISSING else v_int(
        gratuity, "gratuity_pool_cents", minimum=0
    )
    if doors_close_at <= doors_open_at:
        raise bad_window("doors_close_at must be strictly after doors_open_at.")
    tier, _ = calc.attendance_tier(expected_attendance)
    row = new_record(
        "events",
        {
            "name": name,
            "event_date": event_date,
            "doors_open_at": doors_open_at,
            "doors_close_at": doors_close_at,
            "expected_attendance": expected_attendance,
            "historical_actual_attendance": historical,
            "attendance_tier": tier,
            "refund_budget_total_cents": budget,
            "refund_approved_total_cents": 0,
            "refund_budget_remaining_cents": budget,
            "gratuity_pool_cents": gratuity,
            "gratuity_allocated_cents": 0,
            "status": "FORECAST",
        },
    )
    return respond(event_json(row), 201)


@bp.get("/events/<event_id>")
def read_event(event_id):
    auth(*ALL_ROLES)
    return respond(event_json(lookup("events", event_id)))


@bp.get("/events")
def list_events():
    auth(*ALL_ROLES)
    status = q_enum("status", EVENT_STATUSES)
    limit, offset = pagination()
    rows = all_rows("events")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    # latest event_date first; created_at ascending survives as the tie-break
    rows = sorted(rows, key=lambda r: r["event_date"], reverse=True)
    window = rows[offset:offset + limit]
    return respond_list(
        [event_json(r) for r in window], limit, offset, len(rows)
    )


@bp.patch("/events/<event_id>")
def update_event(event_id):
    auth("GuestExperienceDirector")
    body = body_dict()
    name = body.get("name", MISSING)
    if name is not MISSING:
        name = req_str(body, "name")
    doors_open_at = body.get("doors_open_at", MISSING)
    if doors_open_at is not MISSING:
        doors_open_at = req_dt(body, "doors_open_at")
    doors_close_at = body.get("doors_close_at", MISSING)
    if doors_close_at is not MISSING:
        doors_close_at = req_dt(body, "doors_close_at")
    expected = body.get("expected_attendance", MISSING)
    if expected is not MISSING:
        expected = v_int(expected, "expected_attendance", minimum=0)
    historical = _optional_attendance(body, "historical_actual_attendance")
    budget = body.get("refund_budget_total_cents", MISSING)
    if budget is not MISSING:
        budget = v_int(budget, "refund_budget_total_cents", minimum=0)
    gratuity = body.get("gratuity_pool_cents", MISSING)
    if gratuity is not MISSING:
        gratuity = v_int(gratuity, "gratuity_pool_cents", minimum=0)
    # rung 4 outranks path existence, so a body carrying both bounds is judged here
    if (
        doors_open_at is not MISSING
        and doors_close_at is not MISSING
        and doors_close_at <= doors_open_at
    ):
        raise bad_window("doors_close_at must be strictly after doors_open_at.")

    event = lookup("events", event_id)
    open_at = event["doors_open_at"] if doors_open_at is MISSING else doors_open_at
    close_at = event["doors_close_at"] if doors_close_at is MISSING else doors_close_at
    if close_at <= open_at:
        raise bad_window("doors_close_at must be strictly after doors_open_at.")
    if event["status"] in READ_ONLY_EVENT_STATES:
        raise conflict(
            "ERR_EVENT_STATE_INVALID",
            "An event in %s can no longer be revised." % event["status"],
        )

    if name is not MISSING:
        event["name"] = name
    event["doors_open_at"] = open_at
    event["doors_close_at"] = close_at
    if expected is not MISSING:
        event["expected_attendance"] = expected
    if historical is not MISSING:
        event["historical_actual_attendance"] = historical
    if budget is not MISSING:
        event["refund_budget_total_cents"] = budget
    if gratuity is not MISSING:
        event["gratuity_pool_cents"] = gratuity
    event["attendance_tier"] = calc.attendance_tier(event["expected_attendance"])[0]

    for plan in svc.plans_of_event(event):
        if plan["status"] not in ("DRAFT", "ACTIVE"):
            continue
        basis = _basis_for(event, plan["plan_variant"])
        if basis is not None:
            update(
                plan,
                basis_attendance=basis,
                basis_attendance_tier=calc.attendance_tier(basis)[0],
            )
        for slot in svc.slots_of_plan(plan):
            if slot["status"] == "CLOSED":
                continue
            svc.size_slot(slot, plan=plan)
        svc.recost_plan(plan)

    svc.ledger_fields_only(event)
    touch(event)
    return respond(event_json(event))


def _basis_for(event, variant):
    if variant == "FORECAST_BASED":
        return event["expected_attendance"]
    return event["historical_actual_attendance"]


# ---------------------------------------------------------------------------
# event lifecycle (§3.3)
# ---------------------------------------------------------------------------

@bp.post("/events/<event_id>/lifecycle")
def event_lifecycle(event_id):
    auth("GuestExperienceDirector")
    body = body_dict()
    target = req_enum(body, "target_status", EVENT_STATUSES)
    reason = body.get("reason", MISSING)
    if reason is not MISSING and reason is not None:
        req_str(body, "reason")
    event = lookup("events", event_id)
    status = event["status"]

    declared = (
        (target == "IN_PROGRESS" and status == "PLANNED")
        or (target == "CLOSED" and status == "IN_PROGRESS")
        or (
            target == "CANCELLED"
            and status in ("FORECAST", "PLANNED", "IN_PROGRESS")
        )
    )
    if not declared:
        raise conflict(
            "ERR_EVENT_STATE_INVALID",
            "%s -> %s is not a declared event transition." % (status, target),
        )

    if target == "IN_PROGRESS":
        active = [p for p in svc.plans_of_event(event) if p["status"] == "ACTIVE"]
        if len(active) != 1:
            raise conflict(
                "ERR_PLAN_STATE_INVALID",
                "Exactly one ACTIVE staffing plan is required to start the event.",
            )
        update(active[0], status="LOCKED")
        event["status"] = "IN_PROGRESS"
    elif target == "CLOSED":
        locked = svc.plan_in_status(event, ("LOCKED",))
        slots = svc.slots_of_plan(locked) if locked else []
        for slot in slots:
            for assignment in svc.assignments_of_slot(slot):
                if assignment["attendance_status"] == "CHECKED_IN":
                    raise conflict(
                        "ERR_ASSIGNMENT_STATE_INVALID",
                        "A checked-in worker has not clocked out.",
                    )
        for slot in slots:
            released = False
            for assignment in svc.assignments_of_slot(slot):
                if assignment["attendance_status"] == "SCHEDULED":
                    update(
                        assignment,
                        attendance_status="RELEASED",
                        payout_status="VOIDED",
                        total_payout_cents=0,
                    )
                    released = True
            if released:
                svc.recount_slot(slot)
        event["status"] = "CLOSED"
    else:
        event["status"] = "CANCELLED"
        for plan in svc.plans_of_event(event):
            if plan["status"] in ("DRAFT", "ACTIVE", "LOCKED"):
                svc.void_plan(plan, "EVENT_CANCELLED")

    touch(event)
    return respond(event_json(event))


# ---------------------------------------------------------------------------
# payout runs (§3.10)
# ---------------------------------------------------------------------------

@bp.post("/events/<event_id>/payout-run")
def payout_run(event_id):
    auth("GuestExperienceDirector")
    body = body_dict()
    phase = req_enum(body, "phase", PAYOUT_PHASES)
    event = lookup("events", event_id)
    if event["status"] != "CLOSED":
        raise conflict(
            "ERR_PAYOUT_PHASE_INVALID",
            "The event must be CLOSED before a payout run.",
        )
    pending = [a for a in svc.assignments_of_event(event) if svc.gratuity_eligible(a)]
    if phase == "GRATUITY_ALLOCATION":
        if not pending:
            raise conflict(
                "ERR_PAYOUT_PHASE_INVALID",
                "No gratuity-eligible assignment is awaiting allocation.",
            )
        touched = svc.run_gratuity_allocation(event)
    else:
        if pending:
            raise conflict(
                "ERR_PAYOUT_PHASE_INVALID",
                "A gratuity-eligible assignment is still awaiting allocation.",
            )
        touched = svc.run_payroll(event)
    from serialize import staff_assignment_json

    return respond_array([staff_assignment_json(a) for a in touched])


# ---------------------------------------------------------------------------
# computed reads (§3.10)
# ---------------------------------------------------------------------------

@bp.get("/events/<event_id>/satisfaction-summary")
def satisfaction_summary(event_id):
    auth("GuestExperienceDirector", "GuestServicesSupervisor")
    zone_code = q_str("zone_code")
    event = lookup("events", event_id)
    return respond(svc.satisfaction_summary(event, zone_code))


@bp.get("/events/<event_id>/staffing-model-recommendation")
def staffing_model_recommendation(event_id):
    auth("GuestExperienceDirector", "StaffingCoordinator")
    event = lookup("events", event_id)
    if event["status"] != "CLOSED":
        raise conflict(
            "ERR_EVENT_STATE_INVALID",
            "The recommendation is only readable once the event is CLOSED.",
        )
    return respond(svc.staffing_recommendation(event))


# ---------------------------------------------------------------------------
# satisfaction responses (§3.10)
# ---------------------------------------------------------------------------

@bp.get("/events/<event_id>/satisfaction-responses")
def list_event_responses(event_id):
    auth("GuestExperienceDirector", "GuestServicesSupervisor")
    zone_code = q_str("zone_code")
    limit, offset = pagination()
    event = lookup("events", event_id)
    rows = svc.responses_of_event(event)
    if zone_code is not None:
        rows = [r for r in rows if r["zone_code"] == zone_code]
    window = rows[offset:offset + limit]
    return respond_list(
        [satisfaction_response_json(r) for r in window], limit, offset, len(rows)
    )


@bp.post("/satisfaction-responses")
def create_satisfaction_response():
    user_id, _ = auth("GuestServicesSupervisor", "GuestExperienceDirector")
    body = body_dict()
    event_id = req_str(body, "event_id")
    zone_code = req_str(body, "zone_code")
    score = req_int(body, "score", minimum=1, maximum=5)
    comment = body.get("comment", MISSING)
    if comment is MISSING:
        comment = None
    elif comment is not None:
        comment = req_str(body, "comment")
    lookup("events", event_id)
    row = new_record(
        "satisfaction_responses",
        {
            "event_id": event_id,
            "zone_code": zone_code,
            "score": score,
            "comment": comment,
            "submitted_by_user_id": user_id,
        },
        versioned=False,
    )
    return respond(satisfaction_response_json(row), 201)
