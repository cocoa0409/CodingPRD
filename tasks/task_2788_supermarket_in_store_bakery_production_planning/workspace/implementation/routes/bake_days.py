"""Bake day endpoints: opening the day, the forecast, plan generation, the lock
and the close sweep (PRD 3.2, 3.3, 3.9)."""

from flask import Blueprint, request

import serializers
from errors import ApiError
from guards import (
    ANY_ROLE,
    DAYPARTS,
    MARKDOWN_AUTHORIZATIONS,
    PLAN_POSTURES,
    as_bool,
    as_calendar_date,
    as_datetime,
    as_enum,
    as_int,
    authenticate,
    bad,
    body,
    enum_filter,
    find_bake_day,
    find_department,
    find_product,
    scope,
)
from response import created, listing, mark_new, ok, parse_pagination, touch
from services.plan import generate_plan
from services.rollups import (
    recompute_bake_day,
    recompute_slot,
    runs_of_day,
)
from services.runs import attest_waste, cancel_run
from store import by_seq, db, new_entity
from util import day_of_week, q2, q4

bp = Blueprint("bake_days", __name__)


def guard_not_closed(day):
    if day["plan_posture"] == "CLOSED":
        raise ApiError("ERR_BAKE_DAY_CLOSED")


def guard_plan_shaping(day):
    guard_not_closed(day)
    if day["plan_posture"] == "LOCKED":
        raise ApiError("ERR_BAKE_DAY_PLAN_LOCKED")


@bp.post("/bakery/bake-days")
def open_bake_day():
    caller = authenticate(("DepartmentManager",))
    payload = body()
    department = find_department(payload.get("department_id"))
    scope(caller, department["id"])

    business_date = as_calendar_date(payload, "business_date")
    labor_budget = as_int(payload, "labor_budget_minutes", minimum=0)
    shift_start = as_datetime(payload, "oven_shift_start_utc")
    shift_end = as_datetime(payload, "oven_shift_end_utc")
    if shift_end <= shift_start:
        bad("oven_shift_end_utc", "must be strictly after oven_shift_start_utc.")
    authorization = as_enum(payload, "markdown_authorization", MARKDOWN_AUTHORIZATIONS,
                            required=False, default="AUTO")

    iso_date = business_date.isoformat()
    for existing in db.bake_days.values():
        if existing["department_id"] == department["id"] and existing["business_date"] == iso_date:
            raise ApiError("ERR_DUPLICATE_SKU", "A bake day already exists for this department and date.")

    row = new_entity(
        department_id=department["id"],
        business_date=iso_date,
        day_of_week=day_of_week(business_date),
        labor_budget_minutes=labor_budget,
        oven_shift_start_utc=shift_start,
        oven_shift_end_utc=shift_end,
        plan_posture="DRAFT",
        markdown_authorization=authorization,
        forecast_lines=[],
        planned_labor_minutes=q2(0),
        actual_labor_minutes=q2(0),
        planned_units_total=0,
        produced_units_total=0,
        production_cost_cents=0,
        waste_units_total=0,
        shrink_cost_cents=0,
        shrink_cost_basis_pct=q4(0),
        shrink_unit_basis_pct=q4(0),
        plan_unmet_unit_count=0,
    )
    db.bake_days[row["id"]] = row
    mark_new(row)
    return created(serializers.bake_day(row))


@bp.get("/bakery/bake-days/<bakeDayId>")
def read_bake_day(bakeDayId):
    authenticate(ANY_ROLE)
    return ok(serializers.bake_day(find_bake_day(bakeDayId)))


@bp.get("/bakery/bake-days")
def list_bake_days():
    authenticate(ANY_ROLE)
    limit, offset = parse_pagination(request.args)
    department_id = request.args.get("department_id") or None
    posture = enum_filter(request.args, "plan_posture", PLAN_POSTURES)
    business_date = request.args.get("business_date") or None
    rows = []
    for row in db.bake_days.values():
        if department_id is not None and row["department_id"] != department_id:
            continue
        if posture is not None and row["plan_posture"] != posture:
            continue
        if business_date is not None and row["business_date"] != business_date:
            continue
        rows.append(row)
    return listing([serializers.bake_day(row) for row in by_seq(rows)], limit, offset)


@bp.post("/bakery/bake-days/<bakeDayId>/forecast-lines")
def append_forecast_line(bakeDayId):
    caller = authenticate(("DepartmentManager",))
    day = find_bake_day(bakeDayId)
    scope(caller, day["department_id"])
    payload = body()
    product = find_product(payload.get("product_id"))
    daypart = as_enum(payload, "daypart", DAYPARTS)
    forecasted_units = as_int(payload, "forecasted_units", minimum=0)

    guard_plan_shaping(day)

    for line in day["forecast_lines"]:
        if line["product_id"] == product["id"] and line["daypart"] == daypart:
            raise ApiError("ERR_DUPLICATE_FORECAST_LINE")

    if product["department_id"] != day["department_id"]:
        raise ApiError("ERR_INGREDIENT_NOT_IN_DEPARTMENT", "The product belongs to another department.")

    day["forecast_lines"].append(
        {"product_id": product["id"], "daypart": daypart, "forecasted_units": forecasted_units}
    )
    touch(day)
    return ok(serializers.bake_day(day))


@bp.post("/bakery/bake-days/<bakeDayId>/generate-plan")
def generate(bakeDayId):
    caller = authenticate(("DepartmentManager",))
    day = find_bake_day(bakeDayId)
    scope(caller, day["department_id"])
    payload = body()
    expected = as_int(payload, "expected_bake_day_version", minimum=0)
    if expected != day["version"]:
        raise ApiError("ERR_STALE_BAKE_DAY_VERSION")

    guard_plan_shaping(day)
    generate_plan(day)
    return ok(serializers.bake_day(day))


@bp.post("/bakery/bake-days/<bakeDayId>/lock-plan")
def lock_plan(bakeDayId):
    caller = authenticate(("DepartmentManager",))
    day = find_bake_day(bakeDayId)
    scope(caller, day["department_id"])
    guard_not_closed(day)
    if day["plan_posture"] != "PLANNED":
        raise ApiError("ERR_INVALID_RUN_STATE", "The plan may only be locked out of PLANNED.")

    alive = [run for run in runs_of_day(day["id"]) if run["execution_status"] != "CANCELLED"]
    if not alive:
        raise ApiError("ERR_EMPTY_PRODUCTION_PLAN", "The day has no run left to bake.")

    day["plan_posture"] = "LOCKED"
    touch(day)
    return ok(serializers.bake_day(day))


@bp.post("/bakery/bake-days/<bakeDayId>/close")
def close_day(bakeDayId):
    caller = authenticate(("DepartmentManager",))
    day = find_bake_day(bakeDayId)
    scope(caller, day["department_id"])
    payload = body()
    donate_remaining = as_bool(payload, "donate_remaining", default=True)

    guard_not_closed(day)
    if day["plan_posture"] != "LOCKED":
        raise ApiError("ERR_INVALID_RUN_STATE", "The day may only be closed out of LOCKED.")
    for run in runs_of_day(day["id"]):
        if run["execution_status"] in ("PROOFING", "BAKING"):
            raise ApiError("ERR_INVALID_RUN_STATE", "A run is still proofing or baking.")

    department = db.departments.get(day["department_id"])
    donates = bool(donate_remaining) and bool(department["donation_partner_enabled"])
    reason = "DONATED" if donates else "DAY_OLD_UNSOLD"

    # 1. the day-old sweep, in created_at ascending order.
    for run in runs_of_day(day["id"]):
        if run["execution_status"] != "COMPLETED":
            continue
        if run["disposition_status"] not in ("ON_SHELF", "MARKED_DOWN"):
            continue
        remaining = int(run["on_shelf_units"] or 0)
        if remaining <= 0:
            continue
        attest_waste(run, reason, remaining, caller.user_id)

    # 2. unexecuted runs are cancelled whatever their origin.
    for run in runs_of_day(day["id"]):
        if run["execution_status"] == "SCHEDULED":
            cancel_run(run, "DAY_CLOSED")

    # 3. unclaimed cake orders expire and release their decorator capacity.
    orders = by_seq([row for row in db.cake_orders.values() if row["bake_day_id"] == day["id"]])
    touched_slots = []
    for order in orders:
        if order["order_status"] in ("CONFIRMED", "IN_DECORATION", "READY"):
            order["order_status"] = "EXPIRED"
            touch(order)
            slot = db.pickup_slots.get(order["pickup_slot_id"])
            if slot is not None:
                touched_slots.append(slot)
    for slot in touched_slots:
        recompute_slot(slot)

    # 4. every pickup window closes.
    for slot in by_seq([row for row in db.pickup_slots.values() if row["bake_day_id"] == day["id"]]):
        if slot["slot_status"] != "CLOSED":
            slot["slot_status"] = "CLOSED"
            touch(slot)

    day["plan_posture"] = "CLOSED"
    recompute_bake_day(day)
    touch(day)
    return ok(serializers.bake_day(day))
