"""Sitter assignments: scheduling, the watch segments and handoff documentation
(PRD 3.4, 3.5 and 3.6)."""
from datetime import timedelta

from flask import Blueprint

import calc
import db as D
import serializers as S
import services as SVC
from db import (
    BREAK_ELIGIBILITY_MINUTES,
    COMPLETION_REASONS_CALLER,
    EARLY_START_GRACE_MINUTES,
    INTERVENTIONS,
    MAX_SHIFT_MINUTES,
    MIN_BREAK_MINUTES,
    MIN_REST_BUFFER_MINUTES,
    base_entity,
    db,
    touch,
    whole_minutes,
)
from errors import fail
from response import object_response
from validation import (
    authenticate,
    body_json,
    raw_opt_str,
    req_enum,
    req_enum_array,
    req_instant,
    req_int,
    req_str,
)

bp = Blueprint("assignments", __name__)

SITTER_ROLES = ("Sitter", "SystemAdmin")


# ---------------------------------------------------------------------------
# POST /observation/sitter-assignments
# ---------------------------------------------------------------------------
@bp.post("/observation/sitter-assignments")
def create_assignment():
    authenticate(("StaffingCoordinator", "SystemAdmin"))
    body = body_json()
    order_id = req_str(body, "order_id")
    staff_id = req_str(body, "staff_id")
    shift_start_at = req_instant(body, "shift_start_at")
    shift_end_at = req_instant(body, "shift_end_at")
    expected_order_version = req_int(body, "expected_order_version")
    float_code = raw_opt_str(body, "float_authorization_code")
    # Rung 5: body foreign keys, in the endpoint's declared field order.
    order = db.orders.get(order_id)
    if order is None:
        fail("ERR_ORDER_NOT_FOUND")
    staff = db.staff.get(staff_id)
    if staff is None:
        fail("ERR_STAFF_NOT_FOUND")
    # Rung 7: the single optimistic-concurrency guard in this API.
    if expected_order_version != order["version"]:
        fail("ERR_STALE_ORDER_VERSION",
             "expected_order_version %d does not match the order's current version %d."
             % (expected_order_version, order["version"]))
    # Rung 8: the order must still accept labor.
    if order["status"] in ("DISCONTINUED", "LAPSED"):
        fail("ERR_INVALID_ORDER_STATE", "The order has reached a terminal state.")
    # Rungs 10-13: observer fitness. Duty posture is deliberately NOT checked.
    if staff["deescalation_cert_expires_on"] <= db.clock:
        fail("ERR_DEESCALATION_CERT_EXPIRED",
             "The observer's de-escalation certification has expired.")
    if not _competency_ok(staff, order):
        fail("ERR_COMPETENCY_INSUFFICIENT", "The observer does not clear the competency floor.")
    if staff["status"] == "SUSPENDED":
        fail("ERR_STAFF_SUSPENDED", "The observer is suspended.")
    if staff["source_pool"] == "VOLUNTEER" and (
        "SELF_HARM" in order["risk_categories"] or "ELOPEMENT" in order["risk_categories"]
    ):
        fail("ERR_VOLUNTEER_NOT_ELIGIBLE",
             "A volunteer may not keep a self-harm or elopement watch.")
    # Rungs 17-19: the temporal gates, evaluated in the ladder's order.
    peers = calc.shift_peers(staff["id"])
    for peer in peers:
        if peer["shift_start_at"] < shift_end_at and shift_start_at < peer["shift_end_at"]:
            fail("ERR_STAFF_SHIFT_OVERLAP", "The observer already holds an overlapping shift.")
    for peer in peers:
        if shift_start_at >= peer["shift_end_at"]:
            gap = whole_minutes(shift_start_at - peer["shift_end_at"])
        else:
            gap = whole_minutes(peer["shift_start_at"] - shift_end_at)
        if gap < MIN_REST_BUFFER_MINUTES:
            fail("ERR_STAFF_REST_BUFFER_VIOLATION",
                 "The observer needs at least %d whole minutes between shifts."
                 % MIN_REST_BUFFER_MINUTES)
    if shift_end_at <= shift_start_at:
        fail("ERR_INVALID_SHIFT_WINDOW", "shift_end_at must be strictly later than shift_start_at.")
    minutes = whole_minutes(shift_end_at - shift_start_at)
    if minutes > MAX_SHIFT_MINUTES:
        fail("ERR_INVALID_SHIFT_WINDOW",
             "A shift may span at most %d whole minutes." % MAX_SHIFT_MINUTES)
    # Rung 26: cross-unit float authorization.
    unit = calc.unit_of_order(order)
    if unit is not None and staff["home_unit_id"] != unit["id"]:
        if float_code is None or float_code == "":
            fail("ERR_FLOAT_AUTHORIZATION_MISSING",
                 "A float authorization code is required for a cross-unit assignment.")
    # Rungs 28-29: the fiscal gates come last.
    provisional = calc.provisional_cost(staff["hourly_rate_cents"], minutes, staff["source_pool"])
    if unit is not None:
        if calc.ledger_head(unit) + provisional > unit["observation_cost_budget_cents"]:
            fail("ERR_UNIT_BUDGET_EXCEEDED", "The unit observation budget would be exceeded.")
        if unit["status"] == "RESTRICTED" and staff["source_pool"] == "AGENCY":
            fail("ERR_UNIT_RESTRICTED_AGENCY_BLOCKED",
                 "A restricted unit may not take on new agency labor.")
    assignment = base_entity()
    assignment.update({
        "order_id": order["id"],
        "staff_id": staff["id"],
        "shift_start_at": shift_start_at,
        "shift_end_at": shift_end_at,
        "float_authorization_code": float_code,
        "watch_status": "SCHEDULED",
        "documentation_status": "PENDING",
        "provisional_cost_cents": provisional,
        "final_cost_cents": None,
        "current_segment_started_at": None,
        "break_started_at": None,
        "completion_reason": None,
        "voided_at": None,
    })
    db.assignments[assignment["id"]] = assignment
    SVC.post_cost_entry(
        unit_id=unit["id"] if unit is not None else None,
        assignment_id=assignment["id"],
        entry_kind="PROVISIONAL",
        amount_cents=provisional,
        source_pool=staff["source_pool"],
    )
    touch(order)
    touch(unit)
    SVC.reeval_unit_budget(unit)
    touch(staff)
    return object_response(S.assignment_json(assignment), 201)


def _competency_ok(staff, order):
    level = staff["competency_level"]
    if level == "NOT_TRAINED":
        return False
    if "SELF_HARM" in order["risk_categories"]:
        return level == "ADVANCED"
    return level in ("BASIC", "ADVANCED")


def _assignment_or_404(assignment_id):
    assignment = db.assignments.get(assignment_id)
    if assignment is None:
        fail("ERR_ASSIGNMENT_NOT_FOUND")
    return assignment


# ---------------------------------------------------------------------------
# POST /observation/sitter-assignments/{id}/start-watch
# ---------------------------------------------------------------------------
@bp.post("/observation/sitter-assignments/<assignment_id>/start-watch")
def start_watch(assignment_id):
    caller = authenticate(SITTER_ROLES)
    body_json()
    assignment = _assignment_or_404(assignment_id)
    SVC.require_owner(caller, assignment["staff_id"])
    order = db.orders.get(assignment["order_id"])
    if order is None or order["status"] not in ("ACTIVE", "REASSESSMENT_DUE", "ESCALATED"):
        fail("ERR_INVALID_ORDER_STATE", "The order does not permit a watch to start.")
    if assignment["watch_status"] != "SCHEDULED":
        fail("ERR_INVALID_ASSIGNMENT_STATE", "A watch only starts from SCHEDULED.")
    staff = db.staff.get(assignment["staff_id"])
    if staff is None or staff["status"] != "AVAILABLE":
        fail("ERR_STAFF_NOT_AVAILABLE", "The observer is not available for duty.")
    earliest = assignment["shift_start_at"] - timedelta(minutes=EARLY_START_GRACE_MINUTES)
    if db.clock < earliest or db.clock >= assignment["shift_end_at"]:
        fail("ERR_OUTSIDE_SHIFT_WINDOW", "The clock is outside the permitted start window.")
    assignment["current_segment_started_at"] = db.clock
    assignment["watch_status"] = "ON_WATCH"
    touch(assignment)
    staff["status"] = "ON_ASSIGNMENT"
    touch(staff)
    return object_response(S.assignment_json(assignment))


# ---------------------------------------------------------------------------
# POST /observation/sitter-assignments/{id}/break-start
# ---------------------------------------------------------------------------
@bp.post("/observation/sitter-assignments/<assignment_id>/break-start")
def break_start(assignment_id):
    caller = authenticate(SITTER_ROLES)
    body_json()
    assignment = _assignment_or_404(assignment_id)
    SVC.require_owner(caller, assignment["staff_id"])
    if assignment["watch_status"] != "ON_WATCH":
        fail("ERR_INVALID_ASSIGNMENT_STATE", "Break relief only starts from ON_WATCH.")
    elapsed = whole_minutes(db.clock - assignment["current_segment_started_at"])
    if elapsed < BREAK_ELIGIBILITY_MINUTES:
        fail("ERR_BREAK_NOT_YET_ELIGIBLE",
             "At least %d whole minutes must elapse on the open segment."
             % BREAK_ELIGIBILITY_MINUTES)
    SVC.close_open_segment(assignment)
    assignment["break_started_at"] = db.clock
    assignment["watch_status"] = "ON_BREAK"
    touch(assignment)
    staff = db.staff.get(assignment["staff_id"])
    touch(staff)
    unit = calc.unit_of_assignment(assignment)
    touch(unit)
    SVC.reeval_unit_budget(unit)
    return object_response(S.assignment_json(assignment))


# ---------------------------------------------------------------------------
# POST /observation/sitter-assignments/{id}/break-end
# ---------------------------------------------------------------------------
@bp.post("/observation/sitter-assignments/<assignment_id>/break-end")
def break_end(assignment_id):
    caller = authenticate(SITTER_ROLES)
    body_json()
    assignment = _assignment_or_404(assignment_id)
    SVC.require_owner(caller, assignment["staff_id"])
    if assignment["watch_status"] != "ON_BREAK":
        fail("ERR_INVALID_ASSIGNMENT_STATE", "A watch only resumes from ON_BREAK.")
    elapsed = whole_minutes(db.clock - assignment["break_started_at"])
    if elapsed < MIN_BREAK_MINUTES:
        fail("ERR_BREAK_TOO_SHORT",
             "A break must last at least %d whole minutes." % MIN_BREAK_MINUTES)
    # No ledger row whatsoever: break minutes are never billed.
    assignment["current_segment_started_at"] = db.clock
    assignment["break_started_at"] = None
    assignment["watch_status"] = "ON_WATCH"
    touch(assignment)
    return object_response(S.assignment_json(assignment))


# ---------------------------------------------------------------------------
# POST /observation/sitter-assignments/{id}/complete
# ---------------------------------------------------------------------------
@bp.post("/observation/sitter-assignments/<assignment_id>/complete")
def complete_watch(assignment_id):
    caller = authenticate(SITTER_ROLES)
    body = body_json()
    completion_reason = req_enum(body, "completion_reason", COMPLETION_REASONS_CALLER)
    assignment = _assignment_or_404(assignment_id)
    SVC.require_owner(caller, assignment["staff_id"])
    if assignment["watch_status"] != "ON_WATCH":
        fail("ERR_INVALID_ASSIGNMENT_STATE", "A watch is only completed from ON_WATCH.")
    # The single coupling point between the two state dimensions.
    if completion_reason == "HANDOFF_COMPLETE" and assignment["documentation_status"] != "HANDOFF_SIGNED":
        fail("ERR_HANDOFF_NOT_SIGNED",
             "A HANDOFF_COMPLETE closure requires signed handoff documentation.")
    SVC.close_open_segment(assignment)
    SVC.reverse_provisional(assignment)
    assignment["watch_status"] = "COMPLETED"
    assignment["completion_reason"] = completion_reason
    assignment["final_cost_cents"] = calc.final_cost_from_ledger(assignment)
    order = db.orders.get(assignment["order_id"])
    if completion_reason == "SHIFT_END_NO_SUCCESSOR":
        SVC.waive_documentation(assignment)
        if order is not None and order["status"] in D.ORDER_NON_TERMINAL:
            order["coverage_gap_flag"] = True
            touch(order)
    touch(assignment)
    staff = db.staff.get(assignment["staff_id"])
    if staff is not None and staff["status"] == "ON_ASSIGNMENT":
        staff["status"] = "AVAILABLE"
    touch(staff)
    unit = calc.unit_of_assignment(assignment)
    touch(unit)
    SVC.reeval_unit_budget(unit)
    return object_response(S.assignment_json(assignment))


# ---------------------------------------------------------------------------
# POST /observation/sitter-assignments/{id}/void
# ---------------------------------------------------------------------------
@bp.post("/observation/sitter-assignments/<assignment_id>/void")
def void_watch(assignment_id):
    authenticate(("NurseManager", "SystemAdmin"))
    body_json()
    assignment = _assignment_or_404(assignment_id)
    if assignment["watch_status"] != "SCHEDULED":
        fail("ERR_INVALID_ASSIGNMENT_STATE", "Only a watch that has not started may be voided.")
    SVC.system_void_assignment(assignment)
    # A reversal never changes the unit's posture; only the cost close lifts it.
    touch(calc.unit_of_assignment(assignment))
    return object_response(S.assignment_json(assignment))


# ---------------------------------------------------------------------------
# POST /observation/handoffs
# ---------------------------------------------------------------------------
@bp.post("/observation/handoffs")
def draft_handoff():
    caller = authenticate(SITTER_ROLES)
    body = body_json()
    outgoing_id = req_str(body, "outgoing_assignment_id")
    incoming_id = req_str(body, "incoming_assignment_id")
    behavior_summary = req_str(body, "behavior_summary", 1, 500)
    interventions = req_enum_array(
        body, "interventions_used", INTERVENTIONS, non_empty=False, unique=False
    )
    outgoing = db.assignments.get(outgoing_id)
    if outgoing is None:
        fail("ERR_ASSIGNMENT_NOT_FOUND")
    incoming = db.assignments.get(incoming_id)
    if incoming is None:
        fail("ERR_ASSIGNMENT_NOT_FOUND")
    SVC.require_owner(caller, outgoing["staff_id"])
    if outgoing["documentation_status"] != "PENDING":
        fail("ERR_INVALID_HANDOFF_STATE",
             "The outgoing watch already carries handoff documentation.")
    if outgoing["watch_status"] not in ("ON_WATCH", "ON_BREAK"):
        fail("ERR_INVALID_ASSIGNMENT_STATE",
             "The outgoing watch must be ON_WATCH or ON_BREAK.")
    if incoming["watch_status"] != "SCHEDULED":
        fail("ERR_INVALID_ASSIGNMENT_STATE", "The incoming watch must be SCHEDULED.")
    if incoming["order_id"] != outgoing["order_id"] or incoming["id"] == outgoing["id"]:
        fail("ERR_HANDOFF_ORDER_MISMATCH",
             "The two watches must be distinct watches on the same order.")
    record = base_entity()
    record.update({
        "outgoing_assignment_id": outgoing["id"],
        "incoming_assignment_id": incoming["id"],
        "behavior_summary": behavior_summary,
        "interventions_used": interventions,
        "countersigned_by_staff_id": None,
        "countersigned_at": None,
        "documentation_state": "DRAFTED",
    })
    db.handoffs[record["id"]] = record
    # The watch dimension is left completely untouched.
    outgoing["documentation_status"] = "HANDOFF_DRAFTED"
    touch(outgoing)
    return object_response(S.handoff_json(record), 201)


# ---------------------------------------------------------------------------
# POST /observation/handoffs/{id}/countersign
# ---------------------------------------------------------------------------
@bp.post("/observation/handoffs/<handoff_id>/countersign")
def countersign_handoff(handoff_id):
    caller = authenticate(SITTER_ROLES)
    body_json()
    record = db.handoffs.get(handoff_id)
    if record is None:
        fail("ERR_HANDOFF_NOT_FOUND")
    incoming = db.assignments.get(record["incoming_assignment_id"])
    outgoing = db.assignments.get(record["outgoing_assignment_id"])
    SVC.require_owner(caller, incoming["staff_id"] if incoming else None)
    if record["documentation_state"] != "DRAFTED":
        fail("ERR_INVALID_HANDOFF_STATE", "The handoff is already signed.")
    if incoming is not None and outgoing is not None and incoming["staff_id"] == outgoing["staff_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "A sitter may not countersign their own handoff report.")
    record["documentation_state"] = "SIGNED"
    record["countersigned_by_staff_id"] = caller.user_id
    record["countersigned_at"] = db.clock
    touch(record)
    if outgoing is not None:
        if outgoing["documentation_status"] == "HANDOFF_DRAFTED":
            outgoing["documentation_status"] = "HANDOFF_SIGNED"
        touch(outgoing)
    return object_response(S.handoff_json(record))
