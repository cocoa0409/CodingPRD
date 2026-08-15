"""Property endpoints (PRD 3.2)."""

from flask import Blueprint, request

import db
from errors import ApiError, ERR_NOT_FOUND
from middleware import allowed
from response import success_object, success_list
from serializers import ser_property, ser_comparable
from validation import body, req_str, req_int, req_enum, sort_and_page

bp = Blueprint("properties", __name__)

STATE_CODE_PATTERN = r"^[A-Z]{2}$"
PROPERTY_TYPES = {"SINGLE_FAMILY", "CONDO", "TOWNHOME", "MULTI_FAMILY", "MANUFACTURED"}


@bp.post("/bpo/properties")
@allowed("OperationsManager", "ClientAdmin")
def create_property(user_id, role):
    b = body()
    record = db.stamp_new({
        "id": db.new_id(),
        "street_address": req_str(b, "street_address"),
        "city": req_str(b, "city"),
        "state_code": req_str(b, "state_code", pattern=STATE_CODE_PATTERN),
        "postal_code": req_str(b, "postal_code"),
        "living_area_sqft": req_int(b, "living_area_sqft", min_v=1),
        "lot_area_sqft": req_int(b, "lot_area_sqft", min_v=1),
        "year_built": req_int(b, "year_built", min_v=1700, max_v=2100),
        "property_type": req_enum(b, "property_type", PROPERTY_TYPES),
        "status": "REGISTERED",
    })
    db.properties[record["id"]] = record
    return success_object(ser_property(record), 201)


@bp.get("/bpo/properties")
@allowed("OperationsManager", "ClientAdmin", "DispatchCoordinator", "Broker")
def list_properties(user_id, role):
    records = list(db.properties.values())
    state_code = request.args.get("state_code")
    if state_code is not None:
        records = [r for r in records if r["state_code"] == state_code]
    status = request.args.get("status")
    if status is not None:
        records = [r for r in records if r["status"] == status]
    items, limit, offset, total = sort_and_page(records, ser_property)
    return success_list(items, limit, offset, total)


@bp.get("/bpo/properties/<property_id>")
@allowed("OperationsManager", "ClientAdmin", "DispatchCoordinator", "Broker")
def get_property(user_id, role, property_id):
    record = db.properties.get(property_id)
    if record is None:
        raise ApiError(ERR_NOT_FOUND, f"Property {property_id} not found", 404)
    return success_object(ser_property(record))


@bp.get("/bpo/properties/<property_id>/comparables")
@allowed("OperationsManager", "DispatchCoordinator", "Broker", "QCReviewer", "PlatformAdmin")
def list_property_comparables(user_id, role, property_id):
    record = db.properties.get(property_id)
    if record is None:
        raise ApiError(ERR_NOT_FOUND, f"Property {property_id} not found", 404)
    records = [c for c in db.comparables.values() if c["source_property_id"] == property_id]
    status = request.args.get("status")
    if status is not None:
        records = [r for r in records if r["status"] == status]
    items, limit, offset, total = sort_and_page(records, ser_comparable)
    return success_list(items, limit, offset, total)
