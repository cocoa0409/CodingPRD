"""Disputes: response, information requests and resolution (PRD 3.8)."""
from flask import Blueprint

import auth
import calc
import cascade
import clock
import db
import derive
import response
import support
import validate
from errors import ApiError

bp = Blueprint("disputes", __name__)

RESPONDABLE = ("OPEN", "INFO_REQUESTED")
RESOLVABLE = ("OPEN", "MERCHANT_RESPONDED", "INFO_REQUESTED")


@bp.get("/perks/disputes/<row_id>")
def get_dispute(row_id):
    principal = auth.require(auth.MERCHANT, auth.PLATFORM_ADMIN, auth.EMPLOYEE,
                             auth.EMPLOYER_ADMIN)
    if principal.is_employer_admin:
        # PRD 2.10, ahead of existence: an employer never reads dispute detail.
        raise ApiError("ERR_PRIVACY_RESTRICTED",
                       "An employer may not read individual dispute data.")
    row = support.fetch("disputes", row_id)
    auth.check_merchant_scope(principal, row["merchant_id"])
    auth.check_membership_scope(principal, row["raised_by_membership_id"])
    return response.ok(derive.dispute_json(row))


@bp.get("/perks/disputes")
def list_disputes():
    principal = auth.require(auth.MERCHANT, auth.PLATFORM_ADMIN, auth.EMPLOYEE)
    redemption_id = support.arg("redemption_id")
    membership_id = support.arg("raised_by_membership_id")
    merchant_id = support.arg("merchant_id")
    status = support.arg("status")
    rows = []
    for row in db.disputes.values():
        if principal.is_merchant and row["merchant_id"] != principal.user_id:
            continue
        if principal.is_employee and row["raised_by_membership_id"] != principal.user_id:
            continue
        if not support.matches(row, "redemption_id", redemption_id):
            continue
        if not support.matches(row, "raised_by_membership_id", membership_id):
            continue
        if not support.matches(row, "merchant_id", merchant_id):
            continue
        if not support.matches(row, "status", status):
            continue
        rows.append(row)
    return support.paged_sorted(rows, derive.dispute_json)


@bp.post("/perks/disputes/<row_id>/respond")
def respond_dispute(row_id):
    principal = auth.require(auth.MERCHANT)
    row = support.fetch("disputes", row_id)
    auth.check_merchant_scope(principal, row["merchant_id"])
    body = validate.json_body()
    data = validate.fields(body, [
        {"name": "response_note", "type": "str", "required": True},
        {"name": "remedy_offered_cents", "type": "int", "min": 0},
    ])
    if row["status"] not in RESPONDABLE:
        raise ApiError("ERR_DISPUTE_INVALID_STATE",
                       "A response is accepted only from OPEN or INFO_REQUESTED.")
    if not clock.now() < row["response_deadline_at"]:
        raise ApiError("ERR_DISPUTE_DEADLINE_PASSED",
                       "The dispute response deadline has passed.")
    # A second response overwrites rather than accumulating.
    row["response_note"] = data["response_note"]
    row["remedy_offered_cents"] = data["remedy_offered_cents"]
    row["status"] = "MERCHANT_RESPONDED"
    db.touch(row)
    return response.ok(derive.dispute_json(row))


@bp.post("/perks/disputes/<row_id>/request-info")
def request_info(row_id):
    auth.require(auth.PLATFORM_ADMIN)
    row = support.fetch("disputes", row_id)
    if row["status"] != "MERCHANT_RESPONDED":
        raise ApiError("ERR_DISPUTE_INVALID_STATE",
                       "Information may be requested only from MERCHANT_RESPONDED.")
    if int(row["info_request_count"]) >= calc.MAX_INFO_REQUESTS:
        raise ApiError("ERR_MAX_INFO_REQUESTS",
                       "The dispute information-request budget is exhausted.")
    row["status"] = "INFO_REQUESTED"
    row["info_request_count"] = int(row["info_request_count"]) + 1
    row["response_deadline_at"] = clock.plus_hours(
        clock.now(), calc.DISPUTE_RESPONSE_HOURS)
    db.touch(row)
    return response.ok(derive.dispute_json(row))


@bp.post("/perks/disputes/<row_id>/resolve")
def resolve_dispute(row_id):
    auth.require(auth.PLATFORM_ADMIN)
    row = support.fetch("disputes", row_id)
    body = validate.json_body()
    data = validate.fields(body, [
        {"name": "outcome", "type": "enum", "required": True,
         "values": ["MERCHANT_FAULT", "NO_FAULT"]},
        {"name": "outcome_credit_cents", "type": "int", "min": 0, "default": 0},
    ])
    if row["status"] not in RESOLVABLE:
        raise ApiError("ERR_DISPUTE_INVALID_STATE", "The dispute is already resolved.")
    redemption = db.redemptions.get(row["redemption_id"])
    credit = data["outcome_credit_cents"]
    if credit is None:
        credit = 0
    if data["outcome"] == "MERCHANT_FAULT":
        net = int(redemption["net_charged_cents"] or 0) if redemption is not None else 0
        if credit > net:
            raise ApiError("ERR_CREDIT_EXCEEDS_NET",
                           "The goodwill credit exceeds the redemption's net charge.")
        row["status"] = "RESOLVED_MERCHANT_FAULT"
        row["resolved_at"] = clock.now()
        row["outcome_credit_cents"] = credit
        db.touch(row)
        if redemption is not None:
            cascade.merchant_fault_cascade(row, redemption, credit)
    else:
        # No credit check at all: a NO_FAULT outcome forces the credit to 0.
        row["status"] = "RESOLVED_NO_FAULT"
        row["resolved_at"] = clock.now()
        row["outcome_credit_cents"] = 0
        db.touch(row)
        if redemption is not None:
            redemption["fulfillment_status"] = "FULFILLED"
            if redemption["fulfilled_at"] is None:
                redemption["fulfilled_at"] = clock.now()
            db.touch(redemption)
    return response.ok(derive.dispute_json(row))
