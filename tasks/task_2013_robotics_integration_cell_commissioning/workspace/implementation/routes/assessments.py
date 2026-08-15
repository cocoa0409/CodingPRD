"""SafetyRiskAssessment endpoints (PRD §3.3)."""
from flask import Blueprint, request

from db import children, store
from errors import (ApiError, ERR_SAFETY_LEVEL_INSUFFICIENT,
                    ERR_SEGREGATION_OF_DUTIES, invalid_state, not_found)
from middleware import authenticate
from middleware import ROLE_FINANCE_ADMIN as FA
from middleware import ROLE_PROJECT_ENGINEER as PE
from middleware import ROLE_SAFETY_LEAD as SL
from middleware import ROLE_SITE_SUPERVISOR as SS
from response import success, success_list
from services import calculations as calc
from services.domain import common_fields, pub, pubs, touch
from validation import as_bool, as_enum, as_int, as_num, body, paginate, pagination, req

bp = Blueprint("assessments", __name__)

READ_ROLES = {FA, PE, SL, SS}
PL_LEVELS = ("PLc", "PLd", "PLe")


def get_assessment(assessment_id):
    a = store.assessments.get(assessment_id)
    if a is None:
        raise not_found("Safety risk assessment not found")
    return a


@bp.post("/robotics/cell-projects/<project_id>/safety-risk-assessments")
def create_assessment(project_id):
    uid, _role = authenticate({PE})
    if project_id not in store.projects:
        raise not_found("Cell project not found")
    b = body()
    assessment = {
        **common_fields(),
        "cell_project_id": project_id,
        "assessment_revision": 1,
        "risk_score_pre_mitigation": as_int(req(b, "risk_score_pre_mitigation"),
                                            "risk_score_pre_mitigation", 1, 1000),
        "pl_target": as_enum(req(b, "pl_target"), "pl_target", PL_LEVELS),
        "pl_achieved": (as_enum(b["pl_achieved"], "pl_achieved", PL_LEVELS)
                        if "pl_achieved" in b and b["pl_achieved"] is not None else None),
        "fencing_length_m": as_num(req(b, "fencing_length_m"), "fencing_length_m", min_v=0),
        "light_curtain_zones": as_int(req(b, "light_curtain_zones"), "light_curtain_zones", min_v=0),
        "muting_required": as_bool(req(b, "muting_required"), "muting_required"),
        "safety_function_budget_pct": None,
        "status": "DRAFT",
        "approved_by_safety_lead_id": None,
        "_created_by": uid,
    }
    store.assessments[assessment["id"]] = assessment
    return success(pub(assessment), 201)


@bp.get("/robotics/cell-projects/<project_id>/safety-risk-assessments")
def list_assessments(project_id):
    authenticate(READ_ROLES)
    if project_id not in store.projects:
        raise not_found("Cell project not found")
    limit, offset = pagination()
    items = children("assessments", "cell_project_id", project_id)
    status_filter = request.args.get("status")
    if status_filter is not None:
        items = [a for a in items if a["status"] == status_filter]
    approver = request.args.get("approved_by_safety_lead_id")
    if approver is not None:
        items = [a for a in items if a["approved_by_safety_lead_id"] == approver]
    page, total = paginate(items, limit, offset)
    return success_list(pubs(page), limit, offset, total)


@bp.get("/robotics/safety-risk-assessments/<assessment_id>")
def get_one_assessment(assessment_id):
    authenticate(READ_ROLES)
    return success(pub(get_assessment(assessment_id)))


@bp.post("/robotics/safety-risk-assessments/<assessment_id>/submit")
def submit_assessment(assessment_id):
    authenticate({PE})
    a = get_assessment(assessment_id)
    if a["status"] != "DRAFT":
        raise invalid_state("Only a DRAFT assessment can be submitted")
    project = store.projects[a["cell_project_id"]]
    if project["status"] != "STUDY":
        raise invalid_state("Assessment submission requires project status STUDY")
    # pl_achieved must be computable: positive fencing or at least one curtain zone.
    if not (a["fencing_length_m"] > 0 or a["light_curtain_zones"] > 0):
        raise invalid_state(
            "pl_achieved is not computable: fencing_length_m or light_curtain_zones "
            "must be positive")
    budget, pl = calc.safety_budget(a["fencing_length_m"], a["light_curtain_zones"],
                                    a["muting_required"])
    a["safety_function_budget_pct"] = budget
    a["pl_achieved"] = pl
    a["status"] = "IN_REVIEW"
    touch(a)
    return success(pub(a))


@bp.post("/robotics/safety-risk-assessments/<assessment_id>/approve")
def approve_assessment(assessment_id):
    uid, _role = authenticate({SL})
    a = get_assessment(assessment_id)
    if a["status"] != "IN_REVIEW":
        raise invalid_state("Only an IN_REVIEW assessment can be approved")
    # Safety-level rules (priority 6) evaluate before segregation (priority 7).
    if a["risk_score_pre_mitigation"] >= 400 and a["pl_achieved"] != "PLe":
        raise ApiError(ERR_SAFETY_LEVEL_INSUFFICIENT, 422,
                       "risk_score_pre_mitigation >= 400 requires pl_achieved == PLe")
    if a["muting_required"] and not (a["light_curtain_zones"] >= 1
                                     and a["pl_achieved"] in ("PLd", "PLe")):
        raise ApiError(ERR_SAFETY_LEVEL_INSUFFICIENT, 422,
                       "muting_required requires light_curtain_zones >= 1 and "
                       "pl_achieved in {PLd, PLe}")
    if uid == a.get("_created_by"):
        raise ApiError(ERR_SEGREGATION_OF_DUTIES, 422,
                       "The assessment creator cannot approve their own assessment")
    a["status"] = "APPROVED"
    a["approved_by_safety_lead_id"] = uid
    touch(a)
    return success(pub(a))


@bp.post("/robotics/safety-risk-assessments/<assessment_id>/reject")
def reject_assessment(assessment_id):
    authenticate({SL})
    a = get_assessment(assessment_id)
    if a["status"] != "IN_REVIEW":
        raise invalid_state("Only an IN_REVIEW assessment can be rejected")
    a["status"] = "REJECTED"
    touch(a)
    return success(pub(a))


@bp.post("/robotics/safety-risk-assessments/<assessment_id>/revise")
def revise_assessment(assessment_id):
    authenticate({PE})
    a = get_assessment(assessment_id)
    if a["status"] != "REJECTED":
        raise invalid_state("Only a REJECTED assessment can be revised")
    a["status"] = "DRAFT"
    a["assessment_revision"] += 1
    touch(a)
    return success(pub(a))
