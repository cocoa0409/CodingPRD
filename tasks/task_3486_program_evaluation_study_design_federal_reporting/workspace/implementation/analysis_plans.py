"""AnalysisPlan endpoints: create, list, register (preregistration), amend."""
from flask import Blueprint

import store
from clock import now_dt
from errors import raise_err
from serialize import analysis_plan_out
from services import analysis_plans_of_study, current_plan, waves_of_study
from util import new_entity, ok_list, ok_obj, paginate, sort_created, touch
from validation import (ROLE_PRINCIPAL_INVESTIGATOR, STAFF_ROLES,
                        authenticate, authorize, check_schema, get_json_body)

bp = Blueprint("analysis_plans", __name__)


def get_analysis_plan_or_404(plan_id):
    plan = store.analysis_plans.get(plan_id)
    if plan is None:
        raise_err("ERR_NOT_FOUND", "Analysis plan not found")
    return plan


@bp.post("/evaluation/studies/<study_id>/analysis-plans")
def create_analysis_plan(study_id):
    _uid, role = authenticate()
    authorize(role, [ROLE_PRINCIPAL_INVESTIGATOR])
    study = store.studies.get(study_id)
    if study is None:
        raise_err("ERR_NOT_FOUND", "Study not found")
    body = get_json_body()
    check_schema(body, {
        "primary_outcomes": ("arr_str", True),
        "secondary_outcomes": ("arr_str", False),
    })
    if study["status"] not in ("DESIGN", "RECRUITMENT", "DATA_COLLECTION",
                               "ANALYSIS"):
        raise_err("ERR_STUDY_INVALID_STATE",
                  "Analysis plans may only be drafted while the study is "
                  "between DESIGN and ANALYSIS")
    secondary = body.get("secondary_outcomes")
    plan = new_entity({
        "study_id": study_id,
        "primary_outcomes": body["primary_outcomes"],
        "secondary_outcomes": [] if secondary is None else secondary,
        "amendment_count": 0,
        "registered_at": None,
        "status": "DRAFT",
    })
    store.analysis_plans[plan["id"]] = plan
    return ok_obj(analysis_plan_out(plan), 201)


@bp.get("/evaluation/studies/<study_id>/analysis-plans")
def list_analysis_plans(study_id):
    _uid, role = authenticate()
    authorize(role, STAFF_ROLES)
    if study_id not in store.studies:
        raise_err("ERR_NOT_FOUND", "Study not found")
    items = sort_created(analysis_plans_of_study(study_id))
    page, limit, offset, total = paginate(items)
    return ok_list([analysis_plan_out(a) for a in page], limit, offset, total)


@bp.post("/evaluation/analysis-plans/<plan_id>/register")
def register_analysis_plan(plan_id):
    _uid, role = authenticate()
    authorize(role, [ROLE_PRINCIPAL_INVESTIGATOR])
    plan = get_analysis_plan_or_404(plan_id)
    body = get_json_body()
    check_schema(body, {})
    if plan["status"] != "DRAFT":
        raise_err("ERR_ANALYSIS_PLAN_INVALID_STATE",
                  "Only a DRAFT analysis plan can be registered")
    design = current_plan(plan["study_id"])
    if design is None or design["status"] != "LOCKED":
        raise_err("ERR_DESIGN_PLAN_INVALID_STATE",
                  "The study's current design plan must be LOCKED")
    if any(w["status"] in ("CLOSED", "LINKED")
           for w in waves_of_study(plan["study_id"])):
        raise_err("ERR_PREREGISTRATION_TOO_LATE",
                  "A wave of the study has already been closed or linked")
    plan["status"] = "PREREGISTERED"
    plan["registered_at"] = now_dt()
    touch(plan)
    return ok_obj(analysis_plan_out(plan))


@bp.post("/evaluation/analysis-plans/<plan_id>/amend")
def amend_analysis_plan(plan_id):
    _uid, role = authenticate()
    authorize(role, [ROLE_PRINCIPAL_INVESTIGATOR])
    plan = get_analysis_plan_or_404(plan_id)
    body = get_json_body()
    check_schema(body, {
        "secondary_outcomes": ("arr_str", False),
        "primary_outcomes": ("arr_str", False),
    })
    if plan["status"] != "PREREGISTERED":
        raise_err("ERR_ANALYSIS_PLAN_INVALID_STATE",
                  "Only a PREREGISTERED analysis plan can be amended")
    if "primary_outcomes" in body:
        raise_err("ERR_PRIMARY_OUTCOME_FROZEN",
                  "Primary outcomes are frozen at preregistration")
    if body.get("secondary_outcomes") is not None:
        plan["secondary_outcomes"] = body["secondary_outcomes"]
    plan["amendment_count"] += 1
    touch(plan)
    return ok_obj(analysis_plan_out(plan))
