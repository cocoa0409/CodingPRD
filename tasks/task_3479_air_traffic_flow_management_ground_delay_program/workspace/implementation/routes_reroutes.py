"""RerouteAssignment endpoints (PRD 3.8): assign under an ACTIVE REROUTE
initiative, list with filters, fetch."""

from flask import Blueprint, request

from constants import ROLE_FLOW_MANAGER, ROLES
from errors import ApiError
from serialize import serialize_reroute
from storage import DB, create_record
from util import body_json, paginate, req_str, success_object
from validation import (
    auth_context,
    get_facility,
    get_flight,
    get_reroute,
    get_tmi,
    require_roles,
    tmi_require_active,
)

bp = Blueprint("reroutes", __name__)


@bp.route("/atfm/tmis/<tmi_id>/reroute-assignments", methods=["POST"])
def create_reroute_assignment(tmi_id):
    auth_context()
    require_roles(ROLE_FLOW_MANAGER)
    tmi = get_tmi(tmi_id)
    body = body_json()
    flight_id = req_str(body, "flight_id")
    via_sector_id = req_str(body, "via_sector_id")
    assigned_route = req_str(body, "assigned_route")
    flight = get_flight(flight_id)
    sector = get_facility(via_sector_id)
    # Priority 5: the initiative must be an ACTIVE REROUTE, the flight
    # UNCONTROLLED, and the sector not in OUTAGE.
    tmi_require_active(tmi)
    if tmi["tmi_type"] != "REROUTE":
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "reroute assignments require a REROUTE initiative",
        )
    if flight["control_status"] != "UNCONTROLLED":
        raise ApiError(
            "ERR_INVALID_STATE", "only an UNCONTROLLED flight can be rerouted"
        )
    if sector["status"] == "OUTAGE":
        raise ApiError(
            "ERR_FACILITY_NOT_OPERATIONAL",
            "sector %s is in OUTAGE" % sector["id"],
        )
    bucket = flight["estimated_arrival"].replace(minute=0, second=0, microsecond=0)
    # Priority 7: per-(sector, hourly bucket) capacity. Boundary is exact:
    # load == rate - 1 accepts, load == rate rejects.
    load = sum(
        1
        for r in DB["reroutes"].values()
        if r["via_sector_id"] == sector["id"] and r["hourly_bucket"] == bucket
    )
    if load >= sector["base_acceptance_rate"]:
        raise ApiError(
            "ERR_SECTOR_CAPACITY_EXCEEDED",
            "sector hourly capacity %d reached for this bucket"
            % sector["base_acceptance_rate"],
        )
    # Priority 16: the via sector must be an EN_ROUTE_SECTOR.
    if sector["facility_type"] != "EN_ROUTE_SECTOR":
        raise ApiError(
            "ERR_REROUTE_SECTOR_TYPE",
            "via_sector_id must reference an EN_ROUTE_SECTOR facility",
        )
    rec = create_record(
        "reroutes",
        {
            "tmi_id": tmi["id"],
            "flight_id": flight["id"],
            "via_sector_id": sector["id"],
            "assigned_route": assigned_route,
            "hourly_bucket": bucket,
        },
    )
    return success_object(serialize_reroute(rec), 201)


@bp.route("/atfm/reroute-assignments", methods=["GET"])
def list_reroute_assignments():
    auth_context()
    require_roles(*ROLES)
    tmi_filter = request.args.get("tmi_id")
    flight_filter = request.args.get("flight_id")
    sector_filter = request.args.get("via_sector_id")
    rows = [
        r
        for r in DB["reroutes"].values()
        if (tmi_filter is None or r["tmi_id"] == tmi_filter)
        and (flight_filter is None or r["flight_id"] == flight_filter)
        and (sector_filter is None or r["via_sector_id"] == sector_filter)
    ]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return paginate([serialize_reroute(r) for r in rows])


@bp.route("/atfm/reroute-assignments/<assignment_id>", methods=["GET"])
def fetch_reroute_assignment(assignment_id):
    auth_context()
    require_roles(*ROLES)
    return success_object(serialize_reroute(get_reroute(assignment_id)))
