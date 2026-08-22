"""Order capture, pricing, settlement, cancellation and reversal (PRD 3.4-3.6)."""

from flask import Blueprint, request

import db
import response
import serializers
import validation
from constants import (ACCOUNT_PARTICIPATING, EXECUTION_STATUSES, NAV_PRICED,
                       SETTLEMENT_STATUSES, TRADE_TYPES)
from errors import ApiError, invalid
from middleware import (ALL_ROLES, ROLE_CO, ROLE_DEALER, ROLE_FA, ROLE_HOLDER,
                        ROLE_TAO, authenticate)
from money import ZERO
from routes import helpers
from services import (bluesky, capture as capture_service, navs as nav_service,
                      positions as positions_service, pricing as pricing_service,
                      settlement as settlement_service)

bp = Blueprint("trades", __name__)

CANCELLABLE = ("RECEIVED", "PENDING_AS_OF_APPROVAL", "PRICED_PROVISIONAL", "PRICED_FINAL")


@bp.route("/trades", methods=["POST"])
def create_trade():
    caller = authenticate((ROLE_TAO, ROLE_CO, ROLE_DEALER, ROLE_HOLDER))
    body = validation.body()

    account_id = validation.get_id(body, "account_id", required=True)
    share_class_id = validation.get_id(body, "share_class_id", required=True)
    trade_type = validation.get_enum(body, "trade_type", TRADE_TYPES, required=True)
    if trade_type == "REINVESTMENT":
        raise invalid("REINVESTMENT orders are created by the system when a distribution pays.")

    gross_amount = validation.get_decimal(body, "gross_amount", 2, positive=True)
    shares_requested = validation.get_decimal(body, "shares_requested", 3, positive=True)
    exchange_target_id = validation.get_id(body, "exchange_target_share_class_id")
    as_of_date = validation.get_date(body, "as_of_date")
    dealer_reference = validation.get_string(body, "dealer_reference")

    if trade_type == "PURCHASE":
        if gross_amount is None:
            raise invalid("Field 'gross_amount' is required for a PURCHASE.")
        if shares_requested is not None:
            raise invalid("Field 'shares_requested' must be absent for a PURCHASE.")
    else:
        if shares_requested is None:
            raise invalid("Field 'shares_requested' is required for a %s." % trade_type)
        if gross_amount is not None:
            raise invalid("Field 'gross_amount' must be absent for a %s." % trade_type)

    if trade_type == "EXCHANGE":
        if exchange_target_id is None:
            raise invalid("Field 'exchange_target_share_class_id' is required for an EXCHANGE.")
    elif exchange_target_id is not None:
        raise invalid("Field 'exchange_target_share_class_id' is only valid for an EXCHANGE.")

    account = helpers.get_account(account_id)
    share_class = helpers.get_share_class(share_class_id)
    target_class = helpers.get_share_class(exchange_target_id) if exchange_target_id else None

    helpers.require_ownership(caller, account["id"])
    helpers.require_dealer_channel(caller, account["account_channel"])

    if account["status"] not in ACCOUNT_PARTICIPATING:
        raise ApiError("ERR_ACCOUNT_NOT_ACTIVE",
                       "The account must be ACTIVE or RESTRICTED to capture an order.")
    if account["status"] == "RESTRICTED" and trade_type in ("PURCHASE", "EXCHANGE"):
        raise ApiError("ERR_ACCOUNT_RESTRICTED",
                       "A restricted account may not originate purchase-side activity.")

    fund = db.store.funds[share_class["fund_id"]]
    capture_service.check_as_of_controls(fund, as_of_date)

    if trade_type == "EXCHANGE" and target_class["id"] == share_class["id"]:
        raise ApiError("ERR_EXCHANGE_TARGET_INVALID",
                       "An exchange target must differ from the source class.")

    if trade_type == "EXCHANGE":
        target_fund = db.store.funds[target_class["fund_id"]]
        if target_fund["status"] == "CLOSED_TO_NEW":
            raise ApiError("ERR_FUND_CLOSED_TO_NEW",
                           "The target fund is closed to new purchase-side activity.")

    trade = capture_service.capture(
        caller.user_id, account, share_class, fund, trade_type,
        gross_amount=gross_amount, shares_requested=shares_requested,
        as_of_date=as_of_date, dealer_reference=dealer_reference,
        exchange_target_share_class_id=exchange_target_id,
        check_as_of=False)
    return response.created(serializers.trade(trade))


@bp.route("/trades/<trade_id>", methods=["GET"])
def read_trade(trade_id):
    authenticate(ALL_ROLES)
    trade = helpers.get_trade(trade_id)
    return response.ok(serializers.trade(trade))


@bp.route("/trades", methods=["GET"])
def list_trades():
    authenticate(ALL_ROLES)
    limit, offset = validation.pagination()
    records = db.values(db.store.trades)
    records = helpers.filter_equals(records, "account_id", request.args.get("account_id"))
    records = helpers.filter_equals(records, "share_class_id", request.args.get("share_class_id"))
    records = helpers.filter_equals(records, "exchange_target_share_class_id",
                                    request.args.get("exchange_target_share_class_id"))
    records = helpers.filter_equals(records, "parent_distribution_id",
                                    request.args.get("parent_distribution_id"))
    records = helpers.filter_equals(records, "originating_plan_id",
                                    request.args.get("originating_plan_id"))
    records = helpers.filter_equals(records, "blue_sky_registration_id",
                                    request.args.get("blue_sky_registration_id"))
    records = helpers.filter_equals(records, "execution_status",
                                    validation.query_enum("execution_status", EXECUTION_STATUSES))
    records = helpers.filter_equals(records, "settlement_status",
                                    validation.query_enum("settlement_status", SETTLEMENT_STATUSES))
    records = helpers.filter_equals(records, "trade_date", validation.query_date("trade_date"))
    records = helpers.filter_equals(records, "trade_type",
                                    validation.query_enum("trade_type", TRADE_TYPES))
    items, total = helpers.page(records, limit, offset)
    return response.listing([serializers.trade(r) for r in items], total, limit, offset)


@bp.route("/trades/<trade_id>/approve-as-of", methods=["POST"])
def approve_as_of(trade_id):
    caller = authenticate((ROLE_CO,))
    trade = helpers.get_trade(trade_id)
    if trade["execution_status"] != "PENDING_AS_OF_APPROVAL":
        raise ApiError("ERR_INVALID_TRADE_STATE",
                       "Only an order awaiting as-of approval may be released.")
    if caller.user_id == trade["captured_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The approver must differ from the actor that captured the order.")
    trade["execution_status"] = "RECEIVED"
    trade["approved_by_user_id"] = caller.user_id
    db.touch(trade)
    return response.ok(serializers.trade(trade))


def _require_nav(share_class_id, trade_date):
    record = nav_service.find_for(share_class_id, trade_date)
    if record is None:
        raise ApiError("ERR_NAV_NOT_AVAILABLE",
                       "No NAV record exists for the class and trade date.")
    return record


def _require_usable(record):
    if record["status"] in ("UNDER_ERROR_REVIEW", "STALE_REPRICE_REQUIRED"):
        raise ApiError("ERR_NAV_NOT_FINAL",
                       "The NAV record may not be used to price an order.")


@bp.route("/trades/<trade_id>/price", methods=["POST"])
def price_trade(trade_id):
    authenticate((ROLE_TAO, ROLE_FA))
    trade = helpers.get_trade(trade_id)
    if trade["execution_status"] not in ("RECEIVED", "PRICED_PROVISIONAL"):
        raise ApiError("ERR_INVALID_TRADE_STATE", "The order may not be priced from its state.")

    share_class = db.store.share_classes[trade["share_class_id"]]
    source_nav_record = _require_nav(trade["share_class_id"], trade["trade_date"])
    target_class = None
    target_nav_record = None
    if trade["trade_type"] == "EXCHANGE":
        target_class = db.store.share_classes[trade["exchange_target_share_class_id"]]
        target_nav_record = _require_nav(target_class["id"], trade["trade_date"])

    _require_usable(source_nav_record)
    if target_nav_record is not None:
        _require_usable(target_nav_record)

    final = source_nav_record["status"] in NAV_PRICED
    nav = source_nav_record["nav_per_share"]

    if trade["trade_type"] == "PURCHASE":
        pricing_service.price_purchase(trade, share_class, nav)
    elif trade["trade_type"] == "REDEMPTION":
        pricing_service.price_redemption(trade, share_class, nav)
    else:
        pricing_service.price_exchange(trade, share_class, target_class, nav,
                                       target_nav_record["nav_per_share"])

    trade["nav_per_share_applied"] = nav
    trade["pricing_variant"] = "FINAL_NAV" if final else "PRELIMINARY_NAV"
    trade["execution_status"] = "PRICED_FINAL" if final else "PRICED_PROVISIONAL"
    db.touch(trade)
    return response.ok(serializers.trade(trade))


@bp.route("/trades/<trade_id>/settle", methods=["POST"])
def settle_trade(trade_id):
    authenticate((ROLE_TAO,))
    trade = helpers.get_trade(trade_id)
    if trade["execution_status"] != "PRICED_FINAL" or trade["settlement_status"] != "UNSETTLED":
        raise ApiError("ERR_INVALID_TRADE_STATE",
                       "Only a finally priced, unsettled order may settle.")
    if trade["trade_type"] in ("REDEMPTION", "EXCHANGE"):
        position = positions_service.find(trade["account_id"], trade["share_class_id"])
        held = position["shares"] if position is not None else ZERO
        if trade["shares_requested"] > held:
            raise ApiError("ERR_INSUFFICIENT_SHARES",
                           "The position no longer holds enough shares to settle.")

    settlement_service.settle(trade)
    db.touch(trade)
    return response.ok(serializers.trade(trade))


@bp.route("/trades/<trade_id>/cancel", methods=["POST"])
def cancel_trade(trade_id):
    authenticate((ROLE_TAO, ROLE_CO))
    body = validation.body()
    reason = validation.get_string(body, "cancel_reason", required=True)

    trade = helpers.get_trade(trade_id)
    if trade["settlement_status"] != "UNSETTLED" or trade["execution_status"] not in CANCELLABLE:
        raise ApiError("ERR_INVALID_TRADE_STATE", "Only an unsettled order may be cancelled.")

    trade["execution_status"] = "CANCELLED"
    trade["cancel_reason"] = reason
    db.touch(trade)

    registration = db.store.registrations.get(trade["blue_sky_registration_id"])
    if registration is not None and trade["trade_type"] == "PURCHASE":
        bluesky.release_reserved(registration, trade["gross_amount"])
    return response.ok(serializers.trade(trade))


@bp.route("/trades/<trade_id>/reverse", methods=["POST"])
def reverse_trade(trade_id):
    authenticate((ROLE_CO,))
    body = validation.body()
    reason = validation.get_string(body, "reversal_reason", required=True)

    trade = helpers.get_trade(trade_id)
    if trade["settlement_status"] != "SETTLED":
        raise ApiError("ERR_INVALID_TRADE_STATE", "Only a settled order may be reversed.")
    if trade["trade_type"] == "REINVESTMENT":
        raise ApiError("ERR_INVALID_TRADE_STATE",
                       "A reinvestment order is unwound only through its distribution.")
    if settlement_service.resulting_shares_after_reversal(trade) < 0:
        raise ApiError("ERR_INVALID_TRADE_STATE",
                       "Reversing the order would drive the position balance negative.")

    trade["reversal_reason"] = reason
    settlement_service.reverse(trade)
    db.touch(trade)
    return response.ok(serializers.trade(trade))
