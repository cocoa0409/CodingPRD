"""Service network endpoints: centers, mobile vans, parts stock (PRD 3.8)."""

from flask import Blueprint

import errors as E
import store
from errors import ApiError
from store import DB
from util import (auth, require_role, body, req_field, as_str, as_int, find,
                  ok, ok_list, check_state_code)

bp = Blueprint("service", __name__)

_CENTER_READ_ROLES = {"PlatformAdmin", "ServiceDispatcher", "ServiceTechnician"}


@bp.post("/evfleet/service-centers")
def create_service_center():
    _, role = auth()
    require_role(role, {"PlatformAdmin"})
    b = body()
    name = as_str(req_field(b, "name"), "name")
    region_code = as_str(req_field(b, "region_code"), "region_code")
    state_code = check_state_code(req_field(b, "state_code"))
    bay_count = as_int(req_field(b, "bay_count"), "bay_count")
    if bay_count < 1:
        raise ApiError(E.ERR_VALIDATION, 400, "bay_count must be >= 1")
    e = {
        "name": name,
        "region_code": region_code,
        "state_code": state_code,
        "bay_count": bay_count,
    }
    store.stamp_new(e)
    DB.centers[e["id"]] = e
    return ok(store.public(e), 201)


@bp.get("/evfleet/service-centers/<sid>")
def get_service_center(sid):
    _, role = auth()
    require_role(role, _CENTER_READ_ROLES)
    e = find(DB.centers, sid, "service center")
    return ok(store.public(e), 200)


@bp.get("/evfleet/service-centers/<sid>/mobile-vans")
def list_center_vans(sid):
    _, role = auth()
    require_role(role, _CENTER_READ_ROLES)
    find(DB.centers, sid, "service center")
    items = [v for v in DB.vans.values() if v["service_center_id"] == sid]
    return ok_list(items)


@bp.get("/evfleet/service-centers/<sid>/parts-stocks")
def list_center_parts(sid):
    _, role = auth()
    require_role(role, _CENTER_READ_ROLES)
    find(DB.centers, sid, "service center")
    items = [p for p in DB.parts.values() if p["service_center_id"] == sid]
    return ok_list(items)


@bp.post("/evfleet/mobile-vans")
def create_mobile_van():
    _, role = auth()
    require_role(role, {"ServiceDispatcher"})
    b = body()
    service_center_id = as_str(req_field(b, "service_center_id"), "service_center_id")
    # priority 3
    find(DB.centers, service_center_id, "service center")
    # priority 10: van_code globally unique
    van_code = as_str(req_field(b, "van_code"), "van_code")
    if any(v["van_code"] == van_code for v in DB.vans.values()):
        raise ApiError(E.ERR_DUPLICATE_VIN, 409, "van_code %s already exists" % van_code)
    e = {
        "service_center_id": service_center_id,
        "van_code": van_code,
    }
    store.stamp_new(e)
    DB.vans[e["id"]] = e
    return ok(store.public(e), 201)


@bp.post("/evfleet/parts-stocks")
def upsert_parts_stock():
    _, role = auth()
    require_role(role, {"ServiceDispatcher"})
    b = body()
    service_center_id = as_str(req_field(b, "service_center_id"), "service_center_id")
    # priority 3
    find(DB.centers, service_center_id, "service center")
    sku = as_str(req_field(b, "sku"), "sku")
    qty_delta = as_int(req_field(b, "qty_delta"), "qty_delta")
    reorder_threshold = as_int(req_field(b, "reorder_threshold"), "reorder_threshold")
    if reorder_threshold < 0:
        raise ApiError(E.ERR_VALIDATION, 400, "reorder_threshold must be >= 0")
    key = (service_center_id, sku)
    row = DB.parts.get(key)
    if row is None:
        if qty_delta < 0:
            raise ApiError(E.ERR_VALIDATION, 400,
                           "qty_delta may not drive on_hand_qty below 0")
        row = {
            "service_center_id": service_center_id,
            "sku": sku,
            "reorder_threshold": reorder_threshold,
            "on_hand_qty": qty_delta,
            "reserved_qty": 0,
            "consumed_total_qty": 0,
            "received_total_qty": qty_delta,
        }
        row["restock_needed"] = row["on_hand_qty"] < row["reorder_threshold"]
        store.stamp_new(row)
        DB.parts[key] = row
    else:
        if row["on_hand_qty"] + qty_delta < 0:
            raise ApiError(E.ERR_VALIDATION, 400,
                           "qty_delta may not drive on_hand_qty below 0")
        row["on_hand_qty"] += qty_delta
        row["received_total_qty"] += qty_delta
        row["reorder_threshold"] = reorder_threshold
        row["restock_needed"] = row["on_hand_qty"] < row["reorder_threshold"]
        store.touch(row)
    return ok(store.public(row), 201)
