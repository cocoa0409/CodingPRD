"""ImprovementProject lifecycle (PRD 3.3, 3.6)."""
from flask import Blueprint

from auth import require_roles
from db import store
from envelope import success_obj
from errors import (
    ApiError,
    ERR_ADVANCE_LIMIT_EXCEEDED,
    ERR_CASE_FROZEN,
    ERR_DISPUTE_ACTIVE,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
)
from logic import (
    OPEN_DISPUTE_STATES,
    bump,
    case_projects,
    get_or_404,
    list_response,
    maybe_case_ready,
    new_record,
    project_disputes,
    serialize,
)
from validate import body_json, req_bool, req_int, req_str

bp = Blueprint("projects", __name__)


def _case_and_project(caseId, projectId):
    """Nested path validation left to right; child must belong to parent."""
    case = get_or_404(store.cases, caseId, "ConciergeCase")
    project = get_or_404(store.projects, projectId, "ImprovementProject")
    if project["concierge_case_id"] != case["id"]:
        raise ApiError(ERR_NOT_FOUND, "ImprovementProject not found under this case", 404)
    return case, project


@bp.post("/concierge/cases/<caseId>/projects")
@require_roles("ListingAgent")
def create_project(caseId):
    case = get_or_404(store.cases, caseId, "ConciergeCase")
    body = body_json(required=True)
    rec = new_record({
        "concierge_case_id": case["id"],
        "title": req_str(body, "title"),
        "recommended_by_agent": req_bool(body, "recommended_by_agent"),
        "expected_sale_price_lift_cents": req_int(body, "expected_sale_price_lift_cents", min_value=0),
        "estimated_cost_cents": req_int(body, "estimated_cost_cents", min_value=0),
        "approved_cost_cents": None,
        "cost_overrun_cents": 0,
        "status": "DRAFT",
    })
    store.projects[rec["id"]] = rec
    return success_obj(serialize(rec), 201)


@bp.get("/concierge/cases/<caseId>/projects/<projectId>")
@require_roles("Any")
def get_project(caseId, projectId):
    _, project = _case_and_project(caseId, projectId)
    return success_obj(serialize(project))


@bp.get("/concierge/cases/<caseId>/projects")
@require_roles("Any")
def list_projects(caseId):
    get_or_404(store.cases, caseId, "ConciergeCase")
    return list_response(case_projects(caseId))


@bp.post("/concierge/cases/<caseId>/projects/<projectId>/propose")
@require_roles("ListingAgent")
def propose_project(caseId, projectId):
    case, project = _case_and_project(caseId, projectId)
    if project["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, "Project is not in DRAFT", 409)
    if case["status"] != "SCOPE_PLANNING":
        raise ApiError(ERR_INVALID_STATE, "Case is not in SCOPE_PLANNING", 409)
    project["status"] = "PROPOSED"
    bump(project)
    return success_obj(serialize(project))


@bp.post("/concierge/cases/<caseId>/projects/<projectId>/approve")
@require_roles("Homeowner")
def approve_project(caseId, projectId):
    case, project = _case_and_project(caseId, projectId)
    if project["status"] != "PROPOSED":
        raise ApiError(ERR_INVALID_STATE, "Project is not in PROPOSED", 409)
    if case["status"] != "SCOPE_PLANNING":
        raise ApiError(ERR_INVALID_STATE, "Case is not in SCOPE_PLANNING", 409)
    if case["advance_total_cents"] + project["estimated_cost_cents"] > case["advance_limit_cents"]:
        raise ApiError(ERR_ADVANCE_LIMIT_EXCEEDED, "Project cost exceeds advance-limit headroom", 409)
    project["approved_cost_cents"] = project["estimated_cost_cents"]
    project["status"] = "APPROVED"
    bump(project)
    case["advance_total_cents"] += project["approved_cost_cents"]
    bump(case)
    return success_obj(serialize(project))


@bp.post("/concierge/cases/<caseId>/projects/<projectId>/verify")
@require_roles("ListingAgent")
def verify_project(caseId, projectId):
    case, project = _case_and_project(caseId, projectId)
    if project["status"] != "COMPLETE":
        raise ApiError(ERR_INVALID_STATE, "Project is not COMPLETE", 409)
    if any(d["status"] in OPEN_DISPUTE_STATES for d in project_disputes(projectId)):
        raise ApiError(ERR_DISPUTE_ACTIVE, "Project has a dispute in OPEN or IN_REVIEW", 409)
    project["status"] = "VERIFIED"
    bump(project)
    maybe_case_ready(case)
    return success_obj(serialize(project))


@bp.post("/concierge/cases/<caseId>/projects/<projectId>/cancel")
@require_roles("Homeowner")
def cancel_project(caseId, projectId):
    case, project = _case_and_project(caseId, projectId)
    if project["status"] not in ("DRAFT", "PROPOSED"):
        raise ApiError(ERR_INVALID_STATE, "Only DRAFT or PROPOSED projects can be cancelled", 409)
    if case["posture"] == "FROZEN":
        raise ApiError(ERR_CASE_FROZEN, "Case posture is FROZEN", 409)
    project["status"] = "CANCELLED"
    bump(project)
    maybe_case_ready(case)
    return success_obj(serialize(project))
