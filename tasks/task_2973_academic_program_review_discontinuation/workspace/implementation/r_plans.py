"""Teach-out plans, course guarantees and the seat ledger (PRD 3.9)."""

from flask import Blueprint

import cascade
import derive
import envelope
import filters
import serial
import valid
from errors import ApiError
from guards import (ACTIONS_PLAN, ACTIONS_SEAT, CHAIR, COORD, HR, OWNERS_PLAN,
                    PROVOST, REGISTRAR, begin, program_of_guarantee,
                    program_of_plan)
from store import by_created, db, new_row, now, touch

bp = Blueprint("plans", __name__)

PLAN_STATES_CLOSED_TO_CHILDREN = ("COMPLETED", "SUPERSEDED")
PLAN_STATES_FOR_ADVISING = ("DRAFT", "SUBMITTED", "APPROVED", "IN_EFFECT")


@bp.route("/provost/teach-out-plans", methods=["GET"])
def list_plans():
    begin((CHAIR, PROVOST, COORD, REGISTRAR, HR))
    rows = by_created(db.plans.values())
    rows = filters.apply_string(rows, "program_id", "program_id")
    rows = filters.apply_string(rows, "decision_id", "decision_id")
    rows = filters.apply_string(rows, "state", "state")
    return envelope.paginate(rows, serial.plan)


@bp.route("/provost/teach-out-plans/<pid>", methods=["GET"])
def get_plan(pid):
    ctx = begin((CHAIR, PROVOST, COORD, REGISTRAR))
    plan = db.plans.get(pid)
    ctx.chair_owner(program_of_plan(plan))
    ctx.require(plan, "ERR_PLAN_NOT_FOUND")
    return envelope.ok(serial.plan(plan))


# --------------------------------------------------------------------------
# the plan state machine
# --------------------------------------------------------------------------

@bp.route("/provost/teach-out-plans/<pid>/transitions", methods=["POST"])
def transition_plan(pid):
    ctx = begin((CHAIR, PROVOST, COORD), OWNERS_PLAN)
    plan = db.plans.get(pid)
    ctx.chair_owner(program_of_plan(plan))
    ctx.require(plan, "ERR_PLAN_NOT_FOUND")

    body = ctx.require_object_body()
    action = valid.req_enum(body, "action", ACTIONS_PLAN)
    revision_notes = None
    if action == "RETURN":
        revision_notes = valid.opt_str(body, "revision_notes", 1, 2000)

    program = program_of_plan(plan)
    ctx.not_terminal(program)

    decision = db.decisions.get(plan["decision_id"])

    if action == "SUBMIT":
        if plan["state"] != "DRAFT":
            raise ApiError("ERR_PLAN_STATE_INVALID")
        if decision is None or decision["state"] not in ("RATIFIED", "EFFECTUATED"):
            raise ApiError("ERR_DECISION_STATE_INVALID")
        plan["state"] = "SUBMITTED"
        touch(plan)
        return envelope.ok(serial.plan(plan))

    if action == "RETURN":
        if plan["state"] != "SUBMITTED":
            raise ApiError("ERR_PLAN_STATE_INVALID")
        if plan["plan_revision_round"] >= 3:
            raise ApiError("ERR_REVISION_LIMIT_REACHED")
        plan["state"] = "DRAFT"
        plan["plan_revision_round"] = plan["plan_revision_round"] + 1
        plan["revision_notes"] = revision_notes
        touch(plan)
        return envelope.ok(serial.plan(plan))

    if action == "APPROVE":
        if plan["state"] != "SUBMITTED":
            raise ApiError("ERR_PLAN_STATE_INVALID")
        ledger = derive.plan_ledger(plan)
        if ledger["seat_shortfall"] != 0:
            raise ApiError("ERR_COURSE_GUARANTEE_SHORTFALL")
        if ledger["at_risk_student_count"] != 0:
            raise ApiError("ERR_AT_RISK_STUDENTS_PRESENT")
        plan["state"] = "APPROVED"
        plan["approved_at"] = now()
        touch(plan)
        return envelope.ok(serial.plan(plan))

    # ACTIVATE
    if plan["state"] != "APPROVED":
        raise ApiError("ERR_PLAN_STATE_INVALID")
    if decision is None or decision["state"] != "EFFECTUATED":
        raise ApiError("ERR_DECISION_NOT_EFFECTUATED")

    plan["state"] = "IN_EFFECT"
    plan["activated_at"] = now()
    touch(plan)

    for guarantee in by_created(derive.guarantees_of(plan["id"])):
        if (guarantee["status"] == "PLANNED"
                and guarantee["term_index"] <= plan["first_teach_out_term_index"]):
            guarantee["status"] = "OFFERED"
            touch(guarantee)

    # the empty-cohort case completes the plan inside the same request
    cascade.maybe_complete_plan(plan)
    return envelope.ok(serial.plan(plan))


# --------------------------------------------------------------------------
# course guarantees
# --------------------------------------------------------------------------

@bp.route("/provost/teach-out-plans/<pid>/course-guarantees", methods=["POST"])
def create_guarantee(pid):
    ctx = begin((CHAIR,))
    plan = db.plans.get(pid)
    ctx.chair_owner(program_of_plan(plan))
    ctx.require(plan, "ERR_PLAN_NOT_FOUND")

    body = ctx.require_object_body()
    course_code = valid.req_str(body, "course_code", 3, 16)
    term_index = valid.req_term_index(body, "term_index")
    seats = valid.req_int(body, "seats_guaranteed", minimum=1)

    ctx.not_terminal(program_of_plan(plan))

    if plan["state"] in PLAN_STATES_CLOSED_TO_CHILDREN:
        raise ApiError("ERR_PLAN_STATE_INVALID")

    row = new_row()
    row.update({
        "teach_out_plan_id": pid,
        "course_code": course_code,
        "term_index": term_index,
        "seats_guaranteed": seats,
        "status": "PLANNED",
        "substitute_course_code": None,
        "substitution_justification": None,
        "waived_reason_code": None,
    })
    db.guarantees[row["id"]] = row
    touch(plan)
    return envelope.created(serial.guarantee(row))


@bp.route("/provost/teach-out-plans/<pid>/course-guarantees", methods=["GET"])
def list_guarantees(pid):
    ctx = begin((CHAIR, PROVOST, REGISTRAR, COORD))
    plan = db.plans.get(pid)
    ctx.chair_owner(program_of_plan(plan))
    ctx.require(plan, "ERR_PLAN_NOT_FOUND")
    rows = by_created(derive.guarantees_of(pid))
    rows = filters.apply_string(rows, "status", "status")
    rows = filters.apply_int(rows, "term_index", "term_index")
    return envelope.paginate(rows, serial.guarantee)


# --------------------------------------------------------------------------
# the seat ledger and the guarantee status axis
# --------------------------------------------------------------------------

@bp.route("/provost/course-guarantees/<gid>/seat-allocations", methods=["POST"])
def seat_allocation(gid):
    ctx = begin((REGISTRAR,))
    guarantee = db.guarantees.get(gid)
    ctx.require(guarantee, "ERR_GUARANTEE_NOT_FOUND")

    # check 8: the body foreign key
    student = None
    if ctx.body is not None and ctx.body.get("displaced_student_id") is not None:
        supplied = ctx.body.get("displaced_student_id")
        student = db.students.get(supplied) if isinstance(supplied, str) else None
        if student is None:
            raise ApiError("ERR_STUDENT_NOT_FOUND")

    body = ctx.require_object_body()
    action = valid.req_enum(body, "action", ACTIONS_SEAT)
    seat_count = None
    substitute = None
    justification = None
    waived_reason = None
    if action in ("COMMIT", "RELEASE"):
        valid.req_str(body, "displaced_student_id", 1, 200)
        seat_count = valid.req_int(body, "seat_count", minimum=1)
    elif action == "SUBSTITUTE":
        substitute = valid.req_str(body, "substitute_course_code", 3, 16)
        if substitute == guarantee["course_code"]:
            valid.fail("substitute_course_code must differ from course_code.")
        justification = valid.req_str(body, "substitution_justification", 1, 2000)
    else:
        waived_reason = valid.opt_str(body, "waived_reason_code", 1, 40)

    ctx.not_terminal(program_of_guarantee(guarantee))

    if action in ("COMMIT", "RELEASE"):
        if guarantee["status"] == "WAIVED":
            raise ApiError("ERR_GUARANTEE_STATE_INVALID")
    elif action == "SUBSTITUTE":
        if guarantee["status"] not in ("PLANNED", "OFFERED"):
            raise ApiError("ERR_GUARANTEE_STATE_INVALID")
    else:
        if guarantee["status"] == "WAIVED":
            raise ApiError("ERR_GUARANTEE_STATE_INVALID")

    if action == "COMMIT":
        committed = derive.guarantee_committed(gid)
        if committed + seat_count > guarantee["seats_guaranteed"]:
            raise ApiError("ERR_SEAT_CAPACITY_EXCEEDED")
        key = (gid, student["id"])
        db.holdings[key] = db.holdings.get(key, 0) + seat_count
        touch(guarantee)
        return envelope.ok(serial.guarantee(guarantee))

    if action == "RELEASE":
        key = (gid, student["id"])
        held = db.holdings.get(key, 0)
        if held < seat_count:
            raise ApiError("ERR_SEAT_NOT_COMMITTED")
        if derive.student_committed(student["id"]) - seat_count < 0:
            raise ApiError("ERR_SEAT_NOT_COMMITTED")
        remaining = held - seat_count
        if remaining == 0:
            del db.holdings[key]
        else:
            db.holdings[key] = remaining
        touch(guarantee)
        return envelope.ok(serial.guarantee(guarantee))

    if action == "SUBSTITUTE":
        guarantee["status"] = "SUBSTITUTED"
        guarantee["substitute_course_code"] = substitute
        guarantee["substitution_justification"] = justification
        touch(guarantee)
        return envelope.ok(serial.guarantee(guarantee))

    # WAIVE
    if derive.guarantee_committed(gid) != 0:
        raise ApiError("ERR_GUARANTEE_HAS_COMMITMENTS")
    guarantee["status"] = "WAIVED"
    guarantee["waived_reason_code"] = waived_reason
    touch(guarantee)
    return envelope.ok(serial.guarantee(guarantee))
