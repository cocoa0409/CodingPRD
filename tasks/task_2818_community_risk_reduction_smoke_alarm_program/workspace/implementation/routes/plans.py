"""Household escape plans (PRD 3.7)."""

from flask import Blueprint

import db
import domain
import response
import util
import validation
from db import store, touch
from errors import ApiError
from middleware import endpoint

bp = Blueprint("plans", __name__)

READ_ROLES = ("ProgramAdmin", "CanvassCoordinator", "CrrTechnician")


def load_plan(plan_id):
    plan = store.escape_plans.get(plan_id)
    if plan is None:
        raise ApiError("ERR_PLAN_NOT_FOUND")
    return plan


@bp.post("/crr/escape-plans")
@endpoint("CanvassCoordinator")
def create_escape_plan():
    body = validation.json_body()
    validation.reject_unexpected_version(body, allowed="expected_household_version")
    household_id = validation.req_str(body, "household_id")
    expected_household_version = validation.req_int(body, "expected_household_version")
    primary_exit_per_sleeping_area = validation.req_bool(
        body, "primary_exit_per_sleeping_area"
    )
    secondary_exit_count = validation.req_int(body, "secondary_exit_count", minimum=0)
    meeting_point_description = validation.req_str(body, "meeting_point_description")
    drill_scheduled_date = validation.opt_date(body, "drill_scheduled_date")

    household = store.households.get(household_id)
    if household is None:
        raise ApiError("ERR_HOUSEHOLD_NOT_FOUND")

    # Ladder step 8 - the supersede guard of PRD 2.10.
    if expected_household_version != household["version"]:
        raise ApiError("ERR_STALE_HOUSEHOLD_VERSION")

    if household["status"] not in ("VISIT_COMPLETED", "REVISIT_REQUIRED"):
        raise ApiError("ERR_INVALID_HOUSEHOLD_STATE")

    # Ladder step 15 - life-safety completeness.
    if (
        not primary_exit_per_sleeping_area
        or secondary_exit_count < household["sleeping_areas_count"]
    ):
        raise ApiError("ERR_ESCAPE_PLAN_INCOMPLETE")

    row = db.stamp_new({})
    plan = {
        "id": row["id"],
        "household_id": household_id,
        "primary_exit_per_sleeping_area": primary_exit_per_sleeping_area,
        "secondary_exit_count": secondary_exit_count,
        "meeting_point_description": meeting_point_description,
        "drill_scheduled_date": drill_scheduled_date,
        "issued_channel": None,
        "issued_at": None,
        "verified_at": None,
        "lapsed_at": None,
        "lapse_reason": None,
        "reissue_count": 0,
        "status": "DRAFT",
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
        "_seq": row["_seq"],
    }

    # PRD 3.7: the create supersedes whatever live plan the household had.
    for existing in db.by_created_at(list(store.escape_plans.values())):
        if existing["household_id"] != household_id:
            continue
        if existing["status"] in domain.PLAN_LIVE_STATUSES:
            existing["status"] = "SUPERSEDED"
            touch(existing)

    store.escape_plans[plan["id"]] = plan
    touch(household)
    return response.ok_row(plan, 201)


@bp.get("/crr/escape-plans")
@endpoint(*READ_ROLES)
def list_escape_plans():
    limit, offset = validation.pagination()
    rows = db.by_created_at(list(store.escape_plans.values()))
    for name in ("household_id", "status"):
        wanted = validation.filter_value(name)
        if wanted is not None:
            rows = [r for r in rows if r[name] == wanted]
    page, total = validation.paginate(rows, limit, offset)
    return response.ok_list(page, limit, offset, total)


@bp.get("/crr/escape-plans/<plan_id>")
@endpoint(*READ_ROLES)
def get_escape_plan(plan_id):
    return response.ok_row(load_plan(plan_id))


@bp.post("/crr/escape-plans/<plan_id>/issue")
@endpoint("CanvassCoordinator")
def issue_escape_plan(plan_id):
    plan = load_plan(plan_id)
    body = validation.json_body()
    validation.reject_unexpected_version(body)
    issued_channel = validation.req_enum(
        body, "issued_channel", domain.ISSUED_CHANNELS
    )

    if plan["status"] not in ("DRAFT", "LAPSED"):
        raise ApiError("ERR_PLAN_NOT_REISSUABLE")

    household = store.households.get(plan["household_id"])
    if household is None or household["status"] not in (
        "VISIT_COMPLETED",
        "REVISIT_REQUIRED",
        "APPOINTMENT_SCHEDULED",
    ):
        raise ApiError("ERR_INVALID_HOUSEHOLD_STATE")

    origin = plan["status"]
    plan["issued_channel"] = issued_channel
    plan["issued_at"] = util.clock.now()
    plan["status"] = "ISSUED"
    if origin == "LAPSED":
        # PRD 3.7: a re-issue counts and clears the lapse record.
        plan["reissue_count"] = plan["reissue_count"] + 1
        plan["lapsed_at"] = None
        plan["lapse_reason"] = None
    touch(plan)
    return response.ok_row(plan)
