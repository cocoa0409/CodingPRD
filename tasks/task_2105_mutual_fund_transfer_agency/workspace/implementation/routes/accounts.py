"""Shareholder accounts, households and the account lifecycle (PRD 3.2)."""
import re

from flask import Blueprint, request

import clock
import db
import response
import serializers
import validation
from constants import (ACCOUNT_CHANNELS, ACCOUNT_PARTICIPATING, ACCOUNT_STATUSES,
                       DEALER_CHANNELS, DIVIDEND_OPTIONS, REGISTRATION_TYPES)
from errors import ApiError, invalid
from middleware import ALL_ROLES, ROLE_CO, ROLE_DEALER, ROLE_FA, ROLE_HOLDER, ROLE_TAO, authenticate
from money import ZERO, q2
from routes import helpers
from services import household, positions as positions_service

bp = Blueprint("accounts", __name__)

STATE_RE = re.compile(r"^[A-Z]{2}$")


def _variant_for(channel):
    return "HISTORICAL_COST_BASIS" if channel == "OMNIBUS" else "MARKET_VALUE_BASIS"


def _validate_link(account_id, link_id):
    """Order-of-rejection step 19."""
    if link_id is None:
        return
    if link_id == account_id:
        raise ApiError("ERR_ROA_LINK_INVALID", "An account may not be linked to itself.")
    target = db.store.accounts[link_id]
    if target.get("linked_primary_account_id"):
        raise ApiError("ERR_ROA_LINK_INVALID", "Rights-of-accumulation linking is single level.")
    if target["status"] not in ACCOUNT_PARTICIPATING:
        raise ApiError("ERR_ROA_LINK_INVALID",
                       "The primary account must be ACTIVE or RESTRICTED.")


@bp.route("/shareholder-accounts", methods=["POST"])
def create_account():
    caller = authenticate((ROLE_TAO, ROLE_DEALER))
    body = validation.body()

    registration_type = validation.get_enum(body, "registration_type", REGISTRATION_TYPES,
                                            required=True)
    channel = validation.get_enum(body, "account_channel", ACCOUNT_CHANNELS, required=True)
    state_code = validation.get_string(body, "state_code", required=True)
    if not STATE_RE.match(state_code):
        raise invalid("Field 'state_code' must be exactly two uppercase letters.")
    tax_id = validation.get_string(body, "tax_id", required=True)
    owner_name = validation.get_string(body, "primary_owner_name", required=True)
    dividend_option = validation.get_enum(body, "dividend_option", DIVIDEND_OPTIONS,
                                          default="CASH")
    link_id = validation.get_id(body, "linked_primary_account_id")
    dealer_firm_code = validation.get_string(body, "dealer_firm_code")

    if channel in DEALER_CHANNELS and dealer_firm_code is None:
        raise invalid("Field 'dealer_firm_code' is required for networked and omnibus accounts.")
    if channel == "DIRECT" and dealer_firm_code is not None:
        raise invalid("Field 'dealer_firm_code' must be omitted for direct accounts.")

    if link_id is not None:
        helpers.get_account(link_id)

    helpers.require_dealer_channel(caller, channel)

    _validate_link(None, link_id)

    account = db.create(db.store.accounts, {
        "registration_type": registration_type,
        "account_channel": channel,
        "state_code": state_code,
        "tax_id": tax_id,
        "primary_owner_name": owner_name,
        "dealer_firm_code": dealer_firm_code,
        "dividend_option": dividend_option,
        "linked_primary_account_id": link_id,
        "tin_certified": False,
        "status": "PENDING_DOCS",
        "restriction_reason": None,
        "household_basis_amount": q2(ZERO),
        "household_basis_variant": _variant_for(channel),
        "closed_at": None,
    })
    return response.created(serializers.account(account))


@bp.route("/shareholder-accounts/<account_id>", methods=["GET"])
def read_account(account_id):
    caller = authenticate(ALL_ROLES)
    account = helpers.get_account(account_id)
    helpers.require_ownership(caller, account["id"])
    return response.ok(serializers.account(account))


@bp.route("/shareholder-accounts", methods=["GET"])
def list_accounts():
    authenticate((ROLE_TAO, ROLE_FA, ROLE_CO, ROLE_DEALER))
    limit, offset = validation.pagination()
    records = db.values(db.store.accounts)
    records = helpers.filter_equals(records, "linked_primary_account_id",
                                    request.args.get("linked_primary_account_id"))
    records = helpers.filter_equals(records, "status",
                                    validation.query_enum("status", ACCOUNT_STATUSES))
    records = helpers.filter_equals(records, "account_channel",
                                    validation.query_enum("account_channel", ACCOUNT_CHANNELS))
    records = helpers.filter_equals(records, "state_code", request.args.get("state_code"))
    items, total = helpers.page(records, limit, offset)
    return response.listing([serializers.account(r) for r in items], total, limit, offset)


@bp.route("/shareholder-accounts/<account_id>", methods=["PATCH"])
def update_account(account_id):
    caller = authenticate((ROLE_TAO, ROLE_HOLDER))
    body = validation.body()
    dividend_option = validation.get_enum(body, "dividend_option", DIVIDEND_OPTIONS)
    link_supplied = "linked_primary_account_id" in body
    link_id = validation.get_id(body, "linked_primary_account_id")

    account = helpers.get_account(account_id)

    if link_id is not None:
        helpers.get_account(link_id)

    helpers.require_ownership(caller, account["id"])

    if link_supplied:
        _validate_link(account["id"], link_id)

    previous_primary = household.primary_of(account)

    if dividend_option is not None:
        account["dividend_option"] = dividend_option
    if link_supplied:
        account["linked_primary_account_id"] = link_id
    db.touch(account)

    household.recompute(previous_primary)
    household.recompute(account)
    return response.ok(serializers.account(account))


@bp.route("/shareholder-accounts/<account_id>/activate", methods=["POST"])
def activate_account(account_id):
    authenticate((ROLE_TAO,))
    body = validation.body()
    tin_certified = validation.get_bool(body, "tin_certified", required=True)

    account = helpers.get_account(account_id)
    if account["status"] != "PENDING_DOCS":
        raise ApiError("ERR_ACCOUNT_NOT_ACTIVE",
                       "Only an account in PENDING_DOCS may be activated.")

    account["status"] = "ACTIVE"
    account["tin_certified"] = tin_certified
    db.touch(account)
    household.recompute(account)
    return response.ok(serializers.account(account))


@bp.route("/shareholder-accounts/<account_id>/restrict", methods=["POST"])
def restrict_account(account_id):
    authenticate((ROLE_CO,))
    body = validation.body()
    reason = validation.get_string(body, "restriction_reason", required=True)

    account = helpers.get_account(account_id)
    if account["status"] != "ACTIVE":
        raise ApiError("ERR_ACCOUNT_NOT_ACTIVE", "Only an ACTIVE account may be restricted.")

    account["status"] = "RESTRICTED"
    account["restriction_reason"] = reason
    db.touch(account)

    for plan in db.store.plans.values():
        if plan["account_id"] == account["id"] and plan["status"] == "ACTIVE":
            plan["status"] = "SUSPENDED"
            plan["suspension_reason"] = "ACCOUNT_RESTRICTED"
            db.touch(plan)

    household.recompute(account)
    return response.ok(serializers.account(account))


@bp.route("/shareholder-accounts/<account_id>/reinstate", methods=["POST"])
def reinstate_account(account_id):
    authenticate((ROLE_CO,))
    account = helpers.get_account(account_id)
    if account["status"] != "RESTRICTED":
        raise ApiError("ERR_ACCOUNT_NOT_ACTIVE", "Only a RESTRICTED account may be reinstated.")

    account["status"] = "ACTIVE"
    account["restriction_reason"] = None
    db.touch(account)
    household.recompute(account)
    return response.ok(serializers.account(account))


@bp.route("/shareholder-accounts/<account_id>/close", methods=["POST"])
def close_account(account_id):
    authenticate((ROLE_TAO,))
    account = helpers.get_account(account_id)
    if account["status"] not in ACCOUNT_PARTICIPATING:
        raise ApiError("ERR_ACCOUNT_NOT_ACTIVE",
                       "Only an ACTIVE or RESTRICTED account may be closed.")

    for position in positions_service.for_account(account["id"]):
        if position["shares"] != 0:
            raise ApiError("ERR_ACCOUNT_NOT_ACTIVE",
                           "Every position must hold zero shares before the account is closed.")

    for trade in db.store.trades.values():
        if trade["account_id"] != account["id"]:
            continue
        if trade["settlement_status"] == "UNSETTLED" and trade["execution_status"] != "CANCELLED":
            raise ApiError("ERR_INVALID_TRADE_STATE",
                           "The account still has an open unsettled order.")

    account["status"] = "CLOSED"
    account["closed_at"] = clock.now_iso()
    db.touch(account)

    for plan in db.store.plans.values():
        if plan["account_id"] == account["id"] and plan["status"] in ("ACTIVE", "SUSPENDED"):
            plan["status"] = "TERMINATED"
            db.touch(plan)

    household.recompute(account)
    return response.ok(serializers.account(account))


@bp.route("/shareholder-accounts/<account_id>/positions", methods=["GET"])
def list_account_positions(account_id):
    caller = authenticate(ALL_ROLES)
    account = helpers.get_account(account_id)
    helpers.require_ownership(caller, account["id"])
    limit, offset = validation.pagination()
    records = positions_service.for_account(account["id"])
    records = helpers.filter_equals(records, "share_class_id", request.args.get("share_class_id"))
    items, total = helpers.page(records, limit, offset)
    return response.listing([serializers.position(r) for r in items], total, limit, offset)
