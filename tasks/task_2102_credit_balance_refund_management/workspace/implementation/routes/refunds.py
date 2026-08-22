"""Refund requests, the approval tier and the decision cycle (PRD 3.5-3.7)."""
from flask import Blueprint, g, request

import auth
import calc
import cascade
import clock
import db
import derive
import response
import validation as v
from errors import ApiError

bp = Blueprint("refunds", __name__)


@bp.post("/refund-requests")
@auth.require(auth.CREDIT_ANALYST)
def create_refund_request():
    data = v.body()
    v.fk_exists("credit_balance", data, "credit_balance_id")               # rank 4
    # rank 6 - body shape
    credit_balance_id = v.req_str(data, "credit_balance_id")
    requested_amount_cents = v.req_int(data, "requested_amount_cents")
    payee_type = v.req_enum(data, "payee_type", v.PAYEE_TYPES)
    payee_name = v.req_str(data, "payee_name")
    payee_address_line = v.req_str(data, "payee_address_line")
    payee_state_code = v.req_enum(data, "payee_state_code", v.STATE_CODES)
    expected_version = v.req_int(data, "expected_credit_balance_version")

    cb = db.credit_balances[credit_balance_id]
    if cb["status"] != "ATTRIBUTED":                                       # rank 8
        raise ApiError("ERR_CREDIT_BALANCE_INVALID_STATE")
    if expected_version != cb["version"]:                                  # rank 17
        raise ApiError("ERR_STALE_VERSION")

    account = db.patient_accounts.get(cb["account_id"])
    if account is None or account["status"] != "OPEN":                     # rank 34
        raise ApiError("ERR_ACCOUNT_NOT_REFUNDABLE")

    bucket_capacity = int(cb["patient_portion_cents"]) if payee_type == "PATIENT" \
        else int(cb["payer_portion_cents"])
    if bucket_capacity <= 0:                                               # rank 35
        raise ApiError("ERR_PAYEE_TYPE_MISMATCH")
    if requested_amount_cents < calc.MIN_REFUND_CENTS:                     # rank 38
        raise ApiError("ERR_REFUND_BELOW_MINIMUM")
    if derive.account_balance_cents(account["id"]) >= 0:                   # rank 39
        raise ApiError("ERR_CREDIT_ALREADY_CONSUMED")
    outstanding = derive.cb_outstanding_cents(cb)
    if requested_amount_cents > min(bucket_capacity, outstanding):         # rank 40
        raise ApiError("ERR_REFUND_EXCEEDS_CREDIT")

    tier, count = calc.approval_tier(requested_amount_cents, cb, payee_type)
    row = db.base_row()
    row.update({
        "credit_balance_id": credit_balance_id,
        "requested_amount_cents": requested_amount_cents,
        "payee_type": payee_type,
        "payee_name": payee_name,
        "payee_address_line": payee_address_line,
        "payee_state_code": payee_state_code,
        "prepared_by_user_id": g.user_id,
        "required_approval_tier": tier,
        "required_approval_count": count,
        "revision_count": 0,
        "last_decision_user_id": None,
        "approval_state": "DRAFT",
        "disbursement_state": "NOT_SCHEDULED",
    })
    db.refund_requests[row["id"]] = row

    cb["status"] = "REFUND_PENDING"
    db.touch(cb)
    return response.ok(derive.refund_request(row), 201)


@bp.get("/refund-requests")
@auth.require(*auth.ALL_ROLES)
def list_refund_requests():
    rows = db.ordered(list(db.refund_requests.values()))
    credit_balance_id = request.args.get("credit_balance_id")
    if credit_balance_id:
        rows = [r for r in rows if r["credit_balance_id"] == credit_balance_id]
    approval_state = request.args.get("approval_state")
    if approval_state:
        rows = [r for r in rows if r["approval_state"] == approval_state]
    disbursement_state = request.args.get("disbursement_state")
    if disbursement_state:
        rows = [r for r in rows if r["disbursement_state"] == disbursement_state]
    return response.page(rows, derive.refund_request)


@bp.get("/refund-requests/<refund_request_id>")
@auth.require(*auth.ALL_ROLES)
def read_refund_request(refund_request_id):
    return response.ok(derive.refund_request(v.must_exist("refund_request", refund_request_id)))


@bp.post("/refund-requests/<refund_request_id>/submit")
@auth.require(auth.CREDIT_ANALYST)
def submit_refund_request(refund_request_id):
    req = v.must_exist("refund_request", refund_request_id)                # rank 3
    if req["approval_state"] not in ("DRAFT", "RETURNED_FOR_REVISION"):    # rank 9
        raise ApiError("ERR_REFUND_REQUEST_INVALID_STATE")
    if req["approval_state"] == "RETURNED_FOR_REVISION" \
            and req["revision_count"] > calc.MAX_REVISION_ROUNDS:          # rank 46
        raise ApiError("ERR_MAX_REVISIONS_EXCEEDED")

    cb = db.credit_balances.get(req["credit_balance_id"])
    tier, count = calc.approval_tier(req["requested_amount_cents"], cb, req["payee_type"])
    req["required_approval_tier"] = tier
    req["required_approval_count"] = count
    req["approval_state"] = "SUBMITTED"
    db.touch(req)
    return response.ok(derive.refund_request(req))


@bp.post("/refund-requests/<refund_request_id>/decision")
@auth.require(auth.REFUND_APPROVER)
def decide_refund_request(refund_request_id):
    req = v.must_exist("refund_request", refund_request_id)                # rank 3
    data = v.body()
    decision = v.req_enum(data, "decision", v.DECISIONS)                   # rank 6
    approver_tier = v.req_int(data, "approver_tier", minimum=1, maximum=3)
    note = v.opt_str(data, "note")
    if req["approval_state"] != "SUBMITTED":                               # rank 9
        raise ApiError("ERR_REFUND_REQUEST_INVALID_STATE")
    if g.user_id == req["prepared_by_user_id"]:                            # rank 18
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    for existing in db.approvals_for_request(req["id"]):                   # rank 19
        if existing["approver_user_id"] == g.user_id:
            raise ApiError("ERR_DUPLICATE_APPROVER")
    if decision == "APPROVED" and approver_tier < req["required_approval_tier"]:  # rank 41
        raise ApiError("ERR_APPROVAL_TIER_INSUFFICIENT")

    approval = db.base_row(versioned=False)
    approval.update({
        "refund_request_id": req["id"],
        "approver_user_id": g.user_id,
        "approver_tier": approver_tier,
        "decision": decision,
        "note": note,
        "decided_at": clock.now(),
    })
    db.refund_approvals[approval["id"]] = approval
    req["last_decision_user_id"] = g.user_id

    cb = db.credit_balances.get(req["credit_balance_id"])
    if decision == "APPROVED":
        if derive.rr_approvals_received(req) >= req["required_approval_count"]:
            req["approval_state"] = "APPROVED"
    elif decision == "REJECTED":
        req["approval_state"] = "REJECTED"
        if cb is not None:
            cascade.release_credit_balance(cb, req["id"])
    else:  # RETURNED
        req["approval_state"] = "RETURNED_FOR_REVISION"
        req["revision_count"] = int(req["revision_count"]) + 1
    db.touch(req)
    return response.ok(derive.refund_approval(approval), 201)


@bp.post("/refund-requests/<refund_request_id>/cancel")
@auth.require(auth.CREDIT_ANALYST)
def cancel_refund_request(refund_request_id):
    req = v.must_exist("refund_request", refund_request_id)   # rank 3
    data = v.body()
    v.opt_str(data, "reason")                                 # rank 6

    approval_state = req["approval_state"]
    disbursement_state = req["disbursement_state"]
    if approval_state in ("DRAFT", "RETURNED_FOR_REVISION"):
        req["approval_state"] = "CANCELLED"
    elif approval_state == "APPROVED" and disbursement_state == "REISSUE_PENDING":
        req["disbursement_state"] = "VOID_CLOSED"
    else:                                                     # rank 9
        raise ApiError("ERR_REFUND_REQUEST_INVALID_STATE")

    db.touch(req)
    cb = db.credit_balances.get(req["credit_balance_id"])
    if cb is not None:
        cascade.release_credit_balance(cb, req["id"])
    return response.ok(derive.refund_request(req))


@bp.get("/refund-approvals")
@auth.require(*auth.ALL_ROLES)
def list_refund_approvals():
    rows = db.ordered(list(db.refund_approvals.values()))
    refund_request_id = request.args.get("refund_request_id")
    if refund_request_id:
        rows = [r for r in rows if r["refund_request_id"] == refund_request_id]
    decision = request.args.get("decision")
    if decision:
        rows = [r for r in rows if r["decision"] == decision]
    return response.page(rows, derive.refund_approval)


@bp.get("/refund-approvals/<approval_id>")
@auth.require(*auth.ALL_ROLES)
def read_refund_approval(approval_id):
    return response.ok(derive.refund_approval(v.must_exist("refund_approval", approval_id)))
