"""Routes: training sessions and parts stocks."""
from flask import Blueprint, request
from db import DB, stamp_new, touch, _parse_iso
from errors import (
    err_not_found, err_invalid_request, err_invalid_state, err_schedule_conflict,
    err_deadline, err_referential, err_fiscal, err_duplicate,
)
from middleware import require_roles, get_body
from response import success_obj, success_list, public, parse_pagination, paginate
from services.core import update_stock_status

bp = Blueprint("warranty_ops", __name__)

PROPULSION_TYPES = {"DIESEL", "CNG", "HEV", "BEV", "FCEV"}


def _calendar_day(iso_str):
    return _parse_iso(iso_str).date()


@bp.post("/api/training-sessions")
def create_training():
    require_roles("WarrantyAdmin")
    body = get_body()
    agency_id = body.get("agency_id")
    propulsion_type = body.get("propulsion_type")
    scheduled_date = body.get("scheduled_date")
    attendee_count = body.get("attendee_count")
    if agency_id is None:
        raise err_invalid_request("Missing required field: agency_id")
    if propulsion_type is None:
        raise err_invalid_request("Missing required field: propulsion_type")
    if propulsion_type not in PROPULSION_TYPES:
        raise err_invalid_request("Unknown propulsion_type")
    if scheduled_date is None:
        raise err_invalid_request("Missing required field: scheduled_date")
    if attendee_count is None:
        raise err_invalid_request("Missing required field: attendee_count")
    if not isinstance(attendee_count, int) or isinstance(attendee_count, bool):
        raise err_invalid_request("attendee_count must be an integer")
    agency = DB.agencies.get(agency_id)
    if agency is None:
        raise err_not_found("Agency not found")
    try:
        day = _calendar_day(scheduled_date)
    except Exception:
        raise err_invalid_request("Malformed scheduled_date")
    for t in DB.trainings.values():
        if t["agency_id"] == agency_id and t["status"] != "CANCELLED":
            if _calendar_day(t["scheduled_date"]) == day:
                raise err_schedule_conflict("Training session collides on agency and calendar date")
    if attendee_count < 1:
        raise err_fiscal("attendee_count must be >= 1")
    rec = {
        "agency_id": agency_id,
        "propulsion_type": propulsion_type,
        "scheduled_date": scheduled_date,
        "attendee_count": attendee_count,
        "status": "SCHEDULED",
    }
    stamp_new(rec)
    DB.trainings[rec["id"]] = rec
    return success_obj(public(rec), 201)


@bp.get("/api/training-sessions")
def list_trainings():
    require_roles("PlatformAdmin", "WarrantyAdmin", "AgencyAdmin")
    limit, offset = parse_pagination(request.args)
    agency_id = request.args.get("agency_id")
    status = request.args.get("status")
    items = list(DB.trainings.values())
    if agency_id is not None:
        items = [t for t in items if t["agency_id"] == agency_id]
    if status is not None:
        items = [t for t in items if t["status"] == status]
    items.sort(key=lambda r: r["_seq"])
    window, total = paginate(items, limit, offset)
    return success_list([public(t) for t in window], limit, offset, total)


@bp.get("/api/training-sessions/<trainingSessionId>")
def get_training(trainingSessionId):
    require_roles("PlatformAdmin", "WarrantyAdmin", "AgencyAdmin")
    t = DB.trainings.get(trainingSessionId)
    if t is None:
        raise err_not_found("TrainingSession not found")
    return success_obj(public(t))


@bp.post("/api/training-sessions/<trainingSessionId>/complete")
def complete_training(trainingSessionId):
    require_roles("WarrantyAdmin")
    t = DB.trainings.get(trainingSessionId)
    if t is None:
        raise err_not_found("TrainingSession not found")
    if t["status"] != "SCHEDULED":
        raise err_invalid_state("TrainingSession is not SCHEDULED")
    if DB.clock.now() < _parse_iso(t["scheduled_date"]):
        raise err_invalid_state("Current logical time is before scheduled_date")
    t["status"] = "COMPLETED"
    touch(t)
    return success_obj(public(t))


@bp.post("/api/training-sessions/<trainingSessionId>/cancel")
def cancel_training(trainingSessionId):
    require_roles("WarrantyAdmin")
    t = DB.trainings.get(trainingSessionId)
    if t is None:
        raise err_not_found("TrainingSession not found")
    if t["status"] != "SCHEDULED":
        raise err_invalid_state("TrainingSession is not SCHEDULED")
    if not (DB.clock.now() < _parse_iso(t["scheduled_date"])):
        raise err_deadline("Cancellation must be strictly before scheduled_date")
    t["status"] = "CANCELLED"
    touch(t)
    return success_obj(public(t))


@bp.post("/api/parts-stocks")
def create_stock():
    require_roles("WarrantyAdmin")
    body = get_body()
    agency_id = body.get("agency_id")
    component_id = body.get("component_id")
    quantity = body.get("quantity")
    if agency_id is None:
        raise err_invalid_request("Missing required field: agency_id")
    if component_id is None:
        raise err_invalid_request("Missing required field: component_id")
    if quantity is None:
        raise err_invalid_request("Missing required field: quantity")
    if not isinstance(quantity, int) or isinstance(quantity, bool):
        raise err_invalid_request("quantity must be an integer")
    if agency_id not in DB.agencies:
        raise err_referential("Agency not found")
    if component_id not in DB.components:
        raise err_referential("Component not found")
    for s in DB.stocks.values():
        if s["agency_id"] == agency_id and s["component_id"] == component_id:
            raise err_duplicate("(agency_id, component_id) pair already exists")
    if quantity < 0:
        raise err_fiscal("quantity must be non-negative")
    rec = {
        "agency_id": agency_id,
        "component_id": component_id,
        "quantity": quantity,
        "reserved_quantity": 0,
        "status": "ACTIVE" if quantity > 0 else "DEPLETED",
    }
    stamp_new(rec)
    DB.stocks[rec["id"]] = rec
    return success_obj(public(rec), 201)


@bp.get("/api/parts-stocks")
def list_stocks():
    require_roles("PlatformAdmin", "WarrantyAdmin", "AgencyAdmin")
    limit, offset = parse_pagination(request.args)
    agency_id = request.args.get("agency_id")
    component_id = request.args.get("component_id")
    status = request.args.get("status")
    items = list(DB.stocks.values())
    if agency_id is not None:
        items = [s for s in items if s["agency_id"] == agency_id]
    if component_id is not None:
        items = [s for s in items if s["component_id"] == component_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    items.sort(key=lambda r: r["_seq"])
    window, total = paginate(items, limit, offset)
    return success_list([public(s) for s in window], limit, offset, total)


@bp.get("/api/parts-stocks/<partsStockId>")
def get_stock(partsStockId):
    require_roles("PlatformAdmin", "WarrantyAdmin", "AgencyAdmin")
    s = DB.stocks.get(partsStockId)
    if s is None:
        raise err_not_found("PartsStock not found")
    return success_obj(public(s))


@bp.patch("/api/parts-stocks/<partsStockId>")
def patch_stock(partsStockId):
    require_roles("WarrantyAdmin")
    s = DB.stocks.get(partsStockId)
    if s is None:
        raise err_not_found("PartsStock not found")
    body = get_body()
    if "quantity" not in body or body["quantity"] is None:
        raise err_invalid_request("Missing required field: quantity")
    quantity = body["quantity"]
    if not isinstance(quantity, int) or isinstance(quantity, bool):
        raise err_invalid_request("quantity must be an integer")
    if quantity < s["reserved_quantity"]:
        raise err_fiscal("quantity cannot be below reserved_quantity")
    if quantity < 0:
        raise err_fiscal("quantity must be non-negative")
    s["quantity"] = quantity
    touch(s)
    update_stock_status(s)
    return success_obj(public(s))
