"""Displaced students: enrolment, advising, and the close-out branches
(PRD 3.10)."""

from flask import Blueprint

import cascade
import derive
import envelope
import filters
import serial
import valid
from errors import ApiError
from guards import (ACTIONS_PROGRESS, CHAIR, COORD, PROVOST, REGISTRAR, begin,
                    program_of_plan, program_of_student)
from store import by_created, db, new_row, now, touch

bp = Blueprint("students", __name__)

TERMINAL_ADVISING = ("COMPLETED", "WITHDRAWN")
PLAN_STATES_CLOSED_TO_CHILDREN = ("COMPLETED", "SUPERSEDED")
PLAN_STATES_FOR_ADVISING = ("DRAFT", "SUBMITTED", "APPROVED", "IN_EFFECT")


@bp.route("/provost/teach-out-plans/<pid>/displaced-students", methods=["POST"])
def create_student(pid):
    ctx = begin((REGISTRAR,))
    plan = db.plans.get(pid)
    ctx.require(plan, "ERR_PLAN_NOT_FOUND")

    body = ctx.require_object_body()
    number = valid.req_str(body, "student_number", 4, 20)
    credits = valid.req_int(body, "credits_remaining", minimum=0)
    max_credits = valid.req_int(body, "max_credits_per_term", 1, 21)
    for existing in derive.students_of(pid):
        if existing["student_number"] == number:
            valid.fail("student_number must be unique within the plan.")

    ctx.not_terminal(program_of_plan(plan))

    if plan["state"] in PLAN_STATES_CLOSED_TO_CHILDREN:
        raise ApiError("ERR_PLAN_STATE_INVALID")

    row = new_row()
    row.update({
        "teach_out_plan_id": pid,
        "student_number": number,
        "credits_remaining": credits,
        "max_credits_per_term": max_credits,
        "advised_credits_per_term": None,
        "advising_status": "PENDING",
        "completion_term_index": None,
        "withdrawal_reason_code": None,
        "advised_at": None,
    })
    db.students[row["id"]] = row
    touch(plan)
    return envelope.created(serial.student(row))


@bp.route("/provost/teach-out-plans/<pid>/displaced-students", methods=["GET"])
def list_students(pid):
    ctx = begin((REGISTRAR, PROVOST, COORD, CHAIR))
    plan = db.plans.get(pid)
    ctx.chair_owner(program_of_plan(plan))
    ctx.require(plan, "ERR_PLAN_NOT_FOUND")
    rows = by_created(derive.students_of(pid))
    rows = filters.apply_string(rows, "advising_status", "advising_status")
    rows = filters.apply_bool(
        rows, "at_risk", "at_risk",
        lambda r: derive.student_projection(r)["at_risk"])
    return envelope.paginate(rows, serial.student)


@bp.route("/provost/displaced-students/<sid>/advising", methods=["POST"])
def advise_student(sid):
    ctx = begin((REGISTRAR,))
    student = db.students.get(sid)
    ctx.require(student, "ERR_STUDENT_NOT_FOUND")

    body = ctx.require_object_body()
    advised = valid.req_int(body, "advised_credits_per_term", 1, 21)
    if advised > student["max_credits_per_term"]:
        valid.fail("advised_credits_per_term must not exceed "
                   "max_credits_per_term.")
    plan_signed = valid.req_bool(body, "plan_signed")

    ctx.not_terminal(program_of_student(student))

    if student["advising_status"] not in ("PENDING", "ADVISED"):
        raise ApiError("ERR_STUDENT_STATE_INVALID")

    plan = db.plans.get(student["teach_out_plan_id"])
    if plan is None or plan["state"] not in PLAN_STATES_FOR_ADVISING:
        raise ApiError("ERR_PLAN_STATE_INVALID")

    student["advised_credits_per_term"] = advised
    student["advised_at"] = now()
    student["advising_status"] = "PLAN_SIGNED" if plan_signed else "ADVISED"
    touch(student)
    return envelope.ok(serial.student(student))


@bp.route("/provost/displaced-students/<sid>/progress", methods=["POST"])
def student_progress(sid):
    ctx = begin((REGISTRAR,))
    student = db.students.get(sid)
    ctx.require(student, "ERR_STUDENT_NOT_FOUND")

    body = ctx.require_object_body()
    action = valid.req_enum(body, "action", ACTIONS_PROGRESS)
    completion_term = None
    withdrawal_reason = None
    if action == "COMPLETE":
        completion_term = valid.opt_term_index(body, "completion_term_index")
    else:
        withdrawal_reason = valid.opt_str(body, "withdrawal_reason_code", 1, 40)

    ctx.not_terminal(program_of_student(student))

    # check 12's carve-out: only an already terminal student reports here
    if student["advising_status"] in TERMINAL_ADVISING:
        raise ApiError("ERR_STUDENT_STATE_INVALID")

    plan = db.plans.get(student["teach_out_plan_id"])

    if action == "COMPLETE":
        if plan is None or plan["state"] != "IN_EFFECT":
            raise ApiError("ERR_PLAN_STATE_INVALID")
        if student["advising_status"] != "PLAN_SIGNED":
            raise ApiError("ERR_ADVISING_REQUIRED")
        student["completion_term_index"] = completion_term
        student["advising_status"] = "COMPLETED"
    else:
        student["withdrawal_reason_code"] = withdrawal_reason
        student["advising_status"] = "WITHDRAWN"

    derive.release_all_holdings(student["id"])
    touch(student)

    if plan is not None:
        cascade.maybe_complete_plan(plan)
    return envelope.ok(serial.student(student))
