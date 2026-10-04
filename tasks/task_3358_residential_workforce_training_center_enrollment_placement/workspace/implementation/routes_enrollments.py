"""Enrollments: create, list, fetch, training-axis transitions."""
from flask import Blueprint, request

from auth import authenticate, require_role, ALL_ROLES
from db import STORE, new_record, bump
from envelope import ok_object, ok_list
from errors import (
    ApiError,
    ERR_NOT_FOUND,
    ERR_ALREADY_TERMINAL,
    ERR_INVALID_STATE,
    ERR_CONDUCT_HOLD,
    ERR_PREREQUISITE_NOT_MET,
    ERR_APPLICANT_NOT_ELIGIBLE,
    ERR_CENTER_MISMATCH,
    ERR_PROGRAM_NOT_OPEN,
)
from helpers import (
    get_body,
    check_unknown,
    as_str,
    as_bool,
    as_enum,
    pagination_params,
    paginate,
)
import domain
import serializers

bp = Blueprint("enrollments", __name__)

ENROLL_ACTIONS = ["begin_training", "complete", "unenroll", "separate"]


def get_enrollment_or_404(enrollment_id):
    e = STORE.enrollments.get(enrollment_id)
    if e is None:
        raise ApiError(ERR_NOT_FOUND[0], ERR_NOT_FOUND[1], "Enrollment not found")
    return e


@bp.route("/jc/enrollments", methods=["POST"])
def create_enrollment():
    user_id, role = authenticate()
    require_role(role, {"EnrollmentManager"})
    body = get_body()
    check_unknown(body, {"applicant_id", "trade_program_id", "residential_track"})
    applicant_id = as_str(body, "applicant_id", required=True)
    trade_program_id = as_str(body, "trade_program_id", required=True)
    residential_track = as_bool(body, "residential_track", required=True)
    applicant = STORE.applicants.get(applicant_id)
    if applicant is None:
        raise ApiError(ERR_NOT_FOUND[0], ERR_NOT_FOUND[1], "Applicant not found")
    program = STORE.trade_programs.get(trade_program_id)
    if program is None:
        raise ApiError(ERR_NOT_FOUND[0], ERR_NOT_FOUND[1], "Trade program not found")
    # Business rules in scaffold priority order: 12 (prerequisites),
    # 17 (applicant ASSIGNED), 18 (center match), 19 (program OPEN).
    prereqs_met = domain.prereqs_met_for_applicant(applicant["id"], program)
    if not prereqs_met and not program["supports_remediation"]:
        raise ApiError(
            ERR_PREREQUISITE_NOT_MET[0],
            ERR_PREREQUISITE_NOT_MET[1],
            "Required credential types are not VERIFIED and the program does not support remediation",
        )
    if applicant["assignment_status"] != "ASSIGNED":
        raise ApiError(
            ERR_APPLICANT_NOT_ELIGIBLE[0],
            ERR_APPLICANT_NOT_ELIGIBLE[1],
            "Applicant assignment_status is not ASSIGNED",
        )
    if program["center_id"] != applicant["assigned_center_id"]:
        raise ApiError(
            ERR_CENTER_MISMATCH[0],
            ERR_CENTER_MISMATCH[1],
            "Trade program does not belong to the applicant's assigned center",
        )
    if domain.program_status(program) != "OPEN":
        raise ApiError(
            ERR_PROGRAM_NOT_OPEN[0],
            ERR_PROGRAM_NOT_OPEN[1],
            "Trade program is not OPEN",
        )
    rec = new_record()
    rec.update(
        {
            "applicant_id": applicant["id"],
            "trade_program_id": program["id"],
            "residential_track": residential_track,
            "training_status": "TRAINING" if prereqs_met else "REMEDIATION",
            "residential_status": "AWAITING_BED" if residential_track else "NONRESIDENTIAL",
            "conduct_hold": False,
            "exit_date": None,
            "exit_reason": None,
        }
    )
    STORE.enrollments[rec["id"]] = rec
    applicant["assignment_status"] = "ENROLLED"
    bump(applicant)
    return ok_object(serializers.enrollment_view(rec), status=201)


@bp.route("/jc/enrollments", methods=["GET"])
def list_enrollments():
    user_id, role = authenticate()
    require_role(role, {"EnrollmentManager", "OperatorAdmin", "TransitionSpecialist"})
    limit, offset = pagination_params()
    items = list(STORE.enrollments.values())
    f_applicant = request.args.get("applicant_id")
    f_program = request.args.get("trade_program_id")
    f_center = request.args.get("center_id")
    f_status = request.args.get("training_status")
    if f_applicant is not None:
        items = [e for e in items if e["applicant_id"] == f_applicant]
    if f_program is not None:
        items = [e for e in items if e["trade_program_id"] == f_program]
    if f_center is not None:
        items = [
            e
            for e in items
            if STORE.trade_programs[e["trade_program_id"]]["center_id"] == f_center
        ]
    if f_status is not None:
        items = [e for e in items if e["training_status"] == f_status]
    items.sort(key=lambda e: e["_seq"])
    page, meta = paginate([serializers.enrollment_view(e) for e in items], limit, offset)
    return ok_list(page, meta)


@bp.route("/jc/enrollments/<enrollment_id>", methods=["GET"])
def get_enrollment(enrollment_id):
    user_id, role = authenticate()
    require_role(role, ALL_ROLES)
    e = get_enrollment_or_404(enrollment_id)
    return ok_object(serializers.enrollment_view(e))


@bp.route("/jc/enrollments/<enrollment_id>/transition", methods=["POST"])
def enrollment_transition(enrollment_id):
    user_id, role = authenticate()
    require_role(role, {"EnrollmentManager"})
    e = get_enrollment_or_404(enrollment_id)
    body = get_body()
    check_unknown(body, {"action", "reason"})
    action = as_enum(body, "action", ENROLL_ACTIONS, required=True)
    reason = as_str(body, "reason")
    # Priority 7: terminal training axis locks the endpoint.
    if e["training_status"] in domain.TRAINING_TERMINAL:
        raise ApiError(
            ERR_ALREADY_TERMINAL[0],
            ERR_ALREADY_TERMINAL[1],
            "Enrollment training axis is terminal",
        )
    status = e["training_status"]
    if action == "begin_training":
        if status != "REMEDIATION":
            _invalid_state(action, status)
        if not domain.prereqs_met_for_enrollment(e):
            raise ApiError(
                ERR_PREREQUISITE_NOT_MET[0],
                ERR_PREREQUISITE_NOT_MET[1],
                "Required credential types are not VERIFIED on this enrollment",
            )
        e["training_status"] = "TRAINING"
        bump(e)
    elif action == "complete":
        if status != "TRAINING":
            _invalid_state(action, status)
        domain.recompute_conduct_hold(e["id"])
        if e["conduct_hold"]:
            raise ApiError(
                ERR_CONDUCT_HOLD[0],
                ERR_CONDUCT_HOLD[1],
                "Enrollment conduct_hold is active",
            )
        if not domain.prereqs_met_for_enrollment(e):
            raise ApiError(
                ERR_PREREQUISITE_NOT_MET[0],
                ERR_PREREQUISITE_NOT_MET[1],
                "Required credential types are not VERIFIED on this enrollment",
            )
        domain.finalize_enrollment_terminal(e, "COMPLETED", None, True, True)
    elif action == "unenroll":
        if status not in ("REMEDIATION", "TRAINING"):
            _invalid_state(action, status)
        domain.finalize_enrollment_terminal(e, "UNENROLLED", reason, False, False)
    elif action == "separate":
        if status not in ("REMEDIATION", "TRAINING"):
            _invalid_state(action, status)
        domain.finalize_enrollment_terminal(e, "SEPARATED", reason, True, True)
    return ok_object(serializers.enrollment_view(e), status=200)


def _invalid_state(action, status):
    raise ApiError(
        ERR_INVALID_STATE[0],
        ERR_INVALID_STATE[1],
        "Action {} is not defined from state {}".format(action, status),
    )
