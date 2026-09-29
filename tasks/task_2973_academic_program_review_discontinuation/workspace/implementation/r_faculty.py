"""The faculty appointment state machine, the reduction sequence gate and
separation (PRD 3.11)."""

from flask import Blueprint

import derive
import envelope
import serial
import valid
from errors import ApiError
from guards import (ACTIONS_APPOINTMENT, HR, begin, program_of_appointment)
from store import days, db, now, touch

bp = Blueprint("faculty", __name__)

DECLARED_FROM = {
    "RETAIN": ("ASSIGNED",),
    "PROPOSE_REASSIGNMENT": ("ASSIGNED",),
    "WITHDRAW_REASSIGNMENT": ("REASSIGNMENT_PROPOSED",),
    "CONFIRM_REASSIGNMENT": ("REASSIGNMENT_PROPOSED",),
    "ISSUE_NOTICE": ("ASSIGNED",),
    "SEPARATE": ("NOTICE_ISSUED",),
}
LIVE_PLAN_STATES = ("APPROVED", "IN_EFFECT")


@bp.route("/provost/faculty-appointments/<aid>/transitions", methods=["POST"])
def transition_appointment(aid):
    ctx = begin((HR,))
    appointment = db.appointments.get(aid)
    ctx.require(appointment, "ERR_APPOINTMENT_NOT_FOUND")

    body = ctx.require_object_body()
    action = valid.req_enum(body, "action", ACTIONS_APPOINTMENT)
    department = None
    notice_days = None
    if action == "PROPOSE_REASSIGNMENT":
        department = valid.req_str(body, "reassigned_to_department_code", 2, 12)
    elif action == "ISSUE_NOTICE":
        notice_days = valid.req_int(body, "notice_days", minimum=0)

    program = program_of_appointment(appointment)
    ctx.not_terminal(program)

    if appointment["state"] not in DECLARED_FROM[action]:
        raise ApiError("ERR_APPOINTMENT_STATE_INVALID")

    live_plans = [p for p in derive.plans_of(appointment["program_id"])
                  if p["state"] in LIVE_PLAN_STATES]

    if action == "ISSUE_NOTICE":
        # check 41: only the head of the funded queue may be noticed
        water = derive.waterfall(program)
        positions = [water["positions"].get(a["id"])
                     for a in derive.appointments_of(program["id"])
                     if a["state"] == "ASSIGNED"]
        live = [p for p in positions if p is not None]
        mine = water["positions"].get(aid)
        if mine is None or not live or mine != min(live):
            raise ApiError("ERR_REDUCTION_SEQUENCE_VIOLATION")
        # check 42: the statutory floor
        if notice_days < derive.STATUTORY_NOTICE_DAYS[appointment["tenure_status"]]:
            raise ApiError("ERR_TENURE_NOTICE_TOO_SHORT")

    if action == "SEPARATE":
        # check 43 outranks check 44
        if appointment["tenure_status"] == "TENURED" and live_plans:
            raise ApiError("ERR_TENURE_OBLIGATION_ACTIVE")
        issued = appointment["notice_issued_at"]
        span = appointment["notice_days"] or 0
        if issued is None or now() < issued + days(span):
            raise ApiError("ERR_NOTICE_PERIOD_NOT_ELAPSED")

    if action == "RETAIN":
        # check 45: retention needs a live teach-out plan
        if not live_plans:
            raise ApiError("ERR_REASSIGNMENT_TARGET_INVALID")

    if action == "PROPOSE_REASSIGNMENT":
        # check 45: the target may not be the program's own department
        if program is not None and department == program["department_code"]:
            raise ApiError("ERR_REASSIGNMENT_TARGET_INVALID")

    if action == "RETAIN":
        appointment["state"] = "TEACH_OUT_RETAINED"
    elif action == "PROPOSE_REASSIGNMENT":
        appointment["state"] = "REASSIGNMENT_PROPOSED"
        appointment["reassigned_to_department_code"] = department
    elif action == "WITHDRAW_REASSIGNMENT":
        appointment["state"] = "ASSIGNED"
        appointment["reassigned_to_department_code"] = None
        appointment["reassignment_withdraw_count"] = (
            appointment["reassignment_withdraw_count"] + 1)
    elif action == "CONFIRM_REASSIGNMENT":
        appointment["state"] = "REASSIGNED"
    elif action == "ISSUE_NOTICE":
        appointment["state"] = "NOTICE_ISSUED"
        appointment["notice_days"] = notice_days
        appointment["notice_issued_at"] = now()
    else:
        appointment["state"] = "SEPARATED"
        appointment["separated_at"] = now()

    touch(appointment)
    if program is not None:
        touch(program)
    return envelope.ok(serial.appointment(appointment))
