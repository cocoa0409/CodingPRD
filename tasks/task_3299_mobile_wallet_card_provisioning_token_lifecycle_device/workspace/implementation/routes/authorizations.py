# =============================================================================
# Authorizations: POST /payment-tokens/{id}/authorizations (gate chain 8-17,
# cryptogram decision, fee accrual), list per token, global list
# =============================================================================
from flask import Blueprint, request

import db
from domain import (
    DECLINE_STREAK_SUSPEND_THRESHOLD, PER_AUTH_CAP_CENTS, active_agreement_for_issuer,
    add_event, compute_fee, compute_posture, issuer_active_with_agreement,
    suspend_token,
)
from errors import ApiError
from helpers import (
    list_response, new_common_row, resolve_operator, resolve_token,
)
from middleware import (
    get_body, opt_bool, opt_str, req_enum, req_int, req_str, require_roles,
)
from response import success_object

bp = Blueprint("authorizations", __name__)

MERCHANT_CATEGORIES = {"GENERAL", "TRANSIT"}


@bp.post("/payment-tokens/<tokenId>/authorizations")
def create_authorization(tokenId):
    body = get_body()
    cryptogram = req_str(body, "cryptogram")
    amount_cents = req_int(body, "amount_cents")
    currency = req_str(body, "currency")
    merchant_id = req_str(body, "merchant_id")
    merchant_category = req_enum(body, "merchant_category", MERCHANT_CATEGORIES)
    biometric_verified = opt_bool(body, "biometric_verified", False)
    express_mode = opt_bool(body, "express_mode", False)
    transit_operator_id = opt_str(body, "transit_operator_id", None)

    require_roles(["IssuerOperator"])
    token = resolve_token(tokenId)
    device = db.devices.get(token["device_id"])
    account = db.card_accounts.get(token["card_account_id"])

    operator = None
    if transit_operator_id is not None:
        operator = resolve_operator(transit_operator_id)

    # ---- Gate chain, priorities 8-17 (no Authorization row on failure) ----
    # 8: token ACTIVE
    if token["status"] != "ACTIVE":
        raise ApiError("ERR_TOKEN_NOT_ACTIVE", "Token must be ACTIVE to authorize")
    posture = compute_posture(device) if device else "LOST"
    # 9: DEGRADED blocks non-express authorization
    if posture == "DEGRADED" and not express_mode:
        raise ApiError("ERR_DEVICE_UNSECURED", "Device passcode is required")
    # 10: LOST blocks authorization in any mode
    if posture == "LOST":
        raise ApiError("ERR_DEVICE_LOST", "Device is reported lost")
    # 11: issuer ACTIVE with ACTIVE agreement
    if account is None or not issuer_active_with_agreement(token["issuer_id"]):
        raise ApiError("ERR_ISSUER_NOT_ACTIVE",
                       "Issuer must be ACTIVE with an ACTIVE agreement")
    # 12: card account OPEN
    if account["status"] != "OPEN":
        raise ApiError("ERR_CARD_ACCOUNT_RESTRICTED", "Card account must be OPEN")
    # 13: biometric gate (skipped for express mode)
    if not express_mode and device and device["biometric_enabled"] and not biometric_verified:
        raise ApiError("ERR_AUTHENTICATION_REQUIRED", "Biometric verification required")
    # 14: per-authorization amount cap
    if amount_cents > PER_AUTH_CAP_CENTS:
        raise ApiError("ERR_AUTH_AMOUNT_EXCEEDS_CAP",
                       f"amount_cents exceeds the per-authorization cap of {PER_AUTH_CAP_CENTS}")
    # 15: enrolled merchant-program cap
    for enrollment in db.merchant_card_programs.values():
        if (enrollment["card_account_id"] == account["id"]
                and enrollment["status"] == "ACTIVE"):
            program = db.merchant_programs.get(enrollment["merchant_program_id"])
            if (program is not None and program["status"] == "ACTIVE"
                    and program["merchant_name"] == merchant_id
                    and amount_cents > program["max_auth_amount_cents"]):
                raise ApiError("ERR_PROGRAM_AMOUNT_EXCEEDS_CAP",
                               "Authorization exceeds enrolled merchant program cap")
    # 16: express transit eligibility
    if express_mode:
        agreement = active_agreement_for_issuer(token["issuer_id"])
        if not token["express_transit_enabled"]:
            raise ApiError("ERR_EXPRESS_TRANSIT_NOT_SUPPORTED",
                           "Token is not express-transit enabled")
        if account["card_product"] != "TRANSIT":
            raise ApiError("ERR_EXPRESS_TRANSIT_NOT_SUPPORTED",
                           "Express transit requires a TRANSIT card product")
        if agreement is None or not agreement["express_transit_supported"]:
            raise ApiError("ERR_EXPRESS_TRANSIT_NOT_SUPPORTED",
                           "Agreement does not support express transit")
        if operator is None or operator["status"] != "ACTIVE":
            raise ApiError("ERR_EXPRESS_TRANSIT_NOT_SUPPORTED",
                           "An ACTIVE transit operator is required")
        if operator["express_cap_cents"] < amount_cents:
            raise ApiError("ERR_EXPRESS_TRANSIT_NOT_SUPPORTED",
                           "Amount exceeds the operator express cap")
    # 17: transit allowlist (SUSPENDED operator blocks under the same code)
    if operator is not None:
        if operator["status"] != "ACTIVE":
            raise ApiError("ERR_TRANSIT_NOT_ALLOWED", "Transit operator is SUSPENDED")
        if operator["allowlist_active"]:
            allowed = any(
                e["transit_operator_id"] == operator["id"]
                and e["card_account_id"] == account["id"]
                and e["status"] == "ACTIVE"
                for e in db.transit_allowlist.values()
            )
            if not allowed:
                raise ApiError("ERR_TRANSIT_NOT_ALLOWED",
                               "Card account is not on the operator's allowlist")

    # ---- Phase two: persist the Authorization and decide by cryptogram ----
    auth = new_common_row({
        "payment_token_id": token["id"],
        "cryptogram": cryptogram,
        "amount_cents": amount_cents,
        "currency": currency,
        "merchant_id": merchant_id,
        "merchant_category": merchant_category,
        "biometric_verified": biometric_verified,
        "express_mode": express_mode,
        "declined_reason": None,
        "status": "PENDING",
    })
    db.authorizations[auth["id"]] = auth

    token["auth_attempt_count"] += 1

    if cryptogram == "DECLINE":
        auth["status"] = "DECLINED"
        auth["declined_reason"] = "ISSUER_DECLINED"
    elif cryptogram == "DECLINE_FRAUD":
        auth["status"] = "DECLINED"
        auth["declined_reason"] = "FRAUD_SUSPECTED"
    else:
        auth["status"] = "APPROVED"

    if auth["status"] == "APPROVED":
        token["approved_auth_count"] += 1
        token["consecutive_decline_count"] = 0
        # Issuer fee accrual (ledger variant) onto the ACTIVE agreement
        agreement = active_agreement_for_issuer(token["issuer_id"])
        if agreement is not None:
            db.fee_ledgers[agreement["id"]] = (
                db.fee_ledgers.get(agreement["id"], 0)
                + compute_fee(amount_cents, agreement)
            )
        add_event(token["id"], "AUTHORIZATION_APPROVED",
                  {"authorization_id": auth["id"], "amount_cents": amount_cents})
    else:
        token["decline_count"] += 1
        token["consecutive_decline_count"] += 1
        token["last_decline_reason"] = auth["declined_reason"]
        add_event(token["id"], "AUTHORIZATION_DECLINED",
                  {"authorization_id": auth["id"], "reason": auth["declined_reason"]})
        db.touch(token)
        # Auto-suspend on reaching the decline-streak threshold
        if (token["consecutive_decline_count"] >= DECLINE_STREAK_SUSPEND_THRESHOLD
                and token["status"] == "ACTIVE"):
            suspend_token(token, "decline_streak")

    db.touch(token)
    return success_object(auth, 201)


@bp.get("/payment-tokens/<tokenId>/authorizations")
def list_token_authorizations(tokenId):
    resolve_token(tokenId)
    rows = [a for a in db.authorizations.values() if a["payment_token_id"] == tokenId]
    return list_response(rows)


@bp.get("/authorizations")
def list_authorizations():
    return list_response(db.authorizations.values(), filters={
        "payment_token_id": request.args.get("payment_token_id"),
        "status": request.args.get("status"),
        "merchant_id": request.args.get("merchant_id"),
    })
