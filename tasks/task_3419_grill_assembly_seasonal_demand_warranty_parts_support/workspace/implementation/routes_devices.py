"""ConnectedDevice pairing and firmware stewardship (PRD §3.9)."""

import uuid

from flask import Blueprint

import clock
from auth import authenticate, check_ownership, require_role
from errors import api_error, not_found, validation
from serialize import device_out
from store import db, new_entity, touch
from util import get_body, ok, ok_list, paginate, req_str, require

bp = Blueprint("devices", __name__, url_prefix="/grillops")

APP_USER = ("AppUser",)


@bp.post("/devices/pair")
def pair_device():
    _, role = authenticate()
    require_role(role, APP_USER)
    data = get_body()
    # rung 3: body-carried sale reference
    sale_id = require(data, "sale_id")
    sale = db.sales.get(sale_id)
    if sale is None:
        raise not_found("SALE")
    app_account_id = req_str(data, "app_account_id")
    # rung 5/9: at most one live (PAIRED | UPDATING) device per sale
    for other in db.devices.values():
        if other["sale_id"] == sale["id"] and other["status"] in ("PAIRED", "UPDATING"):
            raise api_error("ERR_DEVICE_ALREADY_PAIRED", "sale already has a paired device")
    # pairing doubles as registration: a still-SOLD sale registers with the
    # synthesized proof token; an already-REGISTERED sale is left as is
    if sale["status"] == "SOLD":
        sale["status"] = "REGISTERED"
        sale["proof_of_purchase_token"] = "APP-PAIR"
        sale["registered_at"] = clock.iso_z(clock.now())
        touch(sale)
    model = db.models.get(sale["model_id"])
    firmware = model["current_firmware_version"] if model is not None else "1.0.0"
    device = new_entity({
        "sale_id": sale["id"],
        "app_account_id": app_account_id,
        "pairing_token": str(uuid.uuid4()),
        "firmware_version": firmware,
        "status": "PAIRED",
    })
    db.devices[device["id"]] = device
    return ok(device_out(device), status=201)


@bp.post("/devices/<device_id>/firmware")
def device_firmware(device_id):
    _, role = authenticate()
    require_role(role, APP_USER)
    device = db.devices.get(device_id)
    if device is None:
        raise not_found("DEVICE")
    data = get_body()
    action = require(data, "action")
    if action not in ("UPDATE", "UNPAIR"):
        raise validation("action must be UPDATE or UNPAIR")
    # rung 5: both actions require the device to be currently PAIRED
    if device["status"] != "PAIRED":
        raise api_error("ERR_DEVICE_NOT_PAIRED", "device is not currently PAIRED")
    if action == "UPDATE":
        target_version = req_str(data, "target_version")
        if target_version == device["firmware_version"]:
            raise validation("target_version must differ from the current firmware_version")
        # PAIRED -> UPDATING -> PAIRED within the single request
        device["firmware_version"] = target_version
        device["status"] = "PAIRED"
    else:  # UNPAIR
        device["status"] = "UNPAIRED"
    touch(device)
    return ok(device_out(device))


@bp.get("/sales/<sale_id>/devices")
def list_sale_devices(sale_id):
    user_id, role = authenticate()
    require_role(role, ("ServiceAgent", "AppUser", "ChannelRep", "PlannerAdmin"))
    sale = db.sales.get(sale_id)
    if sale is None:
        raise not_found("SALE")
    if role == "ChannelRep":
        check_ownership(user_id, sale["channel_account_id"])
    # the device view returns the live pairing (zero or one entries)
    items = [
        d for d in db.devices.values()
        if d["sale_id"] == sale["id"] and d["status"] in ("PAIRED", "UPDATING")
    ]
    page, total, limit, offset = paginate(items)
    return ok_list([device_out(d) for d in page], total, limit, offset)
