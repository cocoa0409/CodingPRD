"""Aircraft: register, list, get, retire."""

from flask import Blueprint, request

import db
from common import (
    new_entity,
    get_or_404,
    body,
    require_field,
    require_positive_int,
    touch,
)
from errors import ApiError
from middleware import require_role, require_any_authenticated
from response import ok, paginate

bp = Blueprint("aircraft", __name__)


def _get_aircraft_or_404(aircraft_id):
    return get_or_404(db.aircraft, aircraft_id, "ERR_AIRCRAFT_NOT_FOUND", "Aircraft")


@bp.route("/aircraft", methods=["POST"])
def create_aircraft():
    require_role("OpsController")
    data = body()
    tail = require_field(data, "tail_number", str)
    seats = require_positive_int(data, "seat_capacity", minimum=1)
    daily_cap = require_positive_int(data, "daily_utilization_cap_minutes", minimum=0)
    peak_cap = require_positive_int(data, "peak_day_cap_minutes", minimum=0)
    if peak_cap < daily_cap:
        raise ApiError(
            "ERR_VALIDATION",
            "peak_day_cap_minutes must be >= daily_utilization_cap_minutes",
            422,
        )
    ent = new_entity(
        {
            "tail_number": tail,
            "seat_capacity": seats,
            "daily_utilization_cap_minutes": daily_cap,
            "peak_day_cap_minutes": peak_cap,
            "aircraft_status": "IN_SERVICE",
        }
    )
    db.aircraft[ent["id"]] = ent
    return ok(ent, 201)


@bp.route("/aircraft", methods=["GET"])
def list_aircraft():
    require_any_authenticated()
    items = list(db.aircraft.values())
    status = request.args.get("aircraft_status")
    if status:
        items = [a for a in items if a["aircraft_status"] == status]
    items.sort(key=lambda a: (a["created_at"], a["id"]))
    page, meta = paginate(items)
    return ok(page, 200, pagination=meta)


@bp.route("/aircraft/<aircraft_id>", methods=["GET"])
def get_aircraft(aircraft_id):
    require_any_authenticated()
    ent = _get_aircraft_or_404(aircraft_id)
    return ok(ent)


@bp.route("/aircraft/<aircraft_id>/retire", methods=["POST"])
def retire_aircraft(aircraft_id):
    require_role("OpsController")
    ac = _get_aircraft_or_404(aircraft_id)
    if ac["aircraft_status"] != "IN_SERVICE":
        raise ApiError(
            "ERR_AIRCRAFT_HAS_LIVE_FLIGHTS",
            "Retire requires IN_SERVICE aircraft",
            409,
        )
    live = [
        f
        for f in db.flight_instances.values()
        if f["aircraft_id"] == aircraft_id and f["flight_status"] == "SCHEDULED"
    ]
    if live:
        raise ApiError(
            "ERR_AIRCRAFT_HAS_LIVE_FLIGHTS",
            "Retire blocked: SCHEDULED flights reference this tail",
            409,
        )
    ac["aircraft_status"] = "OUT_OF_SERVICE"
    touch(ac)
    return ok(ac)
