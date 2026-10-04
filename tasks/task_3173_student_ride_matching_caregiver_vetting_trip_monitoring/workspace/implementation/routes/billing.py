"""BillingStatement endpoints: the filtered list plus issue / pay / void.

PRD section 3.10: the statement's rate provenance is stamped as a contract_id
that is deliberately NOT a live foreign key, so the filtered list form of this
collection keeps it resolvable.
"""

import calculations as calc
import db
import models
import validators as v
from errors import (
    ERR_ALREADY_TERMINAL,
    ERR_DISTRICT_OVER_LIMIT,
    ERR_EMPTY_STATEMENT,
    ERR_INVALID_STATE,
    ERR_PERIOD_MISMATCH,
    ApiError,
    not_found,
)
from flask import Blueprint, request
from middleware import requires
from response import array_response, object_response, paginate

bp = Blueprint("billing", __name__)

PAYMENT_INPUT = ("paid_amount_cents",)


def load_statement(statement_id):
    statement = db.get("billing_statements", statement_id)
    if statement is None:
        raise not_found("The addressed billing statement does not exist.")
    return statement


def _state_gate(statement, required, msg):
    """A PAID or VOIDED statement is terminal for this dimension."""
    if statement["status"] in required:
        return
    if statement["status"] in ("PAID", "VOIDED"):
        raise ApiError(
            ERR_ALREADY_TERMINAL,
            "The statement has already reached a terminal state.",
        )
    raise ApiError(ERR_INVALID_STATE, msg)


@bp.get("/student-rides/billing-statements")
@requires("DistrictAdmin", "PlatformAdmin", "SupportCenterAgent")
def list_statements():
    rows = db.all_of("billing_statements")
    contract_id = request.args.get("contract_id")
    district_id = request.args.get("district_id")
    status = request.args.get("status")
    if contract_id:
        rows = [s for s in rows if s.get("contract_id") == contract_id]
    if district_id:
        rows = [s for s in rows if s["district_id"] == district_id]
    if status:
        rows = [s for s in rows if s["status"] == status]
    page, limit, offset, total = paginate(rows, request.args)
    return array_response(models.serialise_all("billing_statements", page), limit, offset, total)


def _assert_issuable(district):
    if district["account_status"] == "SUSPENDED":
        raise ApiError(
            ERR_DISTRICT_OVER_LIMIT,
            "The district's account is suspended and further statement issuance is blocked.",
        )
    if int(district.get("outstanding_balance_cents") or 0) > calc.OVERDUE_THRESHOLD_CENTS:
        raise ApiError(
            ERR_DISTRICT_OVER_LIMIT,
            "The district's outstanding balance exceeds its overdue threshold.",
        )


@bp.post("/student-rides/billing-statements/<statement_id>/issue")
@requires("DistrictAdmin", "PlatformAdmin")
def issue_statement(statement_id):
    statement = load_statement(statement_id)
    district = db.get("districts", statement["district_id"])

    _state_gate(statement, ("OPEN",), "Only an OPEN statement may be issued.")
    if int(statement.get("total_amount_cents") or 0) <= 0:
        raise ApiError(ERR_EMPTY_STATEMENT, "The statement carries no billable amount.")

    billed = [
        t for t in db.all_of("trips")
        if t["district_id"] == statement["district_id"]
        and t["trip_state"] == "COMPLETED"
        and t["scheduled_date"] >= statement["period_start"]
        and t["scheduled_date"] <= statement["period_end"]
    ]
    if any(t.get("billing_period_key") != statement["period_key"] for t in billed):
        raise ApiError(
            ERR_PERIOD_MISMATCH,
            "The statement's period_key does not match the billed trips' billing_period_key.",
        )

    _assert_issuable(district)

    statement["status"] = "ISSUED"
    statement["issued_at"] = db.stamp()
    db.bump_version(statement)

    if district:
        district["outstanding_balance_cents"] = (
            int(district.get("outstanding_balance_cents") or 0)
            + int(statement.get("total_amount_cents") or 0)
        )
        if int(district["outstanding_balance_cents"]) > calc.OVERDUE_THRESHOLD_CENTS:
            district["account_status"] = "SUSPENDED"
        db.bump_version(district)
    return object_response(models.billing_statement_out(statement))


@bp.post("/student-rides/billing-statements/<statement_id>/approve-payment")
@requires("DistrictAdmin", "PlatformAdmin")
def approve_payment(statement_id):
    statement = load_statement(statement_id)
    data = v.body()
    v.reject_unknown(data, PAYMENT_INPUT)
    v.as_int(data, "paid_amount_cents", required_field=False)

    _state_gate(statement, ("ISSUED",), "Only an ISSUED statement may be paid.")

    statement["status"] = "PAID"
    db.bump_version(statement)

    district = db.get("districts", statement["district_id"])
    if district:
        district["outstanding_balance_cents"] = (
            int(district.get("outstanding_balance_cents") or 0)
            - int(statement.get("total_amount_cents") or 0)
        )
        db.bump_version(district)
    return object_response(models.billing_statement_out(statement))


@bp.post("/student-rides/billing-statements/<statement_id>/void")
@requires("DistrictAdmin", "PlatformAdmin")
def void_statement(statement_id):
    statement = load_statement(statement_id)
    _state_gate(statement, ("ISSUED",), "Only an ISSUED statement may be voided through this operation.")

    statement["status"] = "VOIDED"
    db.bump_version(statement)

    district = db.get("districts", statement["district_id"])
    if district:
        district["outstanding_balance_cents"] = (
            int(district.get("outstanding_balance_cents") or 0)
            - int(statement.get("total_amount_cents") or 0)
        )
        # Only the credit actually consumed by the statement returns to the pool.
        district["credit_balance_cents"] = (
            int(district.get("credit_balance_cents") or 0)
            + int(statement.get("applied_credit_cents") or 0)
        )
        db.bump_version(district)
    return object_response(models.billing_statement_out(statement))