"""Routes: clock, stations, airlines, make-up areas, screening lanes, flights."""

import re

from flask import Blueprint, request

from common import (
    authenticate, body, boolean, datetime_value, enum_value, integer, paginate,
    query_flag, query_str, text,
)
from db import DB, new_row, iso, parse_iso, minutes_before, touch
from errors import fail
import calc
import recompute
import serializers as ser

bp = Blueprint("reference", __name__)

POSTURE = ("OPEN", "CONGESTED", "SUSPENDED")
AREA_STATUS = ("ACTIVE", "CLOSED")
LANE_STATUS = ("ACTIVE", "OFFLINE")
FLIGHT_STATUS = ("SCHEDULED", "SORT_OPEN", "BOARDING", "DEPARTED", "CANCELLED")


def _list(rows, query):
    rows = ser.sort_rows(rows)
    window, page = paginate(rows, query)
    return window, page


def _station_or_fail(ident):
    # PRD §2.5: a path identifier that does not resolve is rejected with HTTP
    # 404; the error identifier carries the resource's own name where the
    # catalogue declares one.
    row = DB.stations.get(ident)
    if row is None:
        fail("ERR_STATION_NOT_FOUND")
    return row


def _airline_or_fail(ident):
    row = DB.airlines.get(ident)
    if row is None:
        fail("ERR_INVALID_REQUEST")
    return row


def _area_or_fail(ident):
    row = DB.makeup_areas.get(ident)
    if row is None:
        fail("ERR_INVALID_REQUEST")
    return row


def _lane_or_fail(ident):
    row = DB.lanes.get(ident)
    if row is None:
        fail("ERR_INVALID_REQUEST")
    return row


def _flight_or_fail(ident):
    row = DB.flights.get(ident)
    if row is None:
        fail("ERR_FLIGHT_NOT_FOUND")
    return row


# ------------------------------------------------------------------ clock ---
@bp.post("/_clock/set_current_utc")
def set_clock():
    authenticate()
    payload = body()
    instant = datetime_value(payload, "to_iso8601")
    DB.set_clock(instant)
    return {"current_utc": iso(instant)}, 200


# ---------------------------------------------------------------- stations --
@bp.post("/baggage/stations")
def create_station():
    _, role = authenticate()
    if role != "PlatformAdmin":
        fail("ERR_FORBIDDEN_ROLE")
    payload = body()
    code = text(payload, "code")
    if not re.match(r"^[A-Z]{3}$", code):
        fail("ERR_INVALID_REQUEST")
    row = new_row(DB, {
        "code": code,
        "name": text(payload, "name"),
        "sorter_capacity_bags": integer(payload, "sorter_capacity_bags"),
        "posture": "OPEN",
        "outage_active": False,
        "outage_started_utc": None,
        "active_bag_count": 0,
        "manual_queue_depth": 0,
        "open_liability_cents": 0,
        "settled_liability_cents": 0,
        "ops_run_index": 0,
    })
    DB.add("stations", row)
    return ser.station(row), 201


@bp.get("/baggage/stations/<ident>")
def get_station(ident):
    authenticate()
    return ser.station(_station_or_fail(ident)), 200


@bp.get("/baggage/stations")
def list_stations():
    authenticate()
    rows = DB.all_of("stations")
    code = query_str("code")
    posture = query_str("posture")
    if code:
        rows = [r for r in rows if r["code"] == code]
    if posture:
        rows = [r for r in rows if r["posture"] == posture]
    window, page = _list(rows, request.args)
    return [ser.station(r) for r in window], page


@bp.post("/baggage/stations/<ident>/outage")
def declare_outage(ident):
    _, role = authenticate()
    if role != "PlatformAdmin":
        fail("ERR_FORBIDDEN_ROLE")
    station = _station_or_fail(ident)
    station["outage_active"] = True
    station["outage_started_utc"] = iso(DB.now())
    station["posture"] = "SUSPENDED"
    touch(DB, station)
    return ser.station(station), 200


@bp.post("/baggage/stations/<ident>/outage/clear")
def clear_outage(ident):
    _, role = authenticate()
    if role != "PlatformAdmin":
        fail("ERR_FORBIDDEN_ROLE")
    station = _station_or_fail(ident)
    # There is nothing to clear unless an outage is actually active: the flag is
    # the state this operation transitions.
    if not station.get("outage_active"):
        fail("ERR_INVALID_STATE")
    station["outage_active"] = False
    station["posture"] = calc.station_posture(DB, station)
    touch(DB, station)
    return ser.station(station), 200


# ---------------------------------------------------------------- airlines --
@bp.post("/baggage/airlines")
def create_airline():
    _, role = authenticate()
    if role != "PlatformAdmin":
        fail("ERR_FORBIDDEN_ROLE")
    payload = body()
    code = text(payload, "code")
    if not re.match(r"^[A-Z0-9]{2}$", code):
        fail("ERR_INVALID_REQUEST")
    if any(a["code"] == code for a in DB.airlines.values()):
        fail("ERR_DUPLICATE_AIRLINE")
    row = new_row(DB, {
        "code": code,
        "name": text(payload, "name"),
        "interline_agreement_active": boolean(payload, "interline_agreement_active", False),
        "max_excess_weight_lb": integer(payload, "max_excess_weight_lb"),
        "excess_weight_fee_cents": integer(payload, "excess_weight_fee_cents", required=False) or 0,
        "compensation_cap_cents": integer(payload, "compensation_cap_cents"),
    })
    DB.add("airlines", row)
    return ser.airline(row), 201


@bp.get("/baggage/airlines/<ident>")
def get_airline(ident):
    authenticate()
    return ser.airline(_airline_or_fail(ident)), 200


@bp.get("/baggage/airlines")
def list_airlines():
    authenticate()
    rows = DB.all_of("airlines")
    code = query_str("code")
    if code:
        rows = [r for r in rows if r["code"] == code]
    flag = query_flag("interline_agreement_active")
    if flag is not None:
        rows = [r for r in rows if bool(r["interline_agreement_active"]) == flag]
    window, page = _list(rows, request.args)
    return [ser.airline(r) for r in window], page


# ------------------------------------------------------------ makeup areas --
@bp.post("/baggage/makeup-areas")
def create_area():
    _, role = authenticate()
    if role != "PlatformAdmin":
        fail("ERR_FORBIDDEN_ROLE")
    payload = body()
    station = _station_or_fail(text(payload, "station_id"))
    buffer_minutes = integer(payload, "buffer_minutes", required=False)
    row = new_row(DB, {
        "station_id": station["id"],
        "code": text(payload, "code"),
        "capacity_slots": integer(payload, "capacity_slots"),
        "buffer_minutes": 15 if buffer_minutes is None else buffer_minutes,
        "occupied_slots": 0,
        "released_slots": 0,
        "free_slots": integer(payload, "capacity_slots"),
        "status": "ACTIVE",
    })
    DB.add("makeup_areas", row)
    return ser.makeup_area(row), 201


@bp.get("/baggage/makeup-areas/<ident>")
def get_area(ident):
    authenticate()
    return ser.makeup_area(_area_or_fail(ident)), 200


@bp.get("/baggage/makeup-areas")
def list_areas():
    authenticate()
    rows = DB.all_of("makeup_areas")
    station_id = query_str("station_id")
    status = query_str("status")
    if station_id:
        rows = [r for r in rows if r["station_id"] == station_id]
    if status:
        rows = [r for r in rows if r["status"] == status]
    window, page = _list(rows, request.args)
    return [ser.makeup_area(r) for r in window], page


@bp.get("/baggage/stations/<ident>/makeup-areas")
def list_station_areas(ident):
    authenticate()
    station = _station_or_fail(ident)
    rows = [r for r in DB.makeup_areas.values() if r["station_id"] == station["id"]]
    window, page = _list(rows, request.args)
    return [ser.makeup_area(r) for r in window], page


# --------------------------------------------------------- screening lanes --
@bp.post("/baggage/screening-lanes")
def create_lane():
    _, role = authenticate()
    if role != "PlatformAdmin":
        fail("ERR_FORBIDDEN_ROLE")
    payload = body()
    station = _station_or_fail(text(payload, "station_id"))
    row = new_row(DB, {
        "station_id": station["id"],
        "lane_code": text(payload, "lane_code"),
        "status": "ACTIVE",
        "last_event_end_utc": None,
    })
    DB.add("lanes", row)
    return ser.lane(row), 201


@bp.post("/baggage/screening-lanes/<ident>/offline")
def lane_offline(ident):
    _, role = authenticate()
    if role != "PlatformAdmin":
        fail("ERR_FORBIDDEN_ROLE")
    lane = _lane_or_fail(ident)
    lane["status"] = "OFFLINE"
    touch(DB, lane)
    return ser.lane(lane), 200


@bp.post("/baggage/screening-lanes/<ident>/online")
def lane_online(ident):
    _, role = authenticate()
    if role != "PlatformAdmin":
        fail("ERR_FORBIDDEN_ROLE")
    lane = _lane_or_fail(ident)
    lane["status"] = "ACTIVE"
    touch(DB, lane)
    return ser.lane(lane), 200


@bp.get("/baggage/screening-lanes/<ident>")
def get_lane(ident):
    authenticate()
    return ser.lane(_lane_or_fail(ident)), 200


@bp.get("/baggage/screening-lanes")
def list_lanes():
    authenticate()
    rows = DB.all_of("lanes")
    station_id = query_str("station_id")
    status = query_str("status")
    if station_id:
        rows = [r for r in rows if r["station_id"] == station_id]
    if status:
        rows = [r for r in rows if r["status"] == status]
    window, page = _list(rows, request.args)
    return [ser.lane(r) for r in window], page


# ----------------------------------------------------------------- flights --
@bp.post("/baggage/flights")
def create_flight():
    _, role = authenticate()
    if role != "PlatformAdmin":
        fail("ERR_FORBIDDEN_ROLE")
    payload = body()
    station = _station_or_fail(text(payload, "station_id"))
    airline = _airline_or_fail(text(payload, "airline_id"))
    departure = datetime_value(payload, "scheduled_departure_utc")
    row = new_row(DB, {
        "station_id": station["id"],
        "airline_id": airline["id"],
        "flight_number": text(payload, "flight_number"),
        "bank_code": text(payload, "bank_code"),
        "scheduled_departure_utc": iso(departure),
        "sortation_open_utc": iso(minutes_before(departure, 120)),
        "sortation_close_utc": iso(minutes_before(departure, 45)),
        "status": "SCHEDULED",
        "makeup_ready": True,
        "loaded_bag_count": 0,
    })
    DB.add("flights", row)
    return ser.flight(row), 201


@bp.get("/baggage/flights/<ident>")
def get_flight(ident):
    authenticate()
    return ser.flight(_flight_or_fail(ident)), 200


@bp.get("/baggage/flights")
def list_flights():
    authenticate()
    rows = DB.all_of("flights")
    station_id = query_str("station_id")
    airline_id = query_str("airline_id")
    bank_code = query_str("bank_code")
    status = query_str("status")
    if station_id:
        rows = [r for r in rows if r["station_id"] == station_id]
    if airline_id:
        rows = [r for r in rows if r["airline_id"] == airline_id]
    if bank_code:
        rows = [r for r in rows if r["bank_code"] == bank_code]
    if status:
        rows = [r for r in rows if r["status"] == status]
    window, page = _list(rows, request.args)
    return [ser.flight(r) for r in window], page


@bp.get("/baggage/stations/<ident>/flights")
def list_station_flights(ident):
    authenticate()
    station = _station_or_fail(ident)
    rows = [r for r in DB.flights.values() if r["station_id"] == station["id"]]
    window, page = _list(rows, request.args)
    return [ser.flight(r) for r in window], page


@bp.get("/baggage/airlines/<ident>/flights")
def list_airline_flights(ident):
    authenticate()
    airline = _airline_or_fail(ident)
    rows = [r for r in DB.flights.values() if r["airline_id"] == airline["id"]]
    window, page = _list(rows, request.args)
    return [ser.flight(r) for r in window], page


@bp.get("/baggage/makeup-areas/<ident>/flights")
def list_area_flights(ident):
    authenticate()
    area = _area_or_fail(ident)
    flight_ids = {b["flight_id"] for b in DB.bags.values()
                  if b.get("makeup_area_id") == area["id"] and b.get("flight_id")}
    rows = [f for f in DB.flights.values() if f["id"] in flight_ids]
    window, page = _list(rows, request.args)
    return [ser.flight(r) for r in window], page


@bp.post("/baggage/flights/<ident>/reschedule")
def reschedule_flight(ident):
    _, role = authenticate()
    if role != "PlatformAdmin":
        fail("ERR_FORBIDDEN_ROLE")
    flight = _flight_or_fail(ident)
    payload = body()
    departure = datetime_value(payload, "scheduled_departure_utc")
    if flight["status"] != "SORT_OPEN":
        fail("ERR_INVALID_STATE")
    flight["scheduled_departure_utc"] = iso(departure)
    flight["sortation_open_utc"] = iso(minutes_before(departure, 120))
    flight["sortation_close_utc"] = iso(minutes_before(departure, 45))
    flight["status"] = "SCHEDULED"
    touch(DB, flight)
    for conn in DB.connections.values():
        if conn["onward_flight_id"] == flight["id"]:
            conn["connect_slack_minutes"] = calc.connection_slack(DB, conn)
            bag = DB.bags.get(conn["bag_id"])
            if bag is not None:
                bag["rush_declared"] = calc.rush_declared(DB, bag)
                bag["priority_score"] = calc.priority_score(DB, bag)
                touch(DB, bag)
            touch(DB, conn)
    return ser.flight(flight), 200


@bp.post("/baggage/flights/<ident>/depart")
def depart_flight(ident):
    _, role = authenticate()
    if role != "PlatformAdmin":
        fail("ERR_FORBIDDEN_ROLE")
    flight = _flight_or_fail(ident)
    if flight["status"] != "BOARDING":
        fail("ERR_INVALID_STATE")
    close = parse_iso(flight["sortation_close_utc"])
    if DB.now() < close:
        fail("ERR_SORTATION_WINDOW_OPEN")
    flight["status"] = "DEPARTED"
    touch(DB, flight)
    return ser.flight(flight), 200


@bp.post("/baggage/flights/<ident>/cancel")
def cancel_flight(ident):
    _, role = authenticate()
    if role != "PlatformAdmin":
        fail("ERR_FORBIDDEN_ROLE")
    flight = _flight_or_fail(ident)
    if flight["status"] not in ("SCHEDULED", "SORT_OPEN"):
        fail("ERR_INVALID_STATE")
    flight["status"] = "CANCELLED"
    touch(DB, flight)
    affected_areas = set()
    for bag in DB.bags.values():
        if bag.get("flight_id") != flight["id"]:
            continue
        if bag["custody_status"] not in ("SORTED", "IN_MAKEUP"):
            continue
        if bag.get("makeup_area_id"):
            affected_areas.add(bag["makeup_area_id"])
        bag["custody_status"] = "SORTED"
        bag["flight_id"] = None
        bag["makeup_area_id"] = None
        bag["assigned_makeup_utc"] = None
        bag["duplicate_flag"] = False
        bag["priority_score"] = calc.priority_score(DB, bag)
        touch(DB, bag)
    for area_id in affected_areas:
        recompute.recompute_area(DB, area_id)
    recompute.recompute_station(DB, flight["station_id"])
    return ser.flight(flight), 200