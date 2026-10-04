"""Employer agreements and work-based learning placements."""
from flask import Blueprint

from auth import authenticate, require_role
from db import STORE, new_record, bump
from envelope import ok_object, ok_list
from errors import (
    ApiError,
    ERR_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_ALREADY_TERMINAL,
    ERR_INVALID_STATE,
    ERR_CONDUCT_HOLD,
    ERR_AGREEMENT_INACTIVE,
    ERR_WBL_SLOT_EXCEEDED,
    ERR_SUPERVISION_OVERLOAD,
    ERR_WAGE_BELOW_FLOOR,
)
from helpers import (
    get_body,
    check_unknown,
    as_str,
    as_int,
    as_date,
    as_bool,
    as_enum,
    pagination_params,
    paginate,
)
import domain
import serializers

bp = Blueprint("wbl", __name__)

WBL_ACTIONS = ["activate", "record_hours", "complete", "terminate"]
WBL_TERMINAL = {"COMPLETED", "TERMINATED"}


# ---------------- Employer agreements ----------------
@bp.route("/jc/employer-agreements", methods=["POST"])
def create_agreement():
    user_id, role = authenticate()
    require_role(role, {"OperatorAdmin"})
    body = get_body()
    check_unknown(
        body,
        {
            "employer_name",
            "trade_code",
            "region_code",
            "slot_count",
            "hourly_wage_floor_cents",
            "effective_start",
            "effective_end",
        },
    )
    rec = new_record()
    rec.update(
        {
            "employer_name": as_str(body, "employer_name", required=True),
            "trade_code": as_str(body, "trade_code", required=True),
            "region_code": as_str(body, "region_code", required=True),
            "slot_count": as_int(body, "slot_count", required=True, lo=1),
            "hourly_wage_floor_cents": as_int(
                body, "hourly_wage_floor_cents", required=True, lo=1
            ),
            "effective_start": as_date(body, "effective_start", required=True),
            "effective_end": as_date(body, "effective_end", required=True),
        }
    )
    STORE.employer_agreements[rec["id"]] = rec
    return ok_object(serializers.agreement_view(rec), status=201)


def get_agreement_or_404(agreement_id):
    a = STORE.employer_agreements.get(agreement_id)
    if a is None:
        raise ApiError(ERR_NOT_FOUND[0], ERR_NOT_FOUND[1], "Employer agreement not found")
    return a


@bp.route("/jc/employer-agreements/<agreement_id>", methods=["GET"])
def get_agreement(agreement_id):
    user_id, role = authenticate()
    require_role(role, {"OperatorAdmin", "TransitionSpecialist"})
    a = get_agreement_or_404(agreement_id)
    return ok_object(serializers.agreement_view(a))


@bp.route("/jc/employer-agreements/<agreement_id>/wbl-placements", methods=["GET"])
def list_agreement_placements(agreement_id):
    user_id, role = authenticate()
    require_role(role, {"OperatorAdmin", "TransitionSpecialist"})
    a = get_agreement_or_404(agreement_id)
    limit, offset = pagination_params()
    items = [
        w
        for w in STORE.wbl_placements.values()
        if w["employer_agreement_id"] == a["id"]
    ]
    items.sort(key=lambda w: w["_seq"])
    page, meta = paginate([serializers.wbl_view(w) for w in items], limit, offset)
    return ok_list(page, meta)


# ---------------- WBL placements ----------------
@bp.route("/jc/wbl-placements", methods=["POST"])
def create_placement():
    user_id, role = authenticate()
    require_role(role, {"TransitionSpecialist"})
    body = get_body()
    check_unknown(
        body, {"enrollment_id", "employer_agreement_id", "supervisor_id", "hourly_wage_cents"}
    )
    enrollment_id = as_str(body, "enrollment_id", required=True)
    agreement_id = as_str(body, "employer_agreement_id", required=True)
    supervisor_id = as_str(body, "supervisor_id", required=True)
    hourly_wage_cents = as_int(body, "hourly_wage_cents", required=True, lo=0)
    enrollment = STORE.enrollments.get(enrollment_id)
    if enrollment is None:
        raise ApiError(ERR_NOT_FOUND[0], ERR_NOT_FOUND[1], "Enrollment not found")
    agreement = STORE.employer_agreements.get(agreement_id)
    if agreement is None:
        raise ApiError(ERR_NOT_FOUND[0], ERR_NOT_FOUND[1], "Employer agreement not found")
    # Priority 9: conduct hold gates placement proposals.
    domain.recompute_conduct_hold(enrollment_id)
    if enrollment["conduct_hold"]:
        raise ApiError(ERR_CONDUCT_HOLD[0], ERR_CONDUCT_HOLD[1], "Enrollment conduct_hold is active")
    # Priority 20: agreement must read ACTIVE at proposal.
    if domain.agreement_status(agreement) != "ACTIVE":
        raise ApiError(
            ERR_AGREEMENT_INACTIVE[0], ERR_AGREEMENT_INACTIVE[1], "Employer agreement is EXPIRED"
        )
    # Priority 24: wage floor.
    if hourly_wage_cents < agreement["hourly_wage_floor_cents"]:
        raise ApiError(
            ERR_WAGE_BELOW_FLOOR[0],
            ERR_WAGE_BELOW_FLOOR[1],
            "hourly_wage_cents is below the agreement's floor",
        )
    rec = new_record()
    rec.update(
        {
            "enrollment_id": enrollment_id,
            "employer_agreement_id": agreement_id,
            "supervisor_id": supervisor_id,
            "hourly_wage_cents": hourly_wage_cents,
            "verified_hours_total": 0,
            "provisional_hours_total": 0,
            "status": "PROPOSED",
            "start_date": None,
            "converted_to_hire": False,
            "hire_wage_cents": None,
            "_hours": {},
        }
    )
    STORE.wbl_placements[rec["id"]] = rec
    return ok_object(serializers.wbl_view(rec), status=201)


@bp.route("/jc/enrollments/<enrollment_id>/wbl-placements", methods=["GET"])
def list_enrollment_placements(enrollment_id):
    user_id, role = authenticate()
    require_role(role, {"TransitionSpecialist", "EnrollmentManager"})
    if enrollment_id not in STORE.enrollments:
        raise ApiError(ERR_NOT_FOUND[0], ERR_NOT_FOUND[1], "Enrollment not found")
    limit, offset = pagination_params()
    items = [w for w in STORE.wbl_placements.values() if w["enrollment_id"] == enrollment_id]
    items.sort(key=lambda w: w["_seq"])
    page, meta = paginate([serializers.wbl_view(w) for w in items], limit, offset)
    return ok_list(page, meta)


def _active_count_for_agreement(agreement_id):
    return sum(
        1
        for w in STORE.wbl_placements.values()
        if w["employer_agreement_id"] == agreement_id and w["status"] == "ACTIVE"
    )


def _active_count_for_supervisor(supervisor_id):
    return sum(
        1
        for w in STORE.wbl_placements.values()
        if w["supervisor_id"] == supervisor_id and w["status"] == "ACTIVE"
    )


@bp.route("/jc/wbl-placements/<placement_id>/transition", methods=["POST"])
def placement_transition(placement_id):
    user_id, role = authenticate()
    require_role(role, {"TransitionSpecialist"})
    w = STORE.wbl_placements.get(placement_id)
    if w is None:
        raise ApiError(ERR_NOT_FOUND[0], ERR_NOT_FOUND[1], "WBL placement not found")
    body = get_body()
    check_unknown(
        body,
        {
            "action",
            "work_date",
            "hours",
            "verified",
            "termination_reason",
            "converted_to_hire",
            "hire_wage_cents",
        },
    )
    action = as_enum(body, "action", WBL_ACTIONS, required=True)
    # Shape-level field validation per action.
    work_date = as_date(body, "work_date") if "work_date" in body else None
    hours = None
    if "hours" in body:
        hours = as_int(body, "hours", lo=1, hi=domain.MAX_DAILY_HOURS)
    verified = as_bool(body, "verified") if "verified" in body else None
    termination_reason = as_str(body, "termination_reason") if "termination_reason" in body else None
    converted_to_hire = as_bool(body, "converted_to_hire") if "converted_to_hire" in body else None
    hire_wage_cents = as_int(body, "hire_wage_cents", lo=0) if "hire_wage_cents" in body else None
    if action == "record_hours":
        if work_date is None:
            raise ApiError(
                ERR_INVALID_REQUEST[0], ERR_INVALID_REQUEST[1], "work_date is required"
            )
        if hours is None:
            raise ApiError(ERR_INVALID_REQUEST[0], ERR_INVALID_REQUEST[1], "hours is required")
    if action == "complete" and converted_to_hire is True and hire_wage_cents is None:
        raise ApiError(
            ERR_INVALID_REQUEST[0],
            ERR_INVALID_REQUEST[1],
            "hire_wage_cents is required when converted_to_hire is true",
        )
    # Priority 7: terminal lockdown.
    if w["status"] in WBL_TERMINAL:
        raise ApiError(
            ERR_ALREADY_TERMINAL[0], ERR_ALREADY_TERMINAL[1], "WBL placement is terminal"
        )
    status = w["status"]
    if action == "activate":
        if status != "PROPOSED":
            _invalid_state(action, status)
        enrollment = STORE.enrollments[w["enrollment_id"]]
        # Priority 9: conduct hold gates activation.
        domain.recompute_conduct_hold(enrollment["id"])
        if enrollment["conduct_hold"]:
            raise ApiError(
                ERR_CONDUCT_HOLD[0], ERR_CONDUCT_HOLD[1], "Enrollment conduct_hold is active"
            )
        agreement = STORE.employer_agreements[w["employer_agreement_id"]]
        # Priority 20: agreement must read ACTIVE at activation.
        if domain.agreement_status(agreement) != "ACTIVE":
            raise ApiError(
                ERR_AGREEMENT_INACTIVE[0],
                ERR_AGREEMENT_INACTIVE[1],
                "Employer agreement is EXPIRED",
            )
        # Priority 22: aggregate agreement slot ceiling.
        if _active_count_for_agreement(agreement["id"]) >= agreement["slot_count"]:
            raise ApiError(
                ERR_WBL_SLOT_EXCEEDED[0],
                ERR_WBL_SLOT_EXCEEDED[1],
                "Agreement slot_count would be exceeded",
            )
        # Priority 23: supervision ceiling.
        if _active_count_for_supervisor(w["supervisor_id"]) >= domain.MAX_SUPERVISION_ACTIVE:
            raise ApiError(
                ERR_SUPERVISION_OVERLOAD[0],
                ERR_SUPERVISION_OVERLOAD[1],
                "Supervisor already holds the maximum active placements",
            )
        w["status"] = "ACTIVE"
        w["start_date"] = STORE.clock_date_str()
    elif action == "record_hours":
        if status != "ACTIVE":
            _invalid_state(action, status)
        # Priority 13: hours-entry rules (all ERR_INVALID_REQUEST).
        if work_date in w["_hours"]:
            raise ApiError(
                ERR_INVALID_REQUEST[0],
                ERR_INVALID_REQUEST[1],
                "An hours entry already exists for this work_date",
            )
        if work_date < w["start_date"]:
            raise ApiError(
                ERR_INVALID_REQUEST[0],
                ERR_INVALID_REQUEST[1],
                "work_date must not fall before start_date",
            )
        if work_date > STORE.clock_date_str():
            raise ApiError(
                ERR_INVALID_REQUEST[0],
                ERR_INVALID_REQUEST[1],
                "work_date must not lie after the logical clock date",
            )
        w["_hours"][work_date] = {"hours": hours, "verified": bool(verified)}
        # calculations.wbl_hours_credit: ACTUAL (verified only) and
        # PROVISIONAL (all entries) running totals.
        w["provisional_hours_total"] += hours
        if verified:
            w["verified_hours_total"] += hours
    elif action == "complete":
        if status != "ACTIVE":
            _invalid_state(action, status)
        if w["verified_hours_total"] < domain.WBL_COMPLETION_MIN_HOURS:
            raise ApiError(
                ERR_INVALID_STATE[0],
                ERR_INVALID_STATE[1],
                "verified_hours_total has not reached the completion minimum",
            )
        w["status"] = "COMPLETED"
        w["converted_to_hire"] = bool(converted_to_hire)
        w["hire_wage_cents"] = hire_wage_cents
    elif action == "terminate":
        if status not in ("PROPOSED", "ACTIVE"):
            _invalid_state(action, status)
        w["status"] = "TERMINATED"
    bump(w)
    return ok_object(serializers.wbl_view(w), status=200)


def _invalid_state(action, status):
    raise ApiError(
        ERR_INVALID_STATE[0],
        ERR_INVALID_STATE[1],
        "Action {} is not defined from state {}".format(action, status),
    )
