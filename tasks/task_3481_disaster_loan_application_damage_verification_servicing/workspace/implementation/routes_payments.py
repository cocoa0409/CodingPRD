"""Loan payments (PRD 3.9): waterfall allocation, cure, payoff, reversal."""

from flask import Blueprint, request

import calc
import clock
from auth import check_owner, require_roles
from body import json_body, req_int
from domain import bump, get_or_404, loan_payments
from envelope import page, parse_pagination, success, success_list
from errors import raise_err
from store import new_id, put
from serializers import serialize, serialize_all
from timeutil import days_between

bp = Blueprint("payments", __name__)


@bp.post("/disaster-relief/loans/<loan_id>/payments")
@require_roles("Applicant")
def post_payment(loan_id):
    loan = get_or_404("loans", loan_id)
    check_owner(loan["applicant_id"])
    data = json_body()
    amount = req_int(data, "amount_cents", min_value=1)
    if loan["lifecycle_status"] != "ACTIVE":
        raise_err("ERR_LOAN_NOT_ACTIVE")
    now = clock.get_current()
    # payment_allocation_calc, pinned order. Step (1): interest due, with the
    # accrual rounding happening exactly once, here, before any allocation.
    if loan["last_accrual_date"] is None:
        days = 0
    else:
        days = max(0, days_between(loan["last_accrual_date"], now))
    rate = calc.rate_and_term_for_loan(loan)
    interest_due = loan["accrued_interest_balance_cents"] + calc.daily_interest_cents(
        loan["outstanding_balance_cents"], rate, days)
    total_due = loan["late_fee_balance_cents"] + interest_due + loan["outstanding_balance_cents"]
    if amount > total_due:
        raise_err("ERR_PAYMENT_EXCEEDS_BALANCE")
    # Steps (2)-(4): fees, then interest, then the remainder to principal.
    fee_portion = min(amount, loan["late_fee_balance_cents"])
    rem = amount - fee_portion
    interest_portion = min(rem, interest_due)
    rem -= interest_portion
    principal_portion = rem
    pre_last_accrual = loan["last_accrual_date"]
    loan["late_fee_balance_cents"] -= fee_portion
    loan["accrued_interest_balance_cents"] = interest_due - interest_portion
    loan["outstanding_balance_cents"] -= principal_portion
    loan["last_accrual_date"] = now
    loan["total_principal_paid_cents"] += principal_portion
    loan["total_interest_paid_cents"] += interest_portion
    # A curing payment lifts DELINQUENT to CURRENT (missed principal not required).
    if (loan["servicing_status"] == "DELINQUENT"
            and loan["late_fee_balance_cents"] == 0
            and loan["accrued_interest_balance_cents"] == 0):
        loan["servicing_status"] = "CURRENT"
        loan["days_past_due"] = 0
    caused_pif = False
    if loan["outstanding_balance_cents"] == 0:
        loan["lifecycle_status"] = "PAID_IN_FULL"
        caused_pif = True
    bump(loan)
    payment = {
        "id": new_id(),
        "created_at": now,
        "loan_id": loan["id"],
        "amount_cents": amount,
        "fee_portion_cents": fee_portion,
        "interest_portion_cents": interest_portion,
        "principal_portion_cents": principal_portion,
        "status": "POSTED",
        "_pre_last_accrual": pre_last_accrual,
        "_caused_pif": caused_pif,
    }
    put("payments", payment)
    return success(serialize(payment), 201)


@bp.get("/disaster-relief/loans/<loan_id>/payments")
@require_roles("Applicant", "ServicingAgent", "LoanApprover")
def list_payments(loan_id):
    loan = get_or_404("loans", loan_id)
    check_owner(loan["applicant_id"])
    rows = loan_payments(loan["id"])
    limit, offset = parse_pagination(request.args)
    items, total = page(rows, limit, offset)
    return success_list(serialize_all(items), limit, offset, total)


@bp.post("/disaster-relief/payments/<payment_id>/reverse")
@require_roles("ServicingAgent")
def reverse_payment(payment_id):
    p = get_or_404("payments", payment_id)
    if p["status"] != "POSTED":
        raise_err("ERR_INVALID_REQUEST", "only a POSTED payment can be reversed")
    loan = get_or_404("loans", p["loan_id"])
    # Exact compensation of the allocation.
    loan["outstanding_balance_cents"] += p["principal_portion_cents"]
    loan["total_principal_paid_cents"] -= p["principal_portion_cents"]
    loan["total_interest_paid_cents"] -= p["interest_portion_cents"]
    loan["accrued_interest_balance_cents"] += p["interest_portion_cents"]
    loan["late_fee_balance_cents"] += p["fee_portion_cents"]
    loan["last_accrual_date"] = p["_pre_last_accrual"]
    if p["_caused_pif"] and loan["lifecycle_status"] == "PAID_IN_FULL":
        loan["lifecycle_status"] = "ACTIVE"
    p["status"] = "REVERSED"
    bump(loan)
    return success(serialize(p))
