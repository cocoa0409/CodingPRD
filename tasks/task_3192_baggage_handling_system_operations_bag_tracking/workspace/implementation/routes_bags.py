"""Routes: bag acceptance, particulars, scans, and the custody/weigh advances."""

from datetime import timedelta

from flask import Blueprint, request

from common import (
    authenticate, body, datetime_value, enum_value, integer, number, paginate,
    query_str, require, text, version_token,
)
from db import DB, new_row, iso, parse_iso, touch
from errors import fail
import calc
import recompute
import serializers as ser

bp = Blueprint("bags", __name__)

ITINERARY = ("DOMESTIC", "INTERNATIONAL", "INTERLINE")
SCAN_POINTS = ("INDUCTION", "SCREENING", "SORTATION", "MAKEUP", "LOAD", "DELIVERY")
CUSTODY = ("ACCEPTED", "SCREENING", "SORTED", "IN_MAKEUP", "LOADED", "DELIVERED", "HELD", "OFFLOADED")
SCREENING = ("PENDING", "IN_LINE", "CLEARED", "ALARMED", "IN_INSPECTION", "FAILED")

BAG_WRITE_ROLES = ("AcceptanceAgent", "SortationAgent", "LoadAgent", "Screener",
                   "TransferAgent", "BaggageServiceAgent", "Passenger", "PlatformAdmin")


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


def _station(ident):
    row = DB.stations.get(ident)
    if row is None:
        fail("ERR_INVALID_REQUEST")
    return row


def _guard_passenger(role, user_id, bag):
    """The Passenger role is entity-backed by the bag's passenger_ref."""
    if role == "Passenger" and bag.get("passenger_ref") != user_id:
        fail("ERR_FORBIDDEN_ROLE")


def _guard_station_suspended(bag):
    station = calc.station_of(DB, bag)
    if station is not None and station.get("posture") == "SUSPENDED":
        fail("ERR_STATION_SUSPENDED")


def _guard_screening_cleared(bag):
    """PRD §3.6, §3.7 and §2.13's screening-clearance rung.

    §2.13 names the three statuses that may not advance past the screening stage,
    and §3.6/§3.7 spell the same requirement positively for the make-up and load
    advances: the bag's screening status "must be `CLEARED`".  A bag still in
    `PENDING` or `IN_LINE` has no clearance either, so the gate keys on clearance
    rather than on the three member names alone.
    """
    if bag["screening_status"] != "CLEARED":
        fail("ERR_SCREENING_NOT_CLEARED")


def _listed(rows, query, serializer=lambda r: r):
    rows = ser.sort_rows(rows)
    window, page = paginate(rows, query)
    return [serializer(r) for r in window], page


# ---------------------------------------------------------------- accept ----
@bp.post("/baggage/bags")
def accept_bag():
    _, role = authenticate()
    if role != "AcceptanceAgent":
        fail("ERR_FORBIDDEN_ROLE")
    payload = body()
    require(payload, "station_id", "passenger_name", "passenger_ref", "itinerary_type",
            "weight_lb", "length_in", "width_in", "height_in")
    station = _station(text(payload, "station_id"))
    flight = None
    if payload.get("flight_id"):
        flight = _flight(text(payload, "flight_id"))
    itinerary = enum_value(payload, "itinerary_type", ITINERARY)
    weight_lb = number(payload, "weight_lb")
    length_in = number(payload, "length_in")
    width_in = number(payload, "width_in")
    height_in = number(payload, "height_in")
    linear_in = length_in + width_in + height_in

    # Weight and size envelope (priority 6), then the interline agreement (priority 10).
    airline = DB.airlines.get(flight["airline_id"]) if flight else None
    if airline is not None and weight_lb > airline["max_excess_weight_lb"] + 20:
        fail("ERR_BAG_OVERWEIGHT")
    if linear_in > 130:
        fail("ERR_BAG_OVERSIZE")
    if itinerary == "INTERLINE":
        if airline is None or not airline["interline_agreement_active"]:
            fail("ERR_INTERLINE_AGREEMENT_INACTIVE")

    row = new_row(DB, {
        "station_id": station["id"],
        "flight_id": flight["id"] if flight else None,
        "makeup_area_id": None,
        "tag_number": DB.new_tag_number(),
        "passenger_name": text(payload, "passenger_name"),
        "passenger_ref": text(payload, "passenger_ref"),
        "itinerary_type": itinerary,
        "weight_lb": weight_lb,
        "scale_weight_lb": None,
        "weight_variance_lb": None,
        "length_in": length_in,
        "width_in": width_in,
        "height_in": height_in,
        "linear_in": linear_in,
        "custody_status": "ACCEPTED",
        "screening_status": "PENDING",
        "routing_class": "STANDARD",
        "excess_weight_fee_cents": 0,
        "handling_charge_cents": 0,
        "priority_score": 0,
        "assigned_makeup_utc": None,
        "loaded_utc": None,
        "delivered_utc": None,
        "ops_run_index_at_acceptance": station["ops_run_index"],
        "manual_sortation_delay_minutes": 0,
        "screen_alarm_resolution_time_minutes": 0,
        "anomaly_note": None,
        "rush_declared": False,
        "duplicate_flag": False,
        "_was_held": False,
    })
    DB.add("bags", row)
    # The row is minted at version 1 and acceptance is its creation, not a
    # modification of it, so no self-mutation is applied here.  Every derived
    # field the response publishes (priority_score, duplicate_flag,
    # rush_declared, the delay metrics) is computed at serialization time.
    row["handling_charge_cents"] = calc.handling_charge(DB, row, "PROVISIONAL")
    recompute.recompute_station(DB, station["id"])
    if flight is not None:
        recompute.recompute_flight(DB, flight["id"])
    return ser.bag(DB, row), 201


# ------------------------------------------------------------------ read ----
@bp.get("/baggage/bags/<ident>")
def get_bag(ident):
    user_id, role = authenticate()
    row = _bag(ident)
    _guard_passenger(role, user_id, row)
    station = calc.station_of(DB, row)
    if station is not None:
        station["active_bag_count"] = calc.active_bag_count(DB, station["id"])
    return ser.bag(DB, row), 200


@bp.get("/baggage/bags")
def list_bags():
    user_id, role = authenticate()
    rows = DB.all_of("bags")
    if role == "Passenger":
        rows = [r for r in rows if r.get("passenger_ref") == user_id]
    for key in ("station_id", "flight_id", "makeup_area_id", "custody_status",
                "screening_status", "passenger_ref"):
        value = query_str(key)
        if value is not None:
            rows = [r for r in rows if r.get(key) == value]
    window, page = _listed(rows, request.args, lambda r: ser.bag(DB, r))
    return window, page


@bp.get("/baggage/stations/<ident>/bags")
def list_station_bags(ident):
    authenticate()
    station = DB.stations.get(ident)
    if station is None:
        fail("ERR_INVALID_REQUEST")
    rows = [r for r in DB.bags.values() if r.get("station_id") == station["id"]]
    window, page = _listed(rows, request.args, lambda r: ser.bag(DB, r))
    return window, page


@bp.get("/baggage/flights/<ident>/bags")
def list_flight_bags(ident):
    authenticate()
    flight = _flight(ident)
    rows = [r for r in DB.bags.values() if r.get("flight_id") == flight["id"]]
    window, page = _listed(rows, request.args, lambda r: ser.bag(DB, r))
    return window, page


@bp.get("/baggage/makeup-areas/<ident>/bags")
def list_area_bags(ident):
    authenticate()
    area = DB.makeup_areas.get(ident)
    if area is None:
        fail("ERR_INVALID_REQUEST")
    rows = [r for r in DB.bags.values() if r.get("makeup_area_id") == area["id"]]
    window, page = _listed(rows, request.args, lambda r: ser.bag(DB, r))
    return window, page


@bp.get("/baggage/airlines/<ident>/bags")
def list_airline_bags(ident):
    authenticate()
    airline = DB.airlines.get(ident)
    if airline is None:
        fail("ERR_INVALID_REQUEST")
    flight_ids = {f["id"] for f in DB.flights.values() if f["airline_id"] == airline["id"]}
    rows = [r for r in DB.bags.values() if r.get("flight_id") in flight_ids]
    window, page = _listed(rows, request.args, lambda r: ser.bag(DB, r))
    return window, page


# -------------------------------------------------------------- correction --
@bp.put("/baggage/bags/<ident>")
def correct_bag(ident):
    user_id, role = authenticate()
    if role not in ("Screener", "AcceptanceAgent"):
        fail("ERR_FORBIDDEN_ROLE")
    row = _bag(ident)
    payload = body()
    expected = version_token(payload, "expected_bag_version")
    note_supplied = payload.get("anomaly_note") is not None

    if note_supplied:
        status = row["screening_status"]
        if status == "CLEARED":
            if row["custody_status"] not in ("ACCEPTED", "SCREENING", "SORTED", "HELD"):
                fail("ERR_INVALID_STATE")
        elif status == "FAILED":
            pass
        else:
            fail("ERR_INVALID_STATE")

    if expected != row["version"]:
        fail("ERR_STALE_VERSION")

    if "weight_lb" in payload and payload["weight_lb"] is not None:
        row["weight_lb"] = number(payload, "weight_lb")
        if row.get("scale_weight_lb") is not None:
            row["weight_variance_lb"] = row["scale_weight_lb"] - row["weight_lb"]

    if note_supplied:
        row["anomaly_note"] = text(payload, "anomaly_note")
        if row["screening_status"] == "CLEARED":
            row["screening_status"] = "IN_LINE"
            recompute.append_scan(DB, row, "SCREENING")
        elif row["screening_status"] == "FAILED":
            # Cycle edge 2: the failed bag is re-inspected; its custody stays put.
            row["screening_status"] = "IN_INSPECTION"
            recompute.ensure_delivery(DB, row)

    recompute.recompute_bag_derived(DB, row)
    recompute.recompute_after_bag_write(DB, row)
    recompute.recompute_station(DB, row["station_id"])
    return ser.bag(DB, row), 200


# ------------------------------------------------------------------ weigh ---
@bp.post("/baggage/bags/<ident>/weigh")
def weigh_bag(ident):
    _, role = authenticate()
    if role != "AcceptanceAgent":
        fail("ERR_FORBIDDEN_ROLE")
    row = _bag(ident)
    payload = body()
    scale_weight_lb = number(payload, "scale_weight_lb")

    if row["custody_status"] == "HELD":
        # PRD §3.5 states the re-induction refusals directly on the held bag, so
        # they are the rung this state reaches first.
        if row["linear_in"] > 130:
            fail("ERR_BAG_OVERSIZE")
        station = calc.station_of(DB, row)
        outage = bool(station and station.get("outage_active"))
        if recompute.open_task_for_bag(DB, row["id"]) is not None:
            fail("ERR_MANUAL_INSPECTION_REQUIRED")
        if not (outage or row["screening_status"] in ("ALARMED", "CLEARED")):
            fail("ERR_OUTAGE_NOT_ACTIVE")
        row["custody_status"] = "ACCEPTED"
    elif row["custody_status"] == "ACCEPTED":
        flight = calc.flight_of(DB, row)
        airline = DB.airlines.get(flight["airline_id"]) if flight else None
        if airline is not None and row["weight_lb"] > airline["max_excess_weight_lb"] + 20:
            fail("ERR_BAG_OVERWEIGHT")
        if row["linear_in"] > 130:
            fail("ERR_BAG_OVERSIZE")
        row["custody_status"] = "SCREENING"
    else:
        fail("ERR_INVALID_STATE")

    row["scale_weight_lb"] = scale_weight_lb
    row["weight_variance_lb"] = scale_weight_lb - row["weight_lb"]
    row["excess_weight_fee_cents"] = calc.excess_weight_fee(DB, row)
    row["routing_class"] = calc.routing_class(DB, row)
    row["handling_charge_cents"] = calc.handling_charge(DB, row, "PROVISIONAL")
    row["screening_status"] = "PENDING"
    row["screening_status"] = "IN_LINE"
    recompute.append_scan(DB, row, "INDUCTION")
    recompute.recompute_bag_derived(DB, row)
    recompute.recompute_after_bag_write(DB, row)
    return ser.bag(DB, row), 200


# -------------------------------------------------------------- make-up -----
def _makeup_bucket(moment, buffer_minutes):
    if buffer_minutes <= 0:
        buffer_minutes = 15
    total = int(moment.timestamp())
    size = buffer_minutes * 60
    return (total - (total % size)) // size


def _area_buckets(area):
    buffer_minutes = area["buffer_minutes"]
    buckets = set()
    for other in DB.bags.values():
        if other.get("makeup_area_id") != area["id"]:
            continue
        if other["custody_status"] not in ("SORTED", "IN_MAKEUP"):
            continue
        when = parse_iso(other.get("assigned_makeup_utc"))
        if when is None:
            continue
        buckets.add(_makeup_bucket(when, buffer_minutes))
    return buckets


def _assign_makeup_core(bag, payload, expected):
    # Priority ladder: suspension (3), clearance (4), state (5), scheduling (7),
    # area admission (8), manual-inspection gate (11), concurrency (14), existence (15).
    _guard_station_suspended(bag)
    _guard_screening_cleared(bag)
    if bag["custody_status"] != "SORTED":
        fail("ERR_INVALID_STATE")
    if not bag.get("flight_id"):
        fail("ERR_FLIGHT_NOT_ASSIGNED")
    flight = DB.flights.get(bag["flight_id"])
    if flight is None:
        fail("ERR_FLIGHT_NOT_FOUND")
    if flight["status"] not in ("SCHEDULED", "SORT_OPEN"):
        fail("ERR_FLIGHT_NOT_SORTING")
    close = parse_iso(flight["sortation_close_utc"])
    if close and DB.now() > close:
        fail("ERR_SORTATION_WINDOW_CLOSED")

    require(payload, "makeup_area_id", "induction_utc", "makeup_interval_minutes")
    area_id = text(payload, "makeup_area_id")
    area = DB.makeup_areas.get(area_id)
    induction = datetime_value(payload, "induction_utc")
    integer(payload, "makeup_interval_minutes")
    if area is not None:
        if area["status"] != "ACTIVE":
            fail("ERR_MAKEUP_AREA_CLOSED")
        bucket = _makeup_bucket(induction, area["buffer_minutes"])
        buckets = _area_buckets(area)
        if bucket in buckets or len(buckets) >= area["capacity_slots"]:
            fail("ERR_MAKEUP_SLOT_CONFLICT")

    if recompute.open_task_for_bag(DB, bag["id"]) is not None:
        fail("ERR_MANUAL_INSPECTION_REQUIRED")

    if expected != bag["version"]:
        fail("ERR_STALE_VERSION")

    if area is None:
        fail("ERR_INVALID_REQUEST")

    bag["custody_status"] = "IN_MAKEUP"
    bag["makeup_area_id"] = area["id"]
    bag["assigned_makeup_utc"] = iso(induction)
    recompute.append_scan(DB, bag, "SORTATION")

    recompute.recompute_area(DB, area["id"])
    recompute.recompute_station(DB, bag["station_id"])
    if DB.makeup_areas[area["id"]]["free_slots"] == 0:
        recompute.restamp_overdue_tasks(DB, bag["station_id"])
    recompute.special_item_safeguard(DB, bag)
    recompute.recompute_station(DB, bag["station_id"])
    recompute.recompute_flight(DB, flight["id"])
    recompute.recompute_bag_derived(DB, bag)
    return bag


@bp.post("/baggage/bags/<ident>/assign-makeup")
def assign_makeup(ident):
    _, role = authenticate()
    if role != "SortationAgent":
        fail("ERR_FORBIDDEN_ROLE")
    bag = _bag(ident)
    payload = body()
    expected = version_token(payload, "expected_bag_version")
    _assign_makeup_core(bag, payload, expected)
    return ser.bag(DB, bag), 200


@bp.post("/baggage/bags/bulk-assign-makeup")
def bulk_assign_makeup(ident=None):
    _, role = authenticate()
    if role != "SortationAgent":
        fail("ERR_FORBIDDEN_ROLE")
    payload = body()
    assignments = payload.get("assignments")
    if not isinstance(assignments, list):
        fail("ERR_INVALID_REQUEST")
    assigned = []
    rejected = []
    for item in assignments:
        if not isinstance(item, dict):
            fail("ERR_INVALID_REQUEST")
        bag_id = item.get("bag_id")
        bag = DB.bags.get(bag_id)
        if bag is None:
            rejected.append({"bag_id": bag_id, "error_code": "ERR_BAG_NOT_FOUND"})
            continue
        expected = version_token(item, "expected_bag_version")
        try:
            _assign_makeup_core(bag, item, expected)
        except Exception as exc:
            code = getattr(exc, "error_id", None)
            if code is None:
                raise
            rejected.append({"bag_id": bag_id, "error_code": code})
            continue
        assigned.append(ser.bag(DB, bag))
    return {"assigned": assigned, "rejected": rejected}, 200


# ----------------------------------------------------------------- load -----
@bp.post("/baggage/bags/<ident>/load")
def load_bag(ident):
    _, role = authenticate()
    if role != "LoadAgent":
        fail("ERR_FORBIDDEN_ROLE")
    bag = _bag(ident)
    _guard_station_suspended(bag)
    _guard_screening_cleared(bag)
    if bag["custody_status"] != "IN_MAKEUP":
        fail("ERR_INVALID_STATE")
    if bag.get("duplicate_flag"):
        fail("ERR_DUPLICATE_BAG_ON_FLIGHT")
    if recompute.open_task_for_bag(DB, bag["id"]) is not None:
        fail("ERR_MANUAL_INSPECTION_REQUIRED")
    station = calc.station_of(DB, bag)
    if station is not None and calc.manual_rate_limited(DB, station, bag):
        fail("ERR_MAKEUP_RATE_LIMITED")
    conn = calc.connection_of(DB, bag["id"])
    if conn is not None and conn["status"] not in ("CONFIRMED", "RUSH"):
        fail("ERR_CONNECTION_MISSED")
    flight = DB.flights.get(bag["flight_id"]) if bag.get("flight_id") else None
    if flight is not None:
        close = parse_iso(flight["sortation_close_utc"])
        if close and DB.now() > close:
            fail("ERR_SORTATION_WINDOW_CLOSED")

    recompute.append_scan(DB, bag, "MAKEUP")
    bag["custody_status"] = "LOADED"
    bag["loaded_utc"] = iso(DB.now())
    bag["handling_charge_cents"] = calc.handling_charge(DB, bag, "FINAL")
    recompute.append_scan(DB, bag, "LOAD")
    recompute.recompute_bag_derived(DB, bag)
    recompute.recompute_after_bag_write(DB, bag)
    return ser.bag(DB, bag), 200


@bp.post("/baggage/bags/<ident>/deliver")
def deliver_bag(ident):
    _, role = authenticate()
    if role != "LoadAgent":
        fail("ERR_FORBIDDEN_ROLE")
    bag = _bag(ident)
    _guard_station_suspended(bag)
    if bag["custody_status"] != "LOADED":
        fail("ERR_INVALID_STATE")
    flight = DB.flights.get(bag["flight_id"]) if bag.get("flight_id") else None
    if flight is None or flight["status"] != "DEPARTED":
        fail("ERR_FLIGHT_NOT_DEPARTED")
    bag["custody_status"] = "DELIVERED"
    bag["delivered_utc"] = iso(DB.now())
    bag["handling_charge_cents"] = calc.handling_charge(DB, bag, "FINAL")
    recompute.append_scan(DB, bag, "DELIVERY")
    recompute.recompute_bag_derived(DB, bag)
    recompute.recompute_after_bag_write(DB, bag)
    return ser.bag(DB, bag), 200


@bp.post("/baggage/bags/<ident>/offload")
def offload_bag(ident):
    _, role = authenticate()
    if role != "LoadAgent":
        fail("ERR_FORBIDDEN_ROLE")
    bag = _bag(ident)
    if bag["custody_status"] != "LOADED":
        fail("ERR_INVALID_STATE")
    bag["custody_status"] = "OFFLOADED"
    bag["handling_charge_cents"] = calc.handling_charge(DB, bag, "FINAL")
    conn = calc.connection_of(DB, bag["id"])
    if conn is not None:
        onward = DB.flights.get(conn["onward_flight_id"])
        close = parse_iso(onward["sortation_close_utc"]) if onward else None
        if close is not None and DB.now() > close:
            conn["status"] = "MISSED"
        else:
            conn["status"] = "CONFIRMED"
        touch(DB, conn)
    recompute.ensure_delivery(DB, bag)
    report = new_row(DB, {
        "bag_id": bag["id"],
        "station_id": bag["station_id"],
        "report_type": "DELAYED",
        "status": "REPORTED",
        "delivery_method": None,
        "compensation_offer_cents": 0,
        "claim_status": "NONE",
        "claim_amount_cents": 0,
        "approved_cents": 0,
        "compensation_settled_cents": 0,
        "final_liability_cents": 0,
        "outage_context": False,
    })
    DB.add("reports", report)
    recompute.recompute_report_money(DB, report)
    recompute.recompute_bag_derived(DB, bag)
    recompute.recompute_after_bag_write(DB, bag)
    recompute.recompute_station(DB, bag["station_id"])
    return ser.bag(DB, bag), 200


# ----------------------------------------------------------------- scans ----
@bp.post("/baggage/bags/<ident>/scans")
def create_scan(ident):
    user_id, role = authenticate()
    if role not in ("AcceptanceAgent", "SortationAgent", "LoadAgent", "Screener"):
        fail("ERR_FORBIDDEN_ROLE")
    bag = _bag(ident)
    payload = body()
    point = enum_value(payload, "scan_point", SCAN_POINTS)
    forced = False
    if "scan_source" in payload and payload["scan_source"] is not None:
        source = enum_value(payload, "scan_source", ("AUTOMATED", "MANUAL"))
        forced = source == "MANUAL"
    row = recompute.append_scan(DB, bag, point, forced_manual=forced)
    bag["priority_score"] = calc.priority_score(DB, bag)
    touch(DB, bag)
    return ser.scan(row), 201


@bp.get("/baggage/bags/<ident>/scans")
def list_bag_scans(ident):
    user_id, role = authenticate()
    bag = _bag(ident)
    _guard_passenger(role, user_id, bag)
    rows = calc.scans_of(DB, bag["id"])
    window, page = _listed(rows, request.args, ser.scan)
    return window, page


@bp.get("/baggage/scans")
def list_scans():
    authenticate()
    rows = DB.all_of("scans")
    bag_id = query_str("bag_id")
    point = query_str("scan_point")
    if bag_id:
        if DB.bags.get(bag_id) is None:
            fail("ERR_BAG_NOT_FOUND")
        rows = [r for r in rows if r["bag_id"] == bag_id]
    if point:
        rows = [r for r in rows if r["scan_point"] == point]
    window, page = _listed(rows, request.args, ser.scan)
    return window, page