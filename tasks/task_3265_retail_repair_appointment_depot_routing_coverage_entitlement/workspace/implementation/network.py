"""Service locations, technicians, parts, part inventories."""
from flask import Blueprint, request

from core import (ApiError, STORE, auth, body, entity_bootstrap, get_location, get_part,
                  inventory_at, ok_obj, opt_bool, paginate, pagination, require,
                  require_bool, require_enum, require_int, ser_inventory, ser_location,
                  ser_part, ser_technician, touch)

bp = Blueprint("network", __name__)

LOCATION_TYPES = {"RETAIL_STORE", "AUTHORIZED_PROVIDER", "MAIL_IN_DEPOT"}
CERT_LEVELS = {"BASIC", "ADVANCED", "EXPERT"}
PART_CATEGORIES = {"DISPLAY", "BATTERY", "LOGIC_BOARD", "CAMERA", "ENCLOSURE", "OTHER"}


# ---------------------------------------------------------------------------
# Service locations
# ---------------------------------------------------------------------------

@bp.post("/service-locations")
def create_location():
    auth({"PlatformAdmin"})
    data = require(body(), "location_code", "location_type", "address",
                   "diagnostic_slot_duration_minutes")
    require_bool(data, "supports_same_day_repair", "supports_express_replacement")
    require_enum(data, "location_type", LOCATION_TYPES)
    require_int(data, "diagnostic_slot_duration_minutes")
    if data["diagnostic_slot_duration_minutes"] <= 0:
        raise ApiError("ERR_INVALID_REQUEST", "diagnostic_slot_duration_minutes must be > 0", 400)
    e = entity_bootstrap()
    e.update({
        "location_code": data["location_code"],
        "location_type": data["location_type"],
        "address": data["address"],
        "supports_same_day_repair": data["supports_same_day_repair"],
        "supports_express_replacement": data["supports_express_replacement"],
        "diagnostic_slot_duration_minutes": data["diagnostic_slot_duration_minutes"],
        "location_status": "ACTIVE",
    })
    STORE["service_locations"][e["id"]] = e
    return ok_obj(ser_location(e), 201)


@bp.get("/service-locations/<lid>")
def get_location_view(lid):
    auth({"Customer", "Technician", "CustomerService", "PlatformAdmin"})
    return ok_obj(ser_location(get_location(lid)))


@bp.get("/service-locations")
def list_locations():
    auth({"Customer", "Technician", "CustomerService", "PlatformAdmin"})
    limit, offset = pagination()
    items = list(STORE["service_locations"].values())
    lt = request.args.get("location_type")
    ls = request.args.get("location_status")
    sdr = opt_bool("supports_same_day_repair")
    ser_ = opt_bool("supports_express_replacement")
    if lt:
        items = [l for l in items if l["location_type"] == lt]
    if ls:
        items = [l for l in items if l["location_status"] == ls]
    if sdr is not None:
        items = [l for l in items if l["supports_same_day_repair"] == sdr]
    if ser_ is not None:
        items = [l for l in items if l["supports_express_replacement"] == ser_]
    return paginate([ser_location(l) for l in items], limit, offset)


@bp.get("/locations/<lid>/part-inventories")
def list_location_inventories(lid):
    auth({"Technician", "CustomerService", "PlatformAdmin"})
    get_location(lid)
    limit, offset = pagination()
    items = [i for i in STORE["part_inventories"].values() if i["location_id"] == lid]
    pid = request.args.get("part_id")
    if pid:
        items = [i for i in items if i["part_id"] == pid]
    return paginate([ser_inventory(i) for i in items], limit, offset)


# ---------------------------------------------------------------------------
# Technicians
# ---------------------------------------------------------------------------

@bp.post("/technicians")
def create_technician():
    auth({"PlatformAdmin"})
    data = require(body(), "location_id", "full_name", "certification_level")
    require_enum(data, "certification_level", CERT_LEVELS)
    get_location(data["location_id"])
    e = entity_bootstrap()
    e.update({
        "location_id": data["location_id"],
        "full_name": data["full_name"],
        "certification_level": data["certification_level"],
        "is_active": True,
    })
    STORE["technicians"][e["id"]] = e
    return ok_obj(ser_technician(e), 201)


@bp.get("/technicians/<tid>")
def get_technician(tid):
    auth({"Technician", "CustomerService", "PlatformAdmin"})
    t = STORE["technicians"].get(tid)
    if t is None:
        raise ApiError("ERR_NOT_FOUND", "Technician not found", 404)
    return ok_obj(ser_technician(t))


@bp.get("/technicians")
def list_technicians():
    auth({"Technician", "CustomerService", "PlatformAdmin"})
    limit, offset = pagination()
    items = list(STORE["technicians"].values())
    lid = request.args.get("location_id")
    cl = request.args.get("certification_level")
    ia = opt_bool("is_active")
    if lid:
        items = [t for t in items if t["location_id"] == lid]
    if cl:
        items = [t for t in items if t["certification_level"] == cl]
    if ia is not None:
        items = [t for t in items if t["is_active"] == ia]
    return paginate([ser_technician(t) for t in items], limit, offset)


# ---------------------------------------------------------------------------
# Parts
# ---------------------------------------------------------------------------

@bp.post("/parts")
def create_part():
    auth({"PlatformAdmin"})
    data = require(body(), "part_number", "model_code", "part_category")
    require_bool(data, "is_whole_unit_replacement")
    require_enum(data, "part_category", PART_CATEGORIES)
    e = entity_bootstrap()
    e.update({
        "part_number": data["part_number"],
        "model_code": data["model_code"],
        "part_category": data["part_category"],
        "is_whole_unit_replacement": data["is_whole_unit_replacement"],
        "part_status": "ACTIVE",
    })
    STORE["parts"][e["id"]] = e
    return ok_obj(ser_part(e), 201)


@bp.get("/parts/<pid>")
def get_part_view(pid):
    auth({"Technician", "CustomerService", "PlatformAdmin"})
    return ok_obj(ser_part(get_part(pid)))


# ---------------------------------------------------------------------------
# Part inventories
# ---------------------------------------------------------------------------

@bp.post("/part-inventories")
def upsert_inventory():
    auth({"PlatformAdmin", "DepotAgent"})
    data = require(body(), "location_id", "part_id", "on_hand_quantity")
    require_int(data, "on_hand_quantity")
    get_location(data["location_id"])
    get_part(data["part_id"])
    on_hand = data["on_hand_quantity"]
    express = data.get("express_replacement_quantity", 0)
    if isinstance(express, bool) or not isinstance(express, int):
        raise ApiError("ERR_INVALID_REQUEST", "express_replacement_quantity must be an integer", 400)
    if on_hand < 0 or express < 0:
        raise ApiError("ERR_INVALID_REQUEST", "quantities must be >= 0", 400)
    existing = inventory_at(data["location_id"], data["part_id"])
    if existing is not None:
        # Update in place; reserved_quantity preserved.
        if on_hand - existing["reserved_quantity"] - express < 0:
            raise ApiError("ERR_INVALID_REQUEST",
                           "on_hand_quantity - reserved_quantity - express_replacement_quantity must be >= 0", 400)
        existing["on_hand_quantity"] = on_hand
        existing["express_replacement_quantity"] = express
        touch(existing)
        return ok_obj(ser_inventory(existing), 201)
    e = entity_bootstrap()
    e.update({
        "location_id": data["location_id"],
        "part_id": data["part_id"],
        "on_hand_quantity": on_hand,
        "reserved_quantity": 0,
        "express_replacement_quantity": express,
    })
    STORE["part_inventories"][e["id"]] = e
    return ok_obj(ser_inventory(e), 201)


@bp.get("/part-inventories/<iid>")
def get_inventory(iid):
    auth({"Technician", "CustomerService", "PlatformAdmin"})
    inv = STORE["part_inventories"].get(iid)
    if inv is None:
        raise ApiError("ERR_NOT_FOUND", "Part inventory not found", 404)
    return ok_obj(ser_inventory(inv))


@bp.get("/part-inventories")
def list_inventories():
    auth({"Technician", "CustomerService", "PlatformAdmin"})
    limit, offset = pagination()
    items = list(STORE["part_inventories"].values())
    lid = request.args.get("location_id")
    pid = request.args.get("part_id")
    if lid:
        items = [i for i in items if i["location_id"] == lid]
    if pid:
        items = [i for i in items if i["part_id"] == pid]
    return paginate([ser_inventory(i) for i in items], limit, offset)
