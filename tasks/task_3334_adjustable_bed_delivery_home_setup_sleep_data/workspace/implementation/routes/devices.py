"""Devices and sleep nights."""
from flask import Blueprint, request

import calculations as calc
from db import DB
from errors import ApiError, err_validation, not_found
from helpers import (
    body, new_entity, opt_field, page, parse_pagination, public, req_field,
    require_bool, require_enum, require_int, require_str, sorted_items, touch,
)
from middleware import authenticate, check_customer_ownership, require_roles
from response import success_list, success_object

bp = Blueprint("devices", __name__)

DEVICE_KINDS = {"BASE", "PUMP", "CHAMBER", "SENSOR"}
ORDER_TERMINAL = {"CANCELLED", "CLOSED", "RETURNED"}


def _get_device_or_404(device_id):
    d = DB.devices.get(device_id)
    if d is None:
        raise not_found("ERR_DEVICE_NOT_FOUND", "device id does not resolve")
    return d


@bp.post("/sleep/devices")
def create_device():
    role, uid = authenticate()
    require_roles(role, uid, {"DeliveryTechnician"})
    data = body()
    order_id = require_str(req_field(data, "order_id"), "order_id")
    kind = require_enum(req_field(data, "kind"), "kind", DEVICE_KINDS)
    serial = require_str(req_field(data, "serial_number"), "serial_number")
    firmware = require_str(req_field(data, "firmware_version"), "firmware_version")
    order = DB.orders.get(order_id)
    if order is None:
        raise not_found("ERR_ORDER_NOT_FOUND", "order id does not resolve")
    if order["order_status"] in ORDER_TERMINAL:
        raise ApiError("ERR_INVALID_STATE", 409, "order is terminal")
    ent = new_entity({
        "order_id": order_id,
        "customer_id": order["customer_id"],
        "kind": kind,
        "serial_number": serial,
        "firmware_version": firmware,
        "pairing_status": "UNPAIRED",
        "connectivity": "OFFLINE",
        "final_nights_count": 0,
    })
    DB.devices[ent["id"]] = ent
    return success_object(public(ent), 201)


@bp.get("/sleep/devices/<device_id>")
def get_device(device_id):
    role, uid = authenticate()
    require_roles(role, uid, {"PlatformAdmin", "DeliveryTechnician", "ServiceAgent", "Customer"})
    device = _get_device_or_404(device_id)
    check_customer_ownership(role, uid, device["customer_id"])
    return success_object(public(device))


@bp.get("/sleep/devices")
def list_devices():
    role, uid = authenticate()
    require_roles(role, uid, {"PlatformAdmin", "DeliveryTechnician", "ServiceAgent", "Customer"})
    limit, offset = parse_pagination()
    items = list(DB.devices.values())
    for key in ("order_id", "customer_id"):
        v = request.args.get(key)
        if v is not None:
            items = [d for d in items if d.get(key) == v]
    if role == "Customer":
        items = [d for d in items if d["customer_id"] == uid]
    items = sorted_items(items)
    total = len(items)
    return success_list([public(d) for d in page(items, limit, offset)], limit, offset, total)


@bp.post("/sleep/devices/<device_id>/pair")
def pair_device(device_id):
    role, uid = authenticate()
    require_roles(role, uid, {"DeliveryTechnician"})
    device = _get_device_or_404(device_id)
    data = body()
    target = require_enum(req_field(data, "target_status"), "target_status", {"PAIRED", "UNPAIRED"})
    connectivity_verified = opt_field(data, "connectivity_verified", False)
    connectivity_verified = require_bool(connectivity_verified, "connectivity_verified")
    order = DB.orders.get(device["order_id"])
    if target == "PAIRED":
        if order is not None and order["order_status"] in ("CANCELLED", "RETURNED"):
            raise ApiError("ERR_INVALID_STATE", 409,
                           "order is CANCELLED or RETURNED; pairing refused")
        device["pairing_status"] = "PAIRED"
        device["connectivity"] = "ONLINE" if connectivity_verified else "OFFLINE"
    else:
        device["pairing_status"] = "UNPAIRED"
        device["connectivity"] = "OFFLINE"
    touch(device)
    return success_object(public(device))


# ---------------------------------------------------------------- sleep nights
@bp.post("/sleep/devices/<device_id>/sleep-nights")
def ingest_sleep_night(device_id):
    role, uid = authenticate()
    require_roles(role, uid, {"DeviceGateway"})
    device = _get_device_or_404(device_id)
    data = body()
    night_date = require_str(req_field(data, "night_date"), "night_date")
    import re
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", night_date):
        raise err_validation("night_date must be YYYY-MM-DD")
    minutes = require_int(req_field(data, "minutes_asleep"), "minutes_asleep")
    restlessness = require_int(req_field(data, "restlessness_events"), "restlessness_events")
    hr = require_int(req_field(data, "avg_heart_rate"), "avg_heart_rate")
    for n in DB.sleep_nights.values():
        if n["device_id"] == device_id and n["night_date"] == night_date:
            raise ApiError("ERR_DUPLICATE_NIGHT", 409,
                           "a SleepNight already exists for (device_id, night_date)")
    ent = new_entity({
        "device_id": device_id,
        "customer_id": device["customer_id"],
        "night_date": night_date,
        "minutes_asleep": minutes,
        "restlessness_events": restlessness,
        "avg_heart_rate": hr,
        "provisional_score": calc.provisional_score(minutes, restlessness),
        "final_score": None,
        "status": "PROVISIONAL",
    })
    DB.sleep_nights[ent["id"]] = ent
    return success_object(public(ent), 201)


@bp.get("/sleep/sleep-nights/<night_id>")
def get_sleep_night(night_id):
    role, uid = authenticate()
    require_roles(role, uid, {"PlatformAdmin", "ServiceAgent", "Customer"})
    night = DB.sleep_nights.get(night_id)
    if night is None:
        raise not_found("ERR_SLEEP_NIGHT_NOT_FOUND", "sleep night id does not resolve")
    check_customer_ownership(role, uid, night["customer_id"])
    return success_object(public(night))


@bp.get("/sleep/sleep-nights")
def list_sleep_nights():
    role, uid = authenticate()
    require_roles(role, uid, {"PlatformAdmin", "ServiceAgent", "Customer"})
    limit, offset = parse_pagination()
    items = list(DB.sleep_nights.values())
    for key in ("device_id", "customer_id"):
        v = request.args.get(key)
        if v is not None:
            items = [n for n in items if n.get(key) == v]
    if role == "Customer":
        items = [n for n in items if n["customer_id"] == uid]
    detail = request.args.get("detail")
    if detail == "FULL":
        # entitlement gate on the owning customer(s) of the filtered set
        owner_ids = {n["customer_id"] for n in items}
        for cid in owner_ids:
            cust = DB.customers.get(cid)
            if cust is None:
                continue
            if cust["subscription_tier"] not in ("PLUS", "PREMIUM") or cust["subscription_status"] != "ACTIVE":
                raise ApiError("ERR_ENTITLEMENT_REQUIRED", 403,
                               "detail=FULL requires PLUS or PREMIUM with ACTIVE subscription")
        if not owner_ids:
            # no rows: gate against requesting customer when Customer role
            if role == "Customer":
                cust = DB.customers.get(uid)
                if cust is not None and (
                    cust["subscription_tier"] not in ("PLUS", "PREMIUM")
                    or cust["subscription_status"] != "ACTIVE"
                ):
                    raise ApiError("ERR_ENTITLEMENT_REQUIRED", 403,
                                   "detail=FULL requires PLUS or PREMIUM with ACTIVE subscription")
    items = sorted_items(items)
    total = len(items)
    return success_list([public(n) for n in page(items, limit, offset)], limit, offset, total)
