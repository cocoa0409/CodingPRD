"""Flight instances: list, get, assign-aircraft, mark-operated."""

from flask import Blueprint, request

import db
from common import (
    get_or_404,
    body,
    require_field,
    touch,
    logical_clock_date,
    parse_date,
)
from errors import ApiError
from middleware import require_role, require_any_authenticated
from response import ok, paginate

bp = Blueprint("flight_instances", __name__)


def _get_flight_or_404(flight_id):
    return get_or_404(
        db.flight_instances, flight_id, "ERR_FLIGHT_NOT_FOUND", "FlightInstance"
    )


@bp.route("/flight-instances", methods=["GET"])
def list_flights():
    require_any_authenticated()
    items = list(db.flight_instances.values())
    rid = request.args.get("route_id")
    if rid:
        items = [f for f in items if f["route_id"] == rid]
    pid = request.args.get("publication_id")
    if pid:
        items = [f for f in items if f["publication_id"] == pid]
    aid = request.args.get("aircraft_id")
    if aid:
        items = [f for f in items if f["aircraft_id"] == aid]
    did = request.args.get("cancelled_by_disruption_id")
    if did:
        items = [f for f in items if f["cancelled_by_disruption_id"] == did]
    status = request.args.get("flight_status")
    if status:
        items = [f for f in items if f["flight_status"] == status]
    fdate = request.args.get("flight_date")
    if fdate:
        items = [f for f in items if f["flight_date"] == fdate]
    items.sort(key=lambda f: (f["created_at"], f["id"]))
    page, meta = paginate(items)
    return ok(page, 200, pagination=meta)


@bp.route("/flight-instances/<flight_id>", methods=["GET"])
def get_flight(flight_id):
    require_any_authenticated()
    ent = _get_flight_or_404(flight_id)
    return ok(ent)


@bp.route("/flight-instances/<flight_id>/assign-aircraft", methods=["POST"])
def assign_aircraft(flight_id):
    require_role("OpsController")
    flight = _get_flight_or_404(flight_id)
    data = body()
    aircraft_id = require_field(data, "aircraft_id", str)
    ac = db.aircraft.get(aircraft_id)
    if ac is None:
        raise ApiError("ERR_AIRCRAFT_NOT_FOUND", "Aircraft id does not exist", 404)

    pub = db.schedule_publications.get(flight["publication_id"])
    block = pub["block_minutes"] if pub else 0

    day_minutes = 0
    for other in db.flight_instances.values():
        if (
            other["aircraft_id"] == aircraft_id
            and other["flight_status"] == "SCHEDULED"
            and other["flight_date"] == flight["flight_date"]
            and other["id"] != flight_id
        ):
            other_pub = db.schedule_publications.get(other["publication_id"])
            if other_pub:
                day_minutes += other_pub["block_minutes"]

    proposed = day_minutes + block
    cap = (
        ac["peak_day_cap_minutes"]
        if flight["is_peak_day"]
        else ac["daily_utilization_cap_minutes"]
    )
    if proposed > cap:
        raise ApiError(
            "ERR_UTILIZATION_CAP_EXCEEDED",
            "Daily block minutes would exceed the applicable (peak or non-peak) cap",
            409,
        )
    flight["aircraft_id"] = aircraft_id
    touch(flight)
    return ok(flight)


@bp.route("/flight-instances/<flight_id>/mark-operated", methods=["POST"])
def mark_operated(flight_id):
    require_role("OpsController")
    flight = _get_flight_or_404(flight_id)
    if flight["flight_status"] != "SCHEDULED":
        raise ApiError(
            "ERR_FLIGHT_NOT_SCHEDULED",
            "Operation requires SCHEDULED flight",
            409,
        )
    clock_date = logical_clock_date()
    if clock_date < parse_date(flight["flight_date"]):
        raise ApiError(
            "ERR_FLIGHT_NOT_SCHEDULED",
            "Logical clock has not reached the flight date",
            409,
        )
    flight["flight_status"] = "OPERATED"
    touch(flight)
    for booking in db.bookings.values():
        if (
            booking["flight_instance_id"] == flight_id
            and booking["booking_status"] == "STRANDED_REBOOKED"
        ):
            booking["booking_status"] = "CONFIRMED"
            touch(booking)
    return ok(flight)
