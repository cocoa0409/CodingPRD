"""Venue system and maintenance window routes."""

from datetime import timedelta

from flask import Blueprint, request

from db import DB
from common import base_resource, touch, paginate, parse_dt
from middleware import require_role
from errors import not_found, invalid_state, maintenance_conflict
from response import success_object, success_list
import calc
import services

bp = Blueprint("venue_systems", __name__)


def system_view(s):
    return dict(s)


def window_view(w):
    return dict(w)


@bp.post("/venue-systems")
def create_system():
    require_role("VenueOpsEngineer")
    body = request.get_json(silent=True) or {}
    s = base_resource()
    s.update({
        "name": body.get("name"),
        "kind": body.get("kind"),
        "status": "ONLINE",
        "consecutive_failed_windows": 0,
    })
    DB.venue_systems[s["id"]] = s
    return success_object(system_view(s), 201)


@bp.get("/venue-systems")
def list_systems():
    require_role("VenueOpsEngineer", "VenueScheduler", "ProductionDirector")
    items = sorted(DB.venue_systems.values(), key=lambda x: x["created_at"])
    kind = request.args.get("kind")
    status = request.args.get("status")
    if kind:
        items = [s for s in items if s["kind"] == kind]
    if status:
        items = [s for s in items if s["status"] == status]
    page, limit, offset, total = paginate([system_view(s) for s in items], request.args)
    return success_list(page, limit, offset, total)


@bp.get("/venue-systems/<sid>")
def get_system(sid):
    require_role("VenueOpsEngineer", "VenueScheduler")
    s = DB.venue_systems.get(sid)
    if not s:
        raise not_found()
    return success_object(system_view(s))


@bp.post("/venue-systems/<sid>/repair")
def repair_system(sid):
    require_role("VenueOpsEngineer")
    s = DB.venue_systems.get(sid)
    if not s:
        raise not_found()
    if s["status"] != "DEGRADED":
        raise invalid_state()
    s["status"] = "ONLINE"
    s["consecutive_failed_windows"] = 0
    touch(s)
    services.recompute_tech_readiness()
    return success_object(system_view(s))


@bp.post("/venue/maintenance-windows")
def create_window():
    require_role("VenueOpsEngineer")
    body = request.get_json(silent=True) or {}
    system = DB.venue_systems.get(body.get("venue_system_id"))
    if not system:
        raise not_found("venue_system_id does not exist")
    start = parse_dt(body.get("start_time"))
    end = parse_dt(body.get("end_time"))
    buffer_minutes = int(body.get("buffer_minutes", 0))
    if end <= start:
        raise maintenance_conflict("end_time must be > start_time")
    window_end_with_buffer = end + timedelta(minutes=buffer_minutes)
    for show in DB.shows.values():
        if show["status"] == "CANCELLED":
            continue
        s_start, s_end = calc.show_window(show)
        if calc.windows_overlap(start, window_end_with_buffer, s_start, s_end):
            raise maintenance_conflict("Window overlaps a show reserved window")
    w = base_resource()
    w.update({
        "venue_system_id": body.get("venue_system_id"),
        "start_time": body.get("start_time"),
        "end_time": body.get("end_time"),
        "buffer_minutes": buffer_minutes,
        "status": "SCHEDULED",
    })
    DB.maintenance_windows[w["id"]] = w
    return success_object(window_view(w), 201)


@bp.get("/venue/maintenance-windows")
def list_windows():
    require_role("VenueOpsEngineer", "VenueScheduler")
    items = sorted(DB.maintenance_windows.values(), key=lambda x: x["created_at"])
    vsid = request.args.get("venue_system_id")
    status = request.args.get("status")
    if vsid:
        items = [w for w in items if w["venue_system_id"] == vsid]
    if status:
        items = [w for w in items if w["status"] == status]
    page, limit, offset, total = paginate([window_view(w) for w in items], request.args)
    return success_list(page, limit, offset, total)


@bp.get("/venue/maintenance-windows/<wid>")
def get_window(wid):
    require_role("VenueOpsEngineer", "VenueScheduler")
    w = DB.maintenance_windows.get(wid)
    if not w:
        raise not_found()
    return success_object(window_view(w))


@bp.post("/venue/maintenance-windows/<wid>/complete")
def complete_window(wid):
    require_role("VenueOpsEngineer")
    w = DB.maintenance_windows.get(wid)
    if not w:
        raise not_found()
    if w["status"] != "ACTIVE":
        raise invalid_state()
    if DB.clock < parse_dt(w["end_time"]):
        raise invalid_state("Window end_time not reached")
    w["status"] = "COMPLETED"
    touch(w)
    system = DB.venue_systems.get(w["venue_system_id"])
    if system:
        system["consecutive_failed_windows"] = 0
        if system["status"] == "MAINTENANCE":
            system["status"] = "ONLINE"
        touch(system)
    services.recompute_tech_readiness()
    return success_object(window_view(w))


@bp.post("/venue/maintenance-windows/<wid>/fail")
def fail_window(wid):
    require_role("VenueOpsEngineer")
    w = DB.maintenance_windows.get(wid)
    if not w:
        raise not_found()
    if w["status"] != "ACTIVE":
        raise invalid_state()
    w["status"] = "FAILED"
    touch(w)
    system = DB.venue_systems.get(w["venue_system_id"])
    if system:
        system["consecutive_failed_windows"] += 1
        touch(system)
        services.system_health_cascade(system)
    return success_object(window_view(w))
