"""ReleaseOrders (PRD section 3.5).

Creation gates, in PRD 2.9 order: posture (state) -> min flow -> max release ->
flood control -> outlet capacity -> schedule-in-past. Execution checks storage
before the window, executes even on violation, and opens compliance incidents.
"""
from datetime import timedelta

from flask import Blueprint, request

import calc
from auth import ALL_ROLES, authenticate
from envelope import list_response, success
from errors import ApiError, not_found
from routes_reservoir import reservoir_or_404
from serial import release_view
from store import DB, clock_now, new_record, touch
from validate import as_datetime, as_enum, as_int_range, get_body, required

bp = Blueprint("release_orders", __name__)

PURPOSES = ("DELIVERY", "ENVIRONMENTAL", "FLOOD_CONTROL", "POWER")


@bp.post("/water/reservoirs/<string:reservoir_id>/release-orders")
def create_release_order(reservoir_id):
    authenticate(["ReclamationOperator"])
    body = get_body()
    purpose = as_enum(required(body, "purpose"), "purpose", PURPOSES)
    release_cfs = as_int_range(required(body, "release_cfs"), "release_cfs", 1)
    duration_days = as_int_range(required(body, "duration_days"), "duration_days", 1)
    scheduled_start = as_datetime(required(body, "scheduled_start"), "scheduled_start")
    reservoir = reservoir_or_404(reservoir_id)

    # state gate: creation refused outright while the reservoir is on hold
    if calc.reservoir_posture(reservoir["id"]) == "COMPLIANCE_HOLD":
        raise ApiError("ERR_COMPLIANCE_HOLD", 409,
                       "reservoir is under a compliance hold")

    scheduled_end = scheduled_start + timedelta(days=duration_days)

    # environmental safety, fixed sub-order (a) min flow
    for cons in DB["constraints"].values():
        if cons["reservoir_id"] != reservoir["id"]:
            continue
        if cons["requirement_type"] not in ("MIN_FLOW", "PULSE_FLOW"):
            continue
        if calc.windows_intersect(scheduled_start, scheduled_end,
                                  cons["enforce_start"], cons["enforce_end"]):
            if release_cfs < cons["required_min_cfs"]:
                raise ApiError("ERR_ENV_MIN_FLOW_VIOLATION", 422,
                               "release_cfs is below an intersecting minimum-flow requirement")
    # (b) maximum release ceilings
    for cons in DB["constraints"].values():
        if cons["reservoir_id"] != reservoir["id"]:
            continue
        if cons["requirement_type"] != "MAX_RELEASE":
            continue
        if calc.windows_intersect(scheduled_start, scheduled_end,
                                  cons["enforce_start"], cons["enforce_end"]):
            if release_cfs > cons["max_release_cfs"]:
                raise ApiError("ERR_MAX_RELEASE_EXCEEDED", 422,
                               "release_cfs exceeds an intersecting maximum-release ceiling")
    # (c) flood-control gate (clock month at creation; strict > on storage)
    now = clock_now()
    if (now.month in calc.FLOOD_MONTHS
            and reservoir["current_storage_af"] > reservoir["flood_control_max_storage_af"]
            and purpose != "FLOOD_CONTROL"):
        raise ApiError("ERR_FLOOD_CONTROL_REQUIRED", 422,
                       "flood-control month with storage above the flood-control maximum")

    # business: aggregate per-day outlet capacity (equality allowed)
    for day_start in calc.days_touched(scheduled_start, scheduled_end):
        load = calc.day_load(reservoir["id"], day_start)
        if load + release_cfs > reservoir["outlet_capacity_cfs"]:
            raise ApiError("ERR_OUTLET_CAPACITY_EXCEEDED", 422,
                           "per-day aggregate release exceeds outlet_capacity_cfs")

    # temporal: scheduling into the past
    if scheduled_start < now:
        raise ApiError("ERR_SCHEDULE_IN_PAST", 422,
                       "scheduled_start precedes the current logical clock")

    rec = new_record()
    rec.update({
        "reservoir_id": reservoir["id"],
        "purpose": purpose,
        "release_cfs": release_cfs,
        "duration_days": duration_days,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "volume_af": calc.release_volume_af(release_cfs, duration_days),
        "status": "SCHEDULED",
        "executed_at": None,
    })
    DB["release_orders"][rec["id"]] = rec
    return success(release_view(rec), 201)


@bp.get("/water/reservoirs/<string:reservoir_id>/release-orders")
def list_release_orders(reservoir_id):
    authenticate(ALL_ROLES)
    reservoir = reservoir_or_404(reservoir_id)
    filters = {
        "status": request.args.get("status"),
        "purpose": request.args.get("purpose"),
    }
    records = [r for r in DB["release_orders"].values()
               if r["reservoir_id"] == reservoir["id"]]
    return list_response(records, release_view, filters)


@bp.post("/water/release-orders/<string:release_order_id>/execute")
def execute_release_order(release_order_id):
    authenticate(["ReclamationOperator"])
    order = DB["release_orders"].get(release_order_id)
    if order is None:
        not_found("ReleaseOrder")
    if order["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "only a SCHEDULED release order can be executed")
    reservoir = DB["reservoirs"][order["reservoir_id"]]
    # storage sufficiency runs BEFORE the window check
    if reservoir["current_storage_af"] < order["volume_af"]:
        raise ApiError("ERR_INSUFFICIENT_STORAGE", 422,
                       "current_storage_af is below the release volume")
    now = clock_now()
    if not (order["scheduled_start"] <= now < order["scheduled_end"]):
        raise ApiError("ERR_RELEASE_WINDOW_INVALID", 422,
                       "logical clock is outside [scheduled_start, scheduled_end)")
    reservoir["current_storage_af"] -= order["volume_af"]
    touch(reservoir)
    order["status"] = "EXECUTED"
    order["executed_at"] = now
    touch(order)
    # violations execute anyway and open incidents; posture derives from OPEN rows
    for cons in DB["constraints"].values():
        if cons["reservoir_id"] != reservoir["id"]:
            continue
        if not (cons["enforce_start"] <= now < cons["enforce_end"]):
            continue
        deficit = None
        if (cons["requirement_type"] in ("MIN_FLOW", "PULSE_FLOW")
                and order["release_cfs"] < cons["required_min_cfs"]):
            deficit = cons["required_min_cfs"] - order["release_cfs"]
        elif (cons["requirement_type"] == "MAX_RELEASE"
              and order["release_cfs"] > cons["max_release_cfs"]):
            deficit = order["release_cfs"] - cons["max_release_cfs"]
        if deficit is not None:
            incident = new_record()
            incident.update({
                "reservoir_id": reservoir["id"],
                "constraint_id": cons["id"],
                "release_order_id": order["id"],
                "deficit_cfs": deficit,
                "status": "OPEN",
                "resolution": None,
            })
            DB["incidents"][incident["id"]] = incident
    return success(release_view(order), 200)
