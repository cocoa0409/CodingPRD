import re
from decimal import Decimal

from flask import Blueprint

import constants as C
import validators as V
from auth import authorize, current_user
from domain import (
    apply_changes, banks_of_station, incidents_of_station, recompute_station_posture,
    season_rollover_cascade, serialize_station, station_close_cascade,
    station_suspend_cascade,
)
from envelope import filter_equals, paginate, respond_object
from errors import ApiError
from store import db, new_record, now_stamp, ordered, require

bp = Blueprint("stations", __name__)

IATA_RE = re.compile(r"^[A-Z]{3}$")


@bp.post("/stations")
def create_station():
    authorize([C.ROLE_STATION_MANAGER])
    payload = V.body()

    iata_code = V.req_string(payload, "iata_code")
    if not IATA_RE.match(iata_code):
        raise ApiError("ERR_INVALID_REQUEST", "iata_code must be exactly three uppercase letters.")
    name = V.req_string(payload, "name")
    handler_code = V.req_string(payload, "handler_code")
    season_code = V.opt_enum(payload, "season_code", C.SEASONS, "SUMMER")
    season_start_date = V.opt_datetime(payload, "season_start_date")
    season_end_date = V.opt_datetime(payload, "season_end_date")
    otp_target_pct = V.opt_decimal(
        payload, "otp_target_pct", Decimal("85.00"), Decimal("0.00"), Decimal("100.00")
    )
    otp_tolerance_minutes = V.opt_int(payload, "otp_tolerance_minutes", 15, 0)
    gse_reposition_buffer_minutes = V.opt_int(payload, "gse_reposition_buffer_minutes", 20, 0)
    penalty_cap_cents = V.opt_int(payload, "penalty_cap_cents", 5000000, 0)
    damage_penalty_multiplier = V.opt_decimal(
        payload, "damage_penalty_multiplier", Decimal("1.00"), Decimal("0"), None, True
    )

    for existing in db.stations.values():
        if existing["iata_code"] == iata_code:
            raise ApiError("ERR_DUPLICATE_CODE", "iata_code already exists.")

    station = new_record("Station", {
        "iata_code": iata_code,
        "name": name,
        "handler_code": handler_code,
        "status": "PLANNED",
        "season_code": season_code,
        "season_start_date": season_start_date,
        "season_end_date": season_end_date,
        "otp_target_pct": otp_target_pct.quantize(Decimal("0.01")),
        "otp_tolerance_minutes": otp_tolerance_minutes,
        "gse_reposition_buffer_minutes": gse_reposition_buffer_minutes,
        "penalty_cap_cents": penalty_cap_cents,
        "damage_penalty_multiplier": damage_penalty_multiplier.quantize(Decimal("0.01")),
        "oversight_posture": "NORMAL",
        "open_critical_incident_count": 0,
        "open_major_incident_count": 0,
        "completed_turn_count": 0,
        "on_time_turn_count": 0,
        "otp_rolling_pct": Decimal("100.00"),
        "opened_at": None,
        "closed_at": None,
    })
    db.stations[station["id"]] = station
    return respond_object(serialize_station(station), 201)


@bp.get("/stations/<station_id>")
def read_station(station_id):
    authorize(C.ALL_ROLES)
    station = require(db.stations, station_id, "Station")
    return respond_object(serialize_station(station))


@bp.get("/stations")
def list_stations():
    authorize(C.ALL_ROLES)
    records = filter_equals(db.stations.values(), {"status": "status", "season_code": "season_code"})
    return paginate(ordered(records), serialize_station)


@bp.post("/stations/<station_id>/lifecycle")
def station_lifecycle(station_id):
    authorize([C.ROLE_STATION_MANAGER])
    station = require(db.stations, station_id, "Station")
    payload = V.body()
    action = V.req_enum(payload, "action", C.STATION_ACTIONS)
    V.opt_string(payload, "reason")

    status = station["status"]
    if action == "OPEN":
        if status != "PLANNED":
            raise ApiError("ERR_INVALID_STATE")
        apply_changes(station, {"status": "OPEN", "opened_at": now_stamp()})
        recompute_station_posture(station)
    elif action == "SUSPEND":
        if status != "OPEN":
            raise ApiError("ERR_INVALID_STATE")
        apply_changes(station, {"status": "SUSPENDED"})
        station_suspend_cascade(station)
    elif action == "RESUME":
        if status != "SUSPENDED":
            raise ApiError("ERR_INVALID_STATE")
        open_critical = sum(
            1 for i in incidents_of_station(station["id"])
            if i["severity"] == "CRITICAL" and i["status"] != "CLOSED"
        )
        if open_critical != 0:
            raise ApiError("ERR_INVALID_STATE", "The station still carries an open critical incident.")
        apply_changes(station, {"status": "OPEN"})
        recompute_station_posture(station)
    else:  # CLOSE
        if status not in ("OPEN", "SUSPENDED"):
            raise ApiError("ERR_INVALID_STATE")
        live_turn = any(
            t["status"] in ("SCHEDULED", "RESOURCED", "IN_PROGRESS")
            for t in db.turns.values() if t["station_id"] == station["id"]
        )
        live_period = any(
            p["status"] in ("OPEN", "PENDING_APPROVAL")
            for p in db.billing_periods.values() if p["station_id"] == station["id"]
        )
        if live_turn or live_period:
            raise ApiError("ERR_STATION_HAS_ACTIVE_WORK")
        apply_changes(station, {"status": "CLOSED", "closed_at": now_stamp()})
        station_close_cascade(station)

    return respond_object(serialize_station(station))


@bp.post("/stations/<station_id>/season-rollovers")
def station_season_rollover(station_id):
    authorize([C.ROLE_STATION_MANAGER])
    station = require(db.stations, station_id, "Station")
    payload = V.body()
    to_season_code = V.req_enum(payload, "to_season_code", C.SEASONS)
    season_start_date = V.req_datetime(payload, "season_start_date")
    season_end_date = V.req_datetime(payload, "season_end_date")

    if station["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE")
    outgoing = station["season_code"]
    if to_season_code == outgoing:
        raise ApiError("ERR_SEASON_MISMATCH")

    apply_changes(station, {
        "season_code": to_season_code,
        "season_start_date": season_start_date,
        "season_end_date": season_end_date,
    })
    season_rollover_cascade(station, outgoing)
    return respond_object(serialize_station(station))
