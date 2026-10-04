"""Loans: list, read, accept (PRD 3.6-3.7)."""

from flask import Blueprint, request

from auth import check_owner, require_roles
from domain import bump, get_or_404, loan_tranches
from envelope import page, parse_pagination, success, success_list
from errors import raise_err
from store import all_rows
from serializers import serialize, serialize_all

bp = Blueprint("loans", __name__)

STAFF_ROLES = ("LoanOfficer", "LoanApprover", "ServicingAgent", "LossVerifier", "GrantCoordinator")


@bp.get("/disaster-relief/loans")
@require_roles(*STAFF_ROLES)
def list_loans():
    rows = all_rows("loans")
    for field in ("application_id", "applicant_id", "servicing_status", "lifecycle_status"):
        val = request.args.get(field)
        if val is not None:
            rows = [r for r in rows if str(r.get(field)) == val]
    limit, offset = parse_pagination(request.args)
    items, total = page(rows, limit, offset)
    return success_list(serialize_all(items), limit, offset, total)


@bp.get("/disaster-relief/loans/<loan_id>")
@require_roles("Applicant", "LoanOfficer", "LoanApprover", "ServicingAgent", "LossVerifier")
def get_loan(loan_id):
    loan = get_or_404("loans", loan_id)
    check_owner(loan["applicant_id"])
    return success(serialize(loan))


@bp.post("/disaster-relief/loans/<loan_id>/accept")
@require_roles("Applicant")
def accept_loan(loan_id):
    loan = get_or_404("loans", loan_id)
    check_owner(loan["applicant_id"])
    if loan["lifecycle_status"] != "PENDING_ACCEPTANCE":
        raise_err("ERR_LOAN_NOT_PENDING_ACCEPTANCE")
    loan["lifecycle_status"] = "ACTIVE"
    bump(loan)
    # Acceptance cascade: tranche stage 1 flips SCHEDULED -> ELIGIBLE.
    for t in loan_tranches(loan["id"]):
        if t["stage_number"] == 1 and t["status"] == "SCHEDULED":
            t["status"] = "ELIGIBLE"
            bump(t)
    return success(serialize(loan))
