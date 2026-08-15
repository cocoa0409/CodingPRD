"""ChaseAssignment endpoints (PRD 3.6): assign, list, and the chase crew's
ASSIGNED → EN_ROUTE → AT_LANDING → RECOVERED → DEBRIEFED track."""
from flask import Blueprint

from db import db
from errors import raise_error, ERR_INVALID_REQUEST, ERR_INVALID_STATE
from middleware import authorized, ALL_READ_ROLES
from response import success_object, success_list
from services.core import new_record, touch, public_chase, sort_created
from validate import (
    get_body, req_str, req_int, req_number, require_path_resource, get_pagination,
)

bp = Blueprint("chase", __name__, url_prefix="/v1")


@bp.post("/flights/<flight_id>/chase-assignments")
def create_chase_assignment(flight_id):
    authorized(["OperationsManager"])
    flight = require_path_resource("flights", flight_id, "flight")
    body = get_body()
    rec = new_record("chase_assignments", {
        "flight_id": flight["id"],
        "crew_lead_name": req_str(body, "crew_lead_name"),
        "vehicle_id": req_str(body, "vehicle_id"),
        "crew_size": req_int(body, "crew_size", minimum=1),
        "status": "ASSIGNED",
        "landing_lat": None,
        "landing_lon": None,
    })
    return success_object(public_chase(rec), status=201)


@bp.get("/flights/<flight_id>/chase-assignments")
def list_chase_assignments(flight_id):
    authorized(ALL_READ_ROLES)
    require_path_resource("flights", flight_id, "flight")
    items = [a for a in db["chase_assignments"].values() if a["flight_id"] == flight_id]
    items = sort_created(items)
    total = len(items)
    limit, offset = get_pagination()
    page = items[offset:offset + limit]
    return success_list([public_chase(a) for a in page], total, limit, offset)


@bp.post("/chase-assignments/<assignment_id>/events")
def chase_events(assignment_id):
    authorized(["ChaseCrewLead"])
    rec = require_path_resource("chase_assignments", assignment_id, "chase assignment")
    body = get_body()
    event_type = req_str(body, "event_type")

    if event_type == "DISPATCH":
        if rec["status"] != "ASSIGNED":
            raise_error(ERR_INVALID_STATE, f"cannot DISPATCH from {rec['status']}")
        rec["status"] = "EN_ROUTE"
    elif event_type == "ARRIVE_AT_LANDING":
        lat = req_number(body, "landing_lat")
        lon = req_number(body, "landing_lon")
        if rec["status"] != "EN_ROUTE":
            raise_error(ERR_INVALID_STATE,
                        f"cannot ARRIVE_AT_LANDING from {rec['status']}")
        flight = db["flights"].get(rec["flight_id"])
        if flight is None or flight["status"] not in ("AIRBORNE", "LANDED"):
            raise_error(ERR_INVALID_STATE,
                        "arrival at landing requires the flight to be AIRBORNE or LANDED")
        rec["landing_lat"] = lat
        rec["landing_lon"] = lon
        rec["status"] = "AT_LANDING"
    elif event_type == "RECOVER":
        if rec["status"] != "AT_LANDING":
            raise_error(ERR_INVALID_STATE, f"cannot RECOVER from {rec['status']}")
        rec["status"] = "RECOVERED"
    elif event_type == "DEBRIEF":
        if rec["status"] != "RECOVERED":
            raise_error(ERR_INVALID_STATE, f"cannot DEBRIEF from {rec['status']}")
        rec["status"] = "DEBRIEFED"
    else:
        raise_error(ERR_INVALID_REQUEST, f"unknown event_type: {event_type}")
    touch(rec)
    return success_object(public_chase(rec))
