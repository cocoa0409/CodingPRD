"""Shipments, allocations, and temperature readings (PRD §3.8)."""

from flask import Blueprint

import db
from errors import (
    ApiError,
    ERR_CONTRACT_NOT_ACTIVE,
    ERR_CONTRACT_PRODUCT_MISMATCH,
    ERR_INSUFFICIENT_LOT_UNITS,
    ERR_INVALID_STATE,
    ERR_LOT_NOT_AVAILABLE,
    ERR_SHIPMENT_EMPTY,
)
from middleware import authenticate, ALL_ROLES
from response import success_obj, success_list
from services import serialize
from util import (
    apply_filters,
    body_json,
    check_shape,
    exist_body_fks,
    paginate,
    pagination_params,
    parse_dt,
    path_entity,
)

bp = Blueprint("shipments", __name__)

SHIPMENT_SPEC = {
    "shipment_code": {"type": "string", "required": True},
    "customer_id": {"type": "string", "required": True},
    "contract_id": {"type": "string"},
    "carrier_liability": {"type": "boolean"},
}

ALLOCATION_SPEC = {
    "lot_id": {"type": "string", "required": True},
    "units": {"type": "integer", "min": 1, "required": True},
}

READINGS_SPEC = {
    "readings": {
        "type": "obj_list",
        "required": True,
        "items": {
            "recorded_at": {"type": "datetime", "required": True},
            "temp_c": {"type": "number", "required": True},
        },
    },
}


def _check_contract_link(shipment):
    """Priority 33: a contract-linked shipment requires an ACTIVE contract
    whose customer matches the shipment's customer."""
    contract = db.get("contracts", shipment["contract_id"])
    if (
        contract is None
        or contract["status"] != "ACTIVE"
        or contract["customer_id"] != shipment["customer_id"]
    ):
        raise ApiError(
            ERR_CONTRACT_NOT_ACTIVE,
            422,
            "contract is not ACTIVE or belongs to a different customer",
        )
    return contract


@bp.route("/shipments", methods=["POST"])
def create_shipment():
    authenticate({"WarehouseLead"})
    body = body_json()
    exist_body_fks(body, {
        "customer_id": ("customers", "customer"),
        "contract_id": ("contracts", "contract"),
    })
    check_shape(body, SHIPMENT_SPEC)
    shipment_fields = {
        "shipment_code": body["shipment_code"],
        "customer_id": body["customer_id"],
        "contract_id": body.get("contract_id"),
        "carrier_liability": body.get("carrier_liability", False),
        "status": "PLANNED",
        "allocated_units": 0,
        "dispatched_at": None,
        "closed_at": None,
    }
    if shipment_fields["contract_id"] is not None:
        _check_contract_link(shipment_fields)
    shipment = db.new_entity("shipments", shipment_fields)
    return success_obj(serialize("shipments", shipment), 201)


@bp.route("/shipments", methods=["GET"])
def list_shipments():
    authenticate(ALL_ROLES)
    items = apply_filters(
        db.all_of("shipments"), ["customer_id", "contract_id", "status"]
    )
    limit, offset = pagination_params()
    page, total, has_more = paginate(items, limit, offset)
    return success_list([serialize("shipments", e) for e in page],
                        limit, offset, total, has_more)


@bp.route("/shipments/<shipment_id>", methods=["GET"])
def get_shipment(shipment_id):
    authenticate(ALL_ROLES)
    shipment = path_entity("shipments", shipment_id, "shipment")
    return success_obj(serialize("shipments", shipment))


@bp.route("/shipments/<shipment_id>/allocations", methods=["POST"])
def create_allocation(shipment_id):
    authenticate({"WarehouseLead"})
    shipment = path_entity("shipments", shipment_id, "shipment")
    body = body_json()
    exist_body_fks(body, {"lot_id": ("lots", "inventory lot")})
    check_shape(body, ALLOCATION_SPEC)
    if shipment["status"] != "PLANNED":
        raise ApiError(ERR_INVALID_STATE, 409, "shipment is not PLANNED")
    lot = db.get("lots", body["lot_id"])
    # Priority 23: lot must be AVAILABLE with best_before strictly in the future.
    if lot["status"] != "AVAILABLE" or parse_dt(lot["best_before"]) <= db.now():
        raise ApiError(ERR_LOT_NOT_AVAILABLE, 422, "lot is not available")
    # Priority 24: requested units must not exceed available units.
    if body["units"] > lot["units_available"]:
        raise ApiError(
            ERR_INSUFFICIENT_LOT_UNITS, 422, "units exceed the lot's available units"
        )
    if shipment["contract_id"] is not None:
        contract = _check_contract_link(shipment)
        # Priority 34: allocation product must equal the contract's product.
        if lot["product_id"] != contract["product_id"]:
            raise ApiError(
                ERR_CONTRACT_PRODUCT_MISMATCH,
                422,
                "lot product differs from the shipment contract's product",
            )
    units = body["units"]
    allocation = db.new_entity("allocations", {
        "shipment_id": shipment["id"],
        "lot_id": lot["id"],
        "units": units,
        "status": "ACTIVE",
        "release_reason": None,
    })
    lot["units_available"] -= units
    lot["units_reserved"] += units
    db.touch(lot)
    shipment["allocated_units"] += units
    db.touch(shipment)
    return success_obj(serialize("allocations", allocation), 201)


@bp.route("/shipment-allocations", methods=["GET"])
def list_allocations():
    authenticate(ALL_ROLES)
    items = apply_filters(
        db.all_of("allocations"), ["shipment_id", "lot_id", "status"]
    )
    limit, offset = pagination_params()
    page, total, has_more = paginate(items, limit, offset)
    return success_list([serialize("allocations", e) for e in page],
                        limit, offset, total, has_more)


@bp.route("/shipment-allocations/<allocation_id>", methods=["GET"])
def get_allocation(allocation_id):
    authenticate(ALL_ROLES)
    allocation = path_entity("allocations", allocation_id, "allocation")
    return success_obj(serialize("allocations", allocation))


@bp.route("/shipment-allocations/<allocation_id>/release", methods=["POST"])
def release_allocation(allocation_id):
    authenticate({"WarehouseLead"})
    allocation = path_entity("allocations", allocation_id, "allocation")
    if allocation["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409, "allocation is not ACTIVE")
    shipment = db.get("shipments", allocation["shipment_id"])
    # Manual release is permitted only while the shipment is still PLANNED.
    if shipment is None or shipment["status"] != "PLANNED":
        raise ApiError(ERR_INVALID_STATE, 409, "shipment is not PLANNED")
    units = int(allocation["units"])
    lot = db.get("lots", allocation["lot_id"])
    allocation["status"] = "RELEASED"
    allocation["release_reason"] = "MANUAL"
    db.touch(allocation)
    if lot is not None:
        lot["units_reserved"] -= units
        lot["units_available"] += units
        db.touch(lot)
    shipment["allocated_units"] -= units
    db.touch(shipment)
    return success_obj(serialize("allocations", allocation))


@bp.route("/shipments/<shipment_id>/load", methods=["POST"])
def load_shipment(shipment_id):
    authenticate({"WarehouseLead"})
    shipment = path_entity("shipments", shipment_id, "shipment")
    if shipment["status"] != "PLANNED":
        raise ApiError(ERR_INVALID_STATE, 409, "shipment is not PLANNED")
    # Priority 25: loading requires allocated units.
    if shipment["allocated_units"] <= 0:
        raise ApiError(ERR_SHIPMENT_EMPTY, 422, "shipment has no allocated units")
    shipment["status"] = "LOADED"
    db.touch(shipment)
    return success_obj(serialize("shipments", shipment))


@bp.route("/shipments/<shipment_id>/dispatch", methods=["POST"])
def dispatch_shipment(shipment_id):
    authenticate({"WarehouseLead"})
    shipment = path_entity("shipments", shipment_id, "shipment")
    if shipment["status"] != "LOADED":
        raise ApiError(ERR_INVALID_STATE, 409, "shipment is not LOADED")
    shipment["status"] = "IN_TRANSIT"
    shipment["dispatched_at"] = db.fmt_ts(db.now())
    db.touch(shipment)
    return success_obj(serialize("shipments", shipment))


@bp.route("/shipments/<shipment_id>/deliver", methods=["POST"])
def deliver_shipment(shipment_id):
    authenticate({"WarehouseLead"})
    shipment = path_entity("shipments", shipment_id, "shipment")
    if shipment["status"] != "IN_TRANSIT":
        raise ApiError(ERR_INVALID_STATE, 409, "shipment is not IN_TRANSIT")
    shipment["status"] = "DELIVERED"
    shipment["closed_at"] = db.fmt_ts(db.now())
    delivered_units = 0
    for allocation in db.all_of("allocations"):
        if allocation["shipment_id"] != shipment["id"] or allocation["status"] != "ACTIVE":
            continue
        units = int(allocation["units"])
        allocation["status"] = "FULFILLED"
        db.touch(allocation)
        lot = db.get("lots", allocation["lot_id"])
        if lot is not None:
            lot["units_reserved"] -= units
            lot["units_shipped"] += units
            db.touch(lot)
        delivered_units += units
    if shipment["contract_id"] is not None and delivered_units:
        contract = db.get("contracts", shipment["contract_id"])
        if contract is not None:
            contract["delivered_units"] += delivered_units
            db.touch(contract)
            # contract_fulfillment: exact equality fulfills (>= boundary).
            if (
                contract["status"] == "ACTIVE"
                and contract["delivered_units"] >= contract["committed_units"]
            ):
                contract["status"] = "FULFILLED"
                db.touch(contract)
    db.touch(shipment)
    return success_obj(serialize("shipments", shipment))


@bp.route("/shipments/<shipment_id>/reject", methods=["POST"])
def reject_shipment(shipment_id):
    authenticate({"WarehouseLead"})
    shipment = path_entity("shipments", shipment_id, "shipment")
    if shipment["status"] != "IN_TRANSIT":
        raise ApiError(ERR_INVALID_STATE, 409, "shipment is not IN_TRANSIT")
    shipment["status"] = "REJECTED"
    shipment["closed_at"] = db.fmt_ts(db.now())
    for allocation in db.all_of("allocations"):
        if allocation["shipment_id"] != shipment["id"] or allocation["status"] != "ACTIVE":
            continue
        units = int(allocation["units"])
        allocation["status"] = "RELEASED"
        allocation["release_reason"] = "SHIPMENT_REJECTED"
        db.touch(allocation)
        lot = db.get("lots", allocation["lot_id"])
        if lot is not None:
            lot["units_reserved"] -= units
            lot["units_available"] += units
            db.touch(lot)
    shipment["allocated_units"] = 0
    db.touch(shipment)
    return success_obj(serialize("shipments", shipment))


@bp.route("/shipments/<shipment_id>/temperature-readings", methods=["POST"])
def append_temperature_readings(shipment_id):
    authenticate({"WarehouseLead"})
    shipment = path_entity("shipments", shipment_id, "shipment")
    body = body_json()
    check_shape(body, READINGS_SPEC)
    if shipment["status"] != "IN_TRANSIT":
        raise ApiError(ERR_INVALID_STATE, 409, "shipment is not IN_TRANSIT")
    created = []
    for item in body["readings"]:
        reading = db.new_entity(
            "readings",
            {
                "shipment_id": shipment["id"],
                "recorded_at": item["recorded_at"],
                "temp_c": item["temp_c"],
            },
            common_fields=False,
        )
        created.append(serialize("readings", reading))
    resp = success_list(created, len(created), 0, len(created), False, code=201)
    return resp


@bp.route("/shipments/<shipment_id>/temperature-readings", methods=["GET"])
def list_temperature_readings(shipment_id):
    authenticate(ALL_ROLES)
    path_entity("shipments", shipment_id, "shipment")
    items = [r for r in db.all_of("readings") if r["shipment_id"] == shipment_id]
    limit, offset = pagination_params()
    page, total, has_more = paginate(items, limit, offset)
    return success_list([serialize("readings", e) for e in page],
                        limit, offset, total, has_more)
