"""Application decision / approval cascade (PRD 3.6)."""

from flask import Blueprint

import calc
import cascade
from auth import require_roles
from body import is_int, json_body, req_enum
from domain import (app_grants, bump, get_or_404, latest_pass_review,
                    latest_verification, new_common)
from envelope import success
from errors import raise_err
from store import get, put
from serializers import serialize

bp = Blueprint("decision", __name__)


def _create_loan(app, applicant, approved, collateral_description, collateral_value):
    rate, term = calc.rate_and_term(applicant["applicant_type"], app["loan_purpose"])
    monthly = calc.monthly_payment_cents(approved, rate, term, deferred_capitalized=True)
    loan = new_common()
    loan.update({
        "application_id": app["id"],
        "applicant_id": app["applicant_id"],
        "loan_purpose": app["loan_purpose"],
        "approved_amount_cents": approved,
        "interest_rate": float(rate),
        "term_months": term,
        "deferral_months": calc.DEFERRAL_MONTHS,
        "monthly_payment_cents": monthly,
        "collateral_required": approved > calc.COLLATERAL_THRESHOLD[app["loan_purpose"]],
        "collateral_description": collateral_description,
        "collateral_value_cents": collateral_value,
        "commitment_amount_cents": approved,
        "disbursed_total_cents": 0,
        "outstanding_balance_cents": 0,
        "accrued_interest_balance_cents": 0,
        "last_accrual_date": None,
        "late_fee_balance_cents": 0,
        "total_principal_paid_cents": 0,
        "total_interest_paid_cents": 0,
        "next_due_date": None,
        "days_past_due": 0,
        "lifecycle_status": "PENDING_ACCEPTANCE",
        "servicing_status": "CURRENT",
        "_fee_marker": None,
    })
    put("loans", loan)
    return loan


@bp.post("/disaster-relief/loan-applications/<app_id>/decision")
@require_roles("LoanApprover")
def decide_application(app_id):
    app = get_or_404("applications", app_id)
    data = json_body()
    decision = req_enum(data, "decision", {"APPROVED", "DECLINED"})
    if app["status"] != "DECISION_PENDING":
        raise_err("ERR_APPLICATION_NOT_DECISION_PENDING")
    if decision == "DECLINED":
        app["decline_reason"] = "APPROVER_DECLINE"
        app["status"] = "DECLINED"
        bump(app)
        return success(serialize(app))
    # APPROVED. The verification state-family gate runs before any fiscal check.
    if app["loan_purpose"] == "PHYSICAL_DAMAGE":
        latest = latest_verification(app["id"])
        if latest is None or latest["status"] != "COMPLETED":
            raise_err("ERR_VERIFICATION_REQUIRED")
    applicant = get("applicants", app["applicant_id"])
    if applicant is None:
        raise_err("ERR_NOT_FOUND", "applicant not found")
    approved = calc.approved_amount_cents(
        app, applicant, latest_pass_review(app["id"]),
        latest_verification(app["id"], completed_only=True), app_grants(app["id"]))
    collateral_required = approved > calc.COLLATERAL_THRESHOLD[app["loan_purpose"]]
    collateral_description = None
    collateral_value = None
    if collateral_required:
        cd = data.get("collateral_description")
        cv = data.get("collateral_value_cents")
        if (not isinstance(cd, str) or cd == "" or not is_int(cv) or cv < approved):
            raise_err("ERR_COLLATERAL_REQUIRED")
        collateral_description = cd
        collateral_value = cv
    loan = _create_loan(app, applicant, approved, collateral_description, collateral_value)
    cascade.create_tranche_schedule(loan)
    app["loan_id"] = loan["id"]
    app["status"] = "APPROVED"
    bump(app)
    return success(serialize(app))
