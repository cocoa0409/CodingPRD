"""Delivery windows and visits."""
from flask import Blueprint, request

import calculations as calc
from db import DB, parse_iso
from errors import ApiError, err_validation, not_found
from helpers import (
    body, new_entity, opt_field, page, parse_pagination, public, req_field,
    require_bool, require_int, require_str, sorted_items, touch,
)
from middleware import authenticate, check_customer_ownership, require_roles
from response import success_list, success_object
from sweeps import promote_waitlist, _maybe_order_fulfilling

bp = Blueprint("delivery", __name__)


def _get_window_or_404(window_id):
    w = DB.delivery_windows.get(window_id)
    if w is None:
        raise not_found("ERR_DELIVERY_WINDOW_NOT_FOUND", "delivery window id does not resolve")
    return w


def _get_visit_or_404(visit_id):
    v = DB.delivery_visits.get(visit_id)
    if v is None:
        raise not_found("ERR_DELIVERY_VISIT_NOT_FOUND", "delivery visit id does not resolve")
    return v


# ---------------------------------------------------------------- windows
@bp.post("/sleep/delivery-windows")
def create_window():
    role, uid = authenticate()
    require_roles(role, uid, {"PlatformAdmin"})
    data = body()
    store_id = require_str(req_field(data, "store_id"), "store_id")
    team_id = require_str(req_field(data, "team_id"), "team_id")
    ws_raw = require_str(req_field(data, "window_start"), "window_start")
    we_raw = require_str(req_field(data, "window_end"), "window_end")
    capacity = require_int(req_field(data, "capacity_slots"), "capacity_slots")
    if store_id not in DB.stores:
        raise not_found("ERR_STORE_NOT_FOUND", "store id does not resolve")
    try:
        ws = parse_iso(ws_raw)
        we = parse_iso(we_raw)
    except (ValueError, TypeError):
        raise err_validation("window_start/window_end must be ISO 8601 timestamps")
    if we <= ws:
        raise err_validation("window_end must be strictly after window_start")
    # half-open overlap check per (store_id, team_id)
    for w in DB.delivery_windows.values():
        if w["store_id"] != store_id or w["team_id"] != team_id:
            continue
        ows = parse_iso(w["window_start"])
        owe = parse_iso(w["window_end"])
        if ws < owe and ows < we:
            raise ApiError("ERR_WINDOW_TEAM_OVERLAP", 422,
                           "window overlaps an existing window for this team")
    ent = new_entity({
        "store_id": store_id,
        "team_id": team_id,
        "window_start": ws_raw,
        "window_end": we_raw,
        "capacity_slots": capacity,
        "reserved_slots": 0,
    })
    DB.delivery_windows[ent["id"]] = ent
    return success_object(public(ent), 201)


@bp.get("/sleep/delivery-windows/<window_id>")
def get_window(window_id):
    role, uid = authenticate()
    require_roles(role, uid, {"PlatformAdmin", "SalesAssociate", "DeliveryTechnician"})
    return success_object(public(_get_window_or_404(window_id)))


@bp.get("/sleep/delivery-windows")
def list_windows():
    role, uid = authenticate()
    require_roles(role, uid, {"PlatformAdmin", "SalesAssociate", "DeliveryTechnician"})
    limit, offset = parse_pagination()
    items = list(DB.delivery_windows.values())
    for key in ("store_id", "team_id"):
        v = request.args.get(key)
        if v is not None:
            items = [w for w in items if w.get(key) == v]
    window_date = request.args.get("window_date")
    if window_date is not None:
        items = [w for w in items if str(w.get("window_start", ""))[:10] == window_date]
    items = sorted_items(items)
    total = len(items)
    return success_list([public(w) for w in page(items, limit, offset)], limit, offset, total)


# ---------------------------------------------------------------- visits
@bp.post("/sleep/delivery-visits")
def create_visit():
    role, uid = authenticate()
    require_roles(role, uid, {"SalesAssociate"})
    data = body()
    order_id = require_str(req_field(data, "order_id"), "order_id")
    window_id = require_str(req_field(data, "delivery_window_id"), "delivery_window_id")
    remove_old = opt_field(data, "remove_old_mattress", False)
    remove_old = require_bool(remove_old, "remove_old_mattress")
    room_prep = data.get("room_prep_notes")
    if room_prep is not None:
        room_prep = require_str(room_prep, "room_prep_notes")
    allow_waitlist = opt_field(data, "allow_waitlist", False)
    allow_waitlist = require_bool(allow_waitlist, "allow_waitlist")
    order = DB.orders.get(order_id)
    if order is None:
        raise not_found("ERR_ORDER_NOT_FOUND", "order id does not resolve")
    window = _get_window_or_404(window_id)
    need = calc.slot_need(remove_old)
    # temporal: window start must be strictly after the logical clock
    if parse_iso(window["window_start"]) <= DB.clock.now():
        raise ApiError("ERR_WINDOW_IN_PAST", 422, "target window_start is not after the logical clock")
    # capacity check
    fits = window["reserved_slots"] + need <= window["capacity_slots"]
    if not fits and not allow_waitlist:
        raise ApiError("ERR_WINDOW_CAPACITY_EXCEEDED", 422,
                       "reserved_slots + slot_need exceeds capacity")
    visit = new_entity({
        "order_id": order_id,
        "delivery_window_id": window_id,
        "remove_old_mattress": remove_old,
        "slot_need": need,
        "room_prep_notes": room_prep,
        "setup_checklist": None,
        "status": "SCHEDULED" if fits else "WAITLISTED",
    })
    DB.delivery_visits[visit["id"]] = visit
    if fits:
        window["reserved_slots"] += need
        touch(window)
        _maybe_order_fulfilling(visit)
    return success_object(public(visit), 201)


@bp.get("/sleep/delivery-visits/<visit_id>")
def get_visit(visit_id):
    role, uid = authenticate()
    require_roles(role, uid, {"PlatformAdmin", "SalesAssociate", "DeliveryTechnician", "Customer"})
    visit = _get_visit_or_404(visit_id)
    if role == "Customer":
        order = DB.orders.get(visit["order_id"])
        check_customer_ownership(role, uid, order["customer_id"] if order else None)
    return success_object(public(visit))


@bp.get("/sleep/delivery-visits")
def list_visits():
    role, uid = authenticate()
    require_roles(role, uid, {"PlatformAdmin", "SalesAssociate", "DeliveryTechnician", "Customer"})
    limit, offset = parse_pagination()
    items = list(DB.delivery_visits.values())
    for key in ("order_id", "delivery_window_id"):
        v = request.args.get(key)
        if v is not None:
            items = [x for x in items if x.get(key) == v]
    if role == "Customer":
        own_orders = {o["id"] for o in DB.orders.values() if o["customer_id"] == uid}
        items = [x for x in items if x["order_id"] in own_orders]
    items = sorted_items(items)
    total = len(items)
    return success_list([public(x) for x in page(items, limit, offset)], limit, offset, total)


@bp.post("/sleep/delivery-visits/<visit_id>/reschedule")
def reschedule_visit(visit_id):
    role, uid = authenticate()
    require_roles(role, uid, {"SalesAssociate", "Customer"})
    visit = _get_visit_or_404(visit_id)
    if role == "Customer":
        order = DB.orders.get(visit["order_id"])
        check_customer_ownership(role, uid, order["customer_id"] if order else None)
    data = body()
    if visit["status"] in ("VERIFIED", "CANCELLED"):
        raise ApiError("ERR_VISIT_ALREADY_COMPLETED", 409,
                       "complete/reschedule against a VERIFIED or CANCELLED visit")
    expected = data.get("expected_visit_version")
    if expected is not None:
        expected = require_int(expected, "expected_visit_version")
        if expected != visit["version"]:
            raise ApiError("ERR_STALE_VERSION", 412, "expected_visit_version mismatch")
    new_window_id = require_str(req_field(data, "new_delivery_window_id"), "new_delivery_window_id")
    allow_waitlist = opt_field(data, "allow_waitlist", False)
    allow_waitlist = require_bool(allow_waitlist, "allow_waitlist")
    new_window = _get_window_or_404(new_window_id)
    # temporal check on target window
    if parse_iso(new_window["window_start"]) <= DB.clock.now():
        raise ApiError("ERR_WINDOW_IN_PAST", 422, "target window_start is not after the logical clock")
    was_consuming = visit["status"] in ("SCHEDULED", "FAILED_SETUP")
    old_window = DB.delivery_windows.get(visit["delivery_window_id"])
    need = visit["slot_need"]
    fits = new_window["reserved_slots"] + need <= new_window["capacity_slots"]
    if not fits and not allow_waitlist:
        raise ApiError("ERR_WINDOW_CAPACITY_EXCEEDED", 422,
                       "reserved_slots + slot_need exceeds capacity on new window")
    # release on old window (PRD: on success the visit releases its slot_need
    # on the old window, which triggers waitlist promotion there)
    if was_consuming and old_window is not None:
        old_window["reserved_slots"] -= need
        touch(old_window)
    visit["delivery_window_id"] = new_window_id
    if fits:
        new_window["reserved_slots"] += need
        touch(new_window)
        visit["status"] = "SCHEDULED"
    else:
        visit["status"] = "WAITLISTED"
    touch(visit)
    # waitlist promotion on the old window after release
    if was_consuming and old_window is not None:
        promote_waitlist(old_window)
    return success_object(public(visit))


_CHECKLIST_FLAGS = ("base_assembled", "chambers_connected", "remote_configured", "connectivity_verified")


@bp.post("/sleep/delivery-visits/<visit_id>/complete")
def complete_visit(visit_id):
    role, uid = authenticate()
    require_roles(role, uid, {"DeliveryTechnician"})
    visit = _get_visit_or_404(visit_id)
    data = body()
    if visit["status"] in ("VERIFIED", "CANCELLED"):
        raise ApiError("ERR_VISIT_ALREADY_COMPLETED", 409,
                       "complete/reschedule against a VERIFIED or CANCELLED visit")
    if visit["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "visit is not SCHEDULED")
    outcome = req_field(data, "outcome")
    if outcome not in ("VERIFIED", "FAILED_SETUP"):
        raise err_validation("outcome must be VERIFIED or FAILED_SETUP")
    checklist = req_field(data, "setup_checklist")
    if not isinstance(checklist, dict):
        raise err_validation("setup_checklist must be an object")
    visit["setup_checklist"] = checklist
    if outcome == "VERIFIED":
        if not all(checklist.get(f) is True for f in _CHECKLIST_FLAGS):
            raise ApiError("ERR_SETUP_CHECKLIST_INCOMPLETE", 422,
                           "all four checklist flags must be true")
        order = DB.orders.get(visit["order_id"])
        unpaired_base = any(
            d["order_id"] == visit["order_id"] and d["kind"] == "BASE"
            and d["pairing_status"] != "PAIRED"
            for d in DB.devices.values()
        )
        if unpaired_base:
            raise ApiError("ERR_DEVICE_NOT_PAIRED", 422,
                           "every BASE device on the order must be PAIRED")
        visit["status"] = "VERIFIED"
        touch(visit)
        if order is not None and order["order_status"] == "FULFILLING":
            order["order_status"] = "DELIVERED"
            order["trial_verified_at"] = DB.clock.now_iso()
            touch(order)
    else:
        visit["status"] = "FAILED_SETUP"
        touch(visit)
    return success_object(public(visit))
