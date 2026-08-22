"""Drayage shipments: receipt pricing, dock capacity and operational holds."""
from flask import Blueprint

import db
import response
from errors import ApiError
from middleware import ANY_ROLE, own_exhibitor, own_warehouse, require_roles
from services import calc, state
from validation import json_body, parse_dt, require_row

bp = Blueprint("shipments", __name__)
store = db.store

CHANNELS = ("ADVANCE_WAREHOUSE", "DIRECT_TO_SHOW")


@bp.post("/drayage-shipments")
def create_shipment():
    require_roles("WarehouseAgent")
    body = json_body()
    own_warehouse(body.peek_str("warehouse_id"))

    show_id = body.string("show_id")
    exhibitor_id = body.string("exhibitor_id")
    channel = body.enum("channel", CHANNELS)
    crate_ids = body.id_array("crate_ids")
    received_at = body.datetime_str("received_at")
    dock_start = body.datetime_str("dock_window_start")
    dock_end = body.datetime_str("dock_window_end")
    warehouse_id = body.string("warehouse_id", required=False, default=None)
    coverage = body.boolean("declared_value_coverage", required=False, default=False)
    if channel == "ADVANCE_WAREHOUSE" and warehouse_id is None:
        raise ApiError("ERR_INVALID_REQUEST",
                       "warehouse_id is required for ADVANCE_WAREHOUSE freight")
    if channel == "DIRECT_TO_SHOW" and warehouse_id is not None:
        raise ApiError("ERR_INVALID_REQUEST",
                       "warehouse_id is forbidden for DIRECT_TO_SHOW freight")

    show = require_row(store.shows, show_id, "ERR_SHOW_NOT_FOUND", "Show")
    require_row(store.exhibitors, exhibitor_id, "ERR_EXHIBITOR_NOT_FOUND", "Exhibitor")
    crates = [require_row(store.crates, crate_id, "ERR_CRATE_NOT_FOUND", "Crate")
              for crate_id in crate_ids]
    warehouse = None
    if warehouse_id is not None:
        warehouse = require_row(store.warehouses, warehouse_id, "ERR_WAREHOUSE_NOT_FOUND",
                                "Warehouse")

    venue = store.venues.get(show["venue_id"])
    limit = (venue or {}).get("max_forklift_capacity_lbs")
    if limit is not None:
        for crate in crates:
            if int(crate["weight_lbs"]) > int(limit):
                raise ApiError("ERR_CRATE_WEIGHT_LIMIT_EXCEEDED",
                               "A crate exceeds the venue forklift capacity")

    gross, billable_cwt, charge = calc.drayage_charge(
        crates, channel, parse_dt(received_at),
        parse_dt(show["advance_warehouse_deadline"]))

    if warehouse is not None:
        _check_dock(warehouse, parse_dt(dock_start), parse_dt(dock_end), billable_cwt)

    for crate in crates:
        if crate["exhibitor_id"] != exhibitor_id:
            raise ApiError("ERR_CRATE_EXHIBITOR_MISMATCH",
                           "A listed crate belongs to a different exhibitor")

    if not crate_ids:
        raise ApiError("ERR_EMPTY_COLLECTION", "crate_ids must not be empty")

    shipment = {
        "id": db.new_id(),
        "show_id": show_id,
        "exhibitor_id": exhibitor_id,
        "warehouse_id": warehouse_id,
        "channel": channel,
        "crate_ids": list(crate_ids),
        "received_at": received_at,
        "dock_window_start": dock_start,
        "dock_window_end": dock_end,
        "declared_value_coverage": coverage,
        "gross_weight_lbs": gross,
        "billable_cwt": billable_cwt,
        "drayage_charge_cents": charge,
        "hold_flag": False,
        "hold_reason": None,
        "status": "RECEIVED",
    }
    db.stamp_common(shipment)
    store.shipments[shipment["id"]] = shipment
    for crate in crates:
        crate["shipment_id"] = shipment["id"]
        db.touch(crate)
    return response.created(shipment)


def _check_dock(warehouse, new_start, new_end, new_cwt):
    total = new_cwt
    for shipment in store.shipments.values():
        if shipment.get("warehouse_id") != warehouse["id"]:
            continue
        if shipment["status"] not in ("RECEIVED", "IN_TRANSIT"):
            continue
        existing_start = parse_dt(shipment["dock_window_start"])
        existing_end = parse_dt(shipment["dock_window_end"])
        if existing_start < new_end and new_start < existing_end:
            total += int(shipment["billable_cwt"])
    if total > int(warehouse["dock_capacity_cwt"]):
        raise ApiError("ERR_DOCK_CAPACITY_EXCEEDED",
                       "Aggregate receiving weight exceeds the dock capacity")


@bp.get("/drayage-shipments/<shipment_id>")
def get_shipment(shipment_id):
    require_roles(ANY_ROLE)
    shipment = store.shipments.get(shipment_id)
    own_exhibitor(shipment["exhibitor_id"] if shipment else None)
    shipment = require_row(store.shipments, shipment_id, "ERR_SHIPMENT_NOT_FOUND",
                           "Shipment")
    return response.ok(shipment)


@bp.get("/drayage-shipments")
def list_shipments():
    require_roles(ANY_ROLE)
    rows = list(store.shipments.values())
    rows = response.filter_rows(rows, "show_id", "exhibitor_id", "warehouse_id", "status")
    return response.listing(rows)


@bp.post("/drayage-shipments/<shipment_id>/hold")
def hold(shipment_id):
    require_roles("WarehouseAgent", "ShowOperations")
    body = json_body()
    shipment = store.shipments.get(shipment_id)
    if shipment is not None:
        own_warehouse(shipment.get("warehouse_id"))
    hold_flag = body.boolean("hold_flag", required=True)
    reason = body.string("reason", required=False, default=None)
    shipment = require_row(store.shipments, shipment_id, "ERR_SHIPMENT_NOT_FOUND",
                           "Shipment")

    shipment["hold_flag"] = hold_flag
    if hold_flag:
        shipment["hold_reason"] = reason
    db.touch(shipment)
    state.refresh_exhibitor_show_booths(shipment["exhibitor_id"], shipment["show_id"])
    return response.ok(shipment)
