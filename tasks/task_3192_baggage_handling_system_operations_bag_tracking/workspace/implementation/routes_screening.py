"""Routes: screening events, screening lanes' events, manual inspection queue."""

from datetime import timedelta

from flask import Blueprint, request

from common import (
    authenticate, body, datetime_value, enum_value, integer, paginate,
    query_str, require, text,
)
from db import DB, new_row, iso, parse_iso, touch
from errors import fail
import calc
import recompute
import serializers as ser

bp = Blueprint("screening", __name__)

OUTCOMES = ("CLEARED", "REJECTED")
RESOLUTIONS = ("CLEARED", "BAG_REJECTED")
EVENT_STATUS = ("IN_PROGRESS", "CLEARED", "ALARMED", "FAILED")
WINDOW_MINUTES = 20


def _bag(ident):
    row = DB.bags.get(ident)
    if row is None:
        fail("ERR_BAG_NOT_FOUND")
    return row


def _event(ident):
    row = DB.screenings.get(ident)
    if row is None:
        fail("ERR_INVALID_REQUEST")
    return row


def _task(ident):
    row = DB.inspections.get(ident)
    if row is None:
        fail("ERR_INVALID_REQUEST")
    return row


def _bucket_20(moment):
    total = int(moment.timestamp())
    return (total - (total % (WINDOW_MINUTES * 60))) // (WINDOW_MINUTES * 60)


def _listed(rows, query, serializer=lambda r: r):
    rows = ser.sort_rows(rows)
    window, page = paginate(rows, query)
    return [serializer(r) for r in window], page


def _open_task(bag, event, position=None):
    """Route 2 of §3.3 / cascade C: open a QUEUED task for the bag's latest event."""
    station_id = bag["station_id"]
    if position is None:
        position = calc.manual_queue_depth(DB, station_id) + 1
    row = new_row(DB, {
        "screening_event_id": event["id"],
        "station_id": station_id,
        "queue_position": position,
        "status": "QUEUED",
        "assigned_to": None,
        "due_utc": iso(DB.now() + timedelta(minutes=30)),
        "resolution": None,
    })
    DB.add("inspections", row)
    return row


# ------------------------------------------------------------- induction ----
@bp.post("/baggage/screenings")
def induct_screening():
    user_id, role = authenticate()
    if role != "Screener":
        fail("ERR_FORBIDDEN_ROLE")
    payload = body()
    require(payload, "bag_id", "lane_id", "start_utc")
    bag = _bag(text(payload, "bag_id"))
    lane = DB.lanes.get(text(payload, "lane_id"))
    if lane is None:
        fail("ERR_INVALID_REQUEST")
    if lane["status"] != "ACTIVE":
        fail("ERR_LANE_OFFLINE")
    start = datetime_value(payload, "start_utc")
    alarm_code = payload.get("alarm_code")
    bucket = _bucket_20(start)
    for existing in DB.screenings.values():
        if existing["lane_id"] != lane["id"] or existing["status"] == "FAILED":
            continue
        when = parse_iso(existing["start_utc"])
        if when is None:
            continue
        if _bucket_20(when) == bucket:
            fail("ERR_LANE_INTERVAL_CONFLICT")

    row = new_row(DB, {
        "bag_id": bag["id"],
        "lane_id": lane["id"],
        "start_utc": iso(start),
        "end_utc": iso(start + timedelta(minutes=WINDOW_MINUTES)),
        "alarm_code": alarm_code,
        "status": "IN_PROGRESS",
        "resolution_outcome": None,
        "resolved_by": None,
    })
    DB.add("screenings", row)

    if alarm_code is None:
        row["status"] = "CLEARED"
        row["resolution_outcome"] = "CLEARED"
        touch(DB, row)
        _apply_screening_status(bag, "CLEARED")
        if bag["custody_status"] == "SCREENING":
            bag["custody_status"] = "SORTED"
    else:
        row["status"] = "ALARMED"
        touch(DB, row)
        _apply_screening_status(bag, "ALARMED")
        # PRD §3.3: an alarm "leaves the in-line system and enters the station's
        # manual inspection queue as a ManualInspectionTask, opened against the
        # screening event that raised it", so the event that raised the alarm
        # carries a QUEUED task from this instant.
        if not any(t["screening_event_id"] == row["id"] for t in DB.inspections.values()):
            _open_task(bag, row)
    # A screening-axis write is a modification of the bag row (PRD §2.12).
    touch(DB, bag)

    recompute.recompute_lane(DB, lane["id"])
    recompute.recompute_after_bag_write(DB, bag)
    return ser.screening(row), 201


def _apply_screening_status(bag, status):
    """Write the screening axis first, then re-evaluate the custody axis."""
    bag["screening_status"] = status
    if status == "ALARMED":
        if bag["custody_status"] in ("ACCEPTED", "SCREENING"):
            bag["custody_status"] = "HELD"
            bag["_was_held"] = True
            recompute.ensure_delivery(DB, bag)
    elif status == "FAILED":
        if bag["custody_status"] in ("ACCEPTED", "SCREENING"):
            bag["custody_status"] = "HELD"
        bag["_was_held"] = True
        recompute.ensure_delivery(DB, bag)
    elif status == "IN_INSPECTION":
        if bag["custody_status"] in ("ACCEPTED", "SCREENING"):
            bag["custody_status"] = "HELD"
        bag["_was_held"] = True
        recompute.ensure_delivery(DB, bag)


# ------------------------------------------------------------------ read ----
@bp.get("/baggage/screenings/<ident>")
def get_screening(ident):
    authenticate()
    return ser.screening(_event(ident)), 200


@bp.get("/baggage/screenings")
def list_screenings():
    authenticate()
    rows = DB.all_of("screenings")
    bag_id = query_str("bag_id")
    lane_id = query_str("lane_id")
    status = query_str("status")
    if bag_id:
        if DB.bags.get(bag_id) is None:
            fail("ERR_BAG_NOT_FOUND")
        rows = [r for r in rows if r["bag_id"] == bag_id]
    if lane_id:
        rows = [r for r in rows if r["lane_id"] == lane_id]
    if status:
        rows = [r for r in rows if r["status"] == status]
    window, page = _listed(rows, request.args, ser.screening)
    return window, page


@bp.get("/baggage/bags/<ident>/screenings")
def list_bag_screenings(ident):
    authenticate()
    bag = _bag(ident)
    rows = calc.screenings_of(DB, bag["id"])
    window, page = _listed(rows, request.args, ser.screening)
    return window, page


@bp.get("/baggage/screening-lanes/<ident>/screenings")
def list_lane_screenings(ident):
    authenticate()
    lane = DB.lanes.get(ident)
    if lane is None:
        fail("ERR_INVALID_REQUEST")
    rows = [r for r in DB.screenings.values() if r["lane_id"] == lane["id"]]
    window, page = _listed(rows, request.args, ser.screening)
    return window, page


# ---------------------------------------------------------------- resolve ---
@bp.post("/baggage/screenings/<ident>/resolve")
def resolve_screening(ident):
    user_id, role = authenticate()
    if role != "Screener":
        fail("ERR_FORBIDDEN_ROLE")
    event = _event(ident)
    payload = body()
    outcome = enum_value(payload, "outcome", OUTCOMES)
    if event["status"] != "ALARMED":
        fail("ERR_SCREENING_EVENT_NOT_ALARMED")
    bag = _bag(event["bag_id"])
    if outcome == "CLEARED":
        event["status"] = "CLEARED"
        event["resolution_outcome"] = "CLEARED"
        event["resolved_by"] = user_id
        _apply_screening_status(bag, "CLEARED")
        if bag["custody_status"] == "SCREENING":
            bag["custody_status"] = "SORTED"
        recompute.append_scan(DB, bag, "SORTATION")
        for task in DB.inspections.values():
            if task["screening_event_id"] == event["id"] and task["status"] in ("QUEUED", "IN_PROGRESS"):
                task["status"] = "RESOLVED"
                task["resolution"] = "CLEARED"
                touch(DB, task)
    else:
        event["status"] = "FAILED"
        event["resolution_outcome"] = "REJECTED"
        event["resolved_by"] = user_id
        _apply_screening_status(bag, "FAILED")
        has_task = any(t["screening_event_id"] == event["id"] for t in DB.inspections.values())
        if not has_task:
            _open_task(bag, event)
    touch(DB, bag)
    touch(DB, event)
    recompute.recompute_lane(DB, event["lane_id"])
    recompute.recompute_after_bag_write(DB, bag)
    recompute.recompute_station(DB, bag["station_id"])
    return ser.screening(event), 200


@bp.post("/baggage/screenings/<ident>/reopen")
def reopen_screening(ident):
    authenticate()
    role = request.headers.get("X-User-Role")
    if role != "Screener":
        fail("ERR_FORBIDDEN_ROLE")
    event = _event(ident)
    if event["status"] != "CLEARED":
        fail("ERR_INVALID_STATE")
    end = parse_iso(event["end_utc"])
    if end > DB.now():
        fail("ERR_SCREENING_WINDOW_CLOSED")
    event["status"] = "ALARMED"
    event["resolution_outcome"] = None
    touch(DB, event)
    bag = _bag(event["bag_id"])
    _apply_screening_status(bag, "ALARMED")
    recompute.recompute_lane(DB, event["lane_id"])
    recompute.recompute_after_bag_write(DB, bag)
    return ser.screening(event), 200


# -------------------------------------------------------------- inspections -
@bp.get("/baggage/inspections")
def list_inspections():
    authenticate()
    rows = DB.all_of("inspections")
    station_id = query_str("station_id")
    status = query_str("status")
    event_id = query_str("screening_event_id")
    if station_id:
        rows = [r for r in rows if r["station_id"] == station_id]
    if status:
        rows = [r for r in rows if r["status"] == status]
    if event_id:
        rows = [r for r in rows if r["screening_event_id"] == event_id]
    window, page = _listed(rows, request.args, ser.inspection)
    return window, page


@bp.get("/baggage/inspections/<ident>")
def get_inspection(ident):
    authenticate()
    return ser.inspection(_task(ident)), 200


@bp.get("/baggage/stations/<ident>/inspections")
def list_station_inspections(ident):
    authenticate()
    station = DB.stations.get(ident)
    if station is None:
        fail("ERR_INVALID_REQUEST")
    rows = [r for r in DB.inspections.values() if r["station_id"] == station["id"]]
    window, page = _listed(rows, request.args, ser.inspection)
    return window, page


@bp.get("/baggage/screenings/<ident>/inspections")
def list_event_inspections(ident):
    authenticate()
    event = _event(ident)
    rows = [r for r in DB.inspections.values() if r["screening_event_id"] == event["id"]]
    window, page = _listed(rows, request.args, ser.inspection)
    return window, page


@bp.post("/baggage/inspections/<ident>/claim")
def claim_inspection(ident):
    user_id, role = authenticate()
    if role != "Screener":
        fail("ERR_FORBIDDEN_ROLE")
    task = _task(ident)
    event = DB.screenings.get(task["screening_event_id"])
    if task["status"] != "QUEUED":
        fail("ERR_INVALID_STATE")
    if event is None or event["status"] != "ALARMED":
        fail("ERR_SCREENING_EVENT_NOT_ALARMED")
    task["status"] = "IN_PROGRESS"
    task["assigned_to"] = user_id
    touch(DB, task)
    recompute.recompute_station(DB, task["station_id"])
    return ser.inspection(task), 200


@bp.post("/baggage/inspections/<ident>/resolve")
def resolve_inspection(ident):
    authenticate()
    role = request.headers.get("X-User-Role")
    if role != "Screener":
        fail("ERR_FORBIDDEN_ROLE")
    task = _task(ident)
    payload = body()
    resolution = enum_value(payload, "resolution", RESOLUTIONS)
    event = DB.screenings.get(task["screening_event_id"])
    if task["status"] not in ("QUEUED", "IN_PROGRESS"):
        fail("ERR_INVALID_STATE")
    if event is None or event["status"] != "ALARMED":
        fail("ERR_SCREENING_EVENT_NOT_ALARMED")
    task["status"] = "RESOLVED"
    task["resolution"] = resolution
    touch(DB, task)
    bag = _bag(event["bag_id"])
    _apply_screening_status(bag, "CLEARED" if resolution == "CLEARED" else "FAILED")
    recompute.recompute_bag_derived(DB, bag)
    recompute.recompute_station(DB, task["station_id"])
    if bag.get("flight_id"):
        recompute.recompute_flight(DB, bag["flight_id"])
    return ser.inspection(task), 200