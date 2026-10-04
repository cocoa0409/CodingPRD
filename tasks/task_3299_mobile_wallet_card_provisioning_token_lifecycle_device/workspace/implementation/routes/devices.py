# =============================================================================
# Devices: register, read, set-security, report_lost, report_found,
# default-card (OCC), per-device token listing
# =============================================================================
from flask import Blueprint

import db
from domain import (
    add_event, compute_posture, recompute_active_token_count, suspend_token,
)
from errors import ApiError, forbidden, validation
from helpers import (
    check_child, list_response, new_common_row, resolve_device, resolve_token,
)
from middleware import (
    get_body, opt_bool, req_str, require_cardholder_owner, require_roles,
)
from response import success_object

bp = Blueprint("devices", __name__)


@bp.post("/devices")
def create_device():
    body = get_body()
    cardholder_id = req_str(body, "cardholder_id")
    device_serial = req_str(body, "device_serial")
    device_model = req_str(body, "device_model")
    os_version = req_str(body, "os_version")
    user_id, _ = require_roles(["Cardholder"])
    if cardholder_id not in db.cardholders:
        raise ApiError("ERR_NOT_FOUND", f"Cardholder {cardholder_id} does not exist")
    # Ownership: a cardholder registers devices only for themselves
    if cardholder_id != user_id:
        raise forbidden("Cardholder may only register devices for themselves")
    row = new_common_row({
        "cardholder_id": cardholder_id,
        "device_serial": device_serial,
        "device_model": device_model,
        "os_version": os_version,
        "passcode_enabled": False,
        "biometric_enabled": False,
        "is_lost": False,
        "reported_lost_at": None,
        "found_at": None,
        "security_posture": "DEGRADED",
        "active_token_count": 0,
        "default_card_id": None,
    })
    db.devices[row["id"]] = row
    return success_object(row, 201)


@bp.get("/devices/<deviceId>")
def get_device(deviceId):
    row = resolve_device(deviceId)
    row["security_posture"] = compute_posture(row)
    return success_object(row, 200)


@bp.post("/devices/<deviceId>/set-security")
def set_security(deviceId):
    body = get_body()
    passcode = opt_bool(body, "passcode_enabled", None)
    biometric = opt_bool(body, "biometric_enabled", None)
    device = resolve_device(deviceId)
    require_cardholder_owner(device)
    if passcode is None:
        raise validation("passcode_enabled is required")
    if biometric is None:
        raise validation("biometric_enabled is required")
    device["passcode_enabled"] = passcode
    device["biometric_enabled"] = biometric
    db.touch(device)
    device["security_posture"] = compute_posture(device)
    return success_object(device, 200)


@bp.post("/devices/<deviceId>/report_lost")
def report_lost(deviceId):
    device = resolve_device(deviceId)
    user_id, role = require_roles(["Cardholder", "IssuerOperator", "CustomerService"])
    if role == "Cardholder" and device["cardholder_id"] != user_id:
        raise forbidden("Cardholder does not own this device")
    device["is_lost"] = True
    device["reported_lost_at"] = db.get_clock()
    db.touch(device)
    device["security_posture"] = compute_posture(device)
    # Sweep: every ACTIVE token on this device -> SUSPENDED; default cleared
    for token in db.payment_tokens.values():
        if token["device_id"] == device["id"] and token["status"] == "ACTIVE":
            suspend_token(token, "lost_device")
    device["default_card_id"] = None
    recompute_active_token_count(device)
    return success_object(device, 200)


@bp.post("/devices/<deviceId>/report_found")
def report_found(deviceId):
    device = resolve_device(deviceId)
    user_id, role = require_roles(["Cardholder", "CustomerService"])
    if role == "Cardholder" and device["cardholder_id"] != user_id:
        raise forbidden("Cardholder does not own this device")
    device["found_at"] = db.get_clock()
    device["is_lost"] = False
    db.touch(device)
    device["security_posture"] = compute_posture(device)
    return success_object(device, 200)


@bp.post("/devices/<deviceId>/default-card")
def set_default_card(deviceId):
    body = get_body()
    token_id = req_str(body, "token_id")
    expected = body.get("expected_device_version")
    if expected is None or isinstance(expected, bool) or not isinstance(expected, int):
        raise validation("expected_device_version is required and must be an integer")
    device = resolve_device(deviceId)
    require_cardholder_owner(device)
    token = resolve_token(token_id)
    check_child(device, token, "device_id", "ERR_TOKEN_NOT_FOUND", "PaymentToken")
    # OCC (device-default-stale-version)
    if device["version"] != expected:
        raise ApiError("ERR_VERSION_CONFLICT", "Stale expected_device_version")
    # Priority 21: candidate must be ACTIVE and bound to this device
    if token["status"] != "ACTIVE":
        raise ApiError("ERR_TOKEN_NOT_ACTIVE", "Default card candidate must be ACTIVE")
    device["default_card_id"] = token["id"]
    db.touch(device)
    device["security_posture"] = compute_posture(device)
    return success_object(device, 200)


@bp.get("/devices/<deviceId>/tokens")
def list_device_tokens(deviceId):
    resolve_device(deviceId)
    rows = [t for t in db.payment_tokens.values() if t["device_id"] == deviceId]
    return list_response(rows)
