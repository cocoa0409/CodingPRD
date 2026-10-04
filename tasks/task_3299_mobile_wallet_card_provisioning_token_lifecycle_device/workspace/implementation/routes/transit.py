# =============================================================================
# Transit operators + allowlist + global token-event stream
# =============================================================================
from flask import Blueprint, request

import db
from errors import ApiError
from helpers import (
    list_response, new_common_row, resolve_allowlist_entry,
    resolve_card_account, resolve_operator,
)
from middleware import get_body, opt_bool, req_int, req_str, require_roles
from response import success_object

bp = Blueprint("transit", __name__)


@bp.post("/transit-operators")
def create_operator():
    body = get_body()
    operator_code = req_str(body, "operator_code")
    name = req_str(body, "name")
    flat_fare_cents = req_int(body, "flat_fare_cents")
    express_cap_cents = req_int(body, "express_cap_cents")
    allowlist_active = opt_bool(body, "allowlist_active", False)
    require_roles(["PlatformAdmin"])
    # operator_code unique across operators
    for op in db.transit_operators.values():
        if op["operator_code"] == operator_code:
            raise ApiError("ERR_VALIDATION", "operator_code must be unique")
    row = new_common_row({
        "operator_code": operator_code,
        "name": name,
        "flat_fare_cents": flat_fare_cents,
        "express_cap_cents": express_cap_cents,
        "allowlist_active": allowlist_active,
        "status": "ACTIVE",
    })
    db.transit_operators[row["id"]] = row
    return success_object(row, 201)


@bp.get("/transit-operators/<operatorId>")
def get_operator(operatorId):
    return success_object(resolve_operator(operatorId), 200)


@bp.get("/transit-operators/<operatorId>/allowlist")
def list_operator_allowlist(operatorId):
    resolve_operator(operatorId)
    rows = [e for e in db.transit_allowlist.values()
            if e["transit_operator_id"] == operatorId]
    return list_response(rows)


@bp.post("/transit-allowlist")
def add_allowlist_entry():
    body = get_body()
    transit_operator_id = req_str(body, "transit_operator_id")
    card_account_id = req_str(body, "card_account_id")
    require_roles(["IssuerOperator", "PlatformAdmin"])
    resolve_operator(transit_operator_id)
    resolve_card_account(card_account_id)
    # TransitAllowlist carries id + created_at only (no updated_at/version)
    row = {
        "id": db.new_id(),
        "created_at": db.get_clock(),
        "_seq": db.next_seq(),
        "transit_operator_id": transit_operator_id,
        "card_account_id": card_account_id,
        "status": "ACTIVE",
    }
    db.transit_allowlist[row["id"]] = row
    return success_object(row, 201)


@bp.get("/transit-allowlist/<entryId>")
def get_allowlist_entry(entryId):
    return success_object(resolve_allowlist_entry(entryId), 200)


@bp.get("/transit-allowlist")
def list_allowlist():
    return list_response(db.transit_allowlist.values(), filters={
        "transit_operator_id": request.args.get("transit_operator_id"),
        "card_account_id": request.args.get("card_account_id"),
        "status": request.args.get("status"),
    })


@bp.get("/card-accounts/<cardAccountId>/transit-allowlist")
def list_account_allowlist(cardAccountId):
    resolve_card_account(cardAccountId)
    rows = [e for e in db.transit_allowlist.values()
            if e["card_account_id"] == cardAccountId]
    return list_response(rows)


@bp.get("/token-events")
def list_token_events():
    return list_response(db.token_events.values(), filters={
        "payment_token_id": request.args.get("payment_token_id"),
        "event_type": request.args.get("event_type"),
    })
