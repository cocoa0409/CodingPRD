"""PromotionalEvent: penciling onto the plan calendar, lock (with the cost
estimate + fund reservation), and cancel (the compensating release)."""

from flask import Blueprint, request

import calc
import validation as V
from auth import (
    ALL_ROLES,
    ROLE_MANUFACTURER_PLANNER,
    authenticate,
    authorize,
    scope_plan,
)
from constants import EVENT_TYPES, PLAN_TERMINAL, PROMO_DISCOUNT_DEPTH_MAX_PCT
from envelope import success, success_list
from errors import err
from plans import plan_or_404
from storage import STORE, by_seq, new_id, public, stamp_new, touch
from timeutil import fmt_logical

bp = Blueprint("events", __name__)


def get_event(event_id):
    return STORE["events"].get(event_id)


@bp.post("/jbp/plans/<plan_id>/events")
def create_event(plan_id):
    _uid, role = authenticate()
    authorize(role, [ROLE_MANUFACTURER_PLANNER])
    data = V.body()
    V.check_undeclared(data, {"name", "event_type", "start_date", "end_date", "discount_depth_pct"})
    name = V.as_str(V.require(data, "name"), "name")
    event_type = V.as_enum(V.require(data, "event_type"), "event_type", EVENT_TYPES)
    start = V.as_dt(V.require(data, "start_date"), "start_date")
    end = V.as_dt(V.require(data, "end_date"), "end_date")
    if end <= start:
        err("ERR_VALIDATION", "end_date must be strictly after start_date")
    depth = V.as_num(V.require(data, "discount_depth_pct"), "discount_depth_pct")
    if depth <= 0 or depth > PROMO_DISCOUNT_DEPTH_MAX_PCT:
        err("ERR_VALIDATION", "discount_depth_pct must be in (0, 40]")
    plan = plan_or_404(plan_id)  # 6
    # priority 8: a terminal plan refuses all new events
    if plan["status"] in PLAN_TERMINAL:
        err("ERR_ALREADY_TERMINAL", "plan is terminal")
    # priority 27: half-open overlap per (plan, event_type); adjacency allowed
    for e in STORE["events"].values():
        if (
            e["plan_id"] == plan_id
            and e["event_type"] == event_type
            and e["status"] in ("PENCILED", "LOCKED")
            and start < e["_end_dt"]
            and e["_start_dt"] < end
        ):
            err("ERR_PROMO_OVERLAP", "event interval intersects an existing live event of the same type")
    event = {
        "id": new_id(),
        "plan_id": plan_id,
        "name": name,
        "event_type": event_type,
        "start_date": fmt_logical(start),
        "end_date": fmt_logical(end),
        "discount_depth_pct": depth,
        "status": "PENCILED",
        "estimated_cost_cents": None,
        "_start_dt": start,
        "_end_dt": end,
    }
    stamp_new(event)
    STORE["events"][event["id"]] = event
    return success(public(event), 201)


@bp.get("/jbp/plans/<plan_id>/events")
def list_events(plan_id):
    uid, role = authenticate()
    authorize(role, ALL_ROLES)
    limit, offset = V.pagination()
    plan = STORE["plans"].get(plan_id)
    scope_plan(uid, role, plan)
    if plan is None:
        err("ERR_PLAN_NOT_FOUND", "plan not found")
    items = [e for e in by_seq(STORE["events"].values()) if e["plan_id"] == plan_id]
    f_status = request.args.get("status")
    if f_status is not None:
        items = [e for e in items if e["status"] == f_status]
    f_type = request.args.get("event_type")
    if f_type is not None:
        items = [e for e in items if e["event_type"] == f_type]
    total = len(items)
    page = items[offset : offset + limit]
    return success_list([public(e) for e in page], limit, offset, total)


@bp.post("/jbp/events/<event_id>/lock")
def lock_event(event_id):
    _uid, role = authenticate()
    authorize(role, [ROLE_MANUFACTURER_PLANNER])
    event = get_event(event_id)
    if event is None:
        err("ERR_RESOURCE_NOT_FOUND", "event not found")  # 6
    if event["status"] == "CANCELLED":
        err("ERR_ALREADY_TERMINAL", "event is CANCELLED")  # 8
    if event["status"] != "PENCILED":
        err("ERR_INVALID_STATE", "only a PENCILED event can be locked")  # 7
    plan = STORE["plans"][event["plan_id"]]
    if plan["status"] != "ACTIVATED":
        err("ERR_PLAN_NOT_ACTIVATED", "event lock requires an ACTIVATED plan")  # 12
    estimate = calc.event_cost_estimate(event, plan)
    fund = calc.fund_of_plan(plan["id"])
    if estimate > calc.bucket_available(fund, "EVENT"):
        err("ERR_INSUFFICIENT_FUNDS", "estimated cost exceeds event_available_cents")  # 33
    event["estimated_cost_cents"] = estimate
    event["status"] = "LOCKED"
    touch(event)
    fund["event_reserved_cents"] += estimate
    touch(fund)
    return success(public(event))


@bp.post("/jbp/events/<event_id>/cancel")
def cancel_event(event_id):
    _uid, role = authenticate()
    authorize(role, [ROLE_MANUFACTURER_PLANNER])
    event = get_event(event_id)
    if event is None:
        err("ERR_RESOURCE_NOT_FOUND", "event not found")  # 6
    if event["status"] == "CANCELLED":
        err("ERR_ALREADY_TERMINAL", "event is CANCELLED")  # 8
    if event["status"] == "LOCKED":
        fund = calc.fund_of_plan(event["plan_id"])
        if fund is not None:
            fund["event_reserved_cents"] -= event["estimated_cost_cents"]
            touch(fund)
    event["status"] = "CANCELLED"
    touch(event)
    return success(public(event))
