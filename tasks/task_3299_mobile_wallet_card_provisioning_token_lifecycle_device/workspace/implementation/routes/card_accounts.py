# =============================================================================
# Card accounts: open, get, list, reissue, close, risk
# =============================================================================
from flask import Blueprint, request

import db
from domain import compute_risk, deactivate_token, open_disputes_for_account
from errors import ApiError
from helpers import (
    list_response, new_common_row, resolve_card_account, resolve_cardholder,
    resolve_issuer,
)
from middleware import get_body, req_enum, req_str, require_roles
from response import success_object

bp = Blueprint("card_accounts", __name__)

CARD_PRODUCTS = {"CREDIT", "DEBIT", "PREPAID", "TRANSIT"}


@bp.post("/card-accounts")
def create_card_account():
    body = get_body()
    cardholder_id = req_str(body, "cardholder_id")
    issuer_id = req_str(body, "issuer_id")
    fpan_last4 = req_str(body, "fpan_last4")
    card_product = req_enum(body, "card_product", CARD_PRODUCTS)
    require_roles(["IssuerOperator", "PlatformAdmin"])
    resolve_cardholder(cardholder_id)
    resolve_issuer(issuer_id)
    row = new_common_row({
        "cardholder_id": cardholder_id,
        "issuer_id": issuer_id,
        "fpan_last4": fpan_last4,
        "card_product": card_product,
        "status": "OPEN",
        "reissue_of_account_id": None,
    })
    db.card_accounts[row["id"]] = row
    return success_object(row, 201)


@bp.get("/card-accounts/<cardAccountId>")
def get_card_account(cardAccountId):
    return success_object(resolve_card_account(cardAccountId), 200)


@bp.get("/card-accounts")
def list_card_accounts():
    return list_response(db.card_accounts.values(), filters={
        "issuer_id": request.args.get("issuer_id"),
        "cardholder_id": request.args.get("cardholder_id"),
        "status": request.args.get("status"),
    })


@bp.post("/card-accounts/<cardAccountId>/reissue")
def reissue_card_account(cardAccountId):
    require_roles(["IssuerOperator"])
    account = resolve_card_account(cardAccountId)
    # OPEN -> REISSUED and RESTRICTED -> REISSUED are the defined transitions
    if account["status"] not in ("OPEN", "RESTRICTED"):
        raise ApiError("ERR_INVALID_STATE",
                       f"Account cannot be reissued from {account['status']}")
    account["status"] = "REISSUED"
    db.touch(account)
    # Successor account, OPEN, pointing back at the predecessor
    successor = new_common_row({
        "cardholder_id": account["cardholder_id"],
        "issuer_id": account["issuer_id"],
        "fpan_last4": account["fpan_last4"],
        "card_product": account["card_product"],
        "status": "OPEN",
        "reissue_of_account_id": account["id"],
    })
    db.card_accounts[successor["id"]] = successor
    # Predecessor's artifacts -> DEACTIVATED
    for artifact in db.card_artifacts.values():
        if artifact["card_account_id"] == account["id"] and artifact["status"] != "DEACTIVATED":
            artifact["status"] = "DEACTIVATED"
            db.touch(artifact)
    # Predecessor's ACTIVE|SUSPENDED tokens -> DEACTIVATED (CARD_REISSUE)
    for token in db.payment_tokens.values():
        if token["card_account_id"] == account["id"] and token["status"] in ("ACTIVE", "SUSPENDED"):
            deactivate_token(token, "CARD_REISSUE")
    return success_object(successor, 201)


@bp.post("/card-accounts/<cardAccountId>/close")
def close_card_account(cardAccountId):
    require_roles(["IssuerOperator"])
    account = resolve_card_account(cardAccountId)
    if account["status"] in ("OPEN", "RESTRICTED"):
        # Blocked while any OPEN dispute exists on tokens of this account
        if open_disputes_for_account(account["id"]):
            raise ApiError("ERR_CARD_HAS_OPEN_DISPUTES",
                           "Close blocked while OPEN disputes exist on the account")
    elif account["status"] != "REISSUED":
        raise ApiError("ERR_INVALID_STATE",
                       f"Account cannot be closed from {account['status']}")
    if account["status"] == "OPEN":
        for token in db.payment_tokens.values():
            if token["card_account_id"] == account["id"] and token["status"] in ("ACTIVE", "SUSPENDED"):
                deactivate_token(token, "USER_REMOVE")
    account["status"] = "CLOSED"
    db.touch(account)
    return success_object(account, 200)


@bp.get("/card-accounts/<cardAccountId>/risk")
def card_account_risk(cardAccountId):
    require_roles(["IssuerOperator", "PlatformAdmin", "CustomerService"])
    account = resolve_card_account(cardAccountId)
    score, open_count, open_cents = compute_risk(account)
    return success_object({
        "risk_score": score,
        "open_dispute_count": open_count,
        "open_disputed_cents": open_cents,
    }, 200)
