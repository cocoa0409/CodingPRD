"""Repair milestones (PRD 3.7): report, list, decide with segregation of duties."""

from flask import Blueprint, g, request

import cascade
from auth import check_owner, require_roles
from body import json_body, req_enum, req_int, req_str
from domain import bump, get_or_404, latest_verification, loan_milestones, new_common
from envelope import page, parse_pagination, success, success_list
from errors import raise_err
from store import get, put
from serializers import serialize, serialize_all

bp = Blueprint("milestones", __name__)


@bp.post("/disaster-relief/loans/<loan_id>/repair-milestones")
@require_roles("Applicant")
def report_milestone(loan_id):
    loan = get_or_404("loans", loan_id)
    check_owner(loan["applicant_id"])
    if loan["lifecycle_status"] != "ACTIVE":
        raise_err("ERR_LOAN_NOT_ACTIVE")
    data = json_body()
    description = req_str(data, "description")
    claimed = req_int(data, "claimed_cost_cents", min_value=1)
    row = new_common()
    row.update({
        "loan_id": loan["id"],
        "description": description,
        "claimed_cost_cents": claimed,
        "verified_cost_cents": None,
        "status": "REPORTED",
        "verifier_user_id": None,
    })
    put("milestones", row)
    return success(serialize(row), 201)


@bp.get("/disaster-relief/loans/<loan_id>/repair-milestones")
@require_roles("Applicant", "ServicingAgent", "LossVerifier", "LoanApprover")
def list_milestones(loan_id):
    loan = get_or_404("loans", loan_id)
    check_owner(loan["applicant_id"])
    rows = loan_milestones(loan["id"])
    limit, offset = parse_pagination(request.args)
    items, total = page(rows, limit, offset)
    return success_list(serialize_all(items), limit, offset, total)


@bp.post("/disaster-relief/repair-milestones/<milestone_id>/decision")
@require_roles("LossVerifier")
def decide_milestone(milestone_id):
    m = get_or_404("milestones", milestone_id)
    data = json_body()
    decision = req_enum(data, "decision", {"VERIFIED", "REJECTED"})
    verified_cost = None
    if decision == "VERIFIED":
        verified_cost = req_int(data, "verified_cost_cents", min_value=0)
        if verified_cost > m["claimed_cost_cents"]:
            raise_err("ERR_INVALID_REQUEST", "verified_cost_cents must not exceed claimed_cost_cents")
    if m["status"] != "REPORTED":
        raise_err("ERR_MILESTONE_NOT_REPORTED")
    loan = get_or_404("loans", m["loan_id"])
    # Segregation of duties: not the verifier of the application's latest COMPLETED verification.
    latest = latest_verification(loan["application_id"], completed_only=True)
    if latest is not None and latest["verifier_user_id"] == g.user_id:
        raise_err("ERR_SEGREGATION_OF_DUTIES")
    m["verifier_user_id"] = g.user_id
    if decision == "VERIFIED":
        m["verified_cost_cents"] = verified_cost
        m["status"] = "VERIFIED"
        bump(m)
        cascade.reevaluate_eligibility(loan)
    else:
        m["status"] = "REJECTED"
        bump(m)
    return success(serialize(m))
