"""Forecast: weekly baseline publication with supersession, and retailer
commitment. Publication and commitment are independent state axes."""

from flask import Blueprint, request

import clock
import validation as V
from auth import (
    ALL_ROLES,
    ROLE_RETAILER_BUYER,
    ROLE_SUPPLY_CHAIN_PLANNER,
    authenticate,
    authorize,
    scope_plan,
)
from envelope import success, success_list
from errors import err
from plans import plan_or_404
from storage import STORE, by_seq, new_id, public, stamp_new, touch
from timeutil import fmt_logical, parse_iso

bp = Blueprint("forecasts", __name__)


def _is_monday_midnight(dt):
    return (
        dt.weekday() == 0
        and dt.hour == 0
        and dt.minute == 0
        and dt.second == 0
        and dt.microsecond == 0
    )


@bp.post("/jbp/plans/<plan_id>/forecasts")
def create_forecast(plan_id):
    _uid, role = authenticate()
    authorize(role, [ROLE_SUPPLY_CHAIN_PLANNER])
    data = V.body()
    V.check_undeclared(data, {"week_start", "baseline_cases"})
    week_start = V.as_dt(V.require(data, "week_start"), "week_start")
    baseline = V.as_int(V.require(data, "baseline_cases"), "baseline_cases")
    if baseline <= 0:
        err("ERR_VALIDATION", "baseline_cases must be > 0")
    plan = plan_or_404(plan_id)  # 6
    if plan["status"] != "ACTIVATED":
        err("ERR_PLAN_NOT_ACTIVATED", "forecast create requires an ACTIVATED plan")  # 12
    if not _is_monday_midnight(week_start):
        err("ERR_WEEK_NOT_ALIGNED", "week_start must be a Monday at 00:00:00Z")  # 28
    # supersession: the currently PUBLISHED forecast of the same (plan, week)
    # flips to SUPERSEDED; its commit_status is preserved untouched.
    for fc in STORE["forecasts"].values():
        if (
            fc["plan_id"] == plan_id
            and fc["pub_status"] == "PUBLISHED"
            and fc["_week_start_dt"] == week_start
        ):
            fc["pub_status"] = "SUPERSEDED"
            touch(fc)
    rec = {
        "id": new_id(),
        "plan_id": plan_id,
        "week_start": fmt_logical(week_start),
        "baseline_cases": baseline,
        "pub_status": "PUBLISHED",
        "commit_status": "UNCOMMITTED",
        "committed_cases": None,
        "committed_at": None,
        "_week_start_dt": week_start,
    }
    stamp_new(rec)
    STORE["forecasts"][rec["id"]] = rec
    return success(public(rec), 201)


@bp.get("/jbp/plans/<plan_id>/forecasts")
def list_forecasts(plan_id):
    uid, role = authenticate()
    authorize(role, ALL_ROLES)
    limit, offset = V.pagination()
    plan = STORE["plans"].get(plan_id)
    scope_plan(uid, role, plan)
    if plan is None:
        err("ERR_PLAN_NOT_FOUND", "plan not found")
    items = [f for f in by_seq(STORE["forecasts"].values()) if f["plan_id"] == plan_id]
    f_pub = request.args.get("pub_status")
    if f_pub is not None:
        items = [f for f in items if f["pub_status"] == f_pub]
    f_commit = request.args.get("commit_status")
    if f_commit is not None:
        items = [f for f in items if f["commit_status"] == f_commit]
    f_week = request.args.get("week_start")
    if f_week is not None:
        try:
            target = parse_iso(f_week)
        except (ValueError, OverflowError):
            target = None
        items = [f for f in items if target is not None and f["_week_start_dt"] == target]
    total = len(items)
    page = items[offset : offset + limit]
    return success_list([public(f) for f in page], limit, offset, total)


@bp.post("/jbp/forecasts/<forecast_id>/commit")
def commit_forecast(forecast_id):
    uid, role = authenticate()
    authorize(role, [ROLE_RETAILER_BUYER])
    fc = STORE["forecasts"].get(forecast_id)
    plan = STORE["plans"].get(fc["plan_id"]) if fc is not None else None
    scope_plan(uid, role, plan)  # 3
    data = V.body()
    V.check_undeclared(data, {"committed_cases"})
    committed = V.as_int(V.require(data, "committed_cases"), "committed_cases")
    if committed <= 0:
        err("ERR_VALIDATION", "committed_cases must be > 0")
    if fc is None:
        err("ERR_RESOURCE_NOT_FOUND", "forecast not found")  # 6
    # priority 16: both axes must be PUBLISHED and UNCOMMITTED
    if fc["pub_status"] != "PUBLISHED" or fc["commit_status"] != "UNCOMMITTED":
        err("ERR_FORECAST_NOT_PUBLISHED", "forecast is not PUBLISHED and UNCOMMITTED")
    fc["commit_status"] = "COMMITTED"
    fc["committed_cases"] = committed
    fc["committed_at"] = fmt_logical(clock.now())
    touch(fc)
    return success(public(fc))
