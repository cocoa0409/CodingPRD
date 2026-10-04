# =============================================================================
# Payment tokens: get, global list, suspend / resume / deactivate, events
# =============================================================================
from flask import Blueprint, request

import db
from domain import (
    add_event, compute_posture, deactivate_token, recompute_active_token_count,
)
from errors import ApiError
from helpers import (
    check_child, list_response, resolve_device, resolve_token,
)
from middleware import require_cardholder_owner
from response import success_object

bp = Blueprint("tokens", __name__)


@bp.get("/payment-tokens/<tokenId>")
def get_token(tokenId):
    return success_object(resolve_token(tokenId), 200)


@bp.get("/payment-tokens")
def list_tokens():
    return list_response(db.payment_tokens.values(), filters={
        "device_id": request.args.get("device_id"),
        "card_account_id": request.args.get("card_account_id"),
        "card_artifact_id": request.args.get("card_artifact_id"),
        "issuer_id": request.args.get("issuer_id"),
        "status": request.args.get("status"),
    })


def _resolve_owned_token(deviceId, tokenId):
    device = resolve_device(deviceId)
    require_cardholder_owner(device)
    token = resolve_token(tokenId)
    check_child(device, token, "device_id", "ERR_TOKEN_NOT_FOUND", "PaymentToken")
    return device, token


@bp.post("/devices/<deviceId>/tokens/<tokenId>/suspend")
def suspend_token_route(deviceId, tokenId):
    device, token = _resolve_owned_token(deviceId, tokenId)
    if token["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE",
                       f"Token cannot be suspended from {token['status']}")
    token["status"] = "SUSPENDED"
    token["suspension_count"] += 1
    db.touch(token)
    add_event(token["id"], "SUSPENSION", {"reason": "user"})
    recompute_active_token_count(device)
    db.touch(device)
    return success_object(token, 200)


@bp.post("/devices/<deviceId>/tokens/<tokenId>/resume")
def resume_token_route(deviceId, tokenId):
    device, token = _resolve_owned_token(deviceId, tokenId)
    # Device must be HEALTHY: DEGRADED -> ERR_DEVICE_UNSECURED, LOST -> ERR_DEVICE_LOST
    posture = compute_posture(device)
    if posture == "DEGRADED":
        raise ApiError("ERR_DEVICE_UNSECURED", "Device passcode is required")
    if posture == "LOST":
        raise ApiError("ERR_DEVICE_LOST", "Device is reported lost")
    account = db.card_accounts.get(token["card_account_id"])
    if account is None or account["status"] != "OPEN":
        raise ApiError("ERR_CARD_ACCOUNT_RESTRICTED", "Funding CardAccount must be OPEN")
    if token["status"] != "SUSPENDED":
        raise ApiError("ERR_INVALID_STATE",
                       f"Token cannot be resumed from {token['status']}")
    token["status"] = "ACTIVE"
    db.touch(token)
    add_event(token["id"], "RESUMPTION", {})
    recompute_active_token_count(device)
    db.touch(device)
    return success_object(token, 200)


@bp.post("/devices/<deviceId>/tokens/<tokenId>/deactivate")
def deactivate_token_route(deviceId, tokenId):
    device, token = _resolve_owned_token(deviceId, tokenId)
    if token["status"] not in ("ACTIVE", "SUSPENDED"):
        raise ApiError("ERR_INVALID_STATE",
                       f"Token cannot be deactivated from {token['status']}")
    # User-initiated removal
    deactivate_token(token, "USER_REMOVE")
    return success_object(token, 200)


@bp.get("/payment-tokens/<tokenId>/events")
def list_token_events(tokenId):
    resolve_token(tokenId)
    rows = [e for e in db.token_events.values() if e["payment_token_id"] == tokenId]
    return list_response(rows)
