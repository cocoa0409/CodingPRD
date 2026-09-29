"""Movements by rail, barge and truck (PRD 3.7)."""
from flask import Blueprint, request

import calc
import serialize
import validate as v
from auth import ALL_ROLES, LOGISTICS_COORDINATOR, TERMINAL_OPERATOR, actor
from envelope import list_response, object_response, paging
from errors import ApiError
from guards import duplicate, filtered, load, not_frozen, state
from mutate import touch
from store import db, stamp_new

bp = Blueprint("shipments", __name__)
PREFIX = "/nitrogen-ops/shipments"
MODES = ("BARGE", "RAIL", "TRUCK")
SHIPMENT_STATUSES = ("DRAFT", "BOOKED", "IN_TRANSIT", "DELIVERED", "CANCELLED")
SECURE_CLASSES = ("CONTROLLED", "HIGH_SECURITY")


def _regulated_routing(origin, dest):
    """Rung 16: the product line is found by the origin asset's product code."""
    line = calc.line_for_product_code(origin["product_code"])
    if line is None or not line["regulated"]:
        return
    if (origin["security_class"] not in SECURE_CLASSES
            or dest["security_class"] not in SECURE_CLASSES):
        raise ApiError("ERR_SECURITY_CLASS_INSUFFICIENT")


@bp.post(PREFIX)
def create_shipment():
    actor([LOGISTICS_COORDINATOR])
    body = v.get_body()
    origin_id = v.s_id(body, "origin_asset_id")
    dest_id = v.s_id(body, "dest_asset_id")
    order_id = v.s_id(body, "production_order_id", required=False)
    shipment_code = v.s_code(body, "shipment_code", 2, 16)
    mode = v.s_enum(body, "mode", MODES)
    tons = v.s_num(body, "tons", 3, gt=0)
    distance = v.s_num(body, "distance_miles", 1, gt=0)
    window_start = v.s_dt(body, "window_start")
    window_end = v.s_dt(body, "window_end")
    if window_end <= window_start:
        v.bad("window_end must be strictly after window_start.")
    origin = load("assets", origin_id)
    dest = load("assets", dest_id)
    order = load("orders", order_id) if order_id is not None else None
    duplicate("shipments", "shipment_code", shipment_code)
    state(origin["product_code"] == dest["product_code"], "ERR_PRODUCT_MISMATCH")
    if order is not None:
        state(order["destination_asset_id"] == origin_id, "ERR_PRODUCT_MISMATCH",
              "origin_asset_id must equal the order's destination_asset_id.")
    row = {
        "origin_asset_id": origin_id,
        "dest_asset_id": dest_id,
        "production_order_id": order_id,
        "shipment_code": shipment_code,
        "mode": mode,
        "tons": tons,
        "distance_miles": distance,
        "window_start": window_start,
        "window_end": window_end,
        "base_freight_usd": None,
        "fuel_surcharge_usd": None,
        "freight_total_usd": None,
        "freight_per_ton_usd": None,
        "received_tons": None,
        "status": "DRAFT",
        "cancel_reason": None,
    }
    stamp_new(row)
    db.shipments[row["id"]] = row
    return object_response(serialize.shipment_json(row), 201)


@bp.get(PREFIX + "/<id>")
def get_shipment(id):
    actor(ALL_ROLES)
    return object_response(serialize.shipment_json(load("shipments", id)))


@bp.get(PREFIX)
def list_shipments():
    actor(ALL_ROLES)
    limit, offset = paging(request.args)
    rows = filtered("shipments", [
        ("origin_asset_id", v.query_str("origin_asset_id")),
        ("dest_asset_id", v.query_str("dest_asset_id")),
        ("production_order_id", v.query_str("production_order_id")),
        ("status", v.query_enum("status", SHIPMENT_STATUSES)),
        ("mode", v.query_enum("mode", MODES)),
    ])
    return list_response(serialize.dump("shipments", rows), limit, offset)


@bp.post(PREFIX + "/<id>/book")
def book_shipment(id):
    actor([LOGISTICS_COORDINATOR])
    body = v.get_body()
    expected = v.s_int(body, "expected_origin_asset_version", ge=0)
    ship = load("shipments", id)
    state(ship["status"] == "DRAFT")
    order = db.orders.get(ship["production_order_id"])
    if order is not None:
        state(order["allocation_status"] in ("RESERVED", "CONSUMED"))
    origin = db.assets[ship["origin_asset_id"]]
    dest = db.assets[ship["dest_asset_id"]]
    not_frozen(db.plants[origin["plant_id"]])
    state(expected == origin["version"], "ERR_STALE_STORAGE_VERSION")
    _regulated_routing(origin, dest)
    state(origin["product_code"] == dest["product_code"], "ERR_PRODUCT_MISMATCH")
    if order is not None:
        state(order["destination_asset_id"] == origin["id"], "ERR_PRODUCT_MISMATCH",
              "origin_asset_id must equal the order's destination_asset_id.")
    dest_position = calc.storage_position(dest)
    inbound = calc.inbound_committed_tons(dest["id"], ship["id"])
    state(dest_position["on_hand_tons"] + inbound + ship["tons"]
          <= dest["capacity_tons"], "ERR_STORAGE_CAPACITY_EXCEEDED")
    origin_position = calc.storage_position(origin)
    peak = calc.outbound_overlap_peak(origin["id"], ship["window_start"],
                                      ship["window_end"], ship["tons"], ship["id"])
    ceiling = (origin_position["on_hand_tons"]
               - origin_position["seasonal_reserve_tons"])
    state(peak <= ceiling, "ERR_STORAGE_AVAILABILITY_EXCEEDED")
    figures = calc.freight(ship["mode"], ship["tons"], ship["distance_miles"])
    ship.update(figures)
    ship["status"] = "BOOKED"
    touch(ship)
    touch(origin)
    return object_response(serialize.shipment_json(ship))


@bp.post(PREFIX + "/<id>/depart")
def depart_shipment(id):
    actor([LOGISTICS_COORDINATOR])
    v.get_body()
    ship = load("shipments", id)
    state(ship["status"] == "BOOKED")
    state(db.clock >= ship["window_start"],
          message="The logical clock has not reached window_start.")
    ship["status"] = "IN_TRANSIT"
    touch(ship)
    return object_response(serialize.shipment_json(ship))


@bp.post(PREFIX + "/<id>/deliver")
def deliver_shipment(id):
    who = actor([TERMINAL_OPERATOR])
    body = v.get_body()
    received = v.s_num(body, "received_tons", 3, gt=0)
    ship = load("shipments", id)
    if who["user_id"] != ship["dest_asset_id"]:
        raise ApiError("ERR_TERMINAL_NOT_OWNER")
    state(ship["status"] == "IN_TRANSIT")
    if received > ship["tons"]:
        v.bad("received_tons may not exceed the tons tendered.")
    origin = db.assets[ship["origin_asset_id"]]
    dest = db.assets[ship["dest_asset_id"]]
    dest_position = calc.storage_position(dest)
    state(dest_position["on_hand_tons"] + received <= dest["capacity_tons"],
          "ERR_STORAGE_CAPACITY_EXCEEDED")
    ship["received_tons"] = received
    ship["status"] = "DELIVERED"
    touch(ship)
    touch(origin)
    touch(dest)
    return object_response(serialize.shipment_json(ship))


@bp.post(PREFIX + "/<id>/cancel")
def cancel_shipment(id):
    actor([LOGISTICS_COORDINATOR])
    body = v.get_body()
    reason = v.s_str(body, "cancel_reason", min_len=1)
    ship = load("shipments", id)
    state(ship["status"] in ("DRAFT", "BOOKED"))
    was_booked = ship["status"] == "BOOKED"
    ship["status"] = "CANCELLED"
    ship["cancel_reason"] = reason
    touch(ship)
    if was_booked:
        touch(db.assets[ship["origin_asset_id"]])
    return object_response(serialize.shipment_json(ship))
