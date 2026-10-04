"""Freight lanes, routing quotes, and shipments (book/read/list/deliver/cancel)."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

from auth import require_roles
from calc import d3, round_int
from envelope import success_array, success_list, success_obj
from errors import fail
from store import db, get_clock, new_id, stamp_new, to_jsonable, touch
from validate import (body_dict, paginate, req_decimal, req_int, req_str,
                      sort_created)
from dates import parse_iso

bp = Blueprint("freight", __name__)

MODES = ("TRUCK", "RAIL", "BARGE")


# ---------------------------------------------------------------------------
# Freight lanes
# ---------------------------------------------------------------------------

@bp.post("/api/freight-lanes")
def create_lane():
    require_roles("LogisticsCoordinator")
    body = body_dict()
    # Body FKs (priority 4).
    origin = None
    if body.get("origin_elevator_id") is not None:
        origin = db["elevators"].get(body["origin_elevator_id"])
        if origin is None:
            fail("ERR_ELEVATOR_NOT_FOUND", "origin_elevator_id does not resolve")
    dest = None
    if body.get("destination_plant_id") is not None:
        dest = db["plants"].get(body["destination_plant_id"])
        if dest is None:
            fail("ERR_PLANT_NOT_FOUND", "destination_plant_id does not resolve")
    # Shape (priority 9).
    if origin is None:
        fail("ERR_INVALID_REQUEST", "origin_elevator_id is required")
    if dest is None:
        fail("ERR_INVALID_REQUEST", "destination_plant_id is required")
    mode = req_str(body, "mode")
    if mode not in MODES:
        fail("ERR_INVALID_REQUEST", "mode must be TRUCK, RAIL or BARGE")
    freight = req_int(body, "freight_cents_per_bushel")
    if freight < 0:
        fail("ERR_INVALID_REQUEST", "freight_cents_per_bushel must be >= 0")
    transit = req_int(body, "transit_days")
    if transit < 0:
        fail("ERR_INVALID_REQUEST", "transit_days must be >= 0")
    daily_cap = req_int(body, "daily_capacity_bushels")
    if daily_cap <= 0:
        fail("ERR_INVALID_REQUEST", "daily_capacity_bushels must be > 0")
    rec = {
        "id": new_id(),
        "origin_elevator_id": origin["id"],
        "destination_plant_id": dest["id"],
        "mode": mode,
        "freight_cents_per_bushel": freight,
        "transit_days": transit,
        "daily_capacity_bushels": daily_cap,
    }
    stamp_new(rec)
    db["lanes"][rec["id"]] = rec
    return success_obj(to_jsonable(rec), 201)


@bp.get("/api/freight-lanes/<lid>")
def get_lane(lid):
    require_roles("PlatformAdmin", "LogisticsCoordinator")
    rec = db["lanes"].get(lid)
    if rec is None:
        fail("ERR_LANE_NOT_FOUND", "freight lane not found")
    return success_obj(to_jsonable(rec))


@bp.get("/api/freight-lanes")
def list_lanes():
    require_roles("PlatformAdmin", "LogisticsCoordinator")
    items = sort_created(list(db["lanes"].values()))
    origin = request.args.get("origin_elevator_id")
    dest = request.args.get("destination_plant_id")
    if origin is not None:
        items = [l for l in items if l["origin_elevator_id"] == origin]
    if dest is not None:
        items = [l for l in items if l["destination_plant_id"] == dest]
    page, limit, offset, total = paginate(items)
    return success_list([to_jsonable(l) for l in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Destination optimization (calculations.destination_ranking)
# ---------------------------------------------------------------------------

@bp.post("/api/shipment-routing-quotes")
def routing_quote():
    require_roles("LogisticsCoordinator")
    body = body_dict()
    origin = None
    if body.get("origin_elevator_id") is not None:
        origin = db["elevators"].get(body["origin_elevator_id"])
        if origin is None:
            fail("ERR_ELEVATOR_NOT_FOUND", "origin_elevator_id does not resolve")
    if origin is None:
        fail("ERR_INVALID_REQUEST", "origin_elevator_id is required")
    bushels = req_decimal(body, "bushels")
    if bushels <= 0:
        fail("ERR_INVALID_REQUEST", "bushels must be > 0")
    candidates = []
    for lane in db["lanes"].values():
        if lane["origin_elevator_id"] != origin["id"]:
            continue
        plant = db["plants"].get(lane["destination_plant_id"])
        if plant is None or plant["status"] != "ACTIVE":
            continue
        if lane["mode"] != "BARGE" and lane["daily_capacity_bushels"] < bushels:
            continue
        candidates.append(lane)
    if not candidates:
        fail("ERR_NO_ROUTE_AVAILABLE", "no eligible lane from this origin")
    # freight ASC, transit_days ASC, created_at ASC; ids never break ties.
    candidates.sort(key=lambda l: (l["freight_cents_per_bushel"],
                                   l["transit_days"], l["_seq"]))
    return success_array([to_jsonable(l) for l in candidates])


# ---------------------------------------------------------------------------
# Shipments
# ---------------------------------------------------------------------------

def _derive_gate(elevator):
    elevator["receiving_open"] = (
        elevator["stored_bushels"] < elevator["storage_capacity_bushels"])


@bp.post("/api/shipments")
def create_shipment():
    require_roles("LogisticsCoordinator")
    body = body_dict()
    # Body FKs (priority 4).
    lane = None
    if body.get("lane_id") is not None:
        lane = db["lanes"].get(body["lane_id"])
        if lane is None:
            fail("ERR_LANE_NOT_FOUND", "lane_id does not resolve")
    program = None
    if body.get("certified_program_id") is not None:
        program = db["programs"].get(body["certified_program_id"])
        if program is None:
            fail("ERR_PROGRAM_NOT_FOUND", "certified_program_id does not resolve")
    # Shape baseline for fields every later rule needs.
    if lane is None:
        fail("ERR_INVALID_REQUEST", "lane_id is required")
    bushels = req_decimal(body, "bushels")
    if bushels <= 0:
        fail("ERR_INVALID_REQUEST", "bushels must be > 0")
    bushels = d3(bushels)
    departure = None
    if body.get("departure_date") is not None:
        departure = parse_iso(body["departure_date"])
    if departure is None:
        fail("ERR_INVALID_REQUEST", "departure_date must be an ISO 8601 datetime")
    # Temporal (priority 7): departure not before the current clock date.
    clock = get_clock()
    if departure.date() < clock.date():
        fail("ERR_RUN_DATE_IN_PAST",
             "departure_date is before the current logical clock date")
    # Eligible drawable lots at the origin, oldest first.
    lots = [p for p in db["positions"].values()
            if p["elevator_id"] == lane["origin_elevator_id"]
            and p["current_bushels"] > 0]
    lots.sort(key=lambda p: p["_seq"])
    if program is not None:
        eligible = [p for p in lots if p["program_id"] == program["id"]]
    else:
        eligible = [p for p in lots if p["program_id"] is None]
    supply = sum((p["current_bushels"] for p in eligible), Decimal(0))
    # Safety (priority 8): certified chain of custody.
    if program is not None and supply < bushels:
        fail("ERR_CERTIFICATION_BREAK",
             "certified supply at origin cannot fill this booking")
    # Capacity (priority 10): lane occupancy by mode.
    arrival = departure + timedelta(days=lane["transit_days"])
    if lane["mode"] in ("TRUCK", "RAIL"):
        used = sum((s["bushels"] for s in db["shipments"].values()
                    if s["lane_id"] == lane["id"] and s["status"] != "CANCELLED"
                    and s["departure_date"].date() == departure.date()),
                   Decimal(0))
        if used + bushels > lane["daily_capacity_bushels"]:
            fail("ERR_LANE_DAILY_CAPACITY_EXCEEDED",
                 "lane per-departure-date capacity exceeded")
    else:  # BARGE: half-open [departure, arrival) overlap, back-to-back allowed
        for s in db["shipments"].values():
            if s["lane_id"] != lane["id"] or s["status"] != "BOOKED":
                continue
            if departure < s["arrival_date"] and s["departure_date"] < arrival:
                fail("ERR_BARGE_SCHEDULE_OVERLAP",
                     "barge interval overlaps another booked movement on this lane")
    # Drawable supply (priority 10) for conventional bookings.
    if program is None and supply < bushels:
        fail("ERR_INSUFFICIENT_STORED_BUSHELS",
             "drawable storage at the origin cannot fill this booking")
    # Execute the FIFO draws.
    need = bushels
    draws = []
    for p in eligible:
        if need <= 0:
            break
        take = min(need, p["current_bushels"])
        p["current_bushels"] = Decimal(p["current_bushels"]) - take
        if p["current_bushels"] == 0:
            p["status"] = "DEPLETED"
        touch(p)
        draws.append({"position_id": p["id"], "bushels": take})
        need -= take
    # Elevator counters + gate.
    elevator = db["elevators"][lane["origin_elevator_id"]]
    elevator["stored_bushels"] = Decimal(elevator["stored_bushels"]) - bushels
    if program is not None:
        elevator["certified_stored_bushels"] = (
            Decimal(elevator["certified_stored_bushels"]) - bushels)
    _derive_gate(elevator)
    touch(elevator)
    rec = {
        "id": new_id(),
        "lane_id": lane["id"],
        "bushels": bushels,
        "departure_date": departure,
        "certified_program_id": program["id"] if program else None,
        "arrival_date": arrival,
        "freight_cost_cents": round_int(bushels * lane["freight_cents_per_bushel"]),
        "draws": draws,
        "status": "BOOKED",
    }
    stamp_new(rec)
    db["shipments"][rec["id"]] = rec
    return success_obj(to_jsonable(rec), 201)


@bp.get("/api/shipments/<sid>")
def get_shipment(sid):
    require_roles("PlatformAdmin", "LogisticsCoordinator")
    rec = db["shipments"].get(sid)
    if rec is None:
        fail("ERR_SHIPMENT_NOT_FOUND", "shipment not found")
    return success_obj(to_jsonable(rec))


@bp.get("/api/shipments")
def list_shipments():
    require_roles("PlatformAdmin", "LogisticsCoordinator")
    items = sort_created(list(db["shipments"].values()))
    lane_id = request.args.get("lane_id")
    certified = request.args.get("certified_program_id")
    if lane_id is not None:
        items = [s for s in items if s["lane_id"] == lane_id]
    if certified is not None:
        items = [s for s in items if s["certified_program_id"] == certified]
    page, limit, offset, total = paginate(items)
    return success_list([to_jsonable(s) for s in page], limit, offset, total)


def _get_shipment_booked(sid):
    s = db["shipments"].get(sid)
    if s is None:
        fail("ERR_SHIPMENT_NOT_FOUND", "shipment not found")
    if s["status"] != "BOOKED":
        fail("ERR_INVALID_STATE", "shipment is not in BOOKED")
    return s


@bp.post("/api/shipments/<sid>/deliver")
def deliver_shipment(sid):
    require_roles("LogisticsCoordinator")
    s = _get_shipment_booked(sid)
    clock = get_clock()
    if clock < s["arrival_date"]:
        fail("ERR_SHIPMENT_NOT_ARRIVED",
             "current logical clock has not reached arrival_date")
    lane = db["lanes"][s["lane_id"]]
    plant = db["plants"][lane["destination_plant_id"]]
    plant["bean_inventory_bushels"] = (
        Decimal(plant["bean_inventory_bushels"]) + Decimal(s["bushels"]))
    touch(plant)
    s["status"] = "DELIVERED"
    touch(s)
    return success_obj(to_jsonable(s))


@bp.post("/api/shipments/<sid>/cancel")
def cancel_shipment(sid):
    require_roles("LogisticsCoordinator")
    s = _get_shipment_booked(sid)
    # Compensation: restore every drawn lot exactly, in reverse draw order.
    for d in reversed(s["draws"]):
        pos = db["positions"].get(d["position_id"])
        if pos is None:
            continue
        pos["current_bushels"] = Decimal(pos["current_bushels"]) + Decimal(d["bushels"])
        if pos["status"] == "DEPLETED" and pos["current_bushels"] > 0:
            pos["status"] = "OPEN"
        touch(pos)
    lane = db["lanes"][s["lane_id"]]
    elevator = db["elevators"][lane["origin_elevator_id"]]
    elevator["stored_bushels"] = Decimal(elevator["stored_bushels"]) + Decimal(s["bushels"])
    if s["certified_program_id"]:
        elevator["certified_stored_bushels"] = (
            Decimal(elevator["certified_stored_bushels"]) + Decimal(s["bushels"]))
    _derive_gate(elevator)
    touch(elevator)
    s["status"] = "CANCELLED"
    touch(s)
    return success_obj(to_jsonable(s))
