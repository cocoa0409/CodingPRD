"""Decision records: ratification, effectuation, rescission, improvement
monitoring, and the agency-notification channel (PRD 3.6 to 3.8)."""

from decimal import Decimal

from flask import Blueprint

import cascade
import derive
import envelope
import filters
import serial
import valid
from errors import ApiError
from guards import (ACTIONS_DECISION, ACTIONS_NOTIFICATION, CHAIR, COORD, HR,
                    OWNERS_DECISION, PROVOST, REGISTRAR, begin,
                    program_of_decision, program_of_notification)
from store import by_created, db, new_row, now, touch

bp = Blueprint("decisions", __name__)

AGENCY_TYPES = ("ACCREDITOR", "STATE_AGENCY", "FEDERAL")
LIFECYCLE_ON_RATIFY = {
    "CONTINUE": "ACTIVE",
    "IMPROVEMENT_PLAN": "IMPROVEMENT_MONITORED",
    "CONSOLIDATION": "CONSOLIDATION_PENDING",
    "DISCONTINUATION": "TEACH_OUT_PENDING",
}
WIND_DOWN = ("CONSOLIDATION", "DISCONTINUATION")


@bp.route("/provost/decision-records", methods=["GET"])
def list_decisions():
    begin((PROVOST, COORD, CHAIR, REGISTRAR, HR))
    rows = by_created(db.decisions.values())
    rows = filters.apply_string(rows, "cycle_id", "cycle_id")
    rows = filters.apply_string(rows, "receiving_program_id",
                                "receiving_program_id")
    rows = filters.apply_string(rows, "outcome", "outcome")
    rows = filters.apply_string(rows, "state", "state")
    return envelope.paginate(rows, serial.decision)


@bp.route("/provost/decision-records/<did>", methods=["GET"])
def get_decision(did):
    ctx = begin((PROVOST, COORD, CHAIR, REGISTRAR, HR))
    decision = db.decisions.get(did)
    ctx.chair_owner(program_of_decision(decision))
    ctx.require(decision, "ERR_DECISION_NOT_FOUND")
    return envelope.ok(serial.decision(decision))


# --------------------------------------------------------------------------
# the four transitions
# --------------------------------------------------------------------------

@bp.route("/provost/decision-records/<did>/transitions", methods=["POST"])
def transition_decision(did):
    ctx = begin((PROVOST, COORD), OWNERS_DECISION)
    decision = db.decisions.get(did)
    ctx.segregation(decision)
    ctx.require(decision, "ERR_DECISION_NOT_FOUND")

    body = ctx.require_object_body()
    action = valid.req_enum(body, "action", ACTIONS_DECISION)
    note = None
    reason = None
    if action == "RATIFY":
        note = valid.opt_str(body, "ratification_note", 1, 2000)
    elif action == "RESCIND":
        reason = valid.opt_str(body, "rescission_reason", 1, 2000)

    program = program_of_decision(decision)
    ctx.not_terminal(program)

    cycle = db.cycles.get(decision["cycle_id"])

    if action == "RATIFY":
        return _ratify(decision, cycle, program, ctx.user_id, note)
    if action == "EFFECTUATE":
        return _effectuate(decision, cycle, program)
    if action == "RESCIND":
        return _rescind(decision, cycle, program, reason)
    return _evaluate_improvement(decision, cycle, program)


def _ratify(decision, cycle, program, user_id, note):
    if decision["state"] != "PROPOSED":
        raise ApiError("ERR_DECISION_STATE_INVALID")

    decision["state"] = "RATIFIED"
    decision["ratified_by_user_id"] = user_id
    decision["ratification_note"] = note
    decision["ratified_at"] = now()
    touch(decision)

    # hop 1: the cycle decides
    if cycle is not None and cycle["state"] == "DECISION_PROPOSED":
        cycle["state"] = "DECIDED"
        cycle["decided_at"] = decision["ratified_at"]
        touch(cycle)

    # hop 2: the program takes the branch that matches the outcome
    if program is not None:
        target = LIFECYCLE_ON_RATIFY[decision["outcome"]]
        if program["lifecycle_state"] == "UNDER_REVIEW":
            program["lifecycle_state"] = target
        # hop 3: the wind-down branches suppress marketing and mint notices
        if decision["outcome"] in WIND_DOWN:
            program["catalog_status_pre_decision"] = program["catalog_status"]
            if program["catalog_status"] == "LISTED":
                program["catalog_status"] = "MARKETING_SUPPRESSED"
        touch(program)

    if decision["outcome"] in WIND_DOWN:
        cascade.mint_auto_notifications(decision)

    # hop 4: compliance_posture is derived, so it has already recomputed
    return envelope.ok(serial.decision(decision))


def _effectuate(decision, cycle, program):
    if decision["state"] != "RATIFIED":
        raise ApiError("ERR_DECISION_STATE_INVALID")

    # check 29: the receiving program's eligibility is re-tested
    receiving = None
    if decision["receiving_program_id"] is not None:
        receiving = db.programs.get(decision["receiving_program_id"])
        if (receiving is None
                or receiving["lifecycle_state"] != "ACTIVE"
                or derive.composite_score(receiving)[1] != "CONTINUE_ELIGIBLE"):
            raise ApiError("ERR_RECEIVING_PROGRAM_INELIGIBLE")

    # check 31: the compliance gate outranks the funding gate
    if derive.notification_counters(decision)[1] != 0:
        raise ApiError("ERR_AGENCY_NOTICE_NOT_ACKNOWLEDGED")

    # check 32: a discontinuation needs an approved teach-out plan
    if decision["outcome"] == "DISCONTINUATION":
        linked = [p for p in db.plans.values()
                  if p["decision_id"] == decision["id"]]
        if not any(p["state"] == "APPROVED" for p in linked):
            raise ApiError("ERR_TEACH_OUT_REQUIRED")

    # check 33: the staffing reduction must be fully funded
    if decision["outcome"] in WIND_DOWN and program is not None:
        if derive.deferred_fte(program) != Decimal("0.00"):
            raise ApiError("ERR_SEVERANCE_CAP_EXCEEDED")

    decision["state"] = "EFFECTUATED"
    decision["effectuated_at"] = now()
    if decision["outcome"] == "IMPROVEMENT_PLAN":
        if decision["improvement_state"] == "NOT_APPLICABLE":
            decision["improvement_state"] = "ACTIVE"
    touch(decision)

    if cycle is not None and cycle["state"] == "DECIDED":
        cycle["state"] = "CLOSED"
        touch(cycle)

    if program is not None and decision["outcome"] in WIND_DOWN:
        if decision["outcome"] == "DISCONTINUATION":
            if program["lifecycle_state"] == "TEACH_OUT_PENDING":
                program["lifecycle_state"] = "TEACH_OUT_ACTIVE"
        else:
            if program["lifecycle_state"] == "CONSOLIDATION_PENDING":
                program["lifecycle_state"] = "CONSOLIDATED"
            program["consolidated_into_program_id"] = decision["receiving_program_id"]
        if program["catalog_status"] == "MARKETING_SUPPRESSED":
            program["catalog_status"] = "ADMISSIONS_CLOSED"
        touch(program)

        if decision["outcome"] == "CONSOLIDATION" and receiving is not None:
            for appointment in by_created(derive.appointments_of(program["id"])):
                if appointment["state"] == "ASSIGNED":
                    appointment["state"] = "REASSIGNMENT_PROPOSED"
                    appointment["reassigned_to_department_code"] = (
                        receiving["department_code"])
                    touch(appointment)
    return envelope.ok(serial.decision(decision))


def _rescind(decision, cycle, program, reason):
    if decision["state"] != "RATIFIED":
        raise ApiError("ERR_DECISION_STATE_INVALID")

    decision["state"] = "RESCINDED"
    decision["rescission_reason"] = reason
    if decision["improvement_state"] == "ACTIVE":
        decision["improvement_state"] = "NOT_APPLICABLE"
    touch(decision)

    for notification in by_created(derive.notifications_of(decision["id"])):
        if notification["status"] in ("PENDING", "SENT", "OVERDUE"):
            notification["status"] = "VOIDED"
            touch(notification)

    if program is not None:
        program["lifecycle_state"] = "UNDER_REVIEW"
        if program["catalog_status_pre_decision"] is not None:
            program["catalog_status"] = program["catalog_status_pre_decision"]
            program["catalog_status_pre_decision"] = None
        touch(program)

    for plan in by_created(list(db.plans.values())):
        if plan["decision_id"] != decision["id"]:
            continue
        if plan["state"] in ("DRAFT", "SUBMITTED", "APPROVED"):
            plan["state"] = "SUPERSEDED"
            touch(plan)

    if program is not None:
        cascade.retained_back_to_assigned(program)

    if cycle is not None and cycle["state"] == "DECIDED":
        cycle["state"] = "RESPONSE_SUBMITTED"
        cycle["decided_at"] = None
        touch(cycle)
    return envelope.ok(serial.decision(decision))


def _evaluate_improvement(decision, cycle, program):
    if decision["state"] != "EFFECTUATED":
        raise ApiError("ERR_DECISION_STATE_INVALID")
    if decision["improvement_state"] != "ACTIVE":
        raise ApiError("ERR_DECISION_STATE_INVALID")

    score = None
    if program is not None:
        score = derive.composite_score(program)[0]
    target = decision["improvement_target_score"]
    met = score is not None and target is not None and score >= target

    decision["improvement_state"] = "MET" if met else "UNMET"
    touch(decision)

    if program is not None:
        if met:
            if program["lifecycle_state"] == "IMPROVEMENT_MONITORED":
                program["lifecycle_state"] = "ACTIVE"
                touch(program)
        else:
            if program["lifecycle_state"] == "IMPROVEMENT_MONITORED":
                program["lifecycle_state"] = "UNDER_REVIEW"
            program["discontinuation_override"] = True
            touch(program)

    if not met and cycle is not None and cycle["state"] == "CLOSED":
        cycle["state"] = "RESPONSE_SUBMITTED"
        touch(cycle)
    return envelope.ok(serial.decision(decision))


# --------------------------------------------------------------------------
# agency notifications
# --------------------------------------------------------------------------

@bp.route("/provost/decision-records/<did>/agency-notifications",
          methods=["POST"])
def create_notification(did):
    ctx = begin((COORD,))
    decision = db.decisions.get(did)
    ctx.require(decision, "ERR_DECISION_NOT_FOUND")

    body = ctx.require_object_body()
    agency_type = valid.req_enum(body, "agency_type", AGENCY_TYPES)
    agency_code = valid.req_str(body, "agency_code", 2, 20)

    ctx.not_terminal(program_of_decision(decision))

    row = new_row()
    row.update({
        "decision_id": did,
        "agency_type": agency_type,
        "agency_code": agency_code,
        "status": "PENDING",
        "due_at": derive.notice_due_at(decision, agency_type),
        "sent_at": None,
        "acknowledged_at": None,
        "transmitted_reference": None,
        "origin": "MANUAL",
        "overdue_marked_at": None,
    })
    db.notifications[row["id"]] = row
    touch(decision)
    return envelope.created(serial.notification(row))


@bp.route("/provost/decision-records/<did>/agency-notifications",
          methods=["GET"])
def list_notifications(did):
    ctx = begin((COORD, PROVOST, CHAIR))
    decision = db.decisions.get(did)
    ctx.chair_owner(program_of_decision(decision))
    ctx.require(decision, "ERR_DECISION_NOT_FOUND")
    rows = by_created(derive.notifications_of(did))
    rows = filters.apply_string(rows, "status", "status")
    rows = filters.apply_string(rows, "agency_type", "agency_type")
    return envelope.paginate(rows, serial.notification)


@bp.route("/provost/agency-notifications/<nid>/transitions", methods=["POST"])
def transition_notification(nid):
    ctx = begin((COORD,))
    notification = db.notifications.get(nid)
    ctx.require(notification, "ERR_NOTIFICATION_NOT_FOUND")

    body = ctx.require_object_body()
    action = valid.req_enum(body, "action", ACTIONS_NOTIFICATION)
    reference = None
    if action == "SEND":
        reference = valid.req_nonblank_str(body, "transmitted_reference", 1, 200)

    ctx.not_terminal(program_of_notification(notification))

    if action == "SEND":
        if notification["status"] not in ("PENDING", "OVERDUE"):
            raise ApiError("ERR_NOTIFICATION_STATE_INVALID")
        notification["status"] = "SENT"
        notification["sent_at"] = now()
        notification["transmitted_reference"] = reference
        touch(notification)
        return envelope.ok(serial.notification(notification))

    if notification["status"] != "SENT":
        raise ApiError("ERR_NOTIFICATION_STATE_INVALID")
    notification["status"] = "ACKNOWLEDGED"
    notification["acknowledged_at"] = now()
    touch(notification)
    return envelope.ok(serial.notification(notification))
