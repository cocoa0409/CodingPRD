"""Care plans, goals and interventions."""
from decimal import Decimal

from flask import Blueprint, request

import core
import domain
import http_util as h
import serializers as S
from core import add_days, clock, db, rhu
from errors import ApiError

bp = Blueprint("careplan", __name__)

ALL_READ = ["ProgramAdmin", "CareManager", "ClinicalReviewer", "UtilizationAnalyst"]


# --------------------------------------------------------------------------
# Care plans
# --------------------------------------------------------------------------
@bp.post("/care-plans")
def create_care_plan():
    user_id, _role = h.authenticate(["CareManager"])
    data = h.body()
    enrollment_id = h.req_str(data, "enrollment_id")
    title = h.req_str(data, "title")
    enrollment = domain.get_enrollment(enrollment_id)

    rec = domain.base_record()
    rec.update({
        "enrollment_id": enrollment["id"],
        "authored_by_care_manager_id": user_id,
        "reviewed_by_care_manager_id": None,
        "title": title,
        "status": "DRAFT",
        "plan_version_no": 1,
        "revision_count": 0,
        "review_decision": None,
        "revision_note": None,
        "submitted_at": None,
        "approved_at": None,
        "closed_at": None,
        "next_review_due_at": None,
        "at_risk_goal_count": 0,
        "compliance_posture": "COMPLIANT",
    })
    db.care_plans[rec["id"]] = rec
    return h.ok(S.care_plan_out(rec), 201)


@bp.get("/care-plans/<plan_id>")
def read_care_plan(plan_id):
    h.authenticate(ALL_READ)
    rec = domain.get_care_plan(plan_id)
    return h.ok(S.care_plan_out(rec))


@bp.get("/care-plans")
def list_care_plans():
    h.authenticate(ALL_READ)
    limit, offset = h.pagination()
    rows = list(db.care_plans.values())
    for field in ("enrollment_id", "authored_by_care_manager_id",
                  "reviewed_by_care_manager_id", "status"):
        value = request.args.get(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    rows = domain.sorted_rows(rows)
    page, total = h.paginate(rows, limit, offset)
    return h.ok_list([S.care_plan_out(r) for r in page], limit, offset, total)


@bp.post("/care-plans/<plan_id>/submit")
def submit_care_plan(plan_id):
    user_id, _role = h.authenticate(["CareManager"])
    plan = domain.get_care_plan(plan_id)
    # ladder step 7 - ownership
    if user_id != plan["authored_by_care_manager_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    # ladder step 9 - source state
    if plan["status"] != "DRAFT":
        raise ApiError("ERR_CARE_PLAN_NOT_DRAFT")
    if not domain.plan_goals(plan["id"]):
        raise ApiError("ERR_INVALID_REQUEST",
                       "A care plan must carry at least one goal to be submitted.")
    # ladder step 11 - cross-entity gate
    enrollment = db.enrollments.get(plan["enrollment_id"])
    if enrollment is None or enrollment["enrollment_status"] != "ACTIVE":
        raise ApiError("ERR_ENROLLMENT_NOT_ACTIVE")

    plan["status"] = "PENDING_REVIEW"
    plan["submitted_at"] = clock.now()
    domain.touch_record(plan)
    return h.ok(S.care_plan_out(plan))


@bp.post("/care-plans/<plan_id>/review")
def review_care_plan(plan_id):
    user_id, _role = h.authenticate(["ClinicalReviewer"])
    data = h.body()
    decision = h.req_enum(data, "decision", core.REVIEW_DECISIONS)
    revision_note = h.opt_str(data, "revision_note")
    if decision == "REQUEST_REVISION" and (revision_note is None
                                           or not revision_note.strip()):
        raise ApiError("ERR_INVALID_REQUEST",
                       "Field 'revision_note' is required on a REQUEST_REVISION decision.")

    plan = domain.get_care_plan(plan_id)
    # ladder step 8 - segregation of duties
    if user_id == plan["authored_by_care_manager_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    # ladder step 9 - source state
    if plan["status"] != "PENDING_REVIEW":
        raise ApiError("ERR_CARE_PLAN_NOT_IN_REVIEW")

    enrollment = db.enrollments.get(plan["enrollment_id"])
    if decision == "APPROVE":
        # ladder step 11 - cross-entity gate
        if enrollment is None or enrollment["enrollment_status"] != "ACTIVE":
            raise ApiError("ERR_ENROLLMENT_NOT_ACTIVE")
        now = clock.now()
        program = domain.program_of_enrollment(enrollment)
        plan["status"] = "ACTIVE"
        plan["approved_at"] = now
        plan["review_decision"] = "APPROVED"
        plan["reviewed_by_care_manager_id"] = user_id
        plan["next_review_due_at"] = add_days(
            now, program["care_plan_review_interval_days"] if program else 90)
        domain.refresh_posture(plan)
    else:
        plan["status"] = "DRAFT"
        plan["review_decision"] = "REVISION_REQUESTED"
        plan["revision_note"] = revision_note
        plan["reviewed_by_care_manager_id"] = user_id
        plan["plan_version_no"] += 1
        plan["revision_count"] += 1
        plan["submitted_at"] = None
    domain.touch_record(plan)
    return h.ok(S.care_plan_out(plan))


# --------------------------------------------------------------------------
# Goals
# --------------------------------------------------------------------------
@bp.post("/care-plans/<plan_id>/goals")
def create_goal(plan_id):
    h.authenticate(["CareManager"])
    data = h.body()
    goal_domain = h.req_enum(data, "domain", core.GOAL_DOMAINS)
    description = h.req_str(data, "description")
    target_date = h.req_date_str(data, "target_date")

    plan = domain.get_care_plan(plan_id)
    if plan["status"] != "DRAFT":
        raise ApiError("ERR_CARE_PLAN_NOT_DRAFT")

    rec = domain.base_record()
    rec.update({
        "care_plan_id": plan["id"],
        "domain": goal_domain,
        "description": description,
        "target_date": target_date,
        "status": "OPEN",
        "barrier_flag": False,
        "planned_intervention_count": 0,
        "completed_intervention_count": 0,
    })
    db.goals[rec["id"]] = rec
    return h.ok(S.goal_out(rec), 201)


@bp.get("/care-plans/<plan_id>/goals")
def list_plan_goals(plan_id):
    h.authenticate(ALL_READ)
    limit, offset = h.pagination()
    plan = domain.get_care_plan(plan_id)
    rows = domain.plan_goals(plan["id"])
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    goal_domain = request.args.get("domain")
    if goal_domain is not None:
        rows = [r for r in rows if r["domain"] == goal_domain]
    page, total = h.paginate(rows, limit, offset)
    return h.ok_list([S.goal_out(r) for r in page], limit, offset, total)


@bp.get("/goals/<goal_id>")
def read_goal(goal_id):
    h.authenticate(ALL_READ)
    rec = domain.get_goal(goal_id)
    return h.ok(S.goal_out(rec))


# --------------------------------------------------------------------------
# Interventions
# --------------------------------------------------------------------------
@bp.post("/goals/<goal_id>/interventions")
def create_intervention(goal_id):
    h.authenticate(["CareManager"])
    data = h.body()
    modality = h.req_enum(data, "modality", core.INTERVENTION_MODALITIES)
    staff_minutes = h.req_int(data, "staff_minutes", minimum=1)

    goal = domain.get_goal(goal_id)
    # ladder step 9 - source state
    if goal["status"] not in ("OPEN", "AT_RISK"):
        raise ApiError("ERR_GOAL_NOT_OPEN")
    # ladder step 11 - cross-entity gate
    plan = domain.plan_of_goal(goal)
    if plan is None or plan["status"] != "ACTIVE":
        raise ApiError("ERR_CARE_PLAN_NOT_ACTIVE")
    program = domain.program_of_goal(goal)
    # ladder step 16 - program staff-minute budget
    if program is None:
        raise ApiError("ERR_PROGRAM_STAFF_BUDGET_EXCEEDED")
    projected = (program["committed_staff_minutes"]
                 + program["delivered_staff_minutes"] + staff_minutes)
    if projected > program["staff_minute_budget"]:
        raise ApiError("ERR_PROGRAM_STAFF_BUDGET_EXCEEDED")

    cost_cents = int(rhu(Decimal(staff_minutes) * Decimal(program["hourly_cost_cents"])
                         / Decimal(60), 0))
    rec = domain.base_record()
    rec.update({
        "goal_id": goal["id"],
        "modality": modality,
        "staff_minutes": staff_minutes,
        "status": "PLANNED",
        "cost_cents": cost_cents,
        "delivered_at": None,
        "void_reason": None,
    })
    db.interventions[rec["id"]] = rec
    program["committed_staff_minutes"] += staff_minutes
    domain.touch_record(program)
    goal["planned_intervention_count"] += 1
    domain.touch_record(goal)
    return h.ok(S.intervention_out(rec), 201)


@bp.get("/goals/<goal_id>/interventions")
def list_goal_interventions(goal_id):
    h.authenticate(ALL_READ)
    limit, offset = h.pagination()
    goal = domain.get_goal(goal_id)
    rows = domain.goal_interventions(goal["id"])
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = h.paginate(rows, limit, offset)
    return h.ok_list([S.intervention_out(r) for r in page], limit, offset, total)


@bp.post("/interventions/<intervention_id>/complete")
def complete_intervention(intervention_id):
    h.authenticate(["CareManager"])
    intervention = domain.get_intervention(intervention_id)
    if intervention["status"] != "PLANNED":
        raise ApiError("ERR_INTERVENTION_NOT_PLANNED")
    goal = db.goals.get(intervention["goal_id"])
    plan = domain.plan_of_goal(goal) if goal else None
    if plan is None or plan["status"] != "ACTIVE":
        raise ApiError("ERR_CARE_PLAN_NOT_ACTIVE")

    program = domain.program_of_goal(goal)
    intervention["status"] = "COMPLETED"
    intervention["delivered_at"] = clock.now()
    domain.touch_record(intervention)
    if program is not None:
        program["committed_staff_minutes"] -= intervention["staff_minutes"]
        program["delivered_staff_minutes"] += intervention["staff_minutes"]
        domain.touch_record(program)
    goal["planned_intervention_count"] = max(0, goal["planned_intervention_count"] - 1)
    goal["completed_intervention_count"] += 1
    domain.maybe_complete_goal(goal)
    domain.touch_record(goal)
    return h.ok(S.intervention_out(intervention))


@bp.post("/interventions/<intervention_id>/void")
def void_intervention(intervention_id):
    h.authenticate(["CareManager"])
    data = h.body()
    void_reason = h.req_str(data, "void_reason")
    intervention = domain.get_intervention(intervention_id)
    if intervention["status"] != "PLANNED":
        raise ApiError("ERR_INTERVENTION_NOT_PLANNED")

    goal = db.goals.get(intervention["goal_id"])
    program = domain.program_of_goal(goal) if goal else None
    intervention["status"] = "VOIDED"
    intervention["void_reason"] = void_reason
    domain.touch_record(intervention)
    if program is not None:
        program["committed_staff_minutes"] -= intervention["staff_minutes"]
        domain.touch_record(program)
    if goal is not None:
        goal["planned_intervention_count"] = max(0, goal["planned_intervention_count"] - 1)
        domain.touch_record(goal)
    return h.ok(S.intervention_out(intervention))
