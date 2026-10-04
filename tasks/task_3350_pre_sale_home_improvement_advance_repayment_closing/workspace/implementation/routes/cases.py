"""ConciergeCase lifecycle (PRD 3.2 intake/eligibility, 3.3 plan, 3.7 cancel)."""
from decimal import Decimal

from flask import Blueprint, request

from auth import require_roles
from calc import DEFAULT_LISTING_WINDOW_DAYS, MIN_EQUITY_RATIO, compute_advance_limit
from db import store
from envelope import success_obj
from errors import (
    ApiError,
    ERR_ADVANCE_LIMIT_EXCEEDED,
    ERR_CASE_FROZEN,
    ERR_ELIGIBILITY_FAILED,
    ERR_INVALID_STATE,
    ERR_NO_APPROVED_PROJECTS,
    ERR_STALE_VERSION,
)
from logic import (
    ENGAGEMENT_TERMINAL,
    PROJECT_TERMINAL,
    bump,
    case_disbursements,
    case_projects,
    get_or_404,
    list_response,
    new_record,
    project_engagements,
    release_reservation,
    serialize,
)
from validate import body_json, opt_bool, opt_int, req_int, req_str

bp = Blueprint("cases", __name__)


@bp.post("/concierge/cases")
@require_roles("ListingAgent")
def create_case():
    body = body_json(required=True)
    contribution = opt_int(body, "homeowner_contribution_cents", 0, min_value=0)
    rec = new_record({
        "address_line": req_str(body, "address_line"),
        "estimated_property_value_cents": req_int(body, "estimated_property_value_cents", min_value=0),
        "expected_sale_proceeds_cents": req_int(body, "expected_sale_proceeds_cents", min_value=0),
        "listing_agreement_signed": opt_bool(body, "listing_agreement_signed", False),
        "listing_agreement_disclosure_ack": opt_bool(body, "listing_agreement_disclosure_ack", False),
        "advance_limit_cents": None,
        "advance_total_cents": opt_int(body, "advance_total_cents", 0, min_value=0),
        "homeowner_contribution_cents": contribution,
        "upfront_payment_track": "CONTRIBUTION" if contribution > 0 else "NO_UPFRONT",
        "listing_price_target_cents": None,
        "listing_window_days": opt_int(body, "listing_window_days", DEFAULT_LISTING_WINDOW_DAYS, min_value=1),
        "listed_at": None,
        "closed_at": None,
        "status": "ELIGIBILITY_REVIEW",
        "posture": "OPEN",
    })
    store.cases[rec["id"]] = rec
    return success_obj(serialize(rec), 201)


@bp.get("/concierge/cases/<caseId>")
@require_roles("Any")
def get_case(caseId):
    return success_obj(serialize(get_or_404(store.cases, caseId, "ConciergeCase")))


@bp.get("/concierge/cases")
@require_roles("Any")
def list_cases():
    items = list(store.cases.values())
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    return list_response(items)


@bp.post("/concierge/cases/<caseId>/eligibility/approve")
@require_roles("ProgramUnderwriter")
def approve_eligibility(caseId):
    case = get_or_404(store.cases, caseId, "ConciergeCase")
    if case["status"] != "ELIGIBILITY_REVIEW":
        raise ApiError(ERR_INVALID_STATE, "Case is not in ELIGIBILITY_REVIEW", 409)
    ok = (
        case["estimated_property_value_cents"] > 0
        and Decimal(case["expected_sale_proceeds_cents"])
        > Decimal(case["estimated_property_value_cents"]) * MIN_EQUITY_RATIO
        and case["listing_agreement_signed"]
        and case["listing_agreement_disclosure_ack"]
    )
    if not ok:
        raise ApiError(ERR_ELIGIBILITY_FAILED, "Eligibility preconditions not met", 409)
    case["advance_limit_cents"] = compute_advance_limit(
        case["expected_sale_proceeds_cents"],
        case["estimated_property_value_cents"],
        case["homeowner_contribution_cents"],
    )
    case["status"] = "SCOPE_PLANNING"
    bump(case)
    return success_obj(serialize(case))


@bp.post("/concierge/cases/<caseId>/eligibility/reject")
@require_roles("ProgramUnderwriter")
def reject_eligibility(caseId):
    case = get_or_404(store.cases, caseId, "ConciergeCase")
    if case["status"] != "ELIGIBILITY_REVIEW":
        raise ApiError(ERR_INVALID_STATE, "Case is not in ELIGIBILITY_REVIEW", 409)
    case["status"] = "CANCELLED"
    bump(case)
    return success_obj(serialize(case))


@bp.post("/concierge/cases/<caseId>/plan/approve")
@require_roles("Homeowner")
def approve_plan(caseId):
    case = get_or_404(store.cases, caseId, "ConciergeCase")
    if case["status"] != "SCOPE_PLANNING":
        raise ApiError(ERR_INVALID_STATE, "Case is not in SCOPE_PLANNING", 409)
    body = body_json(required=True)
    expected = req_int(body, "expected_case_version")
    if expected != case["version"]:
        raise ApiError(ERR_STALE_VERSION, "expected_case_version does not match current case version", 412)
    approved = [p for p in case_projects(caseId) if p["status"] == "APPROVED"]
    if not approved:
        raise ApiError(ERR_NO_APPROVED_PROJECTS, "Plan approval requires at least one APPROVED project", 409)
    if sum(p["approved_cost_cents"] for p in approved) > case["advance_limit_cents"]:
        raise ApiError(ERR_ADVANCE_LIMIT_EXCEEDED, "Approved project cost exceeds advance limit", 409)
    if case["posture"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE, "Case posture must be OPEN to approve the plan", 409)
    case["listing_price_target_cents"] = case["estimated_property_value_cents"] + sum(
        p["expected_sale_price_lift_cents"] for p in approved
    )
    case["status"] = "PLAN_APPROVED"
    bump(case)
    return success_obj(serialize(case))


@bp.post("/concierge/cases/<caseId>/cancel")
@require_roles("Homeowner")
def cancel_case(caseId):
    case = get_or_404(store.cases, caseId, "ConciergeCase")
    if case["status"] not in ("SCOPE_PLANNING", "LISTED"):
        raise ApiError(ERR_INVALID_STATE, "Case cannot be cancelled from its current state", 409)
    if case["posture"] == "FROZEN":
        raise ApiError(ERR_CASE_FROZEN, "Case posture is FROZEN", 409)
    if case["status"] == "LISTED":
        if any(d["status"] == "RELEASED" for d in case_disbursements(caseId)):
            raise ApiError(
                ERR_INVALID_STATE,
                "Released disbursements are not yet covered by a closing statement",
                409,
            )
    case["status"] = "CANCELLED"
    bump(case)
    for project in case_projects(caseId):
        if project["status"] not in PROJECT_TERMINAL:
            project["status"] = "CANCELLED"
            bump(project)
        for eng in project_engagements(project["id"]):
            if eng["status"] not in ENGAGEMENT_TERMINAL:
                release_reservation(eng)
                eng["status"] = "CANCELLED"
                bump(eng)
    return success_obj(serialize(case))
