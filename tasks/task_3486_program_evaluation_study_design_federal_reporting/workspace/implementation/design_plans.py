"""DesignPlan endpoints: create (OCC-guarded), list, submit,
agency-decision, revise."""
from flask import Blueprint

import store
from calc import required_sample_size
from errors import raise_err
from serialize import design_plan_out
from services import current_plan, maybe_lock_plan, plans_of_study, recompute_projections
from util import new_entity, ok_list, ok_obj, paginate, sort_created, touch
from validation import (ROLE_AGENCY_OFFICER, ROLE_PRINCIPAL_INVESTIGATOR,
                        STAFF_ROLES, authenticate, authorize, check_schema,
                        get_json_body)

bp = Blueprint("design_plans", __name__)


def get_plan_or_404(plan_id):
    plan = store.design_plans.get(plan_id)
    if plan is None:
        raise_err("ERR_NOT_FOUND", "Design plan not found")
    return plan


@bp.post("/evaluation/studies/<study_id>/design-plans")
def create_design_plan(study_id):
    _uid, role = authenticate()
    authorize(role, [ROLE_PRINCIPAL_INVESTIGATOR])
    study = store.studies.get(study_id)
    if study is None:
        raise_err("ERR_NOT_FOUND", "Study not found")
    body = get_json_body()
    check_schema(body, {
        "design_type": ("enum:RCT|QED_MATCHING|QED_RDD|QED_DID", True),
        "mde": ("num", True),
        "cluster_size": ("int", True),
        "icc": ("num", True),
        "attrition_rate": ("num", True),
        "expected_study_version": ("int", True),
        "alpha": ("num", False),
        "power_target": ("num", False),
        "randomization_ratio_num": ("int", False),
        "randomization_ratio_den": ("int", False),
    })
    mde = body["mde"]
    cluster_size = body["cluster_size"]
    icc = body["icc"]
    attrition = body["attrition_rate"]
    if not mde > 0:
        raise_err("ERR_INVALID_REQUEST", "mde must be > 0")
    if cluster_size < 1:
        raise_err("ERR_INVALID_REQUEST", "cluster_size must be >= 1")
    if not 0 <= icc <= 1:
        raise_err("ERR_INVALID_REQUEST", "icc must be between 0 and 1")
    if not 0 <= attrition < 1:
        raise_err("ERR_INVALID_REQUEST",
                  "attrition_rate must be >= 0 and < 1")
    num = body.get("randomization_ratio_num")
    num = 1 if num is None else num
    den = body.get("randomization_ratio_den")
    den = 2 if den is None else den
    if num < 1:
        raise_err("ERR_INVALID_REQUEST",
                  "randomization_ratio_num must be >= 1")
    if den < 2:
        raise_err("ERR_INVALID_REQUEST",
                  "randomization_ratio_den must be >= 2")
    if num >= den:
        raise_err("ERR_INVALID_REQUEST",
                  "randomization_ratio_num must be < randomization_ratio_den")
    # Stage 5: optimistic concurrency on the study's version.
    if body["expected_study_version"] != study["version"]:
        raise_err("ERR_STALE_VERSION",
                  "expected_study_version does not match the study's current "
                  "version")
    # Stage 6: study must accept a new design plan.
    if study["status"] not in ("DESIGN", "RECRUITMENT"):
        raise_err("ERR_STUDY_INVALID_STATE",
                  "Design plans may only be created while the study is in "
                  "DESIGN or RECRUITMENT")
    n_per_arm, total_n = required_sample_size(
        body["design_type"], mde, cluster_size, icc, attrition)
    revision = 1
    prior = current_plan(study_id)
    if prior is not None and prior["status"] in ("DRAFT",
                                                 "RETURNED_FOR_REVISION"):
        prior["status"] = "SUPERSEDED"
        touch(prior)
        revision = prior["revision_number"] + 1
    alpha = body.get("alpha")
    power_target = body.get("power_target")
    plan = new_entity({
        "study_id": study_id,
        "design_type": body["design_type"],
        "mde": mde,
        "cluster_size": cluster_size,
        "icc": icc,
        "attrition_rate": attrition,
        "alpha": 0.05 if alpha is None else alpha,
        "power_target": 0.8 if power_target is None else power_target,
        "randomization_ratio_num": num,
        "randomization_ratio_den": den,
        "n_per_arm": n_per_arm,
        "required_total_n": total_n,
        "revision_number": revision,
        "status": "DRAFT",
    })
    store.design_plans[plan["id"]] = plan
    touch(study)  # creation bumps Study.version by exactly 1
    recompute_projections(study)
    return ok_obj(design_plan_out(plan), 201)


@bp.get("/evaluation/studies/<study_id>/design-plans")
def list_design_plans(study_id):
    _uid, role = authenticate()
    authorize(role, STAFF_ROLES)
    if study_id not in store.studies:
        raise_err("ERR_NOT_FOUND", "Study not found")
    items = sort_created(plans_of_study(study_id))
    page, limit, offset, total = paginate(items)
    return ok_list([design_plan_out(p) for p in page], limit, offset, total)


@bp.post("/evaluation/design-plans/<plan_id>/submit")
def submit_design_plan(plan_id):
    _uid, role = authenticate()
    authorize(role, [ROLE_PRINCIPAL_INVESTIGATOR])
    plan = get_plan_or_404(plan_id)
    body = get_json_body()
    check_schema(body, {})
    if plan["status"] != "DRAFT":
        raise_err("ERR_DESIGN_PLAN_INVALID_STATE",
                  "Only a DRAFT plan can be submitted")
    study = store.studies.get(plan["study_id"])
    if study["pipeline_projected_n"] < plan["required_total_n"]:
        raise_err("ERR_INSUFFICIENT_POWER",
                  "Study pipeline_projected_n is below the plan's "
                  "required_total_n")
    plan["status"] = "SUBMITTED"
    touch(plan)
    return ok_obj(design_plan_out(plan))


@bp.post("/evaluation/design-plans/<plan_id>/agency-decision")
def design_plan_agency_decision(plan_id):
    _uid, role = authenticate()
    authorize(role, [ROLE_AGENCY_OFFICER])
    plan = get_plan_or_404(plan_id)
    body = get_json_body()
    check_schema(body, {"decision": ("enum:APPROVED|RETURNED", True)})
    if plan["status"] != "SUBMITTED":
        raise_err("ERR_DESIGN_PLAN_INVALID_STATE",
                  "Only a SUBMITTED plan can receive an agency decision")
    study = store.studies.get(plan["study_id"])
    if body["decision"] == "APPROVED":
        plan["status"] = "AGENCY_APPROVED"
        touch(plan)
        maybe_lock_plan(study, plan)
    else:
        plan["status"] = "RETURNED_FOR_REVISION"
        touch(plan)
    return ok_obj(design_plan_out(plan))


@bp.post("/evaluation/design-plans/<plan_id>/revise")
def revise_design_plan(plan_id):
    _uid, role = authenticate()
    authorize(role, [ROLE_PRINCIPAL_INVESTIGATOR])
    plan = get_plan_or_404(plan_id)
    body = get_json_body()
    check_schema(body, {})
    if plan["status"] != "RETURNED_FOR_REVISION":
        raise_err("ERR_DESIGN_PLAN_INVALID_STATE",
                  "Only a RETURNED_FOR_REVISION plan can be revised")
    plan["status"] = "DRAFT"
    plan["revision_number"] += 1
    touch(plan)
    return ok_obj(design_plan_out(plan))
