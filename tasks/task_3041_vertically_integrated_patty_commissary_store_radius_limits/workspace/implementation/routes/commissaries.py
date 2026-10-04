"""Commissary and Truck routes."""

from flask import Blueprint, request

import db
import services.domain as domain
from errors import (
    ERR_COMMISSARY_INVALID_STATE,
    ERR_OPEN_BATCHES_EXIST,
    ERR_STORES_STILL_OPEN,
    ERR_SUPPLIER_NOT_APPROVED,
    ERR_TRUCK_INACTIVE,
    conflict,
    invalid_request,
    not_found,
    unprocessable,
)
from middleware import require_roles
from response import success_list, success_object
from util import (
    base_entity,
    get_json_body,
    paginate,
    req_field,
    req_int,
    req_list,
    req_number,
    req_string,
    touch,
)

bp = Blueprint("commissaries", __name__)


def _validate_delivery_days_mask(mask):
    if not isinstance(mask, list) or len(mask) != 7 or not all(isinstance(x, bool) for x in mask):
        raise invalid_request("delivery_days_mask must be an array of 7 booleans")


@bp.route("/commissaries", methods=["POST"])
def create_commissary():
    require_roles("SupplyChainDirector")
    body = get_json_body()
    name = req_string(body, "name")
    lat = req_number(body, "lat")
    lng = req_number(body, "lng")
    radius_limit_km = req_number(body, "radius_limit_km")
    patty_cap = req_int(body, "daily_patty_capacity")
    bun_cap = req_int(body, "daily_bun_capacity")
    produce_cap = req_int(body, "daily_produce_capacity")
    mask = req_list(body, "delivery_days_mask")
    _validate_delivery_days_mask(mask)
    supplier_id = req_field(body, "supplier_id")
    if not isinstance(supplier_id, str):
        raise invalid_request("supplier_id must be a string")
    # Body FK existence (tier 5).
    supplier = domain.get_supplier(supplier_id)
    c = base_entity()
    c.update({
        "name": name,
        "lat": lat,
        "lng": lng,
        "radius_limit_km": radius_limit_km,
        "daily_patty_capacity": patty_cap,
        "daily_bun_capacity": bun_cap,
        "daily_produce_capacity": produce_cap,
        "raw_beef_lbs_on_hand": 0,
        "delivery_days_mask": mask,
        "regional_entry_open": False,
        "supplier_id": supplier["id"],
        "status": "PLANNING",
    })
    db.commissaries[c["id"]] = c
    return success_object(domain.ser_commissary(c), 201)


@bp.route("/commissaries", methods=["GET"])
def list_commissaries():
    require_roles("SupplyChainDirector", "CommissaryPlanner", "RealEstatePlanner")
    items = list(db.commissaries.values())
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    supplier_id = request.args.get("supplier_id")
    if supplier_id is not None:
        items = [c for c in items if c["supplier_id"] == supplier_id]
    page, limit, offset, total = paginate(items)
    return success_list([domain.ser_commissary(c) for c in page], limit, offset, total)


@bp.route("/commissaries/<cid>", methods=["GET"])
def get_commissary(cid):
    require_roles("SupplyChainDirector", "CommissaryPlanner", "RealEstatePlanner")
    return success_object(domain.ser_commissary(domain.get_commissary(cid)))


@bp.route("/commissaries/<cid>", methods=["PATCH"])
def patch_commissary(cid):
    require_roles("SupplyChainDirector")
    c = domain.get_commissary(cid)
    body = get_json_body()
    # Validate shape of provided fields.
    updates = {}
    if "radius_limit_km" in body and body["radius_limit_km"] is not None:
        updates["radius_limit_km"] = req_number(body, "radius_limit_km")
    if "daily_patty_capacity" in body and body["daily_patty_capacity"] is not None:
        updates["daily_patty_capacity"] = req_int(body, "daily_patty_capacity")
    if "daily_bun_capacity" in body and body["daily_bun_capacity"] is not None:
        updates["daily_bun_capacity"] = req_int(body, "daily_bun_capacity")
    if "daily_produce_capacity" in body and body["daily_produce_capacity"] is not None:
        updates["daily_produce_capacity"] = req_int(body, "daily_produce_capacity")
    if "delivery_days_mask" in body and body["delivery_days_mask"] is not None:
        _validate_delivery_days_mask(body["delivery_days_mask"])
        updates["delivery_days_mask"] = body["delivery_days_mask"]
    # State gate (tier 8): configuration may change only while PLANNING or BUILDING.
    if c["status"] not in ("PLANNING", "BUILDING"):
        raise conflict(ERR_COMMISSARY_INVALID_STATE, "Commissary %s is not updatable" % c["status"])
    for k, v in updates.items():
        c[k] = v
    touch(c)
    return success_object(domain.ser_commissary(c))


@bp.route("/commissaries/<cid>/begin-build", methods=["POST"])
def begin_build(cid):
    require_roles("SupplyChainDirector")
    c = domain.get_commissary(cid)
    if c["status"] != "PLANNING":
        raise conflict(ERR_COMMISSARY_INVALID_STATE, "Commissary must be PLANNING to begin build")
    supplier = domain.get_supplier(c["supplier_id"])
    if supplier["status"] != "APPROVED":
        raise unprocessable(ERR_SUPPLIER_NOT_APPROVED, "Dedicated supplier is not APPROVED")
    c["status"] = "BUILDING"
    return success_object(domain.ser_commissary(c))


@bp.route("/commissaries/<cid>/activate", methods=["POST"])
def activate(cid):
    require_roles("SupplyChainDirector")
    c = domain.get_commissary(cid)
    if c["status"] != "BUILDING":
        raise conflict(ERR_COMMISSARY_INVALID_STATE, "Commissary must be BUILDING to activate")
    c["status"] = "OPERATIONAL"
    c["regional_entry_open"] = True
    touch(c)
    return success_object(domain.ser_commissary(c))


@bp.route("/commissaries/<cid>/recertify", methods=["POST"])
def recertify(cid):
    require_roles("SupplyChainDirector")
    c = domain.get_commissary(cid)
    if c["status"] != "OPERATIONAL":
        raise conflict(ERR_COMMISSARY_INVALID_STATE, "Commissary must be OPERATIONAL to recertify")
    open_batches = any(
        b["commissary_id"] == c["id"] and b["status"] in ("PLANNED", "LOADED")
        for b in db.batches.values()
    )
    if open_batches:
        raise conflict(ERR_OPEN_BATCHES_EXIST, "Open batches exist for this commissary")
    c["status"] = "BUILDING"
    c["regional_entry_open"] = False
    touch(c)
    return success_object(domain.ser_commissary(c))


@bp.route("/commissaries/<cid>/decommission", methods=["POST"])
def decommission(cid):
    require_roles("SupplyChainDirector")
    c = domain.get_commissary(cid)
    if c["status"] != "OPERATIONAL":
        raise conflict(ERR_COMMISSARY_INVALID_STATE, "Commissary must be OPERATIONAL to decommission")
    open_stores = any(
        s["commissary_id"] == c["id"] and s["status"] != "CLOSED"
        for s in db.stores.values()
    )
    if open_stores:
        raise conflict(ERR_STORES_STILL_OPEN, "Not all stores of this commissary are CLOSED")
    domain.commissary_decommission_cascade(c)
    c["status"] = "DECOMMISSIONED"
    c["regional_entry_open"] = False
    touch(c)
    return success_object(domain.ser_commissary(c))


# ---------------- trucks ----------------

@bp.route("/commissaries/<cid>/trucks", methods=["POST"])
def create_truck(cid):
    require_roles("CommissaryPlanner")
    c = domain.get_commissary(cid)
    body = get_json_body()
    plate = req_string(body, "plate")
    route_type = req_string(body, "route_type")
    if route_type not in ("PRIMARY", "RESERVE"):
        raise invalid_request("route_type must be PRIMARY or RESERVE")
    cooler_capacity_cases = req_int(body, "cooler_capacity_cases")
    # Plate unique among ACTIVE trucks.
    for t in db.trucks.values():
        if t["status"] == "ACTIVE" and t["plate"] == plate:
            raise invalid_request("plate must be unique among ACTIVE trucks")
    t = base_entity()
    t.update({
        "commissary_id": c["id"],
        "plate": plate,
        "route_type": route_type,
        "cooler_capacity_cases": cooler_capacity_cases,
        "status": "ACTIVE",
    })
    db.trucks[t["id"]] = t
    return success_object(domain.ser_truck(t), 201)


@bp.route("/commissaries/<cid>/trucks", methods=["GET"])
def list_trucks(cid):
    require_roles("CommissaryPlanner", "SupplyChainDirector")
    c = domain.get_commissary(cid)
    items = [t for t in db.trucks.values() if t["commissary_id"] == c["id"]]
    page, limit, offset, total = paginate(items)
    return success_list([domain.ser_truck(t) for t in page], limit, offset, total)


@bp.route("/trucks/<tid>", methods=["GET"])
def get_truck(tid):
    require_roles("CommissaryPlanner", "SupplyChainDirector")
    return success_object(domain.ser_truck(domain.get_truck(tid)))


@bp.route("/trucks/<tid>/retire", methods=["POST"])
def retire_truck(tid):
    require_roles("CommissaryPlanner")
    t = domain.get_truck(tid)
    if t["status"] != "ACTIVE":
        raise unprocessable(ERR_TRUCK_INACTIVE, "Truck is not ACTIVE")
    t["status"] = "INACTIVE"
    touch(t)
    c = db.commissaries.get(t["commissary_id"])
    if c is not None:
        touch(c)
    return success_object(domain.ser_truck(t))
