"""Clock + capacity-week routes."""
from flask import Blueprint, request

import db
import errors
import helpers
import response
from services import calc

bp = Blueprint("clock_capacity", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    response.require_role("OpsAdmin")
    body = request.get_json(silent=True) or {}
    to = body.get("to_iso8601")
    if not to or not isinstance(to, str):
        raise errors.err_invalid_request("to_iso8601 required")
    dt = helpers.parse_iso(to)
    db.clock_set(dt)
    return response.ok({"current_utc": helpers.stamp()})


@bp.post("/capacity-weeks")
def create_capacity_week():
    response.require_role("MillPlanner")
    body = request.get_json(silent=True) or {}
    week = {
        "id": helpers.new_id(),
        "mill_code": helpers.req_str(body, "mill_code"),
        "week_start_date": helpers.req_str(body, "week_start_date"),
        "total_capacity_mbf": helpers.req_int(body, "total_capacity_mbf", minimum=1),
        "internal_alloc_mbf": 0,
        "market_alloc_mbf": 0,
        "committed_internal_mbf": 0,
        "committed_market_mbf": 0,
        "internal_grants": [],
        "fill_rate_pct": 0,
        "week_status": "OPEN",
        "created_at": helpers.stamp(),
        "updated_at": helpers.stamp(),
        "version": 1,
    }
    db.mill_capacity_weeks[week["id"]] = week
    return response.ok(week, status=201)


@bp.post("/capacity-weeks/<capacity_week_id>/allocate")
def allocate_capacity_week(capacity_week_id):
    response.require_role("MillPlanner")
    week = helpers.get_or_404(db.mill_capacity_weeks, capacity_week_id)
    body = request.get_json(silent=True) or {}
    internal = helpers.req_int(body, "internal_alloc_mbf", minimum=0)
    market = helpers.req_int(body, "market_alloc_mbf", minimum=0)
    expected = body.get("expected_capacity_week_version")
    if expected is not None and expected != week["version"]:
        raise errors.err_stale_version()
    if week["week_status"] != "OPEN":
        raise errors.err_invalid_state("Week is not OPEN")
    if internal + market > week["total_capacity_mbf"]:
        raise errors.err_capacity_exceeded()
    week["internal_alloc_mbf"] = internal
    week["market_alloc_mbf"] = market
    week["version"] += 1
    week["updated_at"] = helpers.stamp()
    return response.ok(week)


@bp.post("/capacity-weeks/<capacity_week_id>/close")
def close_capacity_week(capacity_week_id):
    response.require_role("MillPlanner")
    week = helpers.get_or_404(db.mill_capacity_weeks, capacity_week_id)
    if week["week_status"] != "OPEN":
        raise errors.err_invalid_state("Week is not OPEN")
    calc.capacity_close_waterfall(week)
    week["week_status"] = "CLOSED"
    week["version"] += 1
    week["updated_at"] = helpers.stamp()
    return response.ok(week)
