"""Omnibus and networked reconciliation (PRD 3.10)."""

from flask import Blueprint, request

import dates
import db
import response
import serializers
import validation
from constants import (DEALER_CHANNELS, RECON_STATUSES, RECON_TOLERANCE_FLOOR,
                       RECON_TOLERANCE_RATE)
from errors import ApiError
from middleware import ROLE_CO, ROLE_DEALER, ROLE_FA, ROLE_TAO, authenticate
from money import ZERO, q2, q3
from routes import helpers
from services import positions as positions_service

bp = Blueprint("recons", __name__)


def _booked_magnitude(trade):
    if trade["trade_type"] == "PURCHASE":
        value = trade["gross_amount"]
    elif trade["trade_type"] in ("REDEMPTION", "EXCHANGE"):
        value = trade["gross_proceeds_amount"]
    else:
        value = trade["net_invested_amount"]
    return q2(value) if value is not None else None


@bp.route("/omnibus-reconciliations", methods=["POST"])
def create_reconciliation():
    caller = authenticate((ROLE_TAO, ROLE_DEALER))
    body = validation.body()
    account_id = validation.get_id(body, "account_id", required=True)
    as_of_date = validation.get_date(body, "as_of_date", required=True)
    dealer_purchase = validation.get_decimal(body, "dealer_reported_purchase_amount", 2,
                                             required=True, non_negative=True)
    dealer_redemption = validation.get_decimal(body, "dealer_reported_redemption_amount", 2,
                                               required=True, non_negative=True)
    dealer_net_shares = validation.get_decimal(body, "dealer_reported_net_shares", 3,
                                               required=True)

    account = helpers.get_account(account_id)
    helpers.require_dealer_channel(caller, account["account_channel"])

    if account["account_channel"] not in DEALER_CHANNELS:
        raise ApiError("ERR_RECON_CHANNEL_INVALID",
                       "Reconciliation requires a networked or omnibus account.")

    as_of_text = dates.fmt_date(as_of_date)

    ta_purchase = ZERO
    ta_redemption = ZERO
    for trade in db.store.trades.values():
        if trade["account_id"] != account["id"]:
            continue
        if trade["settlement_status"] != "SETTLED":
            continue
        if trade["trade_date"] != as_of_text:
            continue
        if trade["trade_type"] == "PURCHASE":
            ta_purchase += trade["gross_amount"] or ZERO
        elif trade["trade_type"] == "REDEMPTION":
            ta_redemption += trade["gross_proceeds_amount"] or ZERO

    account_position_ids = set(p["id"] for p in positions_service.for_account(account["id"]))
    ta_net_shares = ZERO
    for entry in db.store.ledger_entries.values():
        if entry["effective_date"] != as_of_text:
            continue
        if entry["position_id"] not in account_position_ids:
            continue
        ta_net_shares += entry["share_delta"]

    ta_net = q2(ta_purchase) - q2(ta_redemption)
    dealer_net = dealer_purchase - dealer_redemption
    break_amount = q2(ta_net - dealer_net)
    dealer_gross = dealer_purchase + dealer_redemption
    tolerance = max(RECON_TOLERANCE_FLOOR, q2(dealer_gross * RECON_TOLERANCE_RATE))

    status = "MATCHED" if abs(break_amount) <= tolerance else "BREAK_IDENTIFIED"

    reconciliation = db.create(db.store.reconciliations, {
        "account_id": account["id"],
        "as_of_date": as_of_text,
        "dealer_reported_purchase_amount": dealer_purchase,
        "dealer_reported_redemption_amount": dealer_redemption,
        "dealer_reported_net_shares": dealer_net_shares,
        "ta_purchase_amount": q2(ta_purchase),
        "ta_redemption_amount": q2(ta_redemption),
        "ta_net_shares": q3(ta_net_shares),
        "break_amount": break_amount,
        "tolerance_amount": q2(tolerance),
        "status": status,
        "adjustment_trade_id": None,
        "resolution_note": None,
        "dispute_note": None,
    })
    return response.created(serializers.reconciliation(reconciliation))


@bp.route("/omnibus-reconciliations/<reconciliation_id>", methods=["GET"])
def read_reconciliation(reconciliation_id):
    authenticate((ROLE_TAO, ROLE_FA, ROLE_CO, ROLE_DEALER))
    reconciliation = helpers.get_reconciliation(reconciliation_id)
    return response.ok(serializers.reconciliation(reconciliation))


@bp.route("/omnibus-reconciliations", methods=["GET"])
def list_reconciliations():
    authenticate((ROLE_TAO, ROLE_FA, ROLE_CO, ROLE_DEALER))
    limit, offset = validation.pagination()
    records = db.values(db.store.reconciliations)
    records = helpers.filter_equals(records, "account_id", request.args.get("account_id"))
    records = helpers.filter_equals(records, "adjustment_trade_id",
                                    request.args.get("adjustment_trade_id"))
    records = helpers.filter_equals(records, "status",
                                    validation.query_enum("status", RECON_STATUSES))
    records = helpers.filter_equals(records, "as_of_date", validation.query_date("as_of_date"))
    items, total = helpers.page(records, limit, offset)
    return response.listing([serializers.reconciliation(r) for r in items], total, limit, offset)


@bp.route("/omnibus-reconciliations/<reconciliation_id>/adjust", methods=["POST"])
def adjust_reconciliation(reconciliation_id):
    authenticate((ROLE_CO,))
    body = validation.body()
    trade_id = validation.get_id(body, "adjustment_trade_id", required=True)
    resolution_note = validation.get_string(body, "resolution_note", required=True)

    reconciliation = helpers.get_reconciliation(reconciliation_id)
    trade = helpers.get_trade(trade_id)

    if reconciliation["status"] != "BREAK_IDENTIFIED":
        raise ApiError("ERR_INVALID_RECONCILIATION_STATE",
                       "Only an identified break may be adjusted.")

    magnitude = _booked_magnitude(trade)
    if (trade["account_id"] != reconciliation["account_id"]
            or trade["trade_date"] != reconciliation["as_of_date"]
            or trade["settlement_status"] != "SETTLED"
            or magnitude is None
            or magnitude != abs(reconciliation["break_amount"])):
        raise ApiError("ERR_ADJUSTMENT_MISMATCH",
                       "The cited order does not match the identified break.")

    reconciliation["status"] = "RESOLVED"
    reconciliation["adjustment_trade_id"] = trade["id"]
    reconciliation["resolution_note"] = resolution_note
    db.touch(reconciliation)
    return response.ok(serializers.reconciliation(reconciliation))


@bp.route("/omnibus-reconciliations/<reconciliation_id>/dispute", methods=["POST"])
def dispute_reconciliation(reconciliation_id):
    authenticate((ROLE_CO,))
    body = validation.body()
    dispute_note = validation.get_string(body, "dispute_note", required=True)

    reconciliation = helpers.get_reconciliation(reconciliation_id)
    if reconciliation["status"] != "BREAK_IDENTIFIED":
        raise ApiError("ERR_INVALID_RECONCILIATION_STATE",
                       "Only an identified break may be disputed.")

    reconciliation["status"] = "DISPUTED"
    reconciliation["dispute_note"] = dispute_note
    db.touch(reconciliation)
    return response.ok(serializers.reconciliation(reconciliation))
