"""CarePlan and StagedProcedure endpoints (PRD §3.6)."""

from flask import Blueprint, request

import db
import services
from errors import (ApiError, ERR_AGE_WINDOW_VIOLATION, ERR_CARE_PLAN_NOT_FOUND,
                    ERR_PLAN_FUNDING_UNRESOLVED, ERR_STAGE_ALREADY_IN_FLIGHT,
                    ERR_STAGE_IN_PAST, ERR_STAGE_NOT_DUE, ERR_STAGE_NOT_FOUND,
                    ERR_STAGES_IN_FLIGHT, bad_request, invalid_state)
from helpers import (get_body, iso_date, months_between, new_id, now_iso,
                     opt_str, parse_dt, req_dt, req_int, touch)
from middleware import require_auth
from response import success_list, success_object, paginate
from routes.applications import get_application_or_404
from views import care_plan_view, stage_view

bp = Blueprint("care_plans", __name__)

LIST_ROLES = ["NetworkAdmin", "CareCoordinator", "PhilanthropyOfficer", "BillingSpecialist"]
APP_PLAN_ROLES = ["NetworkAdmin", "IntakeCoordinator", "ReviewCommitteeMember",
                  "CareCoordinator", "PhilanthropyOfficer"]


def get_plan_or_404(plan_id):
    p = db.care_plans.get(plan_id)
    if p is None:
        raise ApiError(ERR_CARE_PLAN_NOT_FOUND, 404, "Care plan id does not exist")
    return p


def get_stage_or_404(stage_id):
    s = db.stages.get(stage_id)
    if s is None:
        raise ApiError(ERR_STAGE_NOT_FOUND, 404, "Staged procedure id does not exist")
    return s


def _patient_dob_for_plan(plan):
    app = db.applications.get(plan["application_id"])
    if app is None:
        return None
    return parse_dt(app["patient_date_of_birth"])


def _check_age_window(stage, scheduled_date):
    dob = _patient_dob_for_plan(db.care_plans.get(stage["care_plan_id"]))
    if dob is None:
        return
    age = months_between(dob, scheduled_date)
    if not (stage["min_age_months"] <= age < stage["max_age_months"]):
        raise ApiError(ERR_AGE_WINDOW_VIOLATION, 422,
                       "Patient age at scheduled_date outside "
                       "[min_age_months, max_age_months) of the stage")


@bp.get("/applications/<id>/care-plan")
def get_plan_by_application(id):
    require_auth(APP_PLAN_ROLES)
    a = get_application_or_404(id)
    items = [p for p in db.care_plans.values() if p["application_id"] == a["id"]]
    page, total, limit, offset = paginate(items, request.args)
    return success_list([care_plan_view(p) for p in page], total, limit, offset)


@bp.get("/care-plans/<carePlanId>")
def get_plan(carePlanId):
    require_auth(LIST_ROLES)
    p = get_plan_or_404(carePlanId)
    return success_object(care_plan_view(p))


@bp.post("/care-plans/<carePlanId>/discharge")
def discharge_plan(carePlanId):
    require_auth(["CareCoordinator"])
    plan = get_plan_or_404(carePlanId)
    # A plan holding a partial designation cannot close until its allocations
    # resolve to COMMITTED or are withdrawn (PRD §3.6).
    if plan["funding_status"] == "PARTIALLY_FUNDED":
        raise ApiError(ERR_PLAN_FUNDING_UNRESOLVED, 409,
                       "Discharge blocked while funding_status == PARTIALLY_FUNDED")
    if plan["clinical_status"] not in ("SURVEILLANCE", "ACTIVE_TREATMENT"):
        raise invalid_state("Care plan must be SURVEILLANCE or ACTIVE_TREATMENT to discharge")
    if plan["clinical_status"] == "ACTIVE_TREATMENT":
        in_flight = any(s for s in db.stages.values()
                        if s["care_plan_id"] == plan["id"] and s["status"] == "SCHEDULED")
        if in_flight:
            raise ApiError(ERR_STAGES_IN_FLIGHT, 409,
                           "Discharge blocked by a SCHEDULED stage")
    if plan["clinical_status"] == "ACTIVE_TREATMENT":
        # Cascade: every remaining PLANNED stage -> CANCELLED_STAGE; plan contracts
        for s in db.stages.values():
            if s["care_plan_id"] == plan["id"] and s["status"] == "PLANNED":
                s["status"] = "CANCELLED_STAGE"
                touch(s)
                plan["planned_stage_count"] -= 1
    plan["clinical_status"] = "DISCHARGED"
    touch(plan)
    services.recompute_plan_funding(plan)
    return success_object(care_plan_view(plan))


@bp.post("/care-plans/<id>/staged-procedures")
def create_stage(id):
    require_auth(["CareCoordinator"])
    plan = get_plan_or_404(id)
    body = get_body()
    stage_index = req_int(body, "stage_index", minimum=1)
    min_age_months = req_int(body, "min_age_months", minimum=0)
    max_age_months = req_int(body, "max_age_months")
    if max_age_months <= min_age_months:
        raise bad_request("max_age_months must be greater than min_age_months")
    scheduled_date = req_dt(body, "scheduled_date")
    estimated_cost_cents = req_int(body, "estimated_cost_cents", minimum=1)
    # Uniqueness considers only live stages: indexes freed by cancellation may be reused
    for s in db.stages.values():
        if (s["care_plan_id"] == plan["id"] and s["stage_index"] == stage_index
                and s["status"] != "CANCELLED_STAGE"):
            raise bad_request("stage_index must be unique within the care plan")
    now = now_iso()
    s = {
        "id": new_id(),
        "care_plan_id": plan["id"],
        "stage_index": stage_index,
        "min_age_months": min_age_months,
        "max_age_months": max_age_months,
        "scheduled_date": iso_date(scheduled_date),
        "estimated_cost_cents": estimated_cost_cents,
        "status": "PLANNED",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.stages[s["id"]] = s
    # Adding a stage grows the plan: planned_stage_count is derived from the stage list
    plan["planned_stage_count"] += 1
    touch(plan)
    services.recompute_plan_funding(plan)
    return success_object(stage_view(s), 201)


@bp.get("/care-plans/<id>/staged-procedures")
def list_stages(id):
    require_auth(LIST_ROLES)
    plan = get_plan_or_404(id)
    items = [s for s in db.stages.values() if s["care_plan_id"] == plan["id"]]
    status = request.args.get("status")
    if status:
        items = [s for s in items if s["status"] == status]
    page, total, limit, offset = paginate(items, request.args)
    return success_list([stage_view(s) for s in page], total, limit, offset)


@bp.get("/staged-procedures/<stageId>")
def get_stage(stageId):
    require_auth(LIST_ROLES)
    s = get_stage_or_404(stageId)
    return success_object(stage_view(s))


@bp.post("/staged-procedures/<stageId>/schedule")
def schedule_stage(stageId):
    require_auth(["CareCoordinator"])
    s = get_stage_or_404(stageId)
    plan = db.care_plans.get(s["care_plan_id"])
    if s["status"] != "PLANNED":
        raise invalid_state("Stage must be PLANNED to schedule")
    if plan["clinical_status"] not in ("PLANNING", "ACTIVE_TREATMENT"):
        raise invalid_state("Care plan clinical_status must be PLANNING or ACTIVE_TREATMENT")
    scheduled_date = parse_dt(s["scheduled_date"])
    _check_age_window(s, scheduled_date)
    if scheduled_date < db.CLOCK:
        raise ApiError(ERR_STAGE_IN_PAST, 422,
                       "scheduled_date is before the logical clock's current date")
    for other in db.stages.values():
        if (other["care_plan_id"] == plan["id"] and other["id"] != s["id"]
                and other["status"] == "SCHEDULED"):
            raise ApiError(ERR_STAGE_ALREADY_IN_FLIGHT, 409,
                           "Another stage of the same care plan is already SCHEDULED")
    s["status"] = "SCHEDULED"
    touch(s)
    if plan["clinical_status"] == "PLANNING":
        plan["clinical_status"] = "ACTIVE_TREATMENT"
        touch(plan)
    return success_object(stage_view(s))


@bp.post("/staged-procedures/<stageId>/complete")
def complete_stage(stageId):
    require_auth(["CareCoordinator"])
    s = get_stage_or_404(stageId)
    plan = db.care_plans.get(s["care_plan_id"])
    if s["status"] != "SCHEDULED":
        raise invalid_state("Stage must be SCHEDULED to complete")
    scheduled_date = parse_dt(s["scheduled_date"])
    if db.CLOCK < scheduled_date:
        raise ApiError(ERR_STAGE_NOT_DUE, 409,
                       "Complete attempted before scheduled_date (logical clock)")
    s["status"] = "COMPLETED"
    touch(s)
    plan["completed_stage_count"] += 1
    if (plan["completed_stage_count"] == plan["planned_stage_count"]
            and plan["clinical_status"] == "ACTIVE_TREATMENT"):
        plan["clinical_status"] = "SURVEILLANCE"
    touch(plan)
    services.recompute_plan_funding(plan)
    return success_object(stage_view(s))


@bp.post("/staged-procedures/<stageId>/defer")
def defer_stage(stageId):
    require_auth(["CareCoordinator"])
    s = get_stage_or_404(stageId)
    if s["status"] != "SCHEDULED":
        raise invalid_state("Stage must be SCHEDULED to defer")
    s["status"] = "DEFERRED"
    touch(s)
    return success_object(stage_view(s))


@bp.post("/staged-procedures/<stageId>/replan")
def replan_stage(stageId):
    require_auth(["CareCoordinator"])
    s = get_stage_or_404(stageId)
    plan = db.care_plans.get(s["care_plan_id"])
    if s["status"] != "DEFERRED":
        raise invalid_state("Stage must be DEFERRED to replan")
    body = get_body()
    new_scheduled_date = req_dt(body, "new_scheduled_date")
    _check_age_window(s, new_scheduled_date)
    s["scheduled_date"] = iso_date(new_scheduled_date)
    s["status"] = "PLANNED"
    touch(s)
    return success_object(stage_view(s))


@bp.post("/staged-procedures/<stageId>/cancel-stage")
def cancel_stage(stageId):
    require_auth(["CareCoordinator"])
    s = get_stage_or_404(stageId)
    plan = db.care_plans.get(s["care_plan_id"])
    if s["status"] != "PLANNED":
        raise invalid_state("Stage must be PLANNED to cancel")
    s["status"] = "CANCELLED_STAGE"
    touch(s)
    plan["planned_stage_count"] -= 1
    if (plan["completed_stage_count"] == plan["planned_stage_count"]
            and plan["clinical_status"] == "ACTIVE_TREATMENT"):
        plan["clinical_status"] = "SURVEILLANCE"
    touch(plan)
    services.recompute_plan_funding(plan)
    return success_object(stage_view(s))
