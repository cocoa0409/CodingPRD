"""Remediation refunds and ledger compensation (PRD 3.11)."""

from flask import Blueprint

import auth
import calc
import listing
import serialize
import validation as v
from auth import authorize
from envelope import created, ok
from errors import ApiError
from store import db, base_row, touch
from validation import as_int, as_string, parse_body

bp = Blueprint("refunds", __name__)

REFUND_STATES = ("PENDING", "ISSUED", "VOIDED")


def _merchant_of_case(case):
    program = db.programs.get(case["program_id"])
    if program is None:
        return None
    return db.merchants.get(program["merchant_id"])


def _merchant_of_transaction(tx):
    term = db.terminals.get(tx["terminal_id"])
    if term is None:
        return None
    return db.merchants.get(term["merchant_id"])


@bp.post("/complaint-cases/<case_id>/refunds")
def create_refund(case_id):
    actor = authorize(["ComplianceOfficer"])
    case = auth.get_complaint_case(case_id)
    body, malformed = parse_body()
    if malformed:
        raise v.bad("The request body must be a JSON object.")
    v.require_present(body, ["transaction_id", "refund_amount_cents"])
    transaction_id = as_string(body["transaction_id"], "transaction_id", 1)
    refund_amount_cents = as_int(body["refund_amount_cents"], "refund_amount_cents", 1)

    tx = auth.get_transaction(transaction_id)

    if case["remediation_state"] != "PLAN_ACCEPTED":
        raise ApiError("ERR_INVALID_COMPLAINT_STATE",
                       "Refunds may only be created while the remediation plan is PLAN_ACCEPTED.")

    case_merchant = _merchant_of_case(case)
    tx_merchant = _merchant_of_transaction(tx)
    if case_merchant is None or tx_merchant is None or case_merchant["id"] != tx_merchant["id"]:
        raise ApiError("ERR_REFUND_TRANSACTION_SCOPE_MISMATCH",
                       "The refunded sale belongs to another merchant.")

    remainder = tx["surcharge_amount_cents"] - calc.refunded_surcharge_cents(tx["id"])
    if refund_amount_cents > remainder:
        raise ApiError("ERR_REFUND_AMOUNT_EXCEEDS_SURCHARGE",
                       "Only %d cents of this sale's surcharge remain unrefunded." % remainder)

    for peer in calc.case_refunds(case["id"]):
        if peer["transaction_id"] == tx["id"] and peer["state"] != "VOIDED":
            raise ApiError("ERR_REFUND_DUPLICATE_TRANSACTION",
                           "A live refund already exists for this case and sale.")

    row = base_row()
    row.update({
        "complaint_case_id": case["id"],
        "transaction_id": tx["id"],
        "refund_amount_cents": refund_amount_cents,
        "state": "PENDING",
        "created_by_user_id": actor.user_id,
        "issued_by_user_id": None,
        "issued_at": None,
        "voided_at": None,
    })
    db.refunds[row["id"]] = row
    return created(serialize.refund(row))


@bp.post("/remediation-refunds/<refund_id>/issue")
def issue_refund(refund_id):
    actor = authorize(["ComplianceOfficer"])
    refund = auth.get_refund(refund_id)
    body, malformed = parse_body()
    if malformed:
        raise v.bad("The request body must be a JSON object.")

    case = db.complaint_cases.get(refund["complaint_case_id"])
    if case is None or case["remediation_state"] != "PLAN_ACCEPTED":
        raise ApiError("ERR_INVALID_COMPLAINT_STATE",
                       "The owning case's remediation plan is no longer PLAN_ACCEPTED.")
    if refund["state"] != "PENDING":
        raise ApiError("ERR_INVALID_REFUND_STATE",
                       "Only a PENDING refund can be issued.")

    if actor.user_id == refund["created_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The officer who created a refund may not issue it.")

    refund["state"] = "ISSUED"
    refund["issued_at"] = db.now()
    refund["issued_by_user_id"] = actor.user_id
    touch(refund)

    tx = db.transactions.get(refund["transaction_id"])
    if tx is not None:
        merchant = _merchant_of_transaction(tx)
        if merchant is not None:
            touch(merchant)

    return ok(serialize.refund(refund))


@bp.post("/remediation-refunds/<refund_id>/void")
def void_refund(refund_id):
    authorize(["ComplianceOfficer"])
    refund = auth.get_refund(refund_id)
    body, malformed = parse_body()
    if malformed:
        raise v.bad("The request body must be a JSON object.")

    if refund["state"] == "VOIDED":
        raise ApiError("ERR_INVALID_REFUND_STATE",
                       "An already VOIDED refund cannot be voided again.")

    was_issued = refund["state"] == "ISSUED"
    if was_issued:
        case = db.complaint_cases.get(refund["complaint_case_id"])
        if case is not None and case["remediation_state"] == "CLOSED":
            raise ApiError("ERR_INVALID_COMPLAINT_STATE",
                           "An issued refund of a CLOSED case can no longer be voided.")

    refund["state"] = "VOIDED"
    refund["voided_at"] = db.now()
    touch(refund)

    if was_issued:
        tx = db.transactions.get(refund["transaction_id"])
        if tx is not None:
            merchant = _merchant_of_transaction(tx)
            if merchant is not None:
                touch(merchant)

    return ok(serialize.refund(refund))


@bp.get("/remediation-refunds/<refund_id>")
def read_refund(refund_id):
    authorize(auth.READ_ROLES)
    return ok(serialize.refund(auth.get_refund(refund_id)))


@bp.get("/remediation-refunds")
def list_refunds():
    authorize(auth.READ_ROLES)
    rows = listing.filtered(list(db.refunds.values()), [
        (listing.arg("complaint_case_id"), "complaint_case_id"),
        (listing.arg("transaction_id"), "transaction_id"),
        (listing.enum_arg("state", REFUND_STATES), "state"),
    ])
    return listing.list_response(rows, serialize.refund)
