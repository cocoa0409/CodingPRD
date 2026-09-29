"""Servicing: accrual, the classification-dependent waterfall, reversal,
periodic assessment and lot-rent reporting (PRD 3.7)."""

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

bp = Blueprint("servicing", __name__)

PAYMENT_READ_ROLES = security.STAFF + (security.BORROWER,)

SERVICING_OPEN_STATES = ("CURRENT", "DELINQUENT")


def _release_on_settlement(loan):
    """A satisfied loan releases its recorded instrument; never restored."""
    for filing in store.filings_of_loan(loan["id"]):
        if filing["status"] == "RECORDED":
            filing["status"] = "RELEASED"
            filing["released_at"] = core.now()
            filing["_release_cause"] = K.RELEASE_CAUSE_SETTLEMENT
            store.touch(filing)
    loan["perfection_state"] = "RELEASED"


# --------------------------------------------------------------------------
# lot rent
# --------------------------------------------------------------------------

@bp.post("/loans/<loan_id>/lot-rent-report")
def lot_rent_report(loan_id):
    actor = security.require(security.COMMUNITY_OPERATOR)
    loan = store.get_loan(loan_id)
    security.check_loan_scope(actor, loan)
    data = shape.body()
    months = shape.req_int(data, "months_delinquent", minimum=0)
    state = shape.req_enum(data, "lot_rent_state", K.LOT_RENT_STATES)

    if loan["servicing_state"] not in SERVICING_OPEN_STATES:
        raise ApiError("ERR_LOAN_SERVICING_INVALID_STATE")

    loan["lot_rent_months_delinquent"] = months
    loan["lot_rent_state"] = state
    store.touch(loan)
    domain.recompute_exposure_for_loan(loan)
    return envelope.ok(store.serialize(loan))


# --------------------------------------------------------------------------
# payments
# --------------------------------------------------------------------------

def _payment_row(loan, amount_cents, kind, variant, applied, accrual_days,
                 accrued, reverses_payment_id=None):
    record = {
        "id": core.new_id(),
        "loan_id": loan["id"],
        "reverses_payment_id": reverses_payment_id,
        "amount_cents": amount_cents,
        "payment_kind": kind,
        "posted_at": core.now(),
        "accrual_days": accrual_days,
        "accrued_interest_at_posting_cents": accrued,
        "allocation_variant": variant,
        "to_interest_cents": applied["interest"],
        "to_fees_cents": applied["fees"],
        "to_force_placed_cents": applied["force_placed"],
        "to_escrow_cents": applied["escrow"],
        "to_principal_cents": applied["principal"],
        "reversed": False,
    }
    store.stamp_new(record, versioned=False)
    store.payments[record["id"]] = record
    return record


@bp.post("/loans/<loan_id>/payments")
def post_payment(loan_id):
    security.require(security.SERVICER)
    loan = store.get_loan(loan_id)
    data = shape.body()
    amount_cents = shape.req_int(data, "amount_cents")
    kind = shape.req_enum(data, "payment_kind", K.PAYMENT_KINDS)

    if loan["servicing_state"] not in SERVICING_OPEN_STATES:
        raise ApiError("ERR_LOAN_SERVICING_INVALID_STATE")

    # interest accrues exactly once per servicing operation; nothing is
    # committed until every cash-integrity check has passed.
    accrual_days, accrued = domain.accrual_preview(loan)
    interest_outstanding = loan["interest_accrued_unpaid_cents"] + accrued
    variant = domain.allocation_variant_for(loan)

    if kind == "PAYOFF":
        expected = (interest_outstanding
                    + loan["fees_outstanding_cents"]
                    + loan["force_placed_premium_outstanding_cents"]
                    + loan["principal_balance_cents"]
                    - loan["escrow_balance_cents"])
        if amount_cents != expected:
            raise ApiError("ERR_PAYOFF_AMOUNT_MISMATCH")
        applied = {
            "interest": interest_outstanding,
            "fees": loan["fees_outstanding_cents"],
            "force_placed": loan["force_placed_premium_outstanding_cents"],
            "escrow": -loan["escrow_balance_cents"],
            "principal": loan["principal_balance_cents"],
        }
        domain.commit_accrual(loan, accrued)
        loan["interest_accrued_unpaid_cents"] = 0
        loan["fees_outstanding_cents"] = 0
        loan["force_placed_premium_outstanding_cents"] = 0
        loan["escrow_balance_cents"] = 0
        loan["principal_balance_cents"] = 0
        loan["delinquent_days"] = 0
        loan["servicing_state"] = "PAID_OFF"
        _release_on_settlement(loan)
        record = _payment_row(loan, amount_cents, kind, variant, applied,
                              accrual_days, accrued)
        store.touch(loan)
        domain.recompute_exposure_for_loan(loan)
        return envelope.created(store.serialize(record))

    variant, applied, remaining = domain.allocate(loan, amount_cents, interest_outstanding)
    if kind in ("SCHEDULED", "PARTIAL") and remaining > 0:
        raise ApiError("ERR_OVERPAYMENT_NOT_PERMITTED")

    domain.commit_accrual(loan, accrued)
    domain.apply_allocation(loan, applied)

    if (loan["servicing_state"] == "DELINQUENT"
            and loan["interest_accrued_unpaid_cents"] == 0
            and loan["fees_outstanding_cents"] == 0):
        loan["servicing_state"] = "CURRENT"
        if loan["next_due_date"] is not None:
            loan["next_due_date"] = core.add_one_month(loan["next_due_date"])
        loan["delinquent_days"] = 0

    record = _payment_row(loan, amount_cents, kind, variant, applied, accrual_days, accrued)
    store.touch(loan)
    domain.recompute_exposure_for_loan(loan)
    return envelope.created(store.serialize(record))


@bp.get("/payments/<payment_id>")
def read_payment(payment_id):
    actor = security.require(*PAYMENT_READ_ROLES)
    payment = store.get_payment(payment_id)
    loan = store.loans.get(payment["loan_id"])
    if loan is not None:
        security.check_loan_scope(actor, loan)
    return envelope.ok(store.serialize(payment))


@bp.get("/payments")
def list_payments():
    actor = security.require(*PAYMENT_READ_ROLES)
    loan_id = request.args.get("loan_id")
    reverses_payment_id = request.args.get("reverses_payment_id")
    payment_kind = query_enum("payment_kind", K.PAYMENT_KINDS)

    rows = store.ordered(list(store.payments.values()))
    if loan_id:
        rows = [p for p in rows if p["loan_id"] == loan_id]
    if reverses_payment_id:
        rows = [p for p in rows if p["reverses_payment_id"] == reverses_payment_id]
    if payment_kind:
        rows = [p for p in rows if p["payment_kind"] == payment_kind]
    rows = security.narrow_by_loan(actor, rows)
    return envelope.paginate(rows, store.serialize)


@bp.post("/payments/<payment_id>/reverse")
def reverse_payment(payment_id):
    security.require(security.SERVICER)
    original = store.get_payment(payment_id)
    data = shape.body()
    reason = shape.opt_string(data, "reversal_reason")

    if original["reversed"] or original["payment_kind"] == "REVERSAL":
        raise ApiError("ERR_PAYMENT_ALREADY_REVERSED")

    loan = store.get_loan(original["loan_id"])
    applied = {
        "interest": -original["to_interest_cents"],
        "fees": -original["to_fees_cents"],
        "force_placed": -original["to_force_placed_cents"],
        "escrow": -original["to_escrow_cents"],
        "principal": -original["to_principal_cents"],
    }
    # restores every bucket without re-accruing interest
    domain.apply_allocation(loan, applied)
    original["reversed"] = True

    record = _payment_row(loan, -original["amount_cents"], "REVERSAL",
                          original["allocation_variant"], applied, 0, 0,
                          reverses_payment_id=original["id"])
    record["reversal_reason"] = reason
    store.touch(loan)
    domain.recompute_exposure_for_loan(loan)
    return envelope.created(store.serialize(record))


# --------------------------------------------------------------------------
# periodic assessment
# --------------------------------------------------------------------------

@bp.post("/loans/<loan_id>/servicing-assessment")
def servicing_assessment(loan_id):
    security.require(security.SERVICER)
    loan = store.get_loan(loan_id)
    if loan["servicing_state"] not in SERVICING_OPEN_STATES:
        raise ApiError("ERR_LOAN_SERVICING_INVALID_STATE")

    accrual_days, accrued = domain.accrual_preview(loan)
    domain.commit_accrual(loan, accrued)

    loan["delinquent_days"] = domain.delinquent_days_for(loan)

    lapsed_any = False
    for policy in store.policies_of_loan(loan["id"]):
        if policy["status"] == "ACTIVE" and core.now() >= policy["expiry_date"]:
            policy["status"] = "LAPSED"
            store.touch(policy)
            lapsed_any = True
    if lapsed_any:
        loan["insurance_compliance"] = "NON_COMPLIANT"

    if (loan["delinquent_days"] >= K.DELINQUENCY_THRESHOLD_DAYS
            and loan["servicing_state"] == "CURRENT"):
        loan["servicing_state"] = "DELINQUENT"
        loan["fees_outstanding_cents"] += K.LATE_FEE_FLAT_CENTS

    store.touch(loan)
    return envelope.ok(store.serialize(loan))
