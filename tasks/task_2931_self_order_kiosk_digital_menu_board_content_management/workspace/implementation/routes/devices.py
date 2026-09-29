"""Kiosk hardware: registration, heartbeats, cache sync, attestation (PRD 3.8)."""
from flask import Blueprint

import auth
import calc
import constants as C
import derive
import logical_clock as clockmod
import response
import serialize
import shapes
from db import DB, append_audit, new_row, ordered, touch
from errors import fail
from routes.common import fk, listing, path_row

bp = Blueprint("devices", __name__)

READ_ROLES = ("PlatformAdmin", "ContentManager", "ComplianceOfficer", "StoreOperator")


@bp.post("/devices")
def register_device():
    ctx = auth.enter(["PlatformAdmin", "StoreOperator"])
    data = shapes.body()
    raw_store = data.get("store_id")
    if isinstance(raw_store, str):
        auth.require_store_scope(ctx, raw_store)
    store_id = fk(data, "store_id", "stores")
    if store_id is None:
        shapes.req_str(data, "store_id", 1, None)
    kind = shapes.req_enum(data, "device_kind", C.DEVICE_KINDS)
    code = shapes.req_str(data, "device_code", 1, 16)
    capacity = shapes.req_int(data, "offline_cache_capacity", 0, 50)
    firmware = shapes.opt_str(data, "pin_pad_firmware_version", 1, 64, None)
    for other in DB.devices.values():
        if other.get("store_id") == store_id and other.get("device_code") == code:
            fail("ERR_DUPLICATE_NATURAL_KEY", "device_code is already used in this store")
    if kind == "KIOSK" and not firmware:
        fail("ERR_DEVICE_KIND_NOT_SUPPORTED", "a kiosk must declare its PIN-pad firmware version")
    row = new_row({
        "store_id": store_id,
        "device_kind": kind,
        "device_code": code,
        "offline_cache_capacity": capacity,
        "pin_pad_firmware_version": firmware,
        "printer_ok": False,
        "touch_ok": False,
        "screen_reader_ok": False,
        "network_ok": False,
        "last_heartbeat_utc": None,
        "consecutive_missed_heartbeats": 0,
        "rolling_health_score": 0,
        "worst_case_health_score": 0,
        "health_state": "OFFLINE",
        "cached_bundle_id": None,
        "cached_bundle_version": 0,
        "cache_state": "MISSING",
        "offline_order_count": 0,
        "attestation_expiry_utc": None,
        "p2pe_certified": False,
        "payment_compliance_state": "UNATTESTED" if kind == "KIOSK" else "NOT_APPLICABLE",
    })
    DB.devices[row["id"]] = row
    store = DB.stores.get(store_id)
    if store is not None:
        derive.recompute_store(store)
    return response.created(serialize.dump("device", row))


@bp.get("/devices")
def list_devices():
    auth.enter(READ_ROLES)
    return listing("devices", "device")


@bp.get("/devices/<device_id>")
def get_device(device_id):
    ctx = auth.enter(READ_ROLES + ("DeviceAgent",))
    row = DB.devices.get(device_id)
    if row is not None:
        auth.require_store_scope(ctx, row.get("store_id"))
    row = path_row("devices", device_id)
    derive.rescore_device(row)
    derive.recompute_device_payment(row)
    return response.ok(serialize.dump("device", row))


@bp.post("/devices/<device_id>/heartbeat")
def heartbeat(device_id):
    ctx = auth.enter(["DeviceAgent", "PlatformAdmin"])
    auth.require_device_identity(ctx, device_id)
    device = path_row("devices", device_id)
    data = shapes.body()
    printer = shapes.req_bool(data, "printer_ok")
    touch_ok = shapes.req_bool(data, "touch_ok")
    screen_reader = shapes.req_bool(data, "screen_reader_ok")
    network = shapes.req_bool(data, "network_ok")
    device["printer_ok"] = printer
    device["touch_ok"] = touch_ok
    device["screen_reader_ok"] = screen_reader
    device["network_ok"] = network
    device["last_heartbeat_utc"] = clockmod.now_iso()
    device["consecutive_missed_heartbeats"] = 0
    touch(device)
    derive.rescore_device(device, bump=False, audit=False)
    store = DB.stores.get(device.get("store_id"))
    if store is not None:
        derive.recompute_store(store)
    return response.ok(serialize.dump("device", device))


@bp.post("/devices/<device_id>/cache-sync")
def cache_sync(device_id):
    ctx = auth.enter(["DeviceAgent", "PlatformAdmin", "StoreOperator"])
    auth.require_device_identity(ctx, device_id)
    device = DB.devices.get(device_id)
    if device is not None:
        auth.require_store_scope(ctx, device.get("store_id"))
    device = path_row("devices", device_id)
    data = shapes.body()
    bundle_id = fk(data, "bundle_id", "bundles")
    if bundle_id is None:
        shapes.req_str(data, "bundle_id", 1, None)
    flush = shapes.opt_bool(data, "flush_offline_orders", False)
    bundle = DB.bundles[bundle_id]
    store = DB.stores.get(device.get("store_id"))
    chain = calc.store_chain_ids(store) if store is not None else []
    if bundle.get("state") != "PUBLISHED" or bundle.get("cluster_id") not in chain:
        fail("ERR_BUNDLE_NOT_PUBLISHED", "the bundle is not published on this store's chain")
    if 1 > int(device.get("offline_cache_capacity", 0)):
        fail("ERR_OFFLINE_CACHE_CAPACITY_EXCEEDED", "the device may not retain another bundle")
    if device.get("device_kind") == "KIOSK" and store is not None:
        certified = clockmod.parse_instant(store.get("accessibility_certified_until_utc"))
        if certified is None or certified < clockmod.now():
            fail("ERR_STORE_ACCESSIBILITY_LAPSED", "the store's accessibility certification lapsed")
    device["cached_bundle_id"] = bundle["id"]
    device["cached_bundle_version"] = bundle["bundle_version"]
    device["cache_state"] = "STALE" if bundle.get("stale_flag") else "FRESH"
    touch(device)
    if flush:
        for order in ordered(list(DB.orders.values())):
            if order.get("device_id") != device["id"] or order.get("handoff_state") != "CACHED_OFFLINE":
                continue
            derive.apply_changes(order, {"handoff_state": "QUEUED_TO_KITCHEN"})
            append_audit("ORDER_HANDOFF", order["id"], "ORDER_FLUSHED_TO_KITCHEN",
                         ctx["role"], ctx["user_id"], detail="OFFLINE_ORDER_RELEASED")
    derive.recompute_offline_order_count(device, bump=False)
    if store is not None:
        derive.recompute_store(store)
    return response.ok(serialize.dump("device", device))


@bp.post("/devices/<device_id>/payment-attestation")
def payment_attestation(device_id):
    ctx = auth.enter(["ComplianceOfficer", "PlatformAdmin"])
    device = path_row("devices", device_id)
    data = shapes.body()
    firmware = shapes.req_str(data, "pin_pad_firmware_version", 1, 64)
    certified = shapes.req_bool(data, "p2pe_certified")
    expiry = shapes.req_instant(data, "attestation_expiry_utc")
    if device.get("device_kind") == "MENU_BOARD":
        fail("ERR_DEVICE_KIND_NOT_SUPPORTED", "a menu board has no payment device")
    device["pin_pad_firmware_version"] = firmware
    device["p2pe_certified"] = certified
    device["attestation_expiry_utc"] = clockmod.iso(expiry)
    device["payment_compliance_state"] = calc.payment_band(device)
    touch(device)
    append_audit("DEVICE", device["id"], "DEVICE_ATTESTED", ctx["role"], ctx["user_id"],
                 detail="ATTESTATION_RECORDED")
    if device["payment_compliance_state"] == "NON_COMPLIANT":
        append_audit("DEVICE", device["id"], "DEVICE_NON_COMPLIANT", ctx["role"], ctx["user_id"],
                     detail="ATTESTATION_NON_COMPLIANT")
    store = DB.stores.get(device.get("store_id"))
    if store is not None:
        derive.recompute_store(store)
    return response.ok(serialize.dump("device", device))
