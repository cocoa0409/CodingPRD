"""Leveraged ESOP loan endpoints (PRD 3.2)."""

from flask import Blueprint

import calc
import responses
import services
import validation as v
from auth import PLAN_ADMINISTRATOR, PLAN_SPONSOR, READ_ROLES, endpoint
from db import DB, insert, serialize, sorted_rows, touch
from errors import fail

bp = Blueprint("loans", __name__)

RELEASE_METHODS = ("PRINCIPAL_ONLY", "PRINCIPAL_AND_INTEREST")


@bp.post("/esop-loans")
@endpoint([PLAN_SPONSOR])
def create_loan():
    body = v.body()
    plan_id = v.req_string(body, "plan_id")
    lender_name = v.req_string(body, "lender_name")
    original_principal_cents = v.req_integer(body, "original_principal_cents", minimum=1)
    original_interest_cents = v.req_integer(body, "original_interest_cents", minimum=0)
    shares_pledged = v.req_integer(body, "shares_pledged", minimum=1)
    release_method = v.req_enum(body, "release_method", RELEASE_METHODS)

    plan = services.get_plan(plan_id)
    services.check_not_frozen(plan)
    services.require_plan_status(plan, "OPEN")

    loan = insert(DB.loans, {
        "plan_id": plan_id,
        "lender_name": lender_name,
        "original_principal_cents": original_principal_cents,
        "original_interest_cents": original_interest_cents,
        "shares_pledged": shares_pledged,
        "release_method": release_method,
        "principal_balance_cents": original_principal_cents,
        "remaining_interest_cents": original_interest_cents,
        "suspense_shares": shares_pledged,
        "released_shares_cumulative": 0,
        "status": "AMORTIZING",
    })

    plan["total_plan_shares"] += shares_pledged
    plan["suspense_shares"] += shares_pledged
    touch(plan)
    return responses.ok(serialize(loan), 201)


@bp.get("/esop-loans/<loan_id>")
@endpoint(READ_ROLES)
def read_loan(loan_id):
    return responses.ok(serialize(services.get_loan(loan_id)))


@bp.get("/esop-loans")
@endpoint(READ_ROLES)
def list_loans():
    limit, offset = v.pagination()
    plan_id = v.query_str("plan_id")
    status = v.query_str("status")
    rows = sorted_rows(DB.loans)
    if plan_id is not None:
        rows = [r for r in rows if r["plan_id"] == plan_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return services.paged(rows, limit, offset)


@bp.post("/loan-payments")
@endpoint([PLAN_ADMINISTRATOR])
def create_loan_payment():
    body = v.body()
    loan_id = v.req_string(body, "loan_id")
    payment_date = v.req_date(body, "payment_date")
    principal_cents = v.req_integer(body, "principal_cents", minimum=0)
    interest_cents = v.req_integer(body, "interest_cents", minimum=0)

    loan = services.get_loan(loan_id)
    plan = services.get_plan(loan["plan_id"])
    services.check_not_frozen(plan)

    if (principal_cents > loan["principal_balance_cents"]
            or interest_cents > loan["remaining_interest_cents"]):
        fail("ERR_PAYMENT_EXCEEDS_BALANCE")

    result = calc.loan_share_release(
        loan["suspense_shares"], loan["principal_balance_cents"],
        loan["remaining_interest_cents"], principal_cents, interest_cents,
        loan["release_method"])

    payment = insert(DB.loan_payments, {
        "loan_id": loan_id,
        "payment_date": payment_date,
        "principal_cents": principal_cents,
        "interest_cents": interest_cents,
        "suspense_shares_before": result["suspense_shares_before"],
        "released_shares": result["released_shares"],
        "suspense_shares_after": result["suspense_shares_after"],
        "release_method_applied": loan["release_method"],
        "principal_balance_after_cents": result["principal_balance_after_cents"],
        "remaining_interest_after_cents": result["remaining_interest_after_cents"],
    }, common_fields=False)

    released = result["released_shares"]
    loan["principal_balance_cents"] = result["principal_balance_after_cents"]
    loan["remaining_interest_cents"] = result["remaining_interest_after_cents"]
    loan["suspense_shares"] = result["suspense_shares_after"]
    loan["released_shares_cumulative"] += released
    if result["fully_repaid"]:
        loan["suspense_shares"] = 0
        loan["status"] = "REPAID"
    touch(loan)

    plan["suspense_shares"] -= released
    plan["unallocated_released_shares"] += released
    touch(plan)

    return responses.ok(serialize(payment), 201)


@bp.get("/loan-payments/<payment_id>")
@endpoint(READ_ROLES)
def read_loan_payment(payment_id):
    return responses.ok(serialize(services.lookup("loan_payments", payment_id)))


@bp.get("/loan-payments")
@endpoint(READ_ROLES)
def list_loan_payments():
    limit, offset = v.pagination()
    loan_id = v.query_str("loan_id")
    rows = sorted_rows(DB.loan_payments)
    if loan_id is not None:
        rows = [r for r in rows if r["loan_id"] == loan_id]
    return services.paged(rows, limit, offset)
