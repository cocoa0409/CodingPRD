"""WeatherBriefing endpoints (PRD 3.5): record dawn observations (assigned pilot,
flight in WEATHER_REVIEW); newer briefings supersede the prior RECORDED one."""
from flask import Blueprint

from db import db
from errors import (
    raise_error, ERR_INVALID_STATE, ERR_FLIGHT_NOT_ASSIGNED,
)
from middleware import authorized, ALL_READ_ROLES
from response import success_object, success_list
from services.core import new_record, public_briefing, sort_created
from util import CLOCK
from validate import (
    get_body, req_int, req_number, req_bool, require_path_resource, get_pagination,
)

bp = Blueprint("weather", __name__, url_prefix="/v1")


@bp.post("/flights/<flight_id>/weather-briefings")
def record_briefing(flight_id):
    caller = authorized(["Pilot"])
    flight = require_path_resource("flights", flight_id, "flight")
    body = get_body()
    surface = req_int(body, "surface_wind_kts", minimum=0)
    aloft = req_int(body, "aloft_wind_kts", minimum=0)
    visibility = req_number(body, "visibility_mi", minimum=0)
    precipitation = req_bool(body, "precipitation")
    # Priority 6: only the assigned pilot may record observations
    if flight["pilot_id"] != caller.user_id:
        raise_error(ERR_FLIGHT_NOT_ASSIGNED,
                    "acting pilot does not match flight.pilot_id")
    if flight["status"] != "WEATHER_REVIEW":
        raise_error(ERR_INVALID_STATE,
                    f"cannot record a briefing while flight is {flight['status']}")
    site = db["launch_sites"].get(flight["launch_site_id"])
    go = (
        site is not None
        and surface <= site["surface_wind_limit_kts"]
        and aloft <= site["aloft_wind_limit_kts"]
        and visibility >= 3.0
        and precipitation is False
    )
    # Supersede the prior RECORDED briefing — at most one per flight (PRD 2.8)
    for w in db["weather_briefings"].values():
        if w["flight_id"] == flight["id"] and w["status"] == "RECORDED":
            w["status"] = "SUPERSEDED"
    rec = new_record("weather_briefings", {
        "flight_id": flight["id"],
        "observed_at": CLOCK.now_iso(),
        "surface_wind_kts": surface,
        "aloft_wind_kts": aloft,
        "visibility_mi": visibility,
        "precipitation": precipitation,
        "decision": "GO" if go else "NO_GO",
        "status": "RECORDED",
    }, with_version=False)
    return success_object(public_briefing(rec), status=201)


@bp.get("/flights/<flight_id>/weather-briefings")
def list_briefings(flight_id):
    authorized(ALL_READ_ROLES)
    require_path_resource("flights", flight_id, "flight")
    items = [w for w in db["weather_briefings"].values() if w["flight_id"] == flight_id]
    items = sort_created(items)
    total = len(items)
    limit, offset = get_pagination()
    page = items[offset:offset + limit]
    return success_list([public_briefing(w) for w in page], total, limit, offset)
