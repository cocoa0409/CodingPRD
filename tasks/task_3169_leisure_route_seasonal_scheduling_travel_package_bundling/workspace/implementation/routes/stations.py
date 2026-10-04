"""Stations: POST /stations, GET /stations, GET /stations/{id}."""

from flask import Blueprint

import db
from common import new_entity, get_or_404, body, require_field, require_enum
from errors import ApiError
from middleware import require_role, require_any_authenticated
from response import ok, paginate

bp = Blueprint("stations", __name__)

STATION_KINDS = {"ORIGIN_SMALL_CITY", "LEISURE_DESTINATION"}


@bp.route("/stations", methods=["POST"])
def create_station():
    require_role("NetworkPlanner")
    data = body()
    iata = require_field(data, "iata_code", str)
    kind = require_enum(data, "station_kind", STATION_KINDS)
    timezone = require_field(data, "timezone", str)
    single = data.get("single_station_flag", False)
    if not isinstance(single, bool):
        raise ApiError("ERR_VALIDATION", "single_station_flag must be a boolean", 422)
    ent = new_entity(
        {
            "iata_code": iata,
            "station_kind": kind,
            "timezone": timezone,
            "single_station_flag": single,
        }
    )
    db.stations[ent["id"]] = ent
    return ok(ent, 201)


@bp.route("/stations", methods=["GET"])
def list_stations():
    require_any_authenticated()
    items = list(db.stations.values())
    kind = _args("station_kind")
    if kind:
        items = [s for s in items if s["station_kind"] == kind]
    items.sort(key=lambda s: (s["created_at"], s["id"]))
    page, meta = paginate(items)
    return ok(page, 200, pagination=meta)


@bp.route("/stations/<station_id>", methods=["GET"])
def get_station(station_id):
    require_any_authenticated()
    ent = get_or_404(db.stations, station_id, "ERR_STATION_NOT_FOUND", "Station")
    return ok(ent)


def _args(name):
    from flask import request

    return request.args.get(name)
