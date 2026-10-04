"""Disbursement tranches: list and release (PRD 3.7)."""

from flask import Blueprint, request

import cascade
from auth import check_owner, require_roles
from domain import get_or_404, loan_tranches
from envelope import page, parse_pagination, success_list, success
from errors import raise_err
from serializers import serialize, serialize_all

bp = Blueprint("tranches", __name__)


@bp.get("/disaster-relief/loans/<loan_id>/disbursement-tranches")
@require_roles("Applicant", "ServicingAgent", "LoanApprover", "LossVerifier")
def list_tranches(loan_id):
    loan = get_or_404("loans", loan_id)
    check_owner(loan["applicant_id"])
    rows = loan_tranches(loan["id"])  # ascending stage_number
    limit, offset = parse_pagination(request.args)
    items, total = page(rows, limit, offset)
    return success_list(serialize_all(items), limit, offset, total)


@bp.post("/disaster-relief/disbursement-tranches/<tranche_id>/release")
@require_roles("ServicingAgent")
def release_tranche(tranche_id):
    tranche = get_or_404("tranches", tranche_id)
    if tranche["status"] != "ELIGIBLE":
        raise_err("ERR_TRANCHE_NOT_RELEASABLE")
    loan = get_or_404("loans", tranche["loan_id"])
    if loan["lifecycle_status"] != "ACTIVE":
        raise_err("ERR_LOAN_NOT_ACTIVE")
    cascade.release_tranche(loan, tranche)
    return success(serialize(tranche))
