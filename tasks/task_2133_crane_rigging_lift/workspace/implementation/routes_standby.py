"""Standby / hold windows."""
from decimal import Decimal

from flask import Blueprint

import cascades
import derive
from core import (fail, hours_between, new_record, ordered, parse_dt, respond_list,
                  respond_object, rhu, store, touch)
from guards import Body, auth, body, fk, must_exist, pagination, paginate, q_enum, q_str

bp = Blueprint("standby", __name__)

CAUSES = ["WIND", "WEATHER", "CUSTOMER_DELAY", "SITE_ACCESS"]
STANDBY_STATUSES = ["OPEN", "CLOSED"]


@bp.post("/standby-events")
def create_standby():
    auth(["SafetyManager"])
    b = Body(body())
    lift_plan_id = b.string("lift_plan_id")
    cause = b.enum("cause", CAUSES)
    started_raw, started = b.datetime("started_at")
    wind_speed_mph = b.number("wind_speed_mph", required=False, default=0, minimum=0)
    plan = fk("lift_plans", lift_plan_id)

    if cause == "WIND" and wind_speed_mph < plan["allowable_wind_mph"]:
        fail("ERR_WIND_BELOW_HOLD_THRESHOLD",
             "The reported wind is below the plan's derated allowable wind.")

    forced = False
    if plan["field_status"] == "LIFTING":
        plan["field_status"] = "WIND_HOLD"
        touch(plan)
        forced = (cause == "WIND")

    rec = new_record({
        "lift_plan_id": lift_plan_id,
        "cause": cause,
        "wind_speed_mph": wind_speed_mph,
        "started_at": started_raw,
        "ended_at": None,
        "raw_duration_hours": 0,
        "forced_wind_hold": forced,
        "status": "OPEN",
    })
    store.standby_events[rec["id"]] = rec
    return respond_object(derive.standby_json(rec), 201)


@bp.get("/standby-events/<sid>")
def read_standby(sid):
    auth(["Dispatcher", "LiftDirector", "Operator", "SafetyManager", "BillingClerk"])
    rec = must_exist("standby_events", sid)
    return respond_object(derive.standby_json(rec))


@bp.get("/standby-events")
def list_standby():
    auth(["Dispatcher", "LiftDirector", "Operator", "SafetyManager", "BillingClerk"])
    limit, offset = pagination()
    lift_plan_id = q_str("lift_plan_id")
    status = q_enum("status", STANDBY_STATUSES)
    cause = q_enum("cause", CAUSES)
    rows = ordered(store.standby_events)
    if lift_plan_id:
        rows = [r for r in rows if r["lift_plan_id"] == lift_plan_id]
    if status:
        rows = [r for r in rows if r["status"] == status]
    if cause:
        rows = [r for r in rows if r["cause"] == cause]
    items, limit, offset, total = paginate(rows, limit, offset, derive.standby_json)
    return respond_list(items, limit, offset, total)


@bp.post("/standby-events/<sid>/close")
def close_standby(sid):
    auth(["SafetyManager"])
    event = must_exist("standby_events", sid)
    b = Body(body())
    ended_raw, ended = b.datetime("ended_at")

    started = parse_dt(event["started_at"])
    if ended <= started:
        fail("ERR_INVALID_REQUEST", "ended_at must be strictly after started_at.")

    if event["status"] != "OPEN":
        fail("ERR_INVALID_FIELD_STATE", "Only an OPEN standby window may be closed.")

    event["status"] = "CLOSED"
    event["ended_at"] = ended_raw
    event["raw_duration_hours"] = float(rhu(hours_between(started, ended), 4))
    touch(event)

    plan = store.lift_plans.get(event["lift_plan_id"])
    if plan is not None:
        cascades.recompute_plan_standby(plan)
    return respond_object(derive.standby_json(event))
