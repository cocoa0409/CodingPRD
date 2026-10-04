# =============================================================================
# Provisioning sessions: create, list (per-device + global), get,
# verify, tokenize (OCC on session version)
# =============================================================================
from flask import Blueprint, request

import db
from domain import (
    NON_TERMINAL_SESSION_STATES, active_agreement_for_issuer, add_event,
    code_matches, compute_posture, expire_session_if_due,
    issuer_active_with_agreement, mint_dpan, plus_hours, recompute_active_token_count,
    SESSION_TTL_HOURS,
)
from errors import ApiError, validation
from helpers import (
    check_child, list_response, new_common_row, resolve_artifact, resolve_device,
    resolve_session,
)
from middleware import (
    get_body, opt_bool, req_enum, req_str, require_cardholder_owner,
)
from response import success_object

bp = Blueprint("provisioning", __name__)

VERIFY_METHODS = {"OTP_TEXT", "OTP_EMAIL", "ISSUER_APP"}


@bp.post("/devices/<deviceId>/provisioning-sessions")
def create_session(deviceId):
    body = get_body()
    card_artifact_id = req_str(body, "card_artifact_id")
    idempotency_key = req_str(body, "idempotency_key")
    device = resolve_device(deviceId)
    require_cardholder_owner(device)
    # Priority 7: idempotency — same key on same device replays original;
    # same key with a different payload is a conflict. Runs before body-FK
    # resolution so a replayed/conflicting key never 404s on a bogus artifact.
    for s in db.provisioning_sessions.values():
        if s["device_id"] == device["id"] and s["idempotency_key"] == idempotency_key:
            expire_session_if_due(s)
            if s["card_artifact_id"] != card_artifact_id:
                raise ApiError("ERR_IDEMPOTENCY_CONFLICT",
                               "Idempotency key reused with a different payload")
            return success_object(s, 201)
    artifact = resolve_artifact(card_artifact_id)

    # Priority 7.5: one active provisioning window per device
    for s in db.provisioning_sessions.values():
        if s["device_id"] == device["id"]:
            expire_session_if_due(s)
            if s["status"] in NON_TERMINAL_SESSION_STATES:
                raise ApiError("ERR_INVALID_STATE",
                               "Device already has a non-terminal provisioning session")

    # Priority 11: issuer ACTIVE with an ACTIVE agreement
    account = db.card_accounts.get(artifact["card_account_id"])
    if account is None or not issuer_active_with_agreement(account["issuer_id"]):
        raise ApiError("ERR_ISSUER_NOT_ACTIVE",
                       "Issuer must be ACTIVE with an ACTIVE agreement")
    # Priority 12: card account OPEN
    if account["status"] != "OPEN":
        raise ApiError("ERR_CARD_ACCOUNT_RESTRICTED", "Card account must be OPEN")

    now = db.get_clock()
    row = new_common_row({
        "device_id": device["id"],
        "card_artifact_id": card_artifact_id,
        "idempotency_key": idempotency_key,
        "verification_method": None,
        "verification_attempt_count": 0,
        "expires_at": plus_hours(now, SESSION_TTL_HOURS),
        "device_account_number": None,
        # INITIATED -> VERIFICATION_REQUIRED is automatic on creation
        "status": "VERIFICATION_REQUIRED",
    })
    db.provisioning_sessions[row["id"]] = row
    return success_object(row, 201)


@bp.get("/devices/<deviceId>/provisioning-sessions")
def list_device_sessions(deviceId):
    resolve_device(deviceId)
    rows = [s for s in db.provisioning_sessions.values() if s["device_id"] == deviceId]
    for s in rows:
        expire_session_if_due(s)
    return list_response(rows)


@bp.get("/provisioning-sessions/<sessionId>")
def get_session(sessionId):
    session = resolve_session(sessionId)
    expire_session_if_due(session)
    return success_object(session, 200)


@bp.get("/provisioning-sessions")
def list_sessions():
    rows = list(db.provisioning_sessions.values())
    for s in rows:
        expire_session_if_due(s)
    return list_response(rows, filters={
        "device_id": request.args.get("device_id"),
        "card_artifact_id": request.args.get("card_artifact_id"),
        "status": request.args.get("status"),
    })


@bp.post("/devices/<deviceId>/provisioning-sessions/<sessionId>/verify")
def verify_session(deviceId, sessionId):
    body = get_body()
    method = req_enum(body, "method", VERIFY_METHODS)
    code = req_str(body, "code")
    device = resolve_device(deviceId)
    require_cardholder_owner(device)
    session = resolve_session(sessionId)
    check_child(device, session, "device_id", "ERR_NOT_FOUND", "ProvisioningSession")

    # Priority 5: lazy expiry before any other check
    expire_session_if_due(session)
    if session["status"] == "EXPIRED":
        raise ApiError("ERR_PROVISIONING_SESSION_EXPIRED",
                       "Logical clock reached session expires_at")
    if session["status"] != "VERIFICATION_REQUIRED":
        raise ApiError("ERR_INVALID_STATE",
                       f"Session cannot be verified from {session['status']}")

    session["verification_method"] = method
    if not code_matches(session, method, code):
        # Third consecutive mismatch fails the session outright
        if session.get("consecutive_otp_mismatches", 0) + 1 >= 3:
            session["consecutive_otp_mismatches"] = 3
            session["status"] = "FAILED"
            db.touch(session)
            raise ApiError("ERR_OTP_MISMATCH",
                           "Verification code mismatch; session failed after third mismatch")
        session["consecutive_otp_mismatches"] = session.get("consecutive_otp_mismatches", 0) + 1
        db.touch(session)
        raise ApiError("ERR_OTP_MISMATCH", "Verification code does not match the issued challenge")

    session["consecutive_otp_mismatches"] = 0
    session["verification_attempt_count"] += 1
    if session["verification_attempt_count"] >= 2:
        session["status"] = "VERIFIED"
    db.touch(session)
    return success_object(session, 200)


@bp.post("/devices/<deviceId>/provisioning-sessions/<sessionId>/tokenize")
def tokenize_session(deviceId, sessionId):
    body = get_body()
    express = opt_bool(body, "express_transit_enabled", False)
    expected = body.get("expected_session_version")
    if expected is None or isinstance(expected, bool) or not isinstance(expected, int):
        raise validation("expected_session_version is required and must be an integer")
    device = resolve_device(deviceId)
    require_cardholder_owner(device)
    session = resolve_session(sessionId)
    check_child(device, session, "device_id", "ERR_NOT_FOUND", "ProvisioningSession")

    # Priority 5: lazy expiry first
    expire_session_if_due(session)
    if session["status"] == "EXPIRED":
        raise ApiError("ERR_PROVISIONING_SESSION_EXPIRED",
                       "Logical clock reached session expires_at")
    # OCC: tokenize-stale-session-version
    if session["version"] != expected:
        raise ApiError("ERR_VERSION_CONFLICT", "Stale expected_session_version")
    if session["status"] != "VERIFIED":
        raise ApiError("ERR_INVALID_STATE",
                       f"Session cannot be tokenized from {session['status']}")

    artifact = db.card_artifacts.get(session["card_artifact_id"])
    account = db.card_accounts.get(artifact["card_account_id"]) if artifact else None

    # Device posture gates: DEGRADED -> unsecured, LOST -> lost
    posture = compute_posture(device)
    if posture == "DEGRADED":
        raise ApiError("ERR_DEVICE_UNSECURED", "Device passcode is required")
    if posture == "LOST":
        raise ApiError("ERR_DEVICE_LOST", "Device is reported lost")
    # Priority 11/12: issuer participation + account open
    if account is None or not issuer_active_with_agreement(account["issuer_id"]):
        raise ApiError("ERR_ISSUER_NOT_ACTIVE",
                       "Issuer must be ACTIVE with an ACTIVE agreement")
    if account["status"] != "OPEN":
        raise ApiError("ERR_CARD_ACCOUNT_RESTRICTED", "Card account must be OPEN")
    # Express transit flag requires TRANSIT product + agreement support
    if express:
        agreement = active_agreement_for_issuer(account["issuer_id"])
        if account["card_product"] != "TRANSIT" or not agreement["express_transit_supported"]:
            raise ApiError("ERR_EXPRESS_TRANSIT_NOT_SUPPORTED",
                           "Express transit requires TRANSIT product and agreement support")

    dpan = mint_dpan()
    session["device_account_number"] = dpan
    session["status"] = "TOKENIZED"
    db.touch(session)

    token = new_common_row({
        "device_id": device["id"],
        "card_account_id": account["id"],
        "card_artifact_id": artifact["id"],
        "issuer_id": account["issuer_id"],
        "device_account_number": dpan,
        "express_transit_enabled": express,
        "auth_attempt_count": 0,
        "approved_auth_count": 0,
        "decline_count": 0,
        "consecutive_decline_count": 0,
        "suspension_count": 0,
        "last_decline_reason": None,
        "deactivated_reason": None,
        "status": "ACTIVE",
    })
    db.payment_tokens[token["id"]] = token
    add_event(token["id"], "ACTIVATION", {})
    recompute_active_token_count(device)
    db.touch(device)
    return success_object(token, 201)
