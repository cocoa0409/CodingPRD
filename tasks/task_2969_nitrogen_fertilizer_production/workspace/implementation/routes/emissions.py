"""Continuous-emissions monitoring and posture re-derivation (PRD 3.10)."""
from flask import Blueprint, request

import calc
import cascade
import serialize
import validate as v
from auth import ALL_ROLES, REGULATORY_ADMIN, actor
from envelope import list_response, object_response, paging
from errors import ApiError
from guards import filtered, load
from mutate import touch
from store import db, stamp_new

bp = Blueprint("emissions", __name__)
PREFIX = "/nitrogen-ops/emissions-readings"
POLLUTANTS = ("N2O", "NH3", "NOX", "PM")


@bp.post(PREFIX)
def create_reading():
    actor([REGULATORY_ADMIN])
    body = v.get_body()
    plant_id = v.s_id(body, "plant_id")
    pollutant = v.s_enum(body, "pollutant", POLLUTANTS)
    rate = v.s_num(body, "rate_lb_per_hour", 3, ge=0)
    interval = v.s_num(body, "interval_hours", 1, gt=0)
    reading_at = v.s_dt(body, "reading_at")
    plant = load("plants", plant_id)
    if reading_at > db.clock:
        raise ApiError("ERR_EMISSIONS_READING_IN_FUTURE")
    row = {
        "plant_id": plant_id,
        "pollutant": pollutant,
        "rate_lb_per_hour": rate,
        "interval_hours": interval,
        "reading_at": reading_at,
        "tons": calc.reading_tons(rate, interval),
        "rolling_30d_tons": None,
        "exceedance": False,
        "_immutable": True,
    }
    stamp_new(row)
    db.readings[row["id"]] = row
    rolling = calc.rolling_30d_tons(plant_id, pollutant)
    row["rolling_30d_tons"] = rolling
    row["exceedance"] = rolling > plant["permit_limit_tons_30d"]
    touch(plant)
    cascade.rederive_posture(plant)
    return object_response(serialize.reading_json(row), 201)


@bp.get(PREFIX + "/<id>")
def get_reading(id):
    actor(ALL_ROLES)
    return object_response(serialize.reading_json(load("readings", id)))


@bp.get(PREFIX)
def list_readings():
    actor(ALL_ROLES)
    limit, offset = paging(request.args)
    rows = filtered("readings", [
        ("plant_id", v.query_str("plant_id")),
        ("pollutant", v.query_enum("pollutant", POLLUTANTS)),
    ])
    return list_response(serialize.dump("readings", rows), limit, offset)
