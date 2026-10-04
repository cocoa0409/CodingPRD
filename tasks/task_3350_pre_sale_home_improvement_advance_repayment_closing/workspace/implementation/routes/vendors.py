"""Vendor reference data and capacity windows (PRD 3.1)."""
from flask import Blueprint, request

from auth import require_roles
from db import store
from envelope import success_obj
from errors import ApiError, ERR_INVALID_REQUEST
from logic import get_or_404, list_response, new_record, serialize
from validate import body_json, req_dt, req_enum, req_int, req_str

bp = Blueprint("vendors", __name__)

TRADES = ("GENERAL", "ELECTRIC", "PLUMBING", "HVAC", "PAINT", "LANDSCAPE")


@bp.post("/concierge/vendors")
@require_roles("PlatformAdmin")
def create_vendor():
    body = body_json(required=True)
    rec = new_record({
        "legal_name": req_str(body, "legal_name"),
        "trade": req_enum(body, "trade", TRADES),
        "quality_score_bp": 10000,
        "on_time_streak": 0,
    })
    store.vendors[rec["id"]] = rec
    return success_obj(serialize(rec), 201)


@bp.get("/concierge/vendors/<vendorId>")
@require_roles("Any")
def get_vendor(vendorId):
    return success_obj(serialize(get_or_404(store.vendors, vendorId, "Vendor")))


@bp.get("/concierge/vendors")
@require_roles("Any")
def list_vendors():
    items = list(store.vendors.values())
    trade = request.args.get("trade")
    if trade is not None:
        items = [v for v in items if v["trade"] == trade]
    return list_response(items)


@bp.post("/concierge/vendors/<vendorId>/capacity-windows")
@require_roles("PlatformAdmin")
def create_capacity_window(vendorId):
    vendor = get_or_404(store.vendors, vendorId, "Vendor")
    body = body_json(required=True)
    start = req_dt(body, "window_start")
    end = req_dt(body, "window_end")
    if end <= start:
        raise ApiError(ERR_INVALID_REQUEST, "window_end must be after window_start", 400)
    capacity = req_int(body, "capacity_crew_days", min_value=1)
    rec = new_record({
        "vendor_id": vendor["id"],
        "window_start": start,
        "window_end": end,
        "capacity_crew_days": capacity,
        "reserved_crew_days": 0,
        "status": "OPEN",
    })
    store.capacity_windows[rec["id"]] = rec
    return success_obj(serialize(rec), 201)


@bp.get("/concierge/vendors/<vendorId>/capacity-windows")
@require_roles("Any")
def list_capacity_windows(vendorId):
    get_or_404(store.vendors, vendorId, "Vendor")
    items = [w for w in store.capacity_windows.values() if w["vendor_id"] == vendorId]
    return list_response(items)


@bp.get("/concierge/vendors/<vendorId>/engagements")
@require_roles("Any")
def list_vendor_engagements(vendorId):
    get_or_404(store.vendors, vendorId, "Vendor")
    items = [e for e in store.engagements.values() if e["vendor_id"] == vendorId]
    return list_response(items)
