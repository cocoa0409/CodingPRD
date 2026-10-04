"""Excess-funds receivables (PRD 3.8): list and pay down."""

from flask import Blueprint, request

from auth import check_owner, require_roles
from body import json_body, req_int
from domain import bump, get_or_404, loan_receivables
from envelope import page, parse_pagination, success, success_list
from errors import raise_err
from serializers import serialize, serialize_all

bp = Blueprint("receivables", __name__)


@bp.get("/disaster-relief/loans/<loan_id>/excess-funds-receivables")
@require_roles("Applicant", "ServicingAgent", "LoanApprover")
def list_receivables(loan_id):
    loan = get_or_404("loans", loan_id)
    check_owner(loan["applicant_id"])
    rows = loan_receivables(loan["id"])
    limit, offset = parse_pagination(request.args)
    items, total = page(rows, limit, offset)
    return success_list(serialize_all(items), limit, offset, total)


@bp.post("/disaster-relief/excess-funds-receivables/<receivable_id>/payments")
@require_roles("Applicant")
def pay_receivable(receivable_id):
    r = get_or_404("receivables", receivable_id)
    loan = get_or_404("loans", r["loan_id"])
    check_owner(loan["applicant_id"])
    data = json_body()
    amount = req_int(data, "amount_cents", min_value=1)
    if r["status"] not in ("OPEN", "PARTIALLY_PAID"):
        raise_err("ERR_RECEIVABLE_NOT_OPEN")
    remaining = r["amount_due_cents"] - r["amount_paid_cents"]
    if amount > remaining:
        raise_err("ERR_PAYMENT_EXCEEDS_BALANCE")
    r["amount_paid_cents"] += amount
    r["status"] = "PAID" if amount == remaining else "PARTIALLY_PAID"
    bump(r)
    # The excess was disbursed principal: paying it down reduces the loan balance.
    loan["outstanding_balance_cents"] -= amount
    loan["total_principal_paid_cents"] += amount
    if loan["outstanding_balance_cents"] == 0 and loan["lifecycle_status"] == "ACTIVE":
        loan["lifecycle_status"] = "PAID_IN_FULL"
    bump(loan)
    return success(serialize(r), 201)
