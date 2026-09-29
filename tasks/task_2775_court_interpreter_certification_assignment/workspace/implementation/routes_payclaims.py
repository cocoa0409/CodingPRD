"""Pay-claim reads and the fiscal workflow (PRD 3.8)."""
from flask import Blueprint, request

import derive
import serializers as S
from auth import require
from envelope import array_response, object_response, paginate, read_pagination
from errors import ApiError
from store import db, touch
from validation import body_of, query_enum, query_str, str_field

bp = Blueprint("payclaims", __name__)

CLAIM_STATUSES = (
    "ENCUMBERED",
    "FINALIZED",
    "VOIDED",
    "SUBMITTED",
    "APPROVED",
    "PAID",
)
READ_ROLES = ("ProgramAdmin", "FiscalOfficer", "SchedulingCoordinator", "Interpreter")


def _courthouse_of(claim):
    courthouse_id = derive.claim_courthouse_id(claim)
    return db.courthouses.get(courthouse_id) if courthouse_id else None


@bp.route("/pay-claims", methods=["GET"])
def list_pay_claims():
    require(*READ_ROLES)
    limit, offset = read_pagination(request.args)
    assignment_id = query_str(request.args, "assignment_id")
    rate_schedule_id = query_str(request.args, "rate_schedule_id")
    status = query_enum(request.args, "status", CLAIM_STATUSES)
    rows = []
    for row in db.pay_claims.values():
        if assignment_id is not None and row["assignment_id"] != assignment_id:
            continue
        if rate_schedule_id is not None and row["rate_schedule_id"] != rate_schedule_id:
            continue
        if status is not None and row["status"] != status:
            continue
        rows.append(row)
    rows = S.created_order(rows)
    page, total = paginate(rows, limit, offset)
    return array_response([S.pay_claim_out(r) for r in page], limit, offset, total)


@bp.route("/pay-claims/<pay_claim_id>", methods=["GET"])
def get_pay_claim(pay_claim_id):
    require(*READ_ROLES)
    row = derive.get_pay_claim(pay_claim_id)
    return object_response(S.pay_claim_out(row))


@bp.route("/pay-claims/<pay_claim_id>/submit", methods=["POST"])
def submit_pay_claim(pay_claim_id):
    user_id, role = require("Interpreter")
    body_of(request)
    claim = derive.get_pay_claim(pay_claim_id)
    assignment = db.assignments[claim["assignment_id"]]
    if role == "Interpreter" and assignment["interpreter_id"] != user_id:
        raise ApiError(
            "ERR_NOT_RESOURCE_OWNER",
            "This claim compensates another interpreter's assignment.",
        )
    if claim["status"] != "FINALIZED":
        raise ApiError(
            "ERR_INVALID_PAY_CLAIM_STATE",
            "Only a finalized claim may be submitted.",
        )
    claim["status"] = "SUBMITTED"
    touch(claim)
    courthouse = _courthouse_of(claim)
    if courthouse is not None:
        touch(courthouse)
    return object_response(S.pay_claim_out(claim))


@bp.route("/pay-claims/<pay_claim_id>/approve", methods=["POST"])
def approve_pay_claim(pay_claim_id):
    require("FiscalOfficer")
    body_of(request)
    claim = derive.get_pay_claim(pay_claim_id)
    if claim["status"] != "SUBMITTED":
        raise ApiError(
            "ERR_INVALID_PAY_CLAIM_STATE",
            "Only a submitted claim may be approved.",
        )
    assignment = db.assignments[claim["assignment_id"]]
    if assignment["compliance_status"] != "CLEAR":
        raise ApiError(
            "ERR_QUALITY_REVIEW_OPEN",
            "A quality review is open against the underlying assignment.",
        )
    claim["status"] = "APPROVED"
    touch(claim)
    courthouse = _courthouse_of(claim)
    if courthouse is not None:
        touch(courthouse)
    return object_response(S.pay_claim_out(claim))


@bp.route("/pay-claims/<pay_claim_id>/pay", methods=["POST"])
def pay_pay_claim(pay_claim_id):
    require("FiscalOfficer")
    body = body_of(request)
    payment_reference = str_field(body, "payment_reference")
    claim = derive.get_pay_claim(pay_claim_id)
    if claim["status"] != "APPROVED":
        raise ApiError(
            "ERR_INVALID_PAY_CLAIM_STATE",
            "Only an approved claim may be paid.",
        )
    claim["status"] = "PAID"
    claim["payment_reference"] = payment_reference
    touch(claim)
    assignment = db.assignments[claim["assignment_id"]]
    if assignment["interpreter_id"]:
        touch(db.interpreters[assignment["interpreter_id"]])
    courthouse = _courthouse_of(claim)
    if courthouse is not None:
        touch(courthouse)
    return object_response(S.pay_claim_out(claim))
