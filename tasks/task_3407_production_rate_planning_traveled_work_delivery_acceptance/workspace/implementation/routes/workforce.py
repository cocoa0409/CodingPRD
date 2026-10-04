"""Workforce plans and hiring (PRD 3.1)."""
from flask import Blueprint

import svc
from core import (
    ApiError,
    body,
    db,
    endpoint,
    f_int,
    f_str,
    new_row,
    paginate,
    raw_int,
    respond_object,
    sort_created,
    touch,
)

bp = Blueprint("workforce", __name__, url_prefix="/api")


@bp.post("/programs/<program_id>/workforce-plans")
@endpoint("ProductionPlanner")
def create_workforce_plan(program_id):
    program = svc.need_program(program_id)
    payload = body()
    # rung 8 -- skill_code unique within the program
    candidate = payload.get("skill_code")
    if isinstance(candidate, str) and any(
        w["program_id"] == program["id"] and w["skill_code"] == candidate
        for w in db.workforce_plans.values()
    ):
        raise ApiError("ERR_DUPLICATE_CODE")
    # rung 10 -- body shape
    skill_code = f_str(payload, "skill_code")
    required_headcount = f_int(payload, "required_headcount", minimum=1)
    plan = new_row(
        "WorkforcePlan",
        program_id=program["id"],
        skill_code=skill_code,
        required_headcount=required_headcount,
        hired_headcount=0,
    )
    db.workforce_plans[plan["id"]] = plan
    return respond_object(svc.dump_workforce_plan(plan), 201)


@bp.get("/programs/<program_id>/workforce-plans")
@endpoint("ProgramAdmin", "ProductionPlanner")
def list_workforce_plans(program_id):
    svc.need_program(program_id)
    rows = [w for w in db.workforce_plans.values() if w["program_id"] == program_id]
    return paginate(sort_created(rows), svc.dump_workforce_plan)


@bp.post("/workforce-plans/<plan_id>/hire")
@endpoint("ProductionPlanner")
def hire(plan_id):
    plan = svc.need_workforce_plan(plan_id)
    payload = body()
    # rung 9 -- count >= 1 and hired_headcount + count <= required_headcount
    count_raw = payload.get("count")
    if raw_int(count_raw):
        if count_raw < 1 or plan["hired_headcount"] + count_raw > plan["required_headcount"]:
            raise ApiError("ERR_HIRE_EXCEEDS_REQUIRED")
    # rung 10 -- body shape
    count = f_int(payload, "count")
    plan["hired_headcount"] += count
    touch(plan)
    return respond_object(svc.dump_workforce_plan(plan))
