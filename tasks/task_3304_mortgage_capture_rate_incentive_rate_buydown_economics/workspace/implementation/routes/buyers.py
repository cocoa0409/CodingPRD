"""Buyer endpoints."""

from flask import Blueprint, request

from db import db
from errors import fail
from response import ok, ok_list, paginate
from checks import (
    authenticate, body, require_fields, string_field, state_code_field, get_buyer,
    check_buyer_ownership,
)
from services import common, cascades
from services import lock_flows

bp = Blueprint("buyers", __name__)

DETAIL_ROLES = [
    "PlatformAdmin",
    "SalesCounselor",
    "MortgageBanker",
    "ClosingOfficer",
    "ComplianceOfficer",
]
READ_ROLES = DETAIL_ROLES + ["Buyer"]


@bp.post("/housing/buyers")
def create_buyer():
    authenticate(["SalesCounselor", "PlatformAdmin"])
    payload = body()
    require_fields(payload, ["full_name", "email", "state_code"])
    full_name = string_field(payload, "full_name")
    email = string_field(payload, "email")
    state_code = state_code_field(payload, "state_code")
    for existing in db.buyers.values():
        if existing.get("email") == email:
            fail("ERR_INVALID_ENUM_VALUE", "email must be unique across all buyers")
    row = {
        "id": db.new_id(),
        "full_name": full_name,
        "email": email,
        "state_code": state_code,
        "buyer_status": "PROSPECT",
        "affiliated_lender_selected": False,
        "total_incentive_received_cents": 0,
        "steering_protection_flag": True,
    }
    common.stamp_new(row)
    db.buyers[row["id"]] = row
    return ok(common.dump(row), 201)


@bp.get("/housing/buyers/<buyer_id>")
def get_buyer_detail(buyer_id):
    role, user_id = authenticate(READ_ROLES)
    buyer = get_buyer(buyer_id)
    if role == "Buyer" and user_id != buyer_id:
        fail("ERR_FORBIDDEN", "the buyer may only read their own record")
    return ok(common.dump(buyer), 200)


@bp.get("/housing/buyers/<buyer_id>/contracts")
def list_buyer_contracts(buyer_id):
    role, user_id = authenticate(READ_ROLES)
    get_buyer(buyer_id)
    if role == "Buyer" and user_id != buyer_id:
        fail("ERR_FORBIDDEN", "the buyer may only read their own contracts")
    rows = common.contracts_of_buyer(buyer_id)
    window, pagination = paginate(
        common.sort_rows(rows), request.args.get("limit"), request.args.get("offset")
    )
    return ok_list(common.dump_all(window), 200, pagination)


@bp.post("/housing/buyers/<buyer_id>/qualify")
def qualify_buyer(buyer_id):
    authenticate(["MortgageBanker"])
    buyer = get_buyer(buyer_id)
    # The buyer's state machine declares PROSPECT -> CONTRACTED -> QUALIFIED and
    # QUALIFIED -> CONTRACTED; WITHDRAWN -> QUALIFIED is not a declared edge.
    if buyer.get("buyer_status") not in ("PROSPECT", "QUALIFIED", "CONTRACTED"):
        fail("ERR_INVALID_STATE", "the buyer is not in a state that may be qualified")
    buyer["buyer_status"] = "QUALIFIED"
    common.touch(buyer)
    return ok(common.dump(buyer), 200)


@bp.post("/housing/buyers/<buyer_id>/withdraw")
def withdraw_buyer(buyer_id):
    authenticate(["SalesCounselor"])
    buyer = get_buyer(buyer_id)
    if buyer.get("buyer_status") not in ("PROSPECT", "QUALIFIED", "CONTRACTED"):
        fail("ERR_INVALID_STATE", "the buyer cannot be withdrawn from this status")
    for contract in common.contracts_of_buyer(buyer_id):
        if contract.get("contract_status") in ("LOCKED", "APPROVED"):
            fail(
                "ERR_INVALID_STATE",
                "the buyer holds a locked or approved contract and cannot be withdrawn",
            )
    lock_flows.withdraw_buyer(buyer)
    return ok(common.dump(buyer), 200)