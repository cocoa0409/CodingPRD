"""Plan update cycle, state filing and the determination cascade (PRD 3.1, 3.8)."""
import re

from flask import Blueprint

import constants as K
import serial
import validation as V
from db import bump, db, dec, new_row, sort_rows, to_num
from errors import ApiError
from response import (actor, authenticate, created, filter_param, ok, paginate,
                      pagination)
from services import calc, planservice, repo

bp = Blueprint("plans", __name__)

_JURISDICTION = re.compile(r"^[A-Z0-9]{2,12}$")
_READERS = K.ALL_ROLES


@bp.post("/planning/plan-updates")
def create_plan():
    authenticate([K.ROLE_DIRECTOR])
    data = V.body()
    title = V.get_str(data, "title", 1, 160)
    jurisdiction = V.get_str(data, "jurisdiction_code", 2, 12,
                             pattern=_JURISDICTION)
    base_year = V.get_int(data, "base_year", 2000, 2100)
    horizon_year = V.get_int(data, "horizon_year", 2000, 2100)
    if horizon_year - base_year < 10:
        V.bad("horizon_year must be at least 10 years beyond base_year.")

    plan = new_row({
        "title": title,
        "jurisdiction_code": jurisdiction,
        "base_year": base_year,
        "horizon_year": horizon_year,
        "status": "DRAFTING",
        "state_review_status": "NOT_SUBMITTED",
        "compliance_posture": "CAPACITY_HOLD",
        "adopted_scenario_id": None,
        "open_consistency_link_count": 0,
        "required_elements_complete_count": 0,
        "housing_shortfall_total": 0,
        "equity_share_pct": dec("0.0"),
        "participation_weight_total": dec("0.0"),
        "underrepresented_weight_total": dec("0.0"),
        "resubmission_count": 0,
        "monitoring_on_track_count": 0,
        "state_findings": None,
        "adopted_at": None,
    })
    # A brand-new plan has no adopted scenario, so the ladder yields CAPACITY_HOLD.
    plan["compliance_posture"] = calc.compliance_posture(plan)
    db.plan_updates[plan["id"]] = plan
    return created(serial.plan_update(plan))


@bp.get("/planning/plan-updates/<row_id>")
def read_plan(row_id):
    authenticate(_READERS)
    return ok(serial.plan_update(repo.plan(row_id)))


@bp.get("/planning/plan-updates")
def list_plans():
    authenticate(_READERS)
    limit, offset = pagination()
    status = filter_param("status")
    jurisdiction = filter_param("jurisdiction_code")
    scenario_id = filter_param("adopted_scenario_id")
    rows = sort_rows(list(db.plan_updates.values()))
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if jurisdiction is not None:
        rows = [r for r in rows if r["jurisdiction_code"] == jurisdiction]
    if scenario_id is not None:
        rows = [r for r in rows if r["adopted_scenario_id"] == scenario_id]
    return paginate(rows, limit, offset, serial.plan_update)


@bp.post("/planning/plan-updates/<row_id>/state-submission")
def state_submission(row_id):
    authenticate([K.ROLE_DIRECTOR])
    plan = repo.plan(row_id)
    data = V.body()
    V.get_str(data, "submission_note", 1, 2000, required=False, non_blank=False)

    planservice.ensure_not_adopted(plan)
    if plan["status"] not in ("DRAFTING", "STATE_DEFICIENT"):
        raise ApiError("ERR_PLAN_NOT_DRAFTING")
    resubmission = plan["status"] == "STATE_DEFICIENT"

    planservice.recompute_counters(plan)
    # The checklist order of PRD 3.8 is part of the contract.
    if int(plan["required_elements_complete_count"]) != len(K.REQUIRED_ELEMENT_TYPES):
        raise ApiError("ERR_REQUIRED_ELEMENT_MISSING")
    tiers = set(r["income_tier"] for r in repo.allocations_of(plan["id"]))
    if any(tier not in tiers for tier in K.INCOME_TIERS):
        raise ApiError("ERR_ALLOCATION_INCOMPLETE")
    if int(plan["open_consistency_link_count"]) != 0:
        raise ApiError("ERR_CONSISTENCY_UNRESOLVED")
    if not any(r["status"] in ("CIRCULATED", "CERTIFIED")
               for r in repo.reviews_of(plan["id"])):
        raise ApiError("ERR_ENVIRONMENTAL_REVIEW_MISSING")
    if int(plan["housing_shortfall_total"]) != 0:
        raise ApiError("ERR_HOUSING_SHORTFALL")
    if dec(plan["equity_share_pct"]) < K.EQUITY_MIN_SHARE_PCT:
        raise ApiError("ERR_EQUITY_TARGET_NOT_MET")
    if resubmission and int(plan["resubmission_count"]) >= K.MAX_RESUBMISSIONS:
        raise ApiError("ERR_RESUBMISSION_LIMIT_EXCEEDED")

    plan["status"] = "STATE_SUBMITTED"
    plan["state_review_status"] = "SUBMITTED"
    if resubmission:
        plan["resubmission_count"] = int(plan["resubmission_count"]) + 1
    else:
        plan["state_findings"] = None
    planservice.refresh(plan)
    bump(plan)
    return ok(serial.plan_update(plan))


@bp.post("/planning/plan-updates/<row_id>/state-determination")
def state_determination(row_id):
    authenticate([K.ROLE_STATE])
    plan = repo.plan(row_id)
    data = V.body()
    determination = V.get_enum(data, "determination", K.DETERMINATIONS)
    findings = V.get_str(data, "findings", None, 4000, non_blank=False)
    deficient_types = V.get_str_list(data, "deficient_element_types",
                                     K.REQUIRED_ELEMENT_TYPES, required=False)
    if determination == "DEFICIENT" and not deficient_types:
        V.bad("deficient_element_types must be a non-empty subset of the "
              "statutory element types.")

    if plan["state_review_status"] != "SUBMITTED":
        raise ApiError("ERR_PLAN_NOT_SUBMITTED")

    if determination == "CERTIFIED":
        plan["status"] = "STATE_CERTIFIED"
        plan["state_review_status"] = "CERTIFIED"
        plan["state_findings"] = findings
        planservice.refresh(plan)
    else:
        plan["status"] = "STATE_DEFICIENT"
        plan["state_review_status"] = "DEFICIENT"
        plan["state_findings"] = findings
        planservice.demote_approved_elements(plan, types=deficient_types)
        planservice.refresh(plan, force_block=True)
    bump(plan)
    return ok(serial.plan_update(plan))


@bp.get("/planning/plan-updates/<row_id>/compliance-summary")
def compliance_summary(row_id):
    authenticate(_READERS)
    plan = repo.plan(row_id)
    capacity = None
    demand = None
    gap = None
    scenario_id = plan.get("adopted_scenario_id")
    if scenario_id is not None:
        scenario = db.growth_scenarios.get(scenario_id)
        if scenario is not None:
            capacity = scenario["land_capacity_units"]
            demand = scenario["projected_demand_units"]
            gap = scenario["capacity_gap_units"]
    return ok({
        "plan_update_id": plan["id"],
        "compliance_posture": plan["compliance_posture"],
        "state_review_status": plan["state_review_status"],
        "required_elements_complete_count":
            plan["required_elements_complete_count"],
        "missing_element_types": planservice.required_element_types_missing(plan),
        "open_consistency_link_count": plan["open_consistency_link_count"],
        "housing_shortfall_total": plan["housing_shortfall_total"],
        "equity_share_pct": to_num(plan["equity_share_pct"]),
        "land_capacity_units": capacity,
        "projected_demand_units": demand,
        "capacity_gap_units": gap,
        "monitoring_on_track_count": plan["monitoring_on_track_count"],
    })


# --- nested list endpoints on the plan (PRD 2.11) ---------------------------

@bp.get("/planning/plan-updates/<row_id>/inventory-datasets")
def list_plan_inventories(row_id):
    authenticate(_READERS)
    plan = repo.plan(row_id)
    limit, offset = pagination()
    inventory_type = filter_param("inventory_type")
    status = filter_param("status")
    rows = repo.inventories_of(plan["id"])
    if inventory_type is not None:
        rows = [r for r in rows if r["inventory_type"] == inventory_type]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginate(rows, limit, offset, serial.inventory)


@bp.get("/planning/plan-updates/<row_id>/housing-allocations")
def list_plan_allocations(row_id):
    authenticate(_READERS)
    plan = repo.plan(row_id)
    limit, offset = pagination()
    tier = filter_param("income_tier")
    rows = repo.allocations_of(plan["id"])
    if tier is not None:
        rows = [r for r in rows if r["income_tier"] == tier]
    return paginate(rows, limit, offset, serial.allocation)


@bp.get("/planning/plan-updates/<row_id>/plan-elements")
def list_plan_elements(row_id):
    authenticate(_READERS)
    plan = repo.plan(row_id)
    limit, offset = pagination()
    element_type = filter_param("element_type")
    status = filter_param("status")
    rows = repo.elements_of(plan["id"])
    if element_type is not None:
        rows = [r for r in rows if r["element_type"] == element_type]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginate(rows, limit, offset, serial.element)


@bp.get("/planning/plan-updates/<row_id>/hearings")
def list_plan_hearings(row_id):
    authenticate(_READERS)
    plan = repo.plan(row_id)
    limit, offset = pagination()
    body_type = filter_param("body_type")
    status = filter_param("status")
    rows = repo.hearings_of(plan["id"])
    if body_type is not None:
        rows = [r for r in rows if r["body_type"] == body_type]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginate(rows, limit, offset, serial.hearing)


_ = actor  # re-exported for symmetry with the other route modules
