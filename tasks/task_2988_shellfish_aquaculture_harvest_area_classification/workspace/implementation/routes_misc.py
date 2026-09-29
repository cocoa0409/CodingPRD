"""Seasonal vibrio control plans and the logical clock (PRD 2.6, 3.8)."""

from flask import Blueprint

import serializers as ser
from core import (
    ALL_ROLES,
    MIN_PLAN_BASELINE_MINUTES,
    PLAN_STATUSES,
    ROLE_AUTHORITY,
    ROLE_OPERATOR,
    apply_changes,
    authenticate,
    clock,
    db,
    envelope_array,
    envelope_object,
    f_instant,
    f_int,
    f_num,
    get_plan,
    iso,
    json_body,
    pagination,
    paginate,
    q_enum,
    q_int,
    sort_default,
    stamp_new,
)

bp = Blueprint("misc", __name__)


@bp.route("/vibrio-control-plans", methods=["POST"])
def publish_plan():
    authenticate([ROLE_AUTHORITY])
    body = json_body()
    season_month = f_int(body, "season_month", minimum=1, maximum=12)
    baseline = f_int(
        body,
        "max_time_to_temperature_minutes",
        minimum=MIN_PLAN_BASELINE_MINUTES,
    )
    high_water_temp_c = f_num(body, "high_water_temp_c")
    reduction = f_int(body, "high_temp_reduction_minutes", minimum=0)

    plan = {
        "season_month": season_month,
        "max_time_to_temperature_minutes": baseline,
        "high_water_temp_c": high_water_temp_c,
        "high_temp_reduction_minutes": reduction,
        "status": "ACTIVE",
    }
    stamp_new(plan)
    # One active plan per month — the latest publication wins.
    for existing in list(db.vibrio_plans.values()):
        if (
            existing["id"] != plan["id"]
            and existing["season_month"] == season_month
            and existing["status"] == "ACTIVE"
        ):
            apply_changes(existing, {"status": "SUPERSEDED"})
    db.vibrio_plans[plan["id"]] = plan
    return envelope_object(ser.vibrio_plan(plan)), 201


@bp.route("/vibrio-control-plans/<plan_id>", methods=["GET"])
def read_plan(plan_id):
    authenticate([ROLE_AUTHORITY, ROLE_OPERATOR])
    plan = get_plan(plan_id)
    return envelope_object(ser.vibrio_plan(plan)), 200


@bp.route("/vibrio-control-plans", methods=["GET"])
def list_plans():
    authenticate([ROLE_AUTHORITY, ROLE_OPERATOR])
    limit, offset = pagination()
    season_month = q_int("season_month", minimum=1, maximum=12)
    status = q_enum("status", PLAN_STATUSES)
    rows = []
    for plan in db.vibrio_plans.values():
        if season_month is not None and plan["season_month"] != season_month:
            continue
        if status is not None and plan["status"] != status:
            continue
        rows.append(plan)
    rows = sort_default(rows)
    total = len(rows)
    page = paginate(rows, limit, offset)
    return envelope_array(
        [ser.vibrio_plan(r) for r in page], limit, offset, total
    ), 200


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    authenticate(ALL_ROLES)
    body = json_body()
    moment = f_instant(body, "to_iso8601")
    # Setting the clock mutates no entity and triggers no recomputation.
    clock.set(moment)
    return envelope_object({"current_utc": iso(clock.now())}), 200
