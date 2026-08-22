from flask import Blueprint

import constants as C
import validators as V
from auth import authorize
from domain import apply_changes, serialize_gse_unit, set_service_hold
from envelope import filter_equals, paginate, respond_object
from errors import ApiError
from store import (
    as_dt, db, format_iso, new_record, now_stamp, ordered, plus_minutes, require,
)

bp = Blueprint("gse_units", __name__)

SERVICE_EVENT_ROLES = [C.ROLE_STATION_MANAGER, C.ROLE_SAFETY_OFFICER]


@bp.post("/gse-units")
def create_gse_unit():
    authorize([C.ROLE_STATION_MANAGER])
    payload = V.body()

    station_id = V.req_string(payload, "station_id")
    asset_tag = V.req_string(payload, "asset_tag")
    gse_type = V.req_enum(payload, "gse_type", C.GSE_TYPES)
    condition_score = V.opt_int(payload, "condition_score", 100, 0, 100)
    service_interval_cycles = V.opt_int(payload, "service_interval_cycles", 25, 1)
    cycles_since_service = V.opt_int(payload, "cycles_since_service", 0, 0)

    station = require(db.stations, station_id, "Station")

    for existing in db.gse_units.values():
        if existing["station_id"] == station["id"] and existing["asset_tag"] == asset_tag:
            raise ApiError("ERR_DUPLICATE_CODE", "asset_tag already exists at this station.")

    unit = new_record("GseUnit", {
        "station_id": station["id"],
        "asset_tag": asset_tag,
        "gse_type": gse_type,
        "status": "AVAILABLE",
        "condition_score": condition_score,
        "service_interval_cycles": service_interval_cycles,
        "cycles_since_service": cycles_since_service,
        "service_hold_start": None,
        "service_hold_end": None,
        "committed_occupation_minutes": 0,
        "last_service_at": None,
    })
    db.gse_units[unit["id"]] = unit
    return respond_object(serialize_gse_unit(unit), 201)


@bp.get("/gse-units/<gse_unit_id>")
def read_gse_unit(gse_unit_id):
    authorize(C.ALL_ROLES)
    unit = require(db.gse_units, gse_unit_id, "GseUnit")
    return respond_object(serialize_gse_unit(unit))


@bp.get("/gse-units")
def list_gse_units():
    authorize(C.ALL_ROLES)
    records = filter_equals(db.gse_units.values(), {
        "station_id": "station_id",
        "gse_type": "gse_type",
        "status": "status",
    })
    return paginate(ordered(records), serialize_gse_unit)


@bp.post("/gse-units/<gse_unit_id>/service-events")
def gse_service_event(gse_unit_id):
    authorize(SERVICE_EVENT_ROLES)
    unit = require(db.gse_units, gse_unit_id, "GseUnit")
    payload = V.body()
    event_type = V.req_enum(payload, "event_type", C.SERVICE_EVENT_TYPES)
    hold_start = V.opt_datetime(payload, "hold_start")
    hold_end = V.opt_datetime(payload, "hold_end")

    if event_type == "HOLD_SCHEDULED":
        if unit["status"] != "AVAILABLE":
            raise ApiError("ERR_INVALID_STATE")
        start = as_dt(hold_start) if hold_start else db.clock
        end = as_dt(hold_end) if hold_end else plus_minutes(start, C.SERVICE_HOLD_MINUTES)
        apply_changes(unit, {
            "service_hold_start": hold_start if hold_start else now_stamp(),
            "service_hold_end": hold_end if hold_end else format_iso(end),
        })
        if start <= db.clock:
            apply_changes(unit, {"status": "IN_MAINTENANCE"})
    else:  # SERVICE_COMPLETED
        if unit["status"] not in ("IN_MAINTENANCE", "QUARANTINED"):
            raise ApiError("ERR_INVALID_STATE")
        apply_changes(unit, {
            "status": "AVAILABLE",
            "cycles_since_service": 0,
            "last_service_at": now_stamp(),
            "service_hold_start": None,
            "service_hold_end": None,
        })

    return respond_object(serialize_gse_unit(unit))
