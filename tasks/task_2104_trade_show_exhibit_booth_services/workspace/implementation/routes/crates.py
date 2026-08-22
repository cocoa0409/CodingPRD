"""Crates: registration, warehouse check-in and the location lifecycle (PRD §3.6)."""
from flask import Blueprint

import db
import guards
import response
from errors import ApiError
from middleware import ANY_ROLE, own_exhibitor, own_warehouse, require_roles
from services import calc, state
from validation import json_body, require_row

bp = Blueprint("crates", __name__)
store = db.store

CRATE_TYPES = ("WOOD_CRATE", "FIBER_CASE", "LOOSE_UNCRATED")
CRATE_STATUSES = ("REGISTERED", "AT_ADVANCE_WAREHOUSE", "IN_TRANSIT_TO_SHOW",
                  "ON_SHOW_FLOOR", "EMPTY_STORED", "OUTBOUND_STAGED",
                  "RETURNED_TO_WAREHOUSE", "RELEASED_TO_CARRIER", "LOST")
TERMINAL = ("RELEASED_TO_CARRIER", "LOST")
CHECK_IN_EDGES = {"REGISTERED": "AT_ADVANCE_WAREHOUSE",
                  "OUTBOUND_STAGED": "RETURNED_TO_WAREHOUSE"}


@bp.post("/crates")
def create_crate():
    require_roles("Exhibitor", "WarehouseAgent")
    body = json_body()
    own_exhibitor(body.peek_str("exhibitor_id"))
    exhibitor_id = body.string("exhibitor_id")
    crate_label = body.string("crate_label")
    crate_type = body.enum("crate_type", CRATE_TYPES)
    weight = body.integer("weight_lbs")
    asset_id = body.string("asset_id", required=False, default=None)

    require_row(store.exhibitors, exhibitor_id, "ERR_EXHIBITOR_NOT_FOUND", "Exhibitor")
    if asset_id is not None:
        require_row(store.assets, asset_id, "ERR_ASSET_NOT_FOUND", "Exhibit asset")

    crate = {
        "id": db.new_id(),
        "exhibitor_id": exhibitor_id,
        "asset_id": asset_id,
        "warehouse_id": None,
        "shipment_id": None,
        "crate_label": crate_label,
        "crate_type": crate_type,
        "weight_lbs": weight,
        "stored_since": None,
        "storage_charge_cents": 0,
        "status": "REGISTERED",
    }
    db.stamp_common(crate)
    store.crates[crate["id"]] = crate
    return response.created(crate)


@bp.get("/crates/<crate_id>")
def get_crate(crate_id):
    require_roles(ANY_ROLE)
    crate = store.crates.get(crate_id)
    own_exhibitor(crate["exhibitor_id"] if crate else None)
    crate = require_row(store.crates, crate_id, "ERR_CRATE_NOT_FOUND", "Crate")
    return response.ok(crate)


@bp.get("/crates")
def list_crates():
    require_roles(ANY_ROLE)
    rows = list(store.crates.values())
    rows = response.filter_rows(rows, "exhibitor_id", "asset_id", "warehouse_id",
                                "shipment_id", "status")
    return response.listing(rows)


@bp.post("/crates/<crate_id>/warehouse-check-in")
def check_in(crate_id):
    require_roles("WarehouseAgent")
    body = json_body()
    own_warehouse(body.peek_str("warehouse_id"))
    warehouse_id = body.string("warehouse_id")
    expected_version = body.integer("expected_warehouse_version")

    crate = require_row(store.crates, crate_id, "ERR_CRATE_NOT_FOUND", "Crate")
    warehouse = require_row(store.warehouses, warehouse_id, "ERR_WAREHOUSE_NOT_FOUND",
                            "Warehouse")

    guards.transition(crate["status"], TERMINAL, tuple(CHECK_IN_EDGES))
    guards.occ(expected_version, warehouse["version"], "ERR_STALE_WAREHOUSE_VERSION")

    if warehouse["status"] != "ACCEPTING":
        raise ApiError("ERR_WAREHOUSE_CAPACITY_EXCEEDED", "The warehouse is CLOSED")
    projected = int(warehouse["committed_cwt"]) + calc.cwt_of(crate["weight_lbs"])
    if projected > int(warehouse["capacity_cwt"]):
        raise ApiError("ERR_WAREHOUSE_CAPACITY_EXCEEDED",
                       "The warehouse has insufficient remaining capacity")

    crate["status"] = CHECK_IN_EDGES[crate["status"]]
    crate["warehouse_id"] = warehouse_id
    crate["stored_since"] = db.now_stamp()
    db.touch(crate)
    warehouse["committed_cwt"] = _committed(warehouse)
    db.touch(warehouse)
    return response.ok(crate)


def _committed(warehouse):
    total = 0
    for crate in store.crates.values():
        if crate.get("warehouse_id") == warehouse["id"] and \
                crate["status"] in ("AT_ADVANCE_WAREHOUSE", "RETURNED_TO_WAREHOUSE"):
            total += calc.cwt_of(crate["weight_lbs"])
    return total


@bp.post("/crates/<crate_id>/movements")
def movements(crate_id):
    require_roles("WarehouseAgent", "ShowOperations")
    body = json_body()
    to_status = body.enum("to_status", CRATE_STATUSES)
    shipment_id = body.string("shipment_id", required=False, default=None)
    body.string("note", required=False, default=None)

    crate = require_row(store.crates, crate_id, "ERR_CRATE_NOT_FOUND", "Crate")
    shipment = None
    if shipment_id is not None:
        shipment = require_row(store.shipments, shipment_id, "ERR_SHIPMENT_NOT_FOUND",
                               "Shipment")

    current = crate["status"]
    edges = {
        "IN_TRANSIT_TO_SHOW": ("AT_ADVANCE_WAREHOUSE",),
        "ON_SHOW_FLOOR": ("REGISTERED", "IN_TRANSIT_TO_SHOW", "EMPTY_STORED"),
        "EMPTY_STORED": ("ON_SHOW_FLOOR",),
        "OUTBOUND_STAGED": ("ON_SHOW_FLOOR",),
        "RELEASED_TO_CARRIER": ("OUTBOUND_STAGED",),
        "LOST": ("REGISTERED", "AT_ADVANCE_WAREHOUSE", "IN_TRANSIT_TO_SHOW",
                 "ON_SHOW_FLOOR", "EMPTY_STORED", "OUTBOUND_STAGED",
                 "RETURNED_TO_WAREHOUSE"),
    }
    guards.transition(current, TERMINAL, edges.get(to_status, ()))

    effective_shipment = shipment or store.shipments.get(crate.get("shipment_id"))
    show = store.shows.get(effective_shipment["show_id"]) if effective_shipment else None

    if to_status in ("IN_TRANSIT_TO_SHOW", "ON_SHOW_FLOOR") and effective_shipment is None:
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "The crate is not attached to a shipment")

    if to_status == "IN_TRANSIT_TO_SHOW":
        guards.show_accepting(show, ("ADVANCE_CLOSED", "MOVE_IN", "ON_SITE"))
    elif to_status == "ON_SHOW_FLOOR":
        if current == "EMPTY_STORED":
            guards.show_accepting(show, ("ON_SITE", "MOVE_OUT"))
        else:
            guards.show_accepting(show, ("MOVE_IN", "ON_SITE", "MOVE_OUT"))
    elif to_status == "EMPTY_STORED":
        guards.show_accepting(show, ("MOVE_IN", "ON_SITE"))
    elif to_status == "OUTBOUND_STAGED":
        guards.show_accepting(show, ("MOVE_OUT",))

    warehouse = state.warehouse_of_crate(crate)
    if shipment is not None:
        crate["shipment_id"] = shipment_id

    if to_status in ("IN_TRANSIT_TO_SHOW", "LOST"):
        crate["warehouse_id"] = None
        crate["stored_since"] = None

    crate["status"] = to_status
    db.touch(crate)

    if warehouse is not None:
        state.recompute_warehouse_cwt(warehouse)

    if to_status == "IN_TRANSIT_TO_SHOW" and effective_shipment is not None:
        if effective_shipment["status"] == "RECEIVED":
            effective_shipment["status"] = "IN_TRANSIT"
            db.touch(effective_shipment)
    if effective_shipment is not None:
        bubble_up(effective_shipment)

    return response.ok(crate)


def bubble_up(shipment):
    """A shipment reaches DELIVERED_TO_BOOTH once every crate is on the floor."""
    if shipment["status"] not in ("RECEIVED", "IN_TRANSIT"):
        return
    crates = [c for c in store.crates.values() if c.get("shipment_id") == shipment["id"]]
    if not crates:
        return
    if all(c["status"] == "ON_SHOW_FLOOR" for c in crates):
        shipment["status"] = "DELIVERED_TO_BOOTH"
        db.touch(shipment)
