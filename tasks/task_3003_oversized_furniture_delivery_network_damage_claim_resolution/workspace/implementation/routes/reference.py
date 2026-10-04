"""Reference data: suppliers, items, hubs, freight lanes, customers."""
from flask import Blueprint, request

import clock
from db import db, new_id
from errors import (
    err_invalid_request,
    err_invalid_state,
    err_item_has_open_shipments,
)
from middleware import require_roles
from response import success
from services import calculations as calc
from services import supplier_metrics
from services.common import get_or_404, list_response, stamp_new, touch
from validation import (
    get_body,
    opt_int,
    req_bool,
    req_enum,
    req_int,
    req_number,
    req_string,
    req_string_list,
)

bp = Blueprint("reference", __name__)


# --- Suppliers ---------------------------------------------------------------

@bp.post("/suppliers")
@require_roles("NetworkAdmin")
def create_supplier():
    body = get_body(request)
    supplier_code = req_string(body, "supplier_code")
    legal_name = req_string(body, "legal_name")
    drop_ship_enabled = req_bool(body, "drop_ship_enabled")
    lead_time_days = opt_int(body, "lead_time_days", 3)
    if lead_time_days < 0:
        raise err_invalid_request("lead_time_days must be >= 0")
    supplier = stamp_new(
        {
            "id": new_id(),
            "supplier_code": supplier_code,
            "legal_name": legal_name,
            "drop_ship_enabled": drop_ship_enabled,
            "lead_time_days": lead_time_days,
            "compliance_score": 100.00,
            "on_time_ship_rate": 100.00,
            "chargeback_rate": 0.00,
            "status": "ACTIVE",
        }
    )
    db.suppliers[supplier["id"]] = supplier
    return success(supplier, status=201)


@bp.get("/suppliers")
@require_roles("NetworkAdmin", "ClaimsAdjuster", "SupplierRep")
def list_suppliers():
    return list_response(
        db.suppliers,
        [("status", "status", {"ACTIVE", "PROBATION", "SUSPENDED"})],
    )


@bp.get("/suppliers/<supplierId>")
@require_roles("NetworkAdmin", "ClaimsAdjuster", "SupplierRep")
def get_supplier(supplierId):
    return success(get_or_404(db.suppliers, supplierId))


@bp.get("/suppliers/<supplierId>/scorecard")
@require_roles("NetworkAdmin", "ClaimsAdjuster", "SupplierRep")
def supplier_scorecard(supplierId):
    get_or_404(db.suppliers, supplierId)
    window = request.args.get("window", "rolling")
    if window not in ("rolling", "lifetime"):
        raise err_invalid_request("window must be 'rolling' or 'lifetime'")
    metrics = supplier_metrics.compute_metrics(supplierId, window=window)
    return success(
        {
            "on_time_ship_rate": metrics["on_time_ship_rate"],
            "chargeback_rate": metrics["chargeback_rate"],
            "compliance_score": metrics["compliance_score"],
            "window": window,
        }
    )


# --- Items -------------------------------------------------------------------

@bp.post("/items")
@require_roles("NetworkAdmin")
def create_item():
    body = get_body(request)
    supplier = get_or_404(db.suppliers, body.get("supplier_id") if isinstance(body.get("supplier_id"), str) else None)
    sku = req_string(body, "sku")
    dim_l = req_number(body, "dim_length_in")
    dim_w = req_number(body, "dim_width_in")
    dim_h = req_number(body, "dim_height_in")
    weight = req_number(body, "weight_lb")
    declared_value = req_int(body, "declared_value_cents")
    white_glove = req_bool(body, "white_glove_eligible")
    if dim_l <= 0 or dim_w <= 0 or dim_h <= 0:
        raise err_invalid_request("dimensions must be > 0")
    if weight <= 0:
        raise err_invalid_request("weight_lb must be > 0")
    if declared_value < 0:
        raise err_invalid_request("declared_value_cents must be >= 0")

    cube_score = calc.item_cube_score(dim_l, dim_w, dim_h)
    freight_class = calc.freight_class_assignment(cube_score)
    girth, parcel_ok = calc.declared_girth_and_parcel_gate(dim_l, dim_w, dim_h)

    item = stamp_new(
        {
            "id": new_id(),
            "supplier_id": supplier["id"],
            "sku": sku,
            "dim_length_in": dim_l,
            "dim_width_in": dim_w,
            "dim_height_in": dim_h,
            "weight_lb": weight,
            "declared_value_cents": declared_value,
            "white_glove_eligible": white_glove,
            "cube_score": float(cube_score),
            "freight_class": freight_class,
            "declared_girth_in": girth,
            "parcel_ok": parcel_ok,
            "status": "LISTED",
        }
    )
    db.items[item["id"]] = item
    return success(item, status=201)


_FREIGHT_CLASSES = {"PARCEL_ELIGIBLE", "LTL_250", "LTL_150", "LTL_125", "LTL_92_5"}


@bp.get("/items")
@require_roles("NetworkAdmin", "ClaimsAdjuster", "SupplierRep", "Customer")
def list_items():
    return list_response(
        db.items,
        [
            ("supplier_id", "supplier_id", None),
            ("freight_class", "freight_class", _FREIGHT_CLASSES),
            ("status", "status", {"LISTED", "DELISTED"}),
        ],
    )


@bp.get("/items/<itemId>")
@require_roles("NetworkAdmin", "ClaimsAdjuster", "SupplierRep", "Customer")
def get_item(itemId):
    return success(get_or_404(db.items, itemId))


@bp.post("/items/<itemId>/delist")
@require_roles("NetworkAdmin")
def delist_item(itemId):
    item = get_or_404(db.items, itemId)
    if item["status"] != "LISTED":
        raise err_invalid_state("Item must be LISTED to delist")
    open_states = {"CREATED", "TENDERED", "IN_TRANSIT", "AT_HUB", "OUT_FOR_DELIVERY"}
    for s in db.shipments.values():
        if s["item_id"] == item["id"] and s["current_state"] in open_states:
            raise err_item_has_open_shipments()
    item["status"] = "DELISTED"
    touch(item)
    return success(item)


# --- Hubs --------------------------------------------------------------------

@bp.post("/hubs")
@require_roles("NetworkAdmin")
def create_hub():
    body = get_body(request)
    hub_code = req_string(body, "hub_code")
    name = req_string(body, "name")
    serves_zones = req_string_list(body, "serves_zones")
    white_glove_capable = req_bool(body, "white_glove_capable")
    daily_capacity = req_int(body, "daily_capacity")
    if daily_capacity < 0:
        raise err_invalid_request("daily_capacity must be >= 0")
    hub = stamp_new(
        {
            "id": new_id(),
            "hub_code": hub_code,
            "name": name,
            "serves_zones": serves_zones,
            "white_glove_capable": white_glove_capable,
            "daily_capacity": daily_capacity,
            "status": "ACTIVE",
        }
    )
    db.hubs[hub["id"]] = hub
    return success(hub, status=201)


@bp.get("/hubs")
@require_roles("NetworkAdmin", "HubOperator", "ClaimsAdjuster")
def list_hubs():
    return list_response(db.hubs, [])


@bp.get("/hubs/<hubId>")
@require_roles("NetworkAdmin", "HubOperator", "ClaimsAdjuster")
def get_hub(hubId):
    return success(get_or_404(db.hubs, hubId))


# --- Freight lanes ------------------------------------------------------------

@bp.post("/freight-lanes")
@require_roles("NetworkAdmin")
def create_freight_lane():
    body = get_body(request)
    leg_mode = req_enum(body, "leg_mode", {"PARCEL", "LTL", "OWNED_FINAL_MILE"})
    dest_zone = req_string(body, "dest_zone")
    base_rate = req_int(body, "base_rate_cents")
    per_lb_rate = req_int(body, "per_lb_rate_cents")
    transit_days = req_int(body, "transit_days")
    if transit_days < 1:
        raise err_invalid_request("transit_days must be >= 1")
    lane = stamp_new(
        {
            "id": new_id(),
            "leg_mode": leg_mode,
            "dest_zone": dest_zone,
            "base_rate_cents": base_rate,
            "per_lb_rate_cents": per_lb_rate,
            "transit_days": transit_days,
            "status": "ACTIVE",
        }
    )
    db.freight_lanes[lane["id"]] = lane
    return success(lane, status=201)


@bp.get("/freight-lanes")
@require_roles("NetworkAdmin", "HubOperator")
def list_freight_lanes():
    return list_response(
        db.freight_lanes,
        [
            ("leg_mode", "leg_mode", {"PARCEL", "LTL", "OWNED_FINAL_MILE"}),
            ("dest_zone", "dest_zone", None),
            ("status", "status", {"ACTIVE", "INACTIVE"}),
        ],
    )


@bp.get("/freight-lanes/<laneId>")
@require_roles("NetworkAdmin", "HubOperator")
def get_freight_lane(laneId):
    return success(get_or_404(db.freight_lanes, laneId))


# --- Customers ---------------------------------------------------------------

@bp.post("/customers")
@require_roles("NetworkAdmin")
def create_customer():
    body = get_body(request)
    email = req_string(body, "email")
    full_name = req_string(body, "full_name")
    destination_zone = req_string(body, "destination_zone")
    customer = stamp_new(
        {
            "id": new_id(),
            "email": email,
            "full_name": full_name,
            "destination_zone": destination_zone,
        }
    )
    db.customers[customer["id"]] = customer
    return success(customer, status=201)


@bp.get("/customers/<customerId>")
@require_roles("NetworkAdmin", "Customer")
def get_customer(customerId):
    return success(get_or_404(db.customers, customerId))
