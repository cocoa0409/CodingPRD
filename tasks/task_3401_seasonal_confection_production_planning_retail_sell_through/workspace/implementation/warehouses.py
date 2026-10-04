"""Warehouse routes (create, read) and InventoryLot routes (read, list,
manual QA quarantine / release-quarantine)."""

from flask import Blueprint, request

from db import db, touch
from domain import get_warehouse, ser_warehouse, get_lot, ser_lot
from errors import ApiError, ERR_INVALID_STATE
from middleware import authorize, ROLE_PLATFORM_ADMIN, ROLE_CATEGORY_MANAGER, ALL_ROLES
from programs import _create_entity
from respond import ok, created, ok_list, paginate, parse_pagination
from validate import json_body, v_str, v_int, v_bool

bp = Blueprint("warehouses", __name__)

# Post-pull quarantine is permanent: manual quarantine operations are blocked
# once the lot's product's program reaches any of these states.
LOCKED_PROGRAM_STATES = ("DISPOSITION", "CLOSED", "CANCELLED")


def _program_gate_for_lot(lot):
    product = db.products[lot["product_id"]]
    if product["program_id"] is None:
        return  # EVERYDAY product: no program gate
    program = db.programs[product["program_id"]]
    if program["status"] in LOCKED_PROGRAM_STATES:
        raise ApiError(409, ERR_INVALID_STATE,
                       "the program is in %s; quarantine is permanent post-pull" % program["status"])


@bp.post("/confection/warehouses")
def create_warehouse():
    data = json_body()
    name = v_str(data, "name")
    temp_controlled = v_bool(data, "temp_controlled")
    capacity_units = v_int(data, "capacity_units", min_v=1)

    authorize(ROLE_PLATFORM_ADMIN)

    warehouse = _create_entity(db.warehouses, {
        "name": name,
        "temp_controlled": temp_controlled,
        "capacity_units": capacity_units,
    })
    return created(ser_warehouse(warehouse))


@bp.get("/confection/warehouses/<warehouse_id>")
def read_warehouse(warehouse_id):
    authorize(*ALL_ROLES)
    return ok(ser_warehouse(get_warehouse(warehouse_id)))


@bp.get("/confection/inventory-lots/<lot_id>")
def read_lot(lot_id):
    authorize(*ALL_ROLES)
    return ok(ser_lot(get_lot(lot_id)))


@bp.get("/confection/inventory-lots")
def list_lots():
    limit, offset = parse_pagination()
    authorize(*ALL_ROLES)
    items = list(db.lots.values())
    for param in ("product_id", "warehouse_id", "production_run_id", "status"):
        val = request.args.get(param)
        if val is not None:
            items = [l for l in items if l[param] == val]
    page, total, limit, offset = paginate(items, limit, offset)
    return ok_list([ser_lot(l) for l in page], total, limit, offset)


@bp.post("/confection/inventory-lots/<lot_id>/quarantine")
def quarantine_lot(lot_id):
    authorize(ROLE_CATEGORY_MANAGER)
    lot = get_lot(lot_id)
    if lot["status"] != "AVAILABLE":
        raise ApiError(409, ERR_INVALID_STATE,
                       "only an AVAILABLE lot can be quarantined")
    _program_gate_for_lot(lot)
    lot["status"] = "QUARANTINED"
    touch(lot)
    return ok(ser_lot(lot))


@bp.post("/confection/inventory-lots/<lot_id>/release-quarantine")
def release_lot(lot_id):
    authorize(ROLE_CATEGORY_MANAGER)
    lot = get_lot(lot_id)
    if lot["status"] != "QUARANTINED":
        raise ApiError(409, ERR_INVALID_STATE,
                       "only a QUARANTINED lot can be released")
    _program_gate_for_lot(lot)
    lot["status"] = "AVAILABLE"
    touch(lot)
    return ok(ser_lot(lot))
