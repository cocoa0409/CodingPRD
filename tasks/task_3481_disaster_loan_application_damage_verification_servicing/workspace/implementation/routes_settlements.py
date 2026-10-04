"""Insurance settlements (PRD 3.8): report, list, apply (clawback_calc), void."""

from flask import Blueprint, request

import calc
import cascade
from auth import check_owner, require_roles
from body import is_int, json_body, req_dt, req_int
from domain import (bump, get_or_404, latest_verification, loan_settlements,
                    loan_tranches, new_common)
from envelope import page, parse_pagination, success, success_list
from errors import raise_err
from store import get, put, remove
from serializers import serialize, serialize_all

bp = Blueprint("settlements", __name__)


@bp.post("/disaster-relief/loans/<loan_id>/insurance-settlements")
@require_roles("Applicant")
def report_settlement(loan_id):
    loan = get_or_404("loans", loan_id)
    check_owner(loan["applicant_id"])
    if loan["lifecycle_status"] != "ACTIVE":
        raise_err("ERR_LOAN_NOT_ACTIVE")
    data = json_body()
    amount = req_int(data, "settlement_amount_cents", min_value=1)
    received = req_dt(data, "received_date")
    row = new_common()
    row.update({
        "loan_id": loan["id"],
        "settlement_amount_cents": amount,
        "received_date": received,
        "status": "REPORTED",
        "clawback_commitment_delta_cents": None,
        "excess_due_cents": None,
    })
    put("settlements", row)
    return success(serialize(row), 201)


@bp.get("/disaster-relief/loans/<loan_id>/insurance-settlements")
@require_roles("Applicant", "ServicingAgent", "LoanApprover")
def list_settlements(loan_id):
    loan = get_or_404("loans", loan_id)
    check_owner(loan["applicant_id"])
    rows = loan_settlements(loan["id"])
    limit, offset = parse_pagination(request.args)
    items, total = page(rows, limit, offset)
    return success_list(serialize_all(items), limit, offset, total)


@bp.post("/disaster-relief/insurance-settlements/<settlement_id>/apply")
@require_roles("ServicingAgent")
def apply_settlement(settlement_id):
    s = get_or_404("settlements", settlement_id)
    data = json_body()
    expected = data.get("expected_loan_version")
    if not is_int(expected):
        raise_err("ERR_INVALID_REQUEST", "expected_loan_version is required")
    loan = get_or_404("loans", s["loan_id"])
    if expected != loan["version"]:
        raise_err("ERR_STALE_VERSION")
    if s["status"] != "REPORTED":
        raise_err("ERR_SETTLEMENT_NOT_REPORTED")
    # clawback_calc, pinned order:
    # (1) total insurance
    app = get("applications", loan["application_id"])
    latest = latest_verification(loan["application_id"], completed_only=True) if app else None
    insurance_proceeds = latest["insurance_proceeds_cents"] if latest else 0
    verified_loss = latest["verified_loss_cents"] if latest else 0
    applied_sum = sum(x["settlement_amount_cents"] for x in loan_settlements(loan["id"])
                      if x["status"] == "APPLIED")
    total_insurance = insurance_proceeds + applied_sum + s["settlement_amount_cents"]
    # (2) new net loss, (3) new commitment
    new_net_loss = max(0, verified_loss - total_insurance)
    old_commitment = loan["commitment_amount_cents"]
    new_commitment = min(loan["approved_amount_cents"], new_net_loss)
    loan["commitment_amount_cents"] = new_commitment
    # Snapshot un-released tranches so a later void can restore pre-apply values.
    s["_tranche_snapshot"] = [
        {"id": t["id"], "amount_cents": t["amount_cents"], "status": t["status"]}
        for t in loan_tranches(loan["id"]) if t["status"] in ("SCHEDULED", "ELIGIBLE")]
    # (4) tranche waterfall against target
    target = max(0, new_commitment - loan["disbursed_total_cents"])
    cascade.clawback_waterfall(loan, target)
    # (5) excess, (6) receivable
    excess = max(0, loan["disbursed_total_cents"] - new_commitment)
    receivable = None
    if excess > 0:
        receivable = cascade.add_excess_receivable(loan, excess)
    s["_receivable_id"] = receivable["id"] if receivable else None
    s["clawback_commitment_delta_cents"] = old_commitment - new_commitment
    s["excess_due_cents"] = excess
    s["status"] = "APPLIED"
    bump(s)
    bump(loan)
    return success(serialize(s))


@bp.post("/disaster-relief/insurance-settlements/<settlement_id>/void")
@require_roles("ServicingAgent")
def void_settlement(settlement_id):
    s = get_or_404("settlements", settlement_id)
    if s["status"] != "APPLIED":
        raise_err("ERR_SETTLEMENT_NOT_APPLIED")
    loan = get_or_404("loans", s["loan_id"])
    # Exact compensation of the apply cascade.
    loan["commitment_amount_cents"] += s["clawback_commitment_delta_cents"]
    for snap in s.get("_tranche_snapshot", []):
        t = get("tranches", snap["id"])
        if t is not None and t["status"] != "RELEASED":
            t["amount_cents"] = snap["amount_cents"]
            t["status"] = snap["status"]
            bump(t)
    if s["excess_due_cents"] and s.get("_receivable_id"):
        r = get("receivables", s["_receivable_id"])
        if r is not None:
            r["amount_due_cents"] -= s["excess_due_cents"]
            if r["amount_due_cents"] == 0 and r["amount_paid_cents"] == 0:
                remove("receivables", r["id"])
            else:
                if r["amount_due_cents"] == r["amount_paid_cents"]:
                    r["status"] = "PAID"
                bump(r)
    s["status"] = "VOIDED"
    bump(s)
    bump(loan)
    return success(serialize(s))
