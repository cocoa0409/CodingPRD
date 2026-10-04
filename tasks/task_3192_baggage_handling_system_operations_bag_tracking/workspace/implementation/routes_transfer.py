"""Routes: transfer-bag connections on the transfer desk surface."""

from flask import Blueprint, request

from common import (
    authenticate, body, integer, paginate, query_str, require, text,
)
from db import DB, new_row, iso, parse_iso, touch
from errors import fail
import calc
import recompute
import serializers as ser

bp = Blueprint("transfer", __name__)

STATUSES = ("PENDING", "CONFIRMED", "RUSH", "MISSED", "REACCOMMODATED")
RUSH_FLOOR = -15
FIXED_CUSTODY_FOR_MISS = ("LOADED", "OFFLOADED", "SORTED", "IN_MAKEUP")


def _bag(ident):
    row = DB.bags.get(ident)
    if row is None:
        fail("ERR_BAG_NOT_FOUND")
    return row


def _flight(ident):
    row = DB.flights.get(ident)
    if row is None:
        fail("ERR_FLIGHT_NOT_FOUND")
    return row


def _connection(ident):
    row = DB.connections.get(ident)
    if row is None:
        fail("ERR_INVALID_REQUEST")
    return row


def _bump_bag(bag):
    bag["rush_declared"] = calc.rush_declared(DB, bag)
    bag["priority_score"] = calc.priority_score(DB, bag)
    touch(DB, bag)


def _listed(rows, query, serializer=lambda r: r):
    rows = ser.sort_rows(rows)
    window, page = paginate(rows, query)
    return [serializer(r) for r in window], page


@bp.post("/baggage/connections")
def create_connection():
    authenticate()
    role = request.headers.get("X-User-Role")
    if role != "TransferAgent":
        fail("ERR_FORBIDDEN_ROLE")
    payload = body()
    require(payload, "bag_id", "inbound_flight_id", "onward_flight_id", "required_mct_minutes")
    bag = _bag(text(payload, "bag_id"))
    inbound = _flight(text(payload, "inbound_flight_id"))
    onward = _flight(text(payload, "onward_flight_id"))
    required = integer(payload, "required_mct_minutes")
    for existing in DB.connections.values():
        if existing["bag_id"] == bag["id"] and existing["onward_flight_id"] == onward["id"]:
            fail("ERR_DUPLICATE_CONNECTION")
    row = new_row(DB, {
        "bag_id": bag["id"],
        "inbound_flight_id": inbound["id"],
        "onward_flight_id": onward["id"],
        "required_mct_minutes": required,
        "connect_slack_minutes": 0,
        "status": "PENDING",
        "rush_declared_utc": None,
    })
    row["connect_slack_minutes"] = calc.connection_slack(DB, row)
    DB.add("connections", row)
    _bump_bag(bag)
    return ser.connection(row), 201


@bp.get("/baggage/connections/<ident>")
def get_connection(ident):
    authenticate()
    return ser.connection(_connection(ident)), 200


@bp.get("/baggage/connections")
def list_connections():
    authenticate()
    rows = DB.all_of("connections")
    for key in ("bag_id", "inbound_flight_id", "onward_flight_id", "status"):
        value = query_str(key)
        if value is not None:
            rows = [r for r in rows if r.get(key) == value]
    window, page = _listed(rows, request.args, ser.connection)
    return window, page


@bp.get("/baggage/bags/<ident>/connections")
def list_bag_connections(ident):
    authenticate()
    bag = _bag(ident)
    rows = [r for r in DB.connections.values() if r["bag_id"] == bag["id"]]
    window, page = _listed(rows, request.args, ser.connection)
    return window, page


@bp.get("/baggage/flights/<ident>/connections")
def list_flight_connections(ident):
    authenticate()
    flight = _flight(ident)
    rows = [r for r in DB.connections.values() if r["onward_flight_id"] == flight["id"]]
    window, page = _listed(rows, request.args, ser.connection)
    return window, page


@bp.post("/baggage/connections/<ident>/confirm")
def confirm_connection(ident):
    authenticate()
    role = request.headers.get("X-User-Role")
    if role != "TransferAgent":
        fail("ERR_FORBIDDEN_ROLE")
    conn = _connection(ident)
    bag = _bag(conn["bag_id"])
    if bag["screening_status"] != "CLEARED":
        fail("ERR_SCREENING_NOT_CLEARED")
    if conn["status"] not in ("PENDING", "RUSH"):
        fail("ERR_INVALID_STATE")
    if conn["connect_slack_minutes"] < 0:
        fail("ERR_MCT_VIOLATION")
    conn["status"] = "CONFIRMED"
    touch(DB, conn)
    _bump_bag(bag)
    return ser.connection(conn), 200


@bp.post("/baggage/connections/<ident>/declare-rush")
def declare_rush(ident):
    authenticate()
    role = request.headers.get("X-User-Role")
    if role != "TransferAgent":
        fail("ERR_FORBIDDEN_ROLE")
    conn = _connection(ident)
    if conn["status"] not in ("PENDING", "CONFIRMED", "REACCOMMODATED"):
        fail("ERR_INVALID_STATE")
    if conn["connect_slack_minutes"] < RUSH_FLOOR:
        fail("ERR_RUSH_WINDOW_PASSED")
    conn["status"] = "RUSH"
    conn["rush_declared_utc"] = iso(DB.now())
    touch(DB, conn)
    bag = DB.bags.get(conn["bag_id"])
    if bag is not None:
        _bump_bag(bag)
    return ser.connection(conn), 200


@bp.post("/baggage/connections/<ident>/reaccommodate")
def reaccommodate(ident):
    authenticate()
    role = request.headers.get("X-User-Role")
    if role != "TransferAgent":
        fail("ERR_FORBIDDEN_ROLE")
    conn = _connection(ident)
    payload = body()
    require(payload, "onward_flight_id")
    replacement = _flight(text(payload, "onward_flight_id"))
    if conn["status"] != "MISSED":
        fail("ERR_INVALID_STATE")
    if replacement["id"] == conn["onward_flight_id"]:
        fail("ERR_INVALID_REQUEST")
    if replacement["status"] not in ("SCHEDULED", "SORT_OPEN"):
        fail("ERR_FLIGHT_NOT_SORTING")
    conn["onward_flight_id"] = replacement["id"]
    conn["connect_slack_minutes"] = calc.connection_slack(DB, conn)
    conn["status"] = "REACCOMMODATED"
    touch(DB, conn)
    bag = DB.bags.get(conn["bag_id"])
    if bag is not None:
        _bump_bag(bag)
    return ser.connection(conn), 201