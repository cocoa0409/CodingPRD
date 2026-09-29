"""Origination: application, pricing, credit decision and funding (PRD 3.4)."""

from flask import Blueprint, request

import constants as K
import core
import domain
import envelope
import security
import shape
import store
from errors import ApiError
from routes_units import query_enum

bp = Blueprint("loans", __name__)

LOAN_READ_ROLES = security.STAFF + (security.BORROWER,)


def settled_classification(unit):
    """A CONVERSION_PENDING unit is mid-flight; its loans hold a settled value."""
    if unit["classification"] == "REAL_PROPERTY":
        return "REAL_PROPERTY"
    return "PERSONAL_PROPERTY"


def check_origination_valuation(valuation, unit_id):
    if (valuation["status"] != "CERTIFIED" or valuation["variant"] != "ORIGINATION"
            or valuation["unit_id"] != unit_id):
        raise ApiError("ERR_VALUATION_VARIANT_MISMATCH")


@bp.post("/loans")
def create_loan():
    security.require(security.CREDIT_ANALYST)
    data = shape.body()

    borrower = store.get_borrower(shape.req_id(data, "borrower_id"))
    unit = store.get_unit(shape.req_id(data, "unit_id"))
    valuation = store.get_valuation(shape.req_id(data, "origination_valuation_id"))
    refinanced_from_loan_id = shape.opt_id(data, "refinanced_from_loan_id")
    if refinanced_from_loan_id is not None:
        store.get_loan(refinanced_from_loan_id)

    principal_cents = shape.req_int(data, "principal_cents", minimum=1)
    requested_term_months = shape.req_int(data, "requested_term_months", minimum=1)

    check_origination_valuation(valuation, unit["id"])

    if borrower["status"] != "ACTIVE":
        raise ApiError("ERR_BORROWER_SUSPENDED")

    record = {
        "id": core.new_id(),
        "borrower_id": borrower["id"],
        "unit_id": unit["id"],
        "origination_valuation_id": valuation["id"],
        "refinanced_from_loan_id": refinanced_from_loan_id,
        "principal_cents": principal_cents,
        "requested_term_months": requested_term_months,
        "collateral_classification": settled_classification(unit),
        "placement_type": unit["placement_type"],
        "ltv_bps": None,
        "apr_bps": None,
        "term_months": None,
        "underwriting_state": "DRAFT",
        "servicing_state": "NOT_SERVICING",
        "perfection_state": "UNPERFECTED",
        "principal_balance_cents": 0,
        "interest_accrued_unpaid_cents": 0,
        "fees_outstanding_cents": 0,
        "escrow_target_cents": 0,
        "escrow_balance_cents": 0,
        "force_placed_premium_outstanding_cents": 0,
        "insurance_compliance": "UNKNOWN",
        "lot_rent_months_delinquent": 0,
        "lot_rent_state": "CURRENT",
        "next_due_date": None,
        "last_accrual_date": None,
        "delinquent_days": 0,
        "approved_by_user_id": None,
        "decline_reason": None,
        "funded_at": None,
    }
    store.stamp_new(record)
    store.loans[record["id"]] = record
    return envelope.created(store.serialize(record))


@bp.get("/loans/<loan_id>")
def read_loan(loan_id):
    actor = security.require(*LOAN_READ_ROLES)
    loan = store.get_loan(loan_id)
    security.check_loan_scope(actor, loan)
    return envelope.ok(store.serialize(loan))


@bp.get("/loans")
def list_loans():
    actor = security.require(*LOAN_READ_ROLES)
    borrower_id = request.args.get("borrower_id")
    unit_id = request.args.get("unit_id")
    origination_valuation_id = request.args.get("origination_valuation_id")
    refinanced_from_loan_id = request.args.get("refinanced_from_loan_id")
    servicing_state = query_enum("servicing_state", K.SERVICING_STATES)

    rows = store.ordered(list(store.loans.values()))
    if borrower_id:
        rows = [l for l in rows if l["borrower_id"] == borrower_id]
    if unit_id:
        rows = [l for l in rows if l["unit_id"] == unit_id]
    if origination_valuation_id:
        rows = [l for l in rows if l["origination_valuation_id"] == origination_valuation_id]
    if refinanced_from_loan_id:
        rows = [l for l in rows if l["refinanced_from_loan_id"] == refinanced_from_loan_id]
    if servicing_state:
        rows = [l for l in rows if l["servicing_state"] == servicing_state]
    rows = security.narrow_loans(actor, rows)
    return envelope.paginate(rows, store.serialize)


# --------------------------------------------------------------------------
# pricing and the credit decision
# --------------------------------------------------------------------------

@bp.post("/loans/<loan_id>/submit-underwriting")
def submit_underwriting(loan_id):
    security.require(security.CREDIT_ANALYST)
    loan = store.get_loan(loan_id)
    if loan["underwriting_state"] != "DRAFT":
        raise ApiError("ERR_LOAN_UNDERWRITING_INVALID_STATE")

    valuation = store.valuations.get(loan["origination_valuation_id"])
    if valuation is None:
        raise ApiError("ERR_VALUATION_VARIANT_MISMATCH")
    check_origination_valuation(valuation, loan["unit_id"])

    borrower = store.borrowers.get(loan["borrower_id"])
    unit = store.units.get(loan["unit_id"])

    ltv_bps = domain.compute_ltv_bps(loan["principal_cents"], valuation["certified_value_cents"])
    if ltv_bps is None or ltv_bps > K.LTV_CAP_BPS:
        raise ApiError("ERR_LTV_CAP_EXCEEDED")

    apr_bps = domain.compute_apr_bps(loan, borrower, unit, ltv_bps)
    term_months = domain.compute_term_months(loan, unit, valuation)
    if term_months < K.MIN_TERM_MONTHS:
        raise ApiError("ERR_TERM_FLOOR_UNREACHABLE")

    loan["ltv_bps"] = ltv_bps
    loan["apr_bps"] = apr_bps
    loan["term_months"] = term_months
    loan["underwriting_state"] = "UNDERWRITING"
    store.touch(loan)
    return envelope.ok(store.serialize(loan))


@bp.post("/loans/<loan_id>/approve")
def approve_loan(loan_id):
    actor = security.require(security.CREDIT_ANALYST)
    loan = store.get_loan(loan_id)
    if loan["underwriting_state"] != "UNDERWRITING":
        raise ApiError("ERR_LOAN_UNDERWRITING_INVALID_STATE")

    valuation = store.valuations.get(loan["origination_valuation_id"])
    if valuation is not None and valuation["certified_by_user_id"] == actor.user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    borrower = store.borrowers.get(loan["borrower_id"])
    domain.recompute_borrower_exposure(borrower)
    if borrower is not None and borrower["status"] != "ACTIVE":
        raise ApiError("ERR_BORROWER_SUSPENDED")

    outstanding = borrower["total_outstanding_principal_cents"] if borrower else 0
    if outstanding + loan["principal_cents"] > K.EXPOSURE_CAP_CENTS:
        raise ApiError("ERR_EXPOSURE_CAP_EXCEEDED")

    loan["underwriting_state"] = "APPROVED"
    loan["approved_by_user_id"] = actor.user_id
    store.touch(loan)
    return envelope.ok(store.serialize(loan))


@bp.post("/loans/<loan_id>/decline")
def decline_loan(loan_id):
    security.require(security.CREDIT_ANALYST)
    loan = store.get_loan(loan_id)
    if loan["underwriting_state"] != "UNDERWRITING":
        raise ApiError("ERR_LOAN_UNDERWRITING_INVALID_STATE")
    data = shape.body()
    reason = shape.opt_string(data, "decline_reason")
    loan["underwriting_state"] = "DECLINED"
    loan["decline_reason"] = reason
    store.touch(loan)
    return envelope.ok(store.serialize(loan))


# --------------------------------------------------------------------------
# funding
# --------------------------------------------------------------------------

def recorded_filings(loan_id):
    return [f for f in store.filings_of_loan(loan_id) if f["status"] == "RECORDED"]


def covering_active_policies(loan_id):
    rows = []
    for policy in store.policies_of_loan(loan_id):
        if policy["status"] != "ACTIVE":
            continue
        if policy["effective_date"] <= core.now() < policy["expiry_date"]:
            rows.append(policy)
    return rows


def check_funding_insurance(loan, unit):
    candidates = covering_active_policies(loan["id"])
    if not candidates:
        raise ApiError("ERR_INSURANCE_NON_COMPLIANT")
    if domain.wind_required(unit):
        if not any(p["wind_endorsement"] for p in candidates):
            raise ApiError("ERR_WIND_COVERAGE_INSUFFICIENT")
    required = domain.required_coverage_cents(loan)
    if not any(p["dwelling_coverage_cents"] >= required for p in candidates):
        raise ApiError("ERR_DWELLING_COVERAGE_INSUFFICIENT")


@bp.post("/loans/<loan_id>/fund")
def fund_loan(loan_id):
    security.require(security.CLOSING_AGENT)
    loan = store.get_loan(loan_id)
    data = shape.body()
    first_due_date = shape.req_instant(data, "first_due_date")
    escrow_target_cents = shape.opt_int(data, "escrow_target_cents", default=0, minimum=0)

    if loan["underwriting_state"] != "APPROVED":
        raise ApiError("ERR_LOAN_UNDERWRITING_INVALID_STATE")

    unit = store.units.get(loan["unit_id"])

    # the recorded instrument must match the loan's classification
    recorded = recorded_filings(loan["id"])
    expected_type = K.FILING_TYPE_FOR_CLASSIFICATION[loan["collateral_classification"]]
    for filing in recorded:
        if filing["filing_type"] != expected_type:
            raise ApiError("ERR_FILING_TYPE_MISMATCH")

    check_funding_insurance(loan, unit)

    if loan["placement_type"] == "COMMUNITY":
        community = store.communities.get(unit.get("community_id")) if unit else None
        if community is None or community["operator_agreement_status"] != "EXECUTED":
            raise ApiError("ERR_OPERATOR_AGREEMENT_MISSING")

    if loan["perfection_state"] != "PERFECTED" or len(recorded) != 1:
        raise ApiError("ERR_PERFECTION_NOT_ESTABLISHED")

    loan["underwriting_state"] = "FUNDED"
    loan["servicing_state"] = "CURRENT"
    loan["funded_at"] = core.now()
    loan["last_accrual_date"] = core.now()
    loan["next_due_date"] = first_due_date
    loan["principal_balance_cents"] = loan["principal_cents"]
    loan["escrow_target_cents"] = escrow_target_cents
    store.touch(loan)
    domain.recompute_exposure_for_loan(loan)
    return envelope.ok(store.serialize(loan))
