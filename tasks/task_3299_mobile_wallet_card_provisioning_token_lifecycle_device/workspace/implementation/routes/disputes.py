# =============================================================================
# Disputes: open (traced from authorization), get, list, resolve-dispute
# =============================================================================
from flask import Blueprint, request

import db
from errors import ApiError
from helpers import (
    list_response, new_common_row, resolve_authorization,
    resolve_dispute as lookup_dispute, resolve_token,
)
from middleware import get_body, req_enum, req_int, require_roles
from response import success_object

bp = Blueprint("disputes", __name__)

DISPUTE_REASONS = {"UNRECOGNIZED", "DUPLICATE", "FRAUD", "GOODS_NOT_RECEIVED"}


@bp.post("/authorizations/<authorizationId>/disputes")
def create_dispute(authorizationId):
    body = get_body()
    amount_cents = req_int(body, "amount_cents")
    reason = req_enum(body, "reason", DISPUTE_REASONS)
    require_roles(["Cardholder", "CustomerService"])
    auth = resolve_authorization(authorizationId)
    token = db.payment_tokens.get(auth["payment_token_id"])
    account = db.card_accounts.get(token["card_account_id"]) if token else None

    # Priority 19: traceability — amount must equal the auth amount; auth APPROVED
    if amount_cents != auth["amount_cents"]:
        raise ApiError("ERR_DISPUTE_AMOUNT_MISMATCH",
                       "Disputed amount must equal the authorization amount")
    if auth["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE", "Authorization must be APPROVED")

    row = new_common_row({
        "payment_token_id": auth["payment_token_id"],
        "authorization_id": auth["id"],
        "card_account_id": account["id"] if account else None,
        "amount_cents": amount_cents,
        "reason": reason,
        "status": "OPEN",
    })
    db.disputes[row["id"]] = row
    # FRAUD: CardAccount OPEN -> RESTRICTED
    if reason == "FRAUD" and account is not None and account["status"] == "OPEN":
        account["status"] = "RESTRICTED"
        db.touch(account)
    return success_object(row, 201)


@bp.get("/disputes/<disputeId>")
def get_dispute(disputeId):
    return success_object(lookup_dispute(disputeId), 200)


@bp.get("/disputes")
def list_disputes():
    return list_response(db.disputes.values(), filters={
        "payment_token_id": request.args.get("payment_token_id"),
        "authorization_id": request.args.get("authorization_id"),
        "card_account_id": request.args.get("card_account_id"),
        "status": request.args.get("status"),
    })


@bp.get("/payment-tokens/<tokenId>/disputes")
def list_token_disputes(tokenId):
    resolve_token(tokenId)
    rows = [d for d in db.disputes.values() if d["payment_token_id"] == tokenId]
    return list_response(rows)


@bp.post("/disputes/<disputeId>/resolve-dispute")
def resolve_dispute(disputeId):
    body = get_body()
    outcome = req_enum(body, "outcome", {"WON", "LOST"})
    require_roles(["IssuerOperator"])
    dispute = lookup_dispute(disputeId)
    if dispute["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE",
                       f"Dispute cannot be resolved from {dispute['status']}")
    dispute["status"] = outcome
    db.touch(dispute)
    # FRAUD resolution reopens the card account
    if dispute["reason"] == "FRAUD":
        account = db.card_accounts.get(dispute["card_account_id"])
        if account is not None and account["status"] == "RESTRICTED":
            account["status"] = "OPEN"
            db.touch(account)
    return success_object(dispute, 200)
