"""ComplianceIncidents (PRD section 3.5).

Resolving the last OPEN incident on the reservoir returns its posture to
NORMAL and unflags every FLAGGED delivery order (fulfillment untouched).
"""
from flask import Blueprint, request

import calc
from auth import ALL_ROLES, authenticate
from envelope import list_response, success
from errors import ApiError, not_found
from serial import incident_view
from store import DB, touch
from validate import as_enum, get_body, required

bp = Blueprint("compliance_incidents", __name__)

RESOLUTIONS = ("FLOW_RESTORED", "VARIANCE_GRANTED")


@bp.get("/water/compliance-incidents")
def list_incidents():
    authenticate(ALL_ROLES)
    filters = {
        "reservoir_id": request.args.get("reservoir_id"),
        "constraint_id": request.args.get("constraint_id"),
        "release_order_id": request.args.get("release_order_id"),
        "status": request.args.get("status"),
    }
    return list_response(list(DB["incidents"].values()), incident_view, filters)


@bp.get("/water/compliance-incidents/<string:incident_id>")
def get_incident(incident_id):
    authenticate(ALL_ROLES)
    incident = DB["incidents"].get(incident_id)
    if incident is None:
        not_found("ComplianceIncident")
    return success(incident_view(incident))


@bp.post("/water/compliance-incidents/<string:incident_id>/resolve")
def resolve_incident(incident_id):
    authenticate(["EnvironmentalOfficer"])
    body = get_body()
    resolution = as_enum(required(body, "resolution"), "resolution", RESOLUTIONS)
    incident = DB["incidents"].get(incident_id)
    if incident is None:
        not_found("ComplianceIncident")
    if incident["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "only an OPEN incident can be resolved")
    incident["status"] = "RESOLVED"
    incident["resolution"] = resolution
    touch(incident)
    # last-open resolution restores the reservoir and unflags delivery orders
    if calc.open_incident_count(incident["reservoir_id"]) == 0:
        reservoir = DB["reservoirs"].get(incident["reservoir_id"])
        if reservoir is not None:
            touch(reservoir)
        for order in DB["delivery_orders"].values():
            if order["compliance_status"] == "FLAGGED":
                order["compliance_status"] = "CLEARED"
                touch(order)
    return success(incident_view(incident), 200)
