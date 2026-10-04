"""Routes: the operations checkpoint, delivery logistics and passenger tracking."""

from datetime import timedelta

from flask import Blueprint, request

from common import authenticate, body, paginate, query_str, require, text
from db import DB, iso, parse_iso, touch
from errors import fail
import calc
import recompute
import serializers as ser

bp = Blueprint("ops", __name__)

MISSABLE_CUSTODY = ("LOADED", "OFFLOADED", "SORTED", "IN_MAKEUP")


def _bag(ident):
    row = DB.bags.get(ident)
    if row is None:
        fail("ERR_BAG_NOT_FOUND")
    return row


def _delivery(ident):
    row = DB.deliveries.get(ident)
    if row is None:
        fail("ERR_INVALID_REQUEST")
    return row


def _report(ident):
    row = DB.reports.get(ident)
    if row is None:
        fail("ERR_REPORT_NOT_FOUND")
    return row


def _listed(rows, query, serializer=lambda r: r):
    rows = ser.sort_rows(rows)
    window, page = paginate(rows, query)
    return [serializer(r) for r in window], page


# ------------------------------------------------------------ run_ops -------
@bp.post("/baggage/stations/<ident>/run_ops")
def run_ops(ident):
    authenticate()
    role = request.headers.get("X-User-Role")
    if role != "PlatformAdmin":
        fail("ERR_FORBIDDEN_ROLE")
    station = DB.stations.get(ident)
    if station is None:
        fail("ERR_INVALID_REQUEST")

    station["ops_run_index"] = station.get("ops_run_index", 0) + 1
    now = DB.now()

    # 1. Stale-acceptance expiry. Bags are walked by created_at ascending; a
    #    shared created_at is broken by the lower ops_run_index_at_acceptance
    #    first, and only then by created_at ascending. The id is never consulted.
    stale = [b for b in DB.bags.values()
             if b["station_id"] == station["id"] and b["custody_status"] == "ACCEPTED"]
    stale.sort(key=lambda b: (-b.get("ops_run_index_at_acceptance", 0), b["created_at"], b.get("_seq", 0)))
    for bag in stale:
        if bag.get("ops_run_index_at_acceptance", 0) <= station["ops_run_index"] - 2:
            bag["custody_status"] = "HELD"
            bag["screening_status"] = "FAILED"
            bag["_was_held"] = True
            recompute.ensure_delivery(DB, bag)
            touch(DB, bag)

    # 2. Missed connections and the automatic recovery edges.
    #    PRD §3.8 marks MISSED only a connection in CONFIRMED or RUSH whose bag
    #    is still live; REACCOMMODATED is left alone so the re-accommodation
    #    loop the PRD describes stays reachable.
    for conn in DB.connections.values():
        bag = DB.bags.get(conn["bag_id"])
        onward = DB.flights.get(conn["onward_flight_id"])
        closed = False
        if onward is not None:
            close = parse_iso(onward["sortation_close_utc"])
            closed = close is not None and now > close
        if bag is not None and (bag["custody_status"] in MISSABLE_CUSTODY) and closed:
            if conn["status"] in ("CONFIRMED", "RUSH"):
                conn["status"] = "MISSED"
                touch(DB, conn)
                bag["priority_score"] = calc.priority_score(DB, bag)
                touch(DB, bag)
        elif conn["status"] in ("MISSED", "REACCOMMODATED") and conn["connect_slack_minutes"] >= 0:
            conn["status"] = "CONFIRMED"
            touch(DB, conn)
            if bag is not None:
                bag["priority_score"] = calc.priority_score(DB, bag)
                touch(DB, bag)

    # 3. Overdue inspection escalation — only while the station is congested or suspended.
    posture = calc.station_posture(DB, station)
    if posture in ("CONGESTED", "SUSPENDED"):
        for task in DB.inspections.values():
            if task["station_id"] != station["id"]:
                continue
            if task["status"] not in ("QUEUED", "IN_PROGRESS"):
                continue
            due = parse_iso(task.get("due_utc"))
            if due is not None and due <= now:
                task["status"] = "ESCALATED"
                touch(DB, task)
                bag = recompute.bag_for_task(DB, task)
                if bag is not None and bag.get("flight_id"):
                    bag["priority_score"] = calc.priority_score(DB, bag)
                    touch(DB, bag)

    # 4. Flight status sweep.
    affected_flights = set()
    for flight in DB.flights.values():
        if flight["status"] == "SCHEDULED":
            opens = parse_iso(flight["sortation_open_utc"])
            if opens is not None and now >= opens:
                flight["status"] = "SORT_OPEN"
                touch(DB, flight)
                affected_flights.add(flight["id"])
        elif flight["status"] == "SORT_OPEN":
            close = parse_iso(flight["sortation_close_utc"])
            ready = calc.flight_makeup_ready(DB, flight["id"])
            if close is not None and now >= close - timedelta(minutes=15) and ready:
                flight["status"] = "BOARDING"
                touch(DB, flight)
                affected_flights.add(flight["id"])

    recompute.recompute_station(DB, station["id"])
    for flight_id in affected_flights:
        recompute.recompute_flight(DB, flight_id)
    return ser.station(DB.stations[station["id"]]), 200


# ------------------------------------------------------------ deliveries ----
@bp.get("/baggage/deliveries/<ident>")
def get_delivery(ident):
    authenticate()
    return ser.delivery(_delivery(ident)), 200


@bp.get("/baggage/deliveries")
def list_deliveries():
    authenticate()
    rows = DB.all_of("deliveries")
    for key in ("bag_id", "mishandled_report_id", "status"):
        value = query_str(key)
        if value is not None:
            rows = [r for r in rows if r.get(key) == value]
    window, page = _listed(rows, request.args, ser.delivery)
    return window, page


@bp.get("/baggage/bags/<ident>/deliveries")
def list_bag_deliveries(ident):
    user_id, role = authenticate()
    bag = _bag(ident)
    if role == "Passenger" and bag.get("passenger_ref") != user_id:
        fail("ERR_FORBIDDEN_ROLE")
    rows = [r for r in DB.deliveries.values() if r["bag_id"] == bag["id"]]
    window, page = _listed(rows, request.args, ser.delivery)
    return window, page


@bp.get("/baggage/reports/<ident>/deliveries")
def list_report_deliveries(ident):
    authenticate()
    report = _report(ident)
    rows = [r for r in DB.deliveries.values() if r["mishandled_report_id"] == report["id"]]
    window, page = _listed(rows, request.args, ser.delivery)
    return window, page


@bp.post("/baggage/deliveries/<ident>/dispatch")
def dispatch_delivery(ident):
    authenticate()
    role = request.headers.get("X-User-Role")
    if role != "BaggageServiceAgent":
        fail("ERR_FORBIDDEN_ROLE")
    delivery = _delivery(ident)
    payload = body()
    require(payload, "courier_ref")
    courier_ref = text(payload, "courier_ref")
    if delivery["status"] != "IN_TRANSIT":
        fail("ERR_INVALID_STATE")
    if delivery["method"] != "COURIER":
        fail("ERR_INVALID_REQUEST")
    delivery["status"] = "OUT_FOR_DELIVERY"
    delivery["courier_ref"] = courier_ref
    touch(DB, delivery)
    return ser.delivery(delivery), 200


@bp.post("/baggage/deliveries/<ident>/complete")
def complete_delivery(ident):
    authenticate()
    role = request.headers.get("X-User-Role")
    if role != "BaggageServiceAgent":
        fail("ERR_FORBIDDEN_ROLE")
    delivery = _delivery(ident)
    payload = body()
    proof = payload.get("proof_of_delivery")
    if delivery["status"] not in ("IN_TRANSIT", "OUT_FOR_DELIVERY"):
        fail("ERR_INVALID_STATE")
    if delivery.get("proof_required") and proof is None:
        fail("ERR_PROOF_OF_DELIVERY_REQUIRED")
    delivery["status"] = "DELIVERED"
    delivery["delivered_utc"] = iso(DB.now())
    touch(DB, delivery)
    return ser.delivery(delivery), 200


# -------------------------------------------------------------- tracking ----
@bp.get("/baggage/tracking/<tag_number>")
def tracking(tag_number):
    user_id, role = authenticate()
    bag = next((b for b in DB.bags.values() if b["tag_number"] == tag_number), None)
    if bag is None:
        fail("ERR_BAG_NOT_FOUND")
    if role == "Passenger" and bag.get("passenger_ref") != user_id:
        fail("ERR_FORBIDDEN_ROLE")
    return ser.tracking(DB, bag), 200