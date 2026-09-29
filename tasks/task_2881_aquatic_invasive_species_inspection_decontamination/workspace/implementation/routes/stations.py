"""Inspection stations and their operating-hours windows (PRD 3.1)."""

from flask import Blueprint

import services
from envelope import created, ok
from errors import ApiError
from routes._common import ALL_ROLES, listing, matches, read_pagination
from store import base_row, db, fmt_iso, parse_iso, serialize, touch
from validate import (arg_bool_filter, arg_filter, opt_bool, opt_enum, opt_int,
                      opt_ref, opt_str, read_body, req_dt, req_enum, req_str,
                      require_auth)

bp = Blueprint("stations", __name__)

STATION_TYPES = ("WATERBODY_ACCESS", "HIGHWAY_CORRIDOR")
STATION_STATUSES = ("PLANNED", "OPEN", "SUSPENDED", "CLOSED")
STAFFING_LEVELS = ("SINGLE", "DOUBLE")
LIVE_RECORD_STATUSES = ("INITIATED", "SCREENED", "DECON_REQUIRED")


@bp.post("/inspection-stations")
def create_station():
    require_auth(("ProgramAdmin",))
    body = read_body()
    name = req_str(body, "name")
    station_type = req_enum(body, "station_type", STATION_TYPES)
    water_body_id = opt_ref(body, "water_body_id")
    corridor_route_code = opt_str(body, "corridor_route_code", min_len=None)
    mandatory_inspection = opt_bool(body, "mandatory_inspection", False)
    decon_bay_count = opt_int(body, "decon_bay_count", 0, minimum=0)
    hot_water_capable = opt_bool(body, "hot_water_capable", False)
    seal_stock_initial = opt_int(body, "seal_stock_initial_count", 0, minimum=0)

    if water_body_id is not None:
        services.water_body_or_404(water_body_id)

    if station_type == "WATERBODY_ACCESS":
        if water_body_id is None or corridor_route_code is not None:
            raise ApiError("ERR_STATION_SITING_INVALID")
    else:
        if corridor_route_code is None or water_body_id is not None:
            raise ApiError("ERR_STATION_SITING_INVALID")

    row = base_row()
    row.update({
        "name": name,
        "station_type": station_type,
        "water_body_id": water_body_id,
        "corridor_route_code": corridor_route_code,
        "status": "PLANNED",
        "mandatory_inspection": mandatory_inspection,
        "decon_bay_count": decon_bay_count,
        "hot_water_capable": hot_water_capable,
        "seal_stock_initial_count": seal_stock_initial,
        "seal_stock_count": seal_stock_initial,
        "seals_in_circulation_count": 0,
        "seals_retired_count": 0,
        "certified_inspector_count": 0,
        "decon_service_available": False,
        "collected_fees_cents": 0,
        "refunded_fees_cents": 0,
        "campaign_allocated_cents": 0,
    })
    db.stations[row["id"]] = row
    return created(serialize(row))


@bp.get("/inspection-stations/<sid>")
def get_station(sid):
    require_auth(ALL_ROLES)
    return ok(serialize(services.station_or_404(sid)))


@bp.get("/inspection-stations")
def list_stations():
    require_auth(ALL_ROLES)
    limit, offset = read_pagination()
    filters = {
        "water_body_id": arg_filter("water_body_id"),
        "station_type": arg_filter("station_type"),
        "status": arg_filter("status"),
        "hot_water_capable": arg_bool_filter("hot_water_capable"),
    }
    rows = [r for r in db.stations.values() if matches(r, filters)]
    return listing(rows, limit, offset)


@bp.post("/inspection-stations/<sid>/status")
def set_station_status(sid):
    require_auth(("ProgramAdmin",))
    body = read_body()
    target = req_enum(body, "target_status", STATION_STATUSES)
    opt_str(body, "reason", min_len=None)

    station = services.station_or_404(sid)
    current = station["status"]

    if current == "CLOSED":
        raise ApiError("ERR_INVALID_STATION_STATE")

    if target == "OPEN" and current == "PLANNED":
        has_hours = any(w["station_id"] == station["id"]
                        for w in db.station_hours.values())
        if not has_hours:
            raise ApiError("ERR_INVALID_STATION_STATE")
        station["status"] = "OPEN"
        station["seal_stock_count"] = station["seal_stock_initial_count"]
        services.recompute_station_staffing(station)
    elif target == "OPEN" and current == "SUSPENDED":
        station["status"] = "OPEN"
    elif target == "SUSPENDED" and current == "OPEN":
        station["status"] = "SUSPENDED"
    elif target == "CLOSED" and current == "PLANNED":
        station["status"] = "CLOSED"
    elif target == "CLOSED" and current in ("OPEN", "SUSPENDED"):
        live = any(r["station_id"] == station["id"]
                   and r["inspection_status"] in LIVE_RECORD_STATUSES
                   for r in db.records.values())
        if live:
            raise ApiError("ERR_INVALID_STATION_STATE")
        station["status"] = "CLOSED"
    else:
        raise ApiError("ERR_INVALID_STATION_STATE")

    touch(station)
    return ok(serialize(station))


@bp.post("/inspection-stations/<sid>/hours")
def create_hours(sid):
    require_auth(("ProgramAdmin",))
    body = read_body()
    opens_at = req_dt(body, "opens_at")
    closes_at = req_dt(body, "closes_at")
    staffing_level = opt_enum(body, "staffing_level", STAFFING_LEVELS, "SINGLE")
    if not (closes_at > opens_at):
        raise ApiError("ERR_INVALID_REQUEST",
                       "closes_at must be strictly later than opens_at.")

    station = services.station_or_404(sid)

    for window in db.station_hours.values():
        if window["station_id"] != station["id"]:
            continue
        existing_open = parse_iso(window["opens_at"])
        existing_close = parse_iso(window["closes_at"])
        if opens_at < existing_close and existing_open < closes_at:
            raise ApiError("ERR_HOURS_WINDOW_OVERLAP")

    row = base_row()
    row.update({
        "station_id": station["id"],
        "opens_at": fmt_iso(opens_at),
        "closes_at": fmt_iso(closes_at),
        "staffing_level": staffing_level,
    })
    db.station_hours[row["id"]] = row
    return created(serialize(row))


@bp.get("/inspection-stations/<sid>/hours")
def list_hours(sid):
    require_auth(ALL_ROLES)
    limit, offset = read_pagination()
    station = services.station_or_404(sid)
    rows = [w for w in db.station_hours.values()
            if w["station_id"] == station["id"]]
    return listing(rows, limit, offset)
