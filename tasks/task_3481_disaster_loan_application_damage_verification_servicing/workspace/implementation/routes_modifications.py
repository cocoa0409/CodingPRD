"""Modification requests (PRD 3.8): OCC-guarded create with supersede, decision."""

from flask import Blueprint, g, request

import calc
import cascade
from auth import check_owner, require_roles
from body import is_int, json_body, req_enum, req_int, req_str
from domain import bump, get_or_404, new_common
from envelope import page, parse_pagination, success, success_list
from errors import raise_err
from store import all_rows, get, put
from serializers import serialize, serialize_all

bp = Blueprint("modifications", __name__)


@bp.post("/disaster-relief/loans/<loan_id>/modification-requests")
@require_roles("Applicant")
def create_modification(loan_id):
    loan = get_or_404("loans", loan_id)
    check_owner(loan["applicant_id"])
    data = json_body()
    requested = req_int(data, "requested_amount_cents", min_value=1)
    reason = req_str(data, "reason")
    if requested == loan["approved_amount_cents"]:
        raise_err("ERR_INVALID_REQUEST", "requested_amount_cents must differ from the current approved amount")
    expected = data.get("expected_loan_version")
    if not is_int(expected):
        raise_err("ERR_INVALID_REQUEST", "expected_loan_version is required")
    # OCC (priority 6) precedes the loan-state gate (priority 8).
    if expected != loan["version"]:
        raise_err("ERR_STALE_VERSION")
    if loan["lifecycle_status"] != "ACTIVE":
        raise_err("ERR_LOAN_NOT_ACTIVE")
    # A newer create supersedes (auto-DENIES) a still-SUBMITTED predecessor.
    for m in all_rows("modifications"):
        if m["loan_id"] == loan["id"] and m["status"] == "SUBMITTED":
            m["status"] = "DENIED"
            bump(m)
    row = new_common()
    row.update({
        "loan_id": loan["id"],
        "requested_amount_cents": requested,
        "reason": reason,
        "status": "SUBMITTED",
        "decided_by": None,
    })
    put("modifications", row)
    bump(loan)  # a successful create bumps loan.version
    return success(serialize(row), 201)


@bp.get("/disaster-relief/loans/<loan_id>/modification-requests")
@require_roles("Applicant", "LoanApprover", "ServicingAgent")
def list_modifications(loan_id):
    loan = get_or_404("loans", loan_id)
    check_owner(loan["applicant_id"])
    rows = [m for m in all_rows("modifications") if m["loan_id"] == loan_id]
    limit, offset = parse_pagination(request.args)
    items, total = page(rows, limit, offset)
    return success_list(serialize_all(items), limit, offset, total)


@bp.post("/disaster-relief/modification-requests/<mod_id>/decision")
@require_roles("LoanApprover")
def decide_modification(mod_id):
    m = get_or_404("modifications", mod_id)
    data = json_body()
    decision = req_enum(data, "decision", {"APPROVED", "DENIED"})
    if m["status"] != "SUBMITTED":
        raise_err("ERR_MODIFICATION_NOT_SUBMITTED")
    loan = get_or_404("loans", m["loan_id"])
    if decision == "DENIED":
        m["decided_by"] = g.user_id
        m["status"] = "DENIED"
        bump(m)
        return success(serialize(m))
    # APPROVED: cap check, then apply the delta.
    applicant = get_or_404("applicants", loan["applicant_id"])
    cap = calc.statutory_cap(applicant["applicant_type"], loan["loan_purpose"])
    if m["requested_amount_cents"] > cap:
        raise_err("ERR_MODIFICATION_EXCEEDS_CAP")
    old = loan["approved_amount_cents"]
    new = m["requested_amount_cents"]
    delta = new - old
    loan["approved_amount_cents"] = new
    if delta > 0:
        loan["commitment_amount_cents"] += delta
        cascade.append_tranche(loan, delta)
    else:
        new_commitment = min(loan["commitment_amount_cents"], new)
        loan["commitment_amount_cents"] = new_commitment
        target = max(0, new_commitment - loan["disbursed_total_cents"])
        cascade.clawback_waterfall(loan, target)
        excess = max(0, loan["disbursed_total_cents"] - new_commitment)
        if excess > 0:
            cascade.add_excess_receivable(loan, excess)
    # monthly_payment recomputed whenever an approved modification changes the amount.
    rate, term = calc.rate_and_term(applicant["applicant_type"], loan["loan_purpose"])
    loan["monthly_payment_cents"] = calc.monthly_payment_cents(new, rate, term, deferred_capitalized=True)
    m["decided_by"] = g.user_id
    m["status"] = "APPROVED"
    bump(m)
    bump(loan)
    return success(serialize(m))
