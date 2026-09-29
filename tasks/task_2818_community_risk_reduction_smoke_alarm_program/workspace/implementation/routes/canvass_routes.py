"""Canvass routes: planning, publishing and closure (PRD 3.4)."""

from flask import Blueprint

import db
import domain
import response
import util
import validation
from db import store, touch
from errors import ApiError
from middleware import endpoint
from services import visits as visit_service
from services import zones as zone_service

bp = Blueprint("canvass_routes", __name__)

READ_ROLES = ("ProgramAdmin", "CanvassCoordinator", "CrrTechnician")

TARGETABLE_STATUSES = ("ASSESSED", "TARGETED", "SERVICE_ACTIVE")


def load_route(route_id):
    route = store.routes.get(route_id)
    if route is None:
        raise ApiError("ERR_ROUTE_NOT_FOUND")
    return route


@bp.post("/crr/routes")
@endpoint("CanvassCoordinator")
def create_route():
    body = validation.json_body()
    validation.reject_unexpected_version(body)
    zone_id = validation.req_str(body, "zone_id")
    crew_id = validation.req_str(body, "crew_id")
    service_date = validation.req_date(body, "service_date")
    window_start_utc = validation.req_instant(body, "window_start_utc")
    window_end_utc = validation.req_instant(body, "window_end_utc")
    planned_slots = validation.req_int(body, "planned_slots", minimum=1)

    # PRD 3.4: both bounds fall on the service date in UTC, start strictly
    # before end; either violation is a schema failure.
    if window_start_utc.date() != service_date or window_end_utc.date() != service_date:
        validation.bad("Route window bounds must fall on service_date in UTC.")
    if window_start_utc >= window_end_utc:
        validation.bad("window_start_utc must be strictly earlier than window_end_utc.")

    zone = store.zones.get(zone_id)
    if zone is None:
        raise ApiError("ERR_ZONE_NOT_FOUND")
    crew = store.crews.get(crew_id)
    if crew is None:
        raise ApiError("ERR_CREW_NOT_FOUND")

    if (
        zone["zone_kind"] != "LEAF"
        or zone["assessment_status"] not in TARGETABLE_STATUSES
        or zone["risk_tier"] not in ("TIER_1", "TIER_2")
    ):
        raise ApiError("ERR_ZONE_NOT_TARGETABLE")

    first_route_for_zone = not any(
        r["zone_id"] == zone_id for r in store.routes.values()
    )

    row = db.stamp_new({})
    route = {
        "id": row["id"],
        "zone_id": zone_id,
        "crew_id": crew_id,
        "service_date": service_date,
        "window_start_utc": window_start_utc,
        "window_end_utc": window_end_utc,
        "planned_slots": planned_slots,
        "booked_slot_count": 0,
        "status": "PLANNED",
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
        "_seq": row["_seq"],
    }
    store.routes[route["id"]] = route

    if first_route_for_zone and zone["assessment_status"] == "ASSESSED":
        zone["assessment_status"] = "TARGETED"
        touch(zone)
    return response.ok_row(route, 201)


@bp.get("/crr/routes")
@endpoint(*READ_ROLES)
def list_routes():
    limit, offset = validation.pagination()
    rows = db.by_created_at(list(store.routes.values()))
    for name in ("zone_id", "crew_id", "status"):
        wanted = validation.filter_value(name)
        if wanted is not None:
            rows = [r for r in rows if r[name] == wanted]
    wanted_date = validation.filter_value("service_date")
    if wanted_date is not None:
        rows = [r for r in rows if util.fmt_date(r["service_date"]) == wanted_date]
    page, total = validation.paginate(rows, limit, offset)
    return response.ok_list(page, limit, offset, total)


@bp.get("/crr/routes/<route_id>")
@endpoint(*READ_ROLES)
def get_route(route_id):
    return response.ok_row(load_route(route_id))


@bp.post("/crr/routes/<route_id>/publish")
@endpoint("CanvassCoordinator")
def publish_route(route_id):
    route = load_route(route_id)
    body = validation.json_body()
    validation.reject_unexpected_version(body)

    if route["status"] != "PLANNED":
        raise ApiError("ERR_ROUTE_NOT_OPEN")

    zone = store.zones.get(route["zone_id"])
    # PRD 3.4: already-closed routes still consume the day's cap.
    consumed = 0
    for other in store.routes.values():
        if other["id"] == route["id"]:
            continue
        if other["zone_id"] != route["zone_id"]:
            continue
        if other["service_date"] != route["service_date"]:
            continue
        if other["status"] not in ("PUBLISHED", "IN_PROGRESS", "CLOSED"):
            continue
        consumed += other["planned_slots"]
    if zone is not None and consumed + route["planned_slots"] > zone["daily_visit_cap"]:
        raise ApiError("ERR_ZONE_DAILY_CAP_EXCEEDED")

    route["status"] = "PUBLISHED"
    touch(route)
    if zone is not None and zone["assessment_status"] == "ASSESSED":
        zone["assessment_status"] = "TARGETED"
        touch(zone)
    return response.ok_row(route)


@bp.post("/crr/routes/<route_id>/close")
@endpoint("CanvassCoordinator")
def close_route(route_id):
    route = load_route(route_id)
    body = validation.json_body()
    validation.reject_unexpected_version(body)
    # PRD 3.4: closure accepts an optional closure_note; the note is not a
    # declared field of the route resource, so it is validated and not stored.
    validation.opt_str(body, "closure_note")

    if route["status"] not in domain.ROUTE_OPEN_STATUSES:
        raise ApiError("ERR_ROUTE_NOT_OPEN")

    route["status"] = "CLOSED"
    touch(route)

    # PRD 3.4 conditional cascade: only SCHEDULED and IN_PROGRESS visits move.
    for visit in visit_service.visits_of_route(route["id"]):
        if visit_service.project_status(visit) in ("SCHEDULED", "IN_PROGRESS"):
            visit_service.cancel_for_route_closure(visit)
    return response.ok_row(route)
