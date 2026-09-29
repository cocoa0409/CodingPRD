"""Water sourcing, hydrostatic test planning and test cost (PRD 3.7)."""

from flask import Blueprint, g

import common
import derive
import errors
import validate as v
from auth import (ALL_ROLES, AUTHORIZED_INSPECTOR, ERECTION_SUPERINTENDENT,
                  PROJECT_ENGINEER, acting_user, endpoint)
from envelope import array_response, object_response, paged, query_filters
from errors import ApiError
from store import (HYDROTEST_PLANS, TANKS, WATER_SOURCES, WATER_WITHDRAWALS,
                   new_row, touch)
from util import D, add_hours, now_logical, q

bp = Blueprint("water", __name__)

SOURCE_TYPES = ("MUNICIPAL", "RIVER", "WELL", "RECLAIMED")
DISPOSAL_METHODS = ("DISCHARGE_TO_POTW", "LAND_APPLICATION", "HAUL_OFFSITE",
                    "REUSE_NEXT_TANK")
APPROVAL_DECISIONS = ("APPROVE", "REJECT")
COMPLETION_DECISIONS = ("PASS", "FAIL")
HOLD_POINTS = (25, 50, 75, 100)
MIN_HOLD_HOURS = 24
LIVE_PLAN_STATUSES = ("DRAFT", "APPROVED", "FILLING", "FILL_HOLD")


@bp.post("/water-sources")
@endpoint((PROJECT_ENGINEER,))
def create_source():
    body = g.body
    source_name = v.s_str(body, "source_name", required=True)
    source_type = v.s_enum(body, "source_type", SOURCE_TYPES, required=True)
    permitted = v.s_num(body, "permitted_volume_gal", required=True, gt=0)
    max_rate = v.s_num(body, "max_concurrent_rate_gpm", required=True, gt=0)
    water_cost = v.s_num(body, "water_cost_usd_per_kgal", required=True, ge=0)
    disposal_cost = v.s_num(body, "disposal_cost_usd_per_kgal", required=True,
                            ge=0)
    permit_expiry = v.s_dt(body, "permit_expiry_utc", required=True)

    for other in WATER_SOURCES.values():
        if other["source_name"] == source_name:
            raise common.duplicate("source_name must be unique.")

    source = new_row({
        "source_name": source_name,
        "source_type": source_type,
        "permitted_volume_gal": permitted,
        "max_concurrent_rate_gpm": max_rate,
        "water_cost_usd_per_kgal": water_cost,
        "disposal_cost_usd_per_kgal": disposal_cost,
        "permit_expiry_utc": permit_expiry,
        "reserved_volume_gal": 0.0,
        "consumed_volume_gal": 0.0,
        "available_volume_gal": q(permitted, 2),
    })
    WATER_SOURCES[source["id"]] = source
    return object_response(source, 201)


@bp.get("/water-sources")
@endpoint(ALL_ROLES)
def list_sources():
    filters = query_filters("source_name", "source_type")
    rows, limit, offset, total = paged(WATER_SOURCES.values(), filters)
    return array_response(rows, limit, offset, total)


@bp.get("/water-sources/<water_source_id>")
@endpoint(ALL_ROLES)
def read_source(water_source_id):
    return object_response(common.get_water_source(water_source_id))


@bp.post("/hydrotest-plans")
@endpoint((PROJECT_ENGINEER,))
def create_plan():
    body = g.body
    tank_id = v.s_str(body, "tank_id", required=True)
    source_id = v.s_str(body, "water_source_id", required=True)
    fill_volume = v.s_num(body, "fill_volume_gal", required=True, gt=0)
    disposal_method = v.s_enum(body, "disposal_method", DISPOSAL_METHODS,
                               required=True)
    hold_hours = v.s_int(body, "hold_hours", required=True,
                         ge=MIN_HOLD_HOURS)
    expected_version = v.s_int(body, "expected_tank_version", required=True)
    tank = common.get_tank(tank_id)
    source = common.get_water_source(source_id)

    if expected_version != tank["version"]:
        raise ApiError(errors.ERR_STALE_TANK_VERSION, 412,
                       "expected_tank_version does not match the tank's "
                       "current version.")

    previous_plan_id = None
    for older in derive.by_created(derive.plans_of_tank(tank["id"])):
        if older["status"] not in ("DRAFT", "REJECTED"):
            continue
        was_draft = older["status"] == "DRAFT"
        older["status"] = "SUPERSEDED"
        touch(older)
        previous_plan_id = older["id"]
        if was_draft:
            derive.cancel_plan_withdrawals(older, "PLAN_SUPERSEDED")

    plan = new_row({
        "tank_id": tank["id"],
        "water_source_id": source["id"],
        "fill_volume_gal": fill_volume,
        "disposal_method": disposal_method,
        "hold_hours": hold_hours,
        "fill_percent_current": 0.0,
        "settlement_survey_count": 0,
        "hold_started_at_utc": None,
        "completed_at_utc": None,
        "water_cost_usd": 0.0,
        "disposal_cost_usd": 0.0,
        "subtotal_usd": 0.0,
        "permit_surcharge_pct": 0.0,
        "surcharge_usd": 0.0,
        "total_cost_usd": 0.0,
        "status": "DRAFT",
        "approved_by_user_id": None,
        "state_before_suspension": None,
        "suspension_reason": None,
        "previous_plan_id": previous_plan_id,
    })
    HYDROTEST_PLANS[plan["id"]] = plan
    touch(tank)
    return object_response(plan, 201)


@bp.get("/hydrotest-plans")
@endpoint(ALL_ROLES)
def list_plans():
    filters = query_filters("tank_id", "water_source_id", "status")
    rows, limit, offset, total = paged(HYDROTEST_PLANS.values(), filters)
    return array_response(rows, limit, offset, total)


@bp.get("/hydrotest-plans/<hydrotest_plan_id>")
@endpoint(ALL_ROLES)
def read_plan(hydrotest_plan_id):
    return object_response(common.get_hydrotest_plan(hydrotest_plan_id))


@bp.post("/hydrotest-plans/<hydrotest_plan_id>/approval")
@endpoint((PROJECT_ENGINEER,))
def approve_plan(hydrotest_plan_id):
    plan = common.get_hydrotest_plan(hydrotest_plan_id)
    decision = v.s_enum(g.body, "decision", APPROVAL_DECISIONS, required=True)
    v.s_str(g.body, "remarks", required=False)
    tank = TANKS.get(plan["tank_id"])

    if plan["status"] != "DRAFT":
        raise ApiError(errors.ERR_PLAN_STATE_INVALID, 409,
                       "Only a DRAFT plan may be decided.")
    if tank["construction_phase"] != "SHELL_COMPLETE":
        raise ApiError(errors.ERR_PLAN_STATE_INVALID, 409,
                       "The tank must be SHELL_COMPLETE.")

    if decision == "APPROVE":
        common.require_posture_open(tank)
        source = WATER_SOURCES.get(plan["water_source_id"])
        if source is not None and source["permit_expiry_utc"] < now_logical():
            raise ApiError(errors.ERR_WATER_PERMIT_EXPIRED, 409,
                           "The water permit has expired.")
        plan["status"] = "APPROVED"
        plan["approved_by_user_id"] = acting_user()
        touch(plan)
        tank["active_hydrotest_plan_id"] = plan["id"]
        touch(tank)
    else:
        plan["status"] = "REJECTED"
        touch(plan)
        derive.cancel_plan_withdrawals(plan, "PLAN_REJECTED")
    return object_response(plan)


@bp.post("/hydrotest-plans/<hydrotest_plan_id>/fill-advance")
@endpoint((ERECTION_SUPERINTENDENT,))
def fill_advance(hydrotest_plan_id):
    plan = common.get_hydrotest_plan(hydrotest_plan_id)
    target = v.s_num(g.body, "target_fill_percent", required=True, ge=0, le=100)
    survey_id = v.s_str(g.body, "settlement_survey_id", required=False)
    survey = (common.get_settlement_survey(survey_id)
              if survey_id is not None else None)
    tank = TANKS.get(plan["tank_id"])

    if plan["status"] not in ("APPROVED", "FILLING"):
        raise ApiError(errors.ERR_PLAN_STATE_INVALID, 409,
                       "Only an APPROVED or FILLING plan may be advanced.")
    common.require_posture_open(tank)

    if D(target) <= D(plan["fill_percent_current"]):
        raise ApiError(errors.ERR_FILL_PERCENT_NOT_ADVANCING, 409,
                       "target_fill_percent must strictly advance the fill "
                       "level.")

    if any(D(target) == D(point) for point in HOLD_POINTS):
        package = derive.package_of_tank(tank["id"])
        if (survey is None
                or package is None
                or survey["foundation_package_id"] != package["id"]
                or D(survey["fill_percent"]) != D(target)
                or survey["verdict"] != "WITHIN_TOLERANCE"):
            raise ApiError(errors.ERR_SETTLEMENT_HOLD_POINT_MISSING, 409,
                           "A WITHIN_TOLERANCE settlement survey at this fill "
                           "level is required.")

    plan["fill_percent_current"] = target
    if survey is not None:
        plan["settlement_survey_count"] = plan["settlement_survey_count"] + 1
    if D(target) == D(100):
        plan["status"] = "FILL_HOLD"
        plan["hold_started_at_utc"] = now_logical()
    else:
        plan["status"] = "FILLING"
    touch(plan)
    return object_response(plan)


@bp.post("/hydrotest-plans/<hydrotest_plan_id>/completion")
@endpoint((AUTHORIZED_INSPECTOR,))
def complete_plan(hydrotest_plan_id):
    plan = common.get_hydrotest_plan(hydrotest_plan_id)
    decision = v.s_enum(g.body, "decision", COMPLETION_DECISIONS,
                        required=True)
    v.s_str(g.body, "remarks", required=False)
    tank = TANKS.get(plan["tank_id"])

    if plan["status"] != "FILL_HOLD":
        raise ApiError(errors.ERR_PLAN_STATE_INVALID, 409,
                       "Only a FILL_HOLD plan may be completed.")
    if plan["approved_by_user_id"] == acting_user():
        raise ApiError(errors.ERR_SEGREGATION_OF_DUTIES, 403,
                       "The approver may not record the completion decision.")

    if decision == "PASS":
        if plan["settlement_survey_count"] < 4:
            raise ApiError(errors.ERR_SETTLEMENT_HOLD_POINT_MISSING, 409,
                           "All four mandatory hold-point surveys are "
                           "required.")
        started = plan["hold_started_at_utc"]
        if started is None or now_logical() < add_hours(started,
                                                        plan["hold_hours"]):
            raise ApiError(errors.ERR_HOLD_PERIOD_NOT_ELAPSED, 409,
                           "The hold period has not elapsed.")
        plan["status"] = "PASSED"
    else:
        plan["status"] = "FAILED"
    plan["completed_at_utc"] = now_logical()
    touch(plan)

    sources = []
    for withdrawal in derive.by_created(derive.withdrawals_of_plan(plan["id"])):
        if withdrawal["status"] != "RESERVED":
            continue
        withdrawal["status"] = "CONSUMED"
        touch(withdrawal)
        source = WATER_SOURCES.get(withdrawal["water_source_id"])
        if source is not None and source not in sources:
            sources.append(source)
    for source in sources:
        derive.rederive_water_ledger(source)
    derive.recompute_plan_costs(plan)

    if decision == "PASS":
        if tank["construction_phase"] == "SHELL_COMPLETE":
            tank["construction_phase"] = "HYDROTEST_PASSED"
            touch(tank)
    else:
        tank["active_hydrotest_plan_id"] = None
        touch(tank)
        derive.recompute_posture(tank)
    return object_response(plan)


@bp.post("/water-withdrawals")
@endpoint((ERECTION_SUPERINTENDENT,))
def reserve_withdrawal():
    body = g.body
    plan_id = v.s_str(body, "hydrotest_plan_id", required=True)
    source_id = v.s_str(body, "water_source_id", required=True)
    window_start = v.s_dt(body, "window_start_utc", required=True)
    window_end = v.s_dt(body, "window_end_utc", required=True)
    rate_gpm = v.s_num(body, "rate_gpm", required=True, gt=0)
    volume = v.s_num(body, "reserved_volume_gal", required=True, gt=0)
    expected_version = v.s_int(body, "expected_water_source_version",
                               required=True)
    plan = common.get_hydrotest_plan(plan_id)
    source = common.get_water_source(source_id)

    if expected_version != source["version"]:
        raise ApiError(errors.ERR_STALE_WATER_SOURCE_VERSION, 412,
                       "expected_water_source_version does not match the "
                       "source's current version.")

    if plan["status"] not in LIVE_PLAN_STATUSES:
        raise ApiError(errors.ERR_PLAN_STATE_INVALID, 409,
                       "The plan accepts no further action.")
    if plan["water_source_id"] != source["id"]:
        raise common.cross_tank(
            "water_source_id must match the plan's water source.")

    if window_end <= window_start:
        raise ApiError(errors.ERR_INVALID_WINDOW, 409,
                       "window_end_utc must be strictly after "
                       "window_start_utc.")
    if source["permit_expiry_utc"] < window_end:
        raise ApiError(errors.ERR_WATER_PERMIT_EXPIRED, 409,
                       "The withdrawal window runs past the permit expiry.")
    peak = derive.peak_rate_with(source, window_start, window_end, rate_gpm)
    if peak > D(source["max_concurrent_rate_gpm"]):
        raise ApiError(errors.ERR_WITHDRAWAL_CAPACITY_CONFLICT, 409,
                       "The concurrent withdrawal rate envelope would be "
                       "exceeded.")
    if D(volume) > D(source["available_volume_gal"]):
        raise ApiError(errors.ERR_PERMITTED_VOLUME_EXCEEDED, 409,
                       "The permitted volume would be oversubscribed.")

    withdrawal = new_row({
        "hydrotest_plan_id": plan["id"],
        "water_source_id": source["id"],
        "window_start_utc": window_start,
        "window_end_utc": window_end,
        "rate_gpm": rate_gpm,
        "reserved_volume_gal": volume,
        "withdrawal_cost_usd": derive.withdrawal_cost_for(source, volume),
        "status": "RESERVED",
        "cancellation_reason": None,
    })
    WATER_WITHDRAWALS[withdrawal["id"]] = withdrawal

    derive.rederive_water_ledger(source)
    touch(source)
    derive.recompute_plan_costs(plan)
    withdrawal["version"] = 1
    return object_response(withdrawal, 201)


@bp.get("/water-withdrawals")
@endpoint(ALL_ROLES)
def list_withdrawals():
    filters = query_filters("hydrotest_plan_id", "water_source_id", "status")
    rows, limit, offset, total = paged(WATER_WITHDRAWALS.values(), filters)
    return array_response(rows, limit, offset, total)


@bp.get("/water-withdrawals/<water_withdrawal_id>")
@endpoint(ALL_ROLES)
def read_withdrawal(water_withdrawal_id):
    return object_response(common.get_water_withdrawal(water_withdrawal_id))


@bp.post("/water-withdrawals/<water_withdrawal_id>/cancellation")
@endpoint((ERECTION_SUPERINTENDENT,))
def cancel_withdrawal(water_withdrawal_id):
    withdrawal = common.get_water_withdrawal(water_withdrawal_id)
    reason = v.s_str(g.body, "cancellation_reason", required=True)

    if withdrawal["status"] != "RESERVED":
        raise ApiError(errors.ERR_WITHDRAWAL_STATE_INVALID, 409,
                       "Only a RESERVED window may be cancelled.")

    withdrawal["status"] = "CANCELLED"
    withdrawal["cancellation_reason"] = reason
    touch(withdrawal)
    source = WATER_SOURCES.get(withdrawal["water_source_id"])
    if source is not None:
        derive.rederive_water_ledger(source)
    plan = HYDROTEST_PLANS.get(withdrawal["hydrotest_plan_id"])
    if plan is not None:
        derive.recompute_plan_costs(plan)
    return object_response(withdrawal)
