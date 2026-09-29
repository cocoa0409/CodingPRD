"""Federal aid scheduling, release, return and cancellation (PRD 3.9)."""
from flask import Blueprint, request

import db as store
from db import db, new_row, touch
from errors import ApiError, bad_request
from middleware import (ROLE_FINANCIAL_AID_OFFICER, ROLE_PLATFORM_ADMIN,
                        ROLE_REGISTRAR, ROLE_STUDENT, check_student_ownership,
                        require)
from response import json_body, created_response, object_response, paginated
from services import calc, cascade, derive, lookup, serialize, shape

bp = Blueprint("aid", __name__)

READ_AID_ROLES = (ROLE_FINANCIAL_AID_OFFICER, ROLE_REGISTRAR,
                  ROLE_PLATFORM_ADMIN, ROLE_STUDENT)
LIST_AID_ROLES = (ROLE_FINANCIAL_AID_OFFICER, ROLE_REGISTRAR,
                  ROLE_PLATFORM_ADMIN)
SAP_ELIGIBLE = ("GOOD_STANDING", "WARNING")


def _arg(name):
    raw = request.args.get(name, None)
    if raw is None:
        return None
    text = raw.strip()
    return text if text else None


@bp.route("/aid-disbursements", methods=["POST"])
def create_disbursement():
    require(ROLE_FINANCIAL_AID_OFFICER)
    body = json_body()
    student = lookup.student(shape.req_id(body, "student_id"))
    term = lookup.term(shape.req_id(body, "term_id"))
    amount = shape.req_int(body, "scheduled_amount_cents", minimum=1)
    expected = shape.req_expected_version(body, "expected_term_version")
    if term["student_id"] != student["id"]:
        raise bad_request(
            "Field 'term_id' does not belong to the named student.")
    if student["enrollment_status"] != "ACTIVE":
        raise ApiError("ERR_STUDENT_NOT_ACTIVE")
    if expected != term["version"]:
        raise ApiError("ERR_STALE_VERSION")
    for prior in lookup.disbursements_of_term(term["id"]):
        if prior["status"] == "SCHEDULED":
            cascade.cancel_award(prior)
    row = new_row()
    row.update({
        "student_id": student["id"],
        "term_id": term["id"],
        "status": "SCHEDULED",
        "scheduled_amount_cents": amount,
        "outstanding_amount_cents": amount,
        "disbursed_amount_cents": 0,
        "cancelled_amount_cents": 0,
        "returned_amount_cents": 0,
        "retained_amount_cents": 0,
        "hold_reason": None,
        "credit_equivalency_at_disbursement": None,
        "unearned_aid_cents": None,
        "school_return_share_cents": None,
        "student_return_share_cents": None,
        "aid_review_required": False,
        "disbursed_at_utc": None,
        "returned_at_utc": None,
    })
    db.disbursements[row["id"]] = row
    touch(student)
    touch(term)
    return created_response(serialize.disbursement(row))


@bp.route("/aid-disbursements/<did>", methods=["GET"])
def read_disbursement(did):
    caller = require(*READ_AID_ROLES)
    award = lookup.disbursement(did)
    check_student_ownership(caller, award["student_id"])
    return object_response(serialize.disbursement(award))


@bp.route("/aid-disbursements", methods=["GET"])
def list_disbursements():
    require(*LIST_AID_ROLES)
    student_id = _arg("student_id")
    term_id = _arg("term_id")
    status = _arg("status")
    hold_reason = _arg("hold_reason")
    rows = []
    for row in db.disbursements.values():
        if student_id is not None and row["student_id"] != student_id:
            continue
        if term_id is not None and row["term_id"] != term_id:
            continue
        if status is not None and row["status"] != status:
            continue
        if hold_reason is not None and row["hold_reason"] != hold_reason:
            continue
        rows.append(row)
    return paginated(store.by_created(rows), serialize.disbursement)


@bp.route("/aid-disbursements/<did>/disburse", methods=["POST"])
def disburse(did):
    require(ROLE_FINANCIAL_AID_OFFICER)
    award = lookup.disbursement(did)
    student = lookup.student(award["student_id"])
    term = lookup.term(award["term_id"])
    program = lookup.program_of_student(student)
    if student["enrollment_status"] != "ACTIVE":
        raise ApiError("ERR_STUDENT_NOT_ACTIVE")
    if term["status"] != "ACTIVE":
        raise ApiError("ERR_TERM_NOT_ACTIVE")
    if award["status"] == "DISBURSED":
        raise ApiError("ERR_AID_ALREADY_DISBURSED")
    if award["status"] not in ("SCHEDULED", "HELD"):
        raise ApiError("ERR_DISBURSEMENT_NOT_SCHEDULED")
    if derive.student_has_live_case(student["id"]):
        raise ApiError("ERR_INTEGRITY_HOLD_ACTIVE")
    if student["sap_status"] not in SAP_ELIGIBLE:
        raise ApiError("ERR_AID_SAP_INELIGIBLE")
    equivalency = derive.credit_equivalency_earned(term)
    if equivalency < program["aid_min_credit_equivalency"]:
        raise ApiError("ERR_AID_CREDIT_EQUIVALENCY_SHORTFALL")
    amount = award["scheduled_amount_cents"]
    award["status"] = "DISBURSED"
    award["disbursed_amount_cents"] = amount
    award["outstanding_amount_cents"] = 0
    award["retained_amount_cents"] = amount
    award["returned_amount_cents"] = 0
    award["cancelled_amount_cents"] = 0
    award["hold_reason"] = None
    award["disbursed_at_utc"] = db.now()
    award["credit_equivalency_at_disbursement"] = equivalency
    touch(award)
    touch(student)
    return object_response(serialize.disbursement(award))


@bp.route("/aid-disbursements/<did>/return", methods=["POST"])
def return_aid(did):
    require(ROLE_FINANCIAL_AID_OFFICER)
    award = lookup.disbursement(did)
    if award["status"] != "DISBURSED":
        raise ApiError("ERR_AID_NOT_DISBURSED")
    term = lookup.term(award["term_id"])
    if term["status"] not in ("LAPSED", "CANCELLED"):
        raise bad_request(
            "The owning term must be LAPSED or CANCELLED before aid is "
            "returned.")
    earned = term["earned_pct"]
    if earned is None or earned >= 1:
        raise bad_request(
            "A fully earned term has no unearned aid to return.")
    unearned, school, student_share = calc.return_figures(award, term)
    award["unearned_aid_cents"] = unearned
    award["school_return_share_cents"] = school
    award["student_return_share_cents"] = student_share
    award["returned_amount_cents"] = school
    award["retained_amount_cents"] = award["disbursed_amount_cents"] - school
    award["outstanding_amount_cents"] = 0
    award["cancelled_amount_cents"] = 0
    award["returned_at_utc"] = db.now()
    award["status"] = "RETURNED"
    touch(award)
    student = lookup.student(award["student_id"])
    touch(student)
    return object_response(serialize.disbursement(award))


@bp.route("/aid-disbursements/<did>/cancel", methods=["POST"])
def cancel_disbursement(did):
    require(ROLE_FINANCIAL_AID_OFFICER)
    award = lookup.disbursement(did)
    shape.opt_str(json_body(), "reason")
    if award["status"] not in ("SCHEDULED", "HELD"):
        raise ApiError("ERR_DISBURSEMENT_NOT_SCHEDULED")
    cascade.cancel_award(award)
    return object_response(serialize.disbursement(award))
