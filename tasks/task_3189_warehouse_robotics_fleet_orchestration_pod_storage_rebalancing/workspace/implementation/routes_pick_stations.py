"""Pick stations blueprint."""

from flask import Blueprint, request

import errors
from cascades import entity_out, list_out
from db import store
from middleware import require_roles
from models import base_entity, bump, get_or_404, req_int, req_str, require_field
from response import parse_pagination, success_list, success_object

bp = Blueprint("pick_stations", __name__)

READ_ROLES = {"FleetAdmin", "FlowController", "StationOperator"}


@bp.route("/pick-stations", methods=["POST"])
def create_station():
    require_roles({"FleetAdmin"})
    body = request.get_json(silent=True) or {}
    station_code = req_str(body, "station_code")
    zone_id = require_field(body, "zone_id")
    if not isinstance(zone_id, str):
        raise errors.validation("zone_id must be a string")
    get_or_404(store.zones, zone_id, "zone")
    max_queue = req_int(body, "max_queue", minimum=1)
    for s in store.pick_stations.values():
        if s["station_code"] == station_code:
            raise errors.validation(f"station_code already exists: {station_code}")
    station = base_entity()
    station.update(
        {
            "station_code": station_code,
            "zone_id": zone_id,
            "max_queue": max_queue,
            "queue_length": 0,
            "status": "OPEN",
        }
    )
    store.pick_stations[station["id"]] = station
    return success_object(entity_out(station), status=201)


@bp.route("/pick-stations/<station_id>", methods=["GET"])
def get_station(station_id):
    require_roles(READ_ROLES)
    station = get_or_404(store.pick_stations, station_id, "pick station")
    return success_object(entity_out(station))


@bp.route("/pick-stations/<station_id>/pause", methods=["POST"])
def pause_station(station_id):
    require_roles({"FlowController"})
    station = get_or_404(store.pick_stations, station_id, "pick station")
    if station["status"] != "OPEN":
        raise errors.invalid_state("pick station is not OPEN")
    station["status"] = "PAUSED"
    bump(station)
    return success_object(entity_out(station))


@bp.route("/pick-stations/<station_id>/reopen", methods=["POST"])
def reopen_station(station_id):
    require_roles({"FlowController"})
    station = get_or_404(store.pick_stations, station_id, "pick station")
    if station["status"] != "PAUSED":
        raise errors.invalid_state("pick station is not PAUSED")
    station["status"] = "OPEN"
    bump(station)
    return success_object(entity_out(station))


@bp.route("/pick-stations/<station_id>/pick-tasks", methods=["GET"])
def station_tasks(station_id):
    require_roles(READ_ROLES)
    get_or_404(store.pick_stations, station_id, "pick station")
    limit, offset = parse_pagination()
    items = sorted(
        (
            t
            for t in store.pick_tasks.values()
            if t["station_id"] == station_id and t["status"] in {"QUEUED", "DELIVERED"}
        ),
        key=lambda t: (t.get("sequence_index") if t.get("sequence_index") is not None else 1 << 30, t["created_at"]),
    )
    total = len(items)
    return success_list(list_out(items[offset : offset + limit]), limit, offset, total)
