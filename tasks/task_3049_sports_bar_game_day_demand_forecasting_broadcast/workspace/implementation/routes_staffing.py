"""Staffing plans and shifts."""
from flask import Blueprint, request

import db
import errors
from errors import invalid_request
from util import (success, list_response, auth, body, require, req_int,
                  req_str, parse_dt, now_ts, bump)
import services
from util import serialize, serialize_list

bp = Blueprint("staffing", __name__)

READ_STAFFING = ["PlatformAdmin", "VenueManager"]


def get_plan_or_404(plan_id):
    p = db.staffing_plans.get(plan_id)
    if p is None:
        raise errors.not_found()
    return p


@bp.post("/api/venues/<venue_id>/staffing-plans")
def create_plan(venue_id):
    auth(["VenueManager"])
    if venue_id not in db.venues:
        raise errors.not_found()
    data = body()
    name = req_str(data, "name")
    ts = now_ts()
    plan = {
        "id": services.new_id(), "venue_id": venue_id, "name": name,
        "status": "DRAFT", "foh_required": 0, "boh_required": 0,
        "created_at": ts, "updated_at": ts, "version": 1,
    }
    db.staffing_plans[plan["id"]] = plan
    return success(serialize(plan), code=201)


@bp.get("/api/staffing-plans/<plan_id>")
def get_plan(plan_id):
    auth(READ_STAFFING)
    return success(serialize(get_plan_or_404(plan_id)))


@bp.get("/api/venues/<venue_id>/staffing-plans")
def list_venue_plans(venue_id):
    auth(READ_STAFFING)
    if venue_id not in db.venues:
        raise errors.not_found()
    items = sorted([p for p in db.staffing_plans.values()
                    if p["venue_id"] == venue_id],
                   key=lambda p: p["created_at"])
    status = request.args.get("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    return list_response(serialize_list(items))


@bp.post("/api/staffing-plans/<plan_id>/shifts")
def add_shift(plan_id):
    auth(["VenueManager"])
    plan = get_plan_or_404(plan_id)
    if plan["status"] != "DRAFT":
        raise errors.invalid_state("Plan is not DRAFT")
    data = body()
    role = require(data, "role")
    if role not in ("FOH", "BOH"):
        raise invalid_request("role must be FOH or BOH")
    start_time = parse_dt(require(data, "start_time"), "start_time")
    end_time = parse_dt(require(data, "end_time"), "end_time")
    if end_time <= start_time:
        raise errors.shift_window_invalid("end_time must be after start_time")
    headcount = req_int(data, "headcount", minimum=0)
    expected_covers = req_int(data, "expected_covers", minimum=0)
    shift = {
        "id": services.new_id(), "plan_id": plan_id, "role": role,
        "start_time": start_time, "end_time": end_time,
        "headcount": headcount, "expected_covers": expected_covers,
        "created_at": now_ts(),
    }
    db.shifts[shift["id"]] = shift
    services.recompute_staffing(plan)
    return success(serialize(shift), code=201)


@bp.get("/api/staffing-plans/<plan_id>/shifts")
def list_plan_shifts(plan_id):
    auth(READ_STAFFING)
    get_plan_or_404(plan_id)
    items = sorted([s for s in db.shifts.values() if s["plan_id"] == plan_id],
                   key=lambda s: s["created_at"])
    return list_response(serialize_list(items))


@bp.get("/api/shifts/<shift_id>")
def get_shift(shift_id):
    auth(READ_STAFFING)
    s = db.shifts.get(shift_id)
    if s is None:
        raise errors.not_found()
    return success(serialize(s))


@bp.post("/api/staffing-plans/<plan_id>/publish")
def publish_plan(plan_id):
    auth(["VenueManager"])
    plan = get_plan_or_404(plan_id)
    if plan["status"] != "DRAFT":
        raise errors.invalid_state("Plan is not DRAFT")
    plan_shifts = [s for s in db.shifts.values() if s["plan_id"] == plan_id]
    if not plan_shifts:
        raise errors.invalid_state("Plan must have at least one shift")
    services.recompute_staffing(plan)
    if plan["foh_required"] <= 0 or plan["boh_required"] <= 0:
        raise errors.invalid_state("foh_required and boh_required must be > 0")
    plan["status"] = "PUBLISHED"
    bump(plan)
    return success(serialize(plan))


@bp.post("/api/staffing-plans/<plan_id>/revert")
def revert_plan(plan_id):
    auth(["VenueManager"])
    plan = get_plan_or_404(plan_id)
    if plan["status"] != "PUBLISHED":
        raise errors.invalid_state("Plan is not PUBLISHED")
    now = db.now()
    for s in db.shifts.values():
        if s["plan_id"] == plan_id and s["start_time"] <= now:
            raise errors.invalid_state("A shift has already started")
    plan["status"] = "DRAFT"
    bump(plan)
    return success(serialize(plan))


@bp.post("/api/staffing-plans/<plan_id>/lock")
def lock_plan(plan_id):
    auth(["VenueManager"])
    plan = get_plan_or_404(plan_id)
    if plan["status"] != "PUBLISHED":
        raise errors.invalid_state("Plan is not PUBLISHED")
    plan["status"] = "LOCKED"
    bump(plan)
    return success(serialize(plan))
