"""Show routes."""

from datetime import timedelta

from flask import Blueprint, request

from db import DB
from common import base_resource, touch, paginate, parse_dt
from middleware import require_role
from errors import (not_found, invalid_state, show_conflict, stale_version,
                    no_approved_asset, tech_not_ready)
from response import success_object, success_list
import calc
import services

bp = Blueprint("shows", __name__)


def show_view(s):
    return dict(s)


def _reserved_window(show):
    return calc.show_window(show)


def _check_show_conflict(show, exclude_id=None):
    start, end = _reserved_window(show)
    for other in DB.shows.values():
        if other["id"] == (exclude_id or show["id"]):
            continue
        if other["status"] == "CANCELLED":
            continue
        o_start, o_end = _reserved_window(other)
        if calc.windows_overlap(start, end, o_start, o_end):
            raise show_conflict()


def _tech_readiness_now():
    degraded = any(s["status"] in ("DEGRADED", "OFFLINE") for s in DB.venue_systems.values())
    return "DEGRADED" if degraded else "READY"


@bp.post("/venue/shows")
def create_show():
    require_role("VenueScheduler")
    body = request.get_json(silent=True) or {}
    prod = DB.productions.get(body.get("production_id"))
    if not prod:
        raise not_found("production_id does not exist")
    s = base_resource()
    s.update({
        "production_id": body.get("production_id"),
        "show_format": body.get("show_format"),
        "start_time": body.get("start_time"),
        "length_minutes": body.get("length_minutes"),
        "peak_rush_minutes": body.get("peak_rush_minutes", 0),
        "rehearsal_minutes": 0,
        "changeover_minutes": 0,
        "tech_readiness": _tech_readiness_now(),
        "status": "TENTATIVE",
        "utilization_at_lock": 0,
        "haptic_surcharge_cents_at_lock": 0,
        "settlement_snapshot_id": None,
    })
    DB.shows[s["id"]] = s
    return success_object(show_view(s), 201)


@bp.get("/venue/shows")
def list_shows():
    require_role("VenueScheduler", "ProductionDirector", "BoxOfficeAgent")
    items = sorted(DB.shows.values(), key=lambda x: x["created_at"])
    pid = request.args.get("production_id")
    status = request.args.get("status")
    if pid:
        items = [s for s in items if s["production_id"] == pid]
    if status:
        items = [s for s in items if s["status"] == status]
    page, limit, offset, total = paginate([show_view(s) for s in items], request.args)
    return success_list(page, limit, offset, total)


@bp.get("/venue/shows/<sid>")
def get_show(sid):
    require_role("VenueScheduler", "ProductionDirector", "BoxOfficeAgent", "Guest")
    s = DB.shows.get(sid)
    if not s:
        raise not_found()
    return success_object(show_view(s))


@bp.post("/venue/shows/<sid>/schedule-rehearsal")
def schedule_rehearsal(sid):
    require_role("VenueScheduler")
    s = DB.shows.get(sid)
    if not s:
        raise not_found()
    if s["status"] != "TENTATIVE":
        raise invalid_state()
    prod = DB.productions.get(s["production_id"])
    if not prod or prod["status"] != "ACTIVE":
        raise invalid_state("Production must be ACTIVE")
    s["rehearsal_minutes"] = calc.REHEARSAL_MIN
    s["changeover_minutes"] = calc.compute_changeover_minutes(s)
    _check_show_conflict(s)
    s["status"] = "REHEARSAL"
    touch(s)
    return success_object(show_view(s))


@bp.post("/venue/shows/<sid>/confirm")
def confirm_show(sid):
    require_role("VenueScheduler")
    s = DB.shows.get(sid)
    if not s:
        raise not_found()
    if s["status"] != "REHEARSAL":
        raise invalid_state()
    prod = DB.productions.get(s["production_id"])
    if not prod or prod["status"] != "ACTIVE":
        raise invalid_state("Production must be ACTIVE")
    has_approved = any(
        a["production_id"] == prod["id"] and a["status"] == "APPROVED"
        for a in DB.assets.values()
    )
    if not has_approved:
        raise no_approved_asset()
    if _tech_readiness_now() != "READY":
        raise tech_not_ready()
    body = request.get_json(silent=True) or {}
    expected = body.get("expected_production_version")
    if expected is not None and expected != prod["version"]:
        raise stale_version()
    s["status"] = "CONFIRMED"
    s["utilization_at_lock"] = 0
    s["haptic_surcharge_cents_at_lock"] = 0
    touch(s)
    return success_object(show_view(s))


@bp.post("/venue/shows/<sid>/complete")
def complete_show(sid):
    require_role("VenueScheduler")
    s = DB.shows.get(sid)
    if not s:
        raise not_found()
    if s["status"] != "CONFIRMED":
        raise invalid_state()
    end = parse_dt(s["start_time"]) + timedelta(minutes=s["length_minutes"])
    if DB.clock < end:
        raise invalid_state("Show has not finished yet")
    services.complete_show(s)
    return success_object(show_view(s))


@bp.post("/venue/shows/<sid>/cancel")
def cancel_show_route(sid):
    require_role("VenueScheduler", "ProductionDirector")
    s = DB.shows.get(sid)
    if not s:
        raise not_found()
    if s["status"] not in ("TENTATIVE", "REHEARSAL", "CONFIRMED"):
        raise invalid_state()
    services.cancel_show(s)
    return success_object(show_view(s))
