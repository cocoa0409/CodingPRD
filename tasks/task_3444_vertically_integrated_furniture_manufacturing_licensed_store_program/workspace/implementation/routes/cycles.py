"""Allocation cycles (PRD §3.4): week exclusivity, waterfall run, close+score."""
from datetime import timedelta

from flask import Blueprint, request

from db import store
from errors import err
from middleware import auth, require_role
from routes.factories import get_factory
from services.engine import close_cycle, run_waterfall
from util import (
    get_body, new_record, now_dt, ok_list, ok_object, paginate, req_dt, req_str,
    serialize, touch,
)

bp = Blueprint("cycles", __name__)

_WEEK = timedelta(days=7)


def get_cycle(cid):
    c = store.cycles.get(cid)
    if c is None:
        err("ERR_CYCLE_NOT_FOUND", "unknown allocation cycle id")
    return c


@bp.route("/api/allocation-cycles", methods=["POST"])
def create_cycle():
    _uid, role = auth()
    data = get_body()
    factory_id = req_str(data, "factory_id")
    week_start = req_dt(data, "week_start")
    if (week_start.hour, week_start.minute, week_start.second, week_start.microsecond) != (0, 0, 0, 0):
        err("ERR_VALIDATION", "week_start must be midnight-aligned (00:00:00Z)")
    require_role(role, ["ProductionPlanner"])
    factory = get_factory(factory_id)
    if factory["status"] == "OFFLINE":
        err("ERR_FACTORY_OFFLINE", "cannot open a cycle against an OFFLINE factory")
    week_end = week_start + _WEEK
    for other in store.cycles.values():
        if other["factory_id"] != factory_id:
            continue
        o_start, o_end = other["week_start"], other["week_start"] + _WEEK
        # Strict half-open week exclusion per factory; exact adjacency allowed.
        if week_start < o_end and o_start < week_end:
            err("ERR_CYCLE_WEEK_OVERLAP", "week window overlaps another cycle of this factory")
    if factory["status"] == "CONSTRAINED":
        capacity = factory["weekly_capacity_units"] // 2  # floor(weekly * 0.5)
    else:
        capacity = factory["weekly_capacity_units"]
    rec = new_record()
    rec.update({
        "factory_id": factory_id,
        "week_start": week_start,
        "capacity_units": capacity,
        "status": "OPEN",
        "licensee_reserved_units": 0,
        "wholesale_reserved_units": 0,
        "available_units": capacity,
        "run_at": None,
        "closed_at": None,
    })
    store.cycles[rec["id"]] = rec
    return ok_object(serialize(rec), 201)


@bp.route("/api/allocation-cycles/<cid>", methods=["GET"])
def fetch_cycle(cid):
    auth()
    return ok_object(serialize(get_cycle(cid)), 200)


@bp.route("/api/allocation-cycles", methods=["GET"])
def list_cycles():
    auth()
    factory_id = request.args.get("factory_id")
    status = request.args.get("status")
    items = list(store.cycles.values())
    if factory_id is not None:
        items = [c for c in items if c["factory_id"] == factory_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    page, pagination = paginate(items)
    return ok_list([serialize(c) for c in page], pagination)


@bp.route("/api/allocation-cycles/<cid>/run-allocation", methods=["POST"])
def run_allocation(cid):
    _uid, role = auth()
    get_body()
    require_role(role, ["ProductionPlanner"])
    cycle = get_cycle(cid)
    if cycle["status"] != "OPEN":
        err("ERR_INVALID_TRANSITION", "run-allocation requires an OPEN cycle")
    bumped = set()
    cycle["status"] = "ALLOCATED"
    cycle["run_at"] = now_dt()
    touch(cycle, bumped)
    run_waterfall(cycle, bumped)
    return ok_object(serialize(cycle), 200)


@bp.route("/api/allocation-cycles/<cid>/close", methods=["POST"])
def close(cid):
    _uid, role = auth()
    get_body()
    require_role(role, ["ProductionPlanner"])
    cycle = get_cycle(cid)
    if cycle["status"] != "ALLOCATED":
        err("ERR_INVALID_TRANSITION", "close requires an ALLOCATED cycle")
    bumped = set()
    close_cycle(cycle, bumped)
    return ok_object(serialize(cycle), 200)
