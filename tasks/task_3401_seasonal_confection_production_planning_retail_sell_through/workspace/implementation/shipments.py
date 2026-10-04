"""Shipment routes: create (FEFO draw from AVAILABLE lots), read, list, deliver."""

from flask import Blueprint, request

from db import db, touch, fmt_instant
from domain import (
    get_shipment, ser_shipment, lot_draw_order, delivered_units_of_commitment,
)
from errors import (
    ApiError, ERR_COMMITMENT_NOT_FOUND, ERR_WAREHOUSE_NOT_FOUND,
    ERR_INVALID_STATE, ERR_SHIP_WINDOW_VIOLATION, ERR_SHIPMENT_EXCEEDS_ALLOCATION,
    ERR_INSUFFICIENT_STOCK,
)
from middleware import authorize, ROLE_LOGISTICS_COORDINATOR, ALL_ROLES
from programs import _create_entity
from respond import ok, created, ok_list, paginate, parse_pagination
from validate import json_body, v_str, v_int, v_bool, v_dt

bp = Blueprint("shipments", __name__)


@bp.post("/confection/shipments")
def create_shipment():
    data = json_body()
    commitment_id = v_str(data, "commitment_id")
    warehouse_id = v_str(data, "warehouse_id")
    units = v_int(data, "units", min_v=1)
    ship_dt, ship_raw = v_dt(data, "ship_on")
    temp_controlled = v_bool(data, "temp_controlled")
    declined = v_bool(data, "temp_control_declined_by_retailer", required=False, default=False)

    authorize(ROLE_LOGISTICS_COORDINATOR)

    # Body FKs in declared input order: commitment_id, warehouse_id.
    commitment = db.commitments.get(commitment_id)
    if commitment is None:
        raise ApiError(404, ERR_COMMITMENT_NOT_FOUND,
                       "RetailerCommitment %s does not exist" % commitment_id)
    warehouse = db.warehouses.get(warehouse_id)
    if warehouse is None:
        raise ApiError(404, ERR_WAREHOUSE_NOT_FOUND,
                       "Warehouse %s does not exist" % warehouse_id)

    program = db.programs[commitment["program_id"]]

    # Temporal (priority 9): ship_on inside BOTH ship windows, closes inclusive.
    in_commitment = commitment["_ship_open_dt"] <= ship_dt <= commitment["_ship_close_dt"]
    in_program = program["_ship_window_open_dt"] <= ship_dt <= program["_ship_window_close_dt"]
    if not (in_commitment and in_program):
        raise ApiError(422, ERR_SHIP_WINDOW_VIOLATION,
                       "ship_on must lie inside both the commitment and program ship windows")

    # Structural (priority 10): cumulative shipped units must not exceed allocation.
    cumulative = sum(s["units"] for s in db.shipments.values()
                     if s["commitment_id"] == commitment_id
                     and s["status"] in ("PLANNED", "DELIVERED"))
    if cumulative + units > commitment["allocated_units"]:
        raise ApiError(422, ERR_SHIPMENT_EXCEEDS_ALLOCATION,
                       "cumulative shipment units would exceed the commitment's allocated_units")

    # Capacity (priority 11): FEFO stock sufficiency, checked atomically first.
    available = [l for l in db.lots.values()
                 if l["warehouse_id"] == warehouse_id
                 and l["product_id"] == commitment["product_id"]
                 and l["status"] == "AVAILABLE" and l["units_on_hand"] > 0]
    if sum(l["units_on_hand"] for l in available) < units:
        raise ApiError(409, ERR_INSUFFICIENT_STOCK,
                       "AVAILABLE lots at this warehouse hold fewer units than requested")

    # FEFO draw: created_at ASC, lot_code ASC; a lot hitting zero -> DEPLETED.
    draws = []
    remaining = units
    for lot in lot_draw_order(available):
        if remaining == 0:
            break
        take = min(lot["units_on_hand"], remaining)
        lot["units_on_hand"] -= take
        remaining -= take
        draws.append((lot["id"], take))
        if lot["units_on_hand"] == 0:
            lot["status"] = "DEPLETED"
        touch(lot)

    shipment = _create_entity(db.shipments, {
        "commitment_id": commitment_id,
        "warehouse_id": warehouse_id,
        "units": units,
        "ship_on": ship_raw,
        "_ship_dt": ship_dt,
        "temp_controlled": temp_controlled,
        "temp_control_declined_by_retailer": declined,
        "delivered_on": None,
        "status": "PLANNED",
        "_draws": draws,
    })

    # The first shipment against an ALLOCATED or SHORTED commitment moves it
    # to FULFILLING.
    if commitment["status"] in ("ALLOCATED", "SHORTED"):
        commitment["status"] = "FULFILLING"
        touch(commitment)

    return created(ser_shipment(shipment))


@bp.get("/confection/shipments/<shipment_id>")
def read_shipment(shipment_id):
    authorize(*ALL_ROLES)
    return ok(ser_shipment(get_shipment(shipment_id)))


@bp.get("/confection/shipments")
def list_shipments():
    limit, offset = parse_pagination()
    authorize(*ALL_ROLES)
    items = list(db.shipments.values())
    for param in ("commitment_id", "warehouse_id", "status"):
        val = request.args.get(param)
        if val is not None:
            items = [s for s in items if s[param] == val]
    page, total, limit, offset = paginate(items, limit, offset)
    return ok_list([ser_shipment(s) for s in page], total, limit, offset)


@bp.post("/confection/shipments/<shipment_id>/deliver")
def deliver_shipment(shipment_id):
    authorize(ROLE_LOGISTICS_COORDINATOR)
    shipment = get_shipment(shipment_id)
    if shipment["status"] != "PLANNED":
        raise ApiError(409, ERR_INVALID_STATE,
                       "only a PLANNED shipment can be delivered")
    shipment["status"] = "DELIVERED"
    shipment["delivered_on"] = fmt_instant(db.clock)
    touch(shipment)

    commitment = db.commitments[shipment["commitment_id"]]
    if commitment["status"] == "FULFILLING":
        if delivered_units_of_commitment(commitment["id"]) >= commitment["allocated_units"]:
            commitment["status"] = "FULFILLED"
            touch(commitment)
    return ok(ser_shipment(shipment))
