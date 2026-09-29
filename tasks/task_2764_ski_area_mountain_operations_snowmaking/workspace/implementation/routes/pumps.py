"""Pump house endpoints."""
from flask import Blueprint

import db
import response
import validate
from errors import ApiError
from middleware import (auth, ALL_ROLES, MOUNTAIN_OPS_DIRECTOR,
                        SNOWMAKING_SUPERVISOR)
from services import cascade, serialize

bp = Blueprint("pumps", __name__)

PUMP_STATUSES = ("ONLINE", "MAINTENANCE")


@bp.route("/pump-houses", methods=["POST"])
def create_pump_house():
    auth(SNOWMAKING_SUPERVISOR, MOUNTAIN_OPS_DIRECTOR)
    body = validate.body()
    season = validate.fk(body, "season_id", db.store.seasons, "ERR_SEASON_NOT_FOUND")
    validate.get_str(body, "season_id")
    code = validate.get_str(body, "pump_house_code", max_len=32)
    max_gpm = validate.get_int(body, "max_gpm", minimum=1)
    gun_count = validate.get_int(body, "gun_count", minimum=1)
    name = validate.get_str(body, "name", required=False, max_len=120)
    status = validate.get_enum(body, "status", PUMP_STATUSES,
                               required=False, default="ONLINE")
    for existing in db.season_pumps(season["id"]):
        if existing["pump_house_code"] == code:
            raise ApiError("ERR_DUPLICATE_CODE")
    cascade.require_season_writable(season)
    row = db.new_row({
        "season_id": season["id"],
        "pump_house_code": code,
        "name": name,
        "max_gpm": max_gpm,
        "gun_count": gun_count,
        "status": status,
        "peak_committed_gpm": 0,
        "active_session_count": 0,
    })
    db.store.pumps[row["id"]] = row
    return response.object_response(serialize.pump_house(row), 201)


@bp.route("/pump-houses/<pump_id>", methods=["GET"])
def get_pump_house(pump_id):
    auth(*ALL_ROLES)
    row = validate.path_row(db.store.pumps, pump_id, "ERR_PUMP_HOUSE_NOT_FOUND")
    return response.object_response(serialize.pump_house(row), 200)


@bp.route("/pump-houses", methods=["GET"])
def list_pump_houses():
    auth(*ALL_ROLES)
    limit, offset = validate.pagination()
    rows = db.ordered(db.store.pumps)
    season_id = validate.query_value("season_id")
    status = validate.query_value("status")
    if season_id:
        rows = [r for r in rows if r["season_id"] == season_id]
    if status:
        rows = [r for r in rows if r["status"] == status]
    return response.list_response(rows, serialize.pump_house, limit, offset)


@bp.route("/pump-houses/<pump_id>/status", methods=["POST"])
def set_pump_status(pump_id):
    auth(SNOWMAKING_SUPERVISOR)
    pump = validate.path_row(db.store.pumps, pump_id, "ERR_PUMP_HOUSE_NOT_FOUND")
    body = validate.body()
    status = validate.get_enum(body, "status", PUMP_STATUSES)
    season = db.store.seasons.get(pump["season_id"])
    cascade.require_season_writable(season)
    pump["status"] = status
    db.mark(pump)
    return response.object_response(serialize.pump_house(pump), 200)
