"""Pricing error cases and the reprocessing cascade (PRD 3.9)."""
from decimal import Decimal

from flask import Blueprint, request

import db
import response
import serializers
import validation
from constants import CASE_STATUSES, MATERIALITIES, MATERIALITY_THRESHOLD_BPS
from errors import ApiError
from middleware import ROLE_CO, ROLE_FA, ROLE_TAO, authenticate
from money import q2, q3
from routes import helpers
from services import household, positions as positions_service, pricing as pricing_service

bp = Blueprint("cases", __name__)


@bp.route("/pricing-error-cases", methods=["POST"])
def open_case():
    caller = authenticate((ROLE_FA,))
    body = validation.body()
    nav_record_id = validation.get_id(body, "nav_record_id", required=True)
    corrected = validation.get_decimal(body, "corrected_nav_per_share", 4,
                                       required=True, positive=True)
    error_reason = validation.get_string(body, "error_reason", required=True)
    expected_version = validation.get_int(body, "expected_nav_record_version", required=True)

    record = helpers.get_nav_record(nav_record_id)

    if expected_version != record["version"]:
        raise ApiError("ERR_STALE_NAV_RECORD_VERSION",
                       "The supplied expected_nav_record_version is stale.")

    if record["status"] != "FINAL":
        raise ApiError("ERR_INVALID_NAV_STATE",
                       "A pricing error case may only be opened against a FINAL record.")

    for existing in db.store.cases.values():
        if existing["nav_record_id"] == record["id"] and existing["status"] in ("DETECTED", "ASSESSED"):
            existing["status"] = "SUPERSEDED"
            db.touch(existing)

    case = db.create(db.store.cases, {
        "nav_record_id": record["id"],
        "corrected_nav_per_share": corrected,
        "error_reason": error_reason,
        "original_nav_per_share": record["nav_per_share"],
        "error_bps": None,
        "materiality": None,
        "status": "DETECTED",
        "detected_by_user_id": caller.user_id,
        "approved_by_user_id": None,
        "reprocessed_by_user_id": None,
        "restated_trade_count": 0,
        "invalidated_nav_record_count": 0,
    })

    record["status"] = "UNDER_ERROR_REVIEW"
    db.touch(record)
    return response.created(serializers.case(case))


@bp.route("/pricing-error-cases/<case_id>", methods=["GET"])
def read_case(case_id):
    authenticate((ROLE_TAO, ROLE_FA, ROLE_CO))
    case = helpers.get_case(case_id)
    return response.ok(serializers.case(case))


@bp.route("/pricing-error-cases", methods=["GET"])
def list_cases():
    authenticate((ROLE_TAO, ROLE_FA, ROLE_CO))
    limit, offset = validation.pagination()
    records = db.values(db.store.cases)
    records = helpers.filter_equals(records, "nav_record_id", request.args.get("nav_record_id"))
    records = helpers.filter_equals(records, "status",
                                    validation.query_enum("status", CASE_STATUSES))
    records = helpers.filter_equals(records, "materiality",
                                    validation.query_enum("materiality", MATERIALITIES))
    items, total = helpers.page(records, limit, offset)
    return response.listing([serializers.case(r) for r in items], total, limit, offset)


@bp.route("/pricing-error-cases/<case_id>/assess", methods=["POST"])
def assess_case(case_id):
    authenticate((ROLE_FA,))
    case = helpers.get_case(case_id)
    if case["status"] != "DETECTED":
        raise ApiError("ERR_INVALID_CASE_STATE", "Only a DETECTED case may be assessed.")

    original = case["original_nav_per_share"]
    corrected = case["corrected_nav_per_share"]
    error_bps = q2(abs(corrected - original) / original * Decimal(10000))
    case["error_bps"] = error_bps
    case["materiality"] = "MATERIAL" if error_bps >= MATERIALITY_THRESHOLD_BPS else "IMMATERIAL"
    case["status"] = "ASSESSED"
    db.touch(case)
    return response.ok(serializers.case(case))


@bp.route("/pricing-error-cases/<case_id>/close-immaterial", methods=["POST"])
def close_immaterial(case_id):
    caller = authenticate((ROLE_CO,))
    case = helpers.get_case(case_id)
    if case["status"] != "ASSESSED" or case["materiality"] != "IMMATERIAL":
        raise ApiError("ERR_INVALID_CASE_STATE",
                       "Only an ASSESSED case determined IMMATERIAL may be closed this way.")

    case["status"] = "IMMATERIAL_CLOSED"
    case["approved_by_user_id"] = caller.user_id
    db.touch(case)

    record = db.store.nav_records[case["nav_record_id"]]
    record["original_nav_per_share"] = record["nav_per_share"]
    record["nav_per_share"] = case["corrected_nav_per_share"]
    record["status"] = "FINAL"
    db.touch(record)
    return response.ok(serializers.case(case))


@bp.route("/pricing-error-cases/<case_id>/approve-correction", methods=["POST"])
def approve_correction(case_id):
    caller = authenticate((ROLE_CO,))
    case = helpers.get_case(case_id)
    if case["status"] != "ASSESSED" or case["materiality"] != "MATERIAL":
        raise ApiError("ERR_INVALID_CASE_STATE",
                       "Only an ASSESSED case determined MATERIAL may be approved.")
    case["status"] = "MATERIAL_APPROVED"
    case["approved_by_user_id"] = caller.user_id
    db.touch(case)
    return response.ok(serializers.case(case))


@bp.route("/pricing-error-cases/<case_id>/reprocess", methods=["POST"])
def reprocess_case(case_id):
    caller = authenticate((ROLE_FA,))
    case = helpers.get_case(case_id)
    if case["status"] != "MATERIAL_APPROVED":
        raise ApiError("ERR_INVALID_CASE_STATE",
                       "Only an approved material case may be reprocessed.")
    if caller.user_id == case["detected_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The sweeping accountant must differ from the accountant that opened the case.")

    record = db.store.nav_records[case["nav_record_id"]]
    corrected = case["corrected_nav_per_share"]

    # link 1 -- the record is corrected.
    record["original_nav_per_share"] = record["nav_per_share"]
    record["nav_per_share"] = corrected
    record["status"] = "CORRECTED"
    db.touch(record)

    # link 2 -- settled trades priced on that record are restated.
    restated = []
    for trade in db.store.trades.values():
        if trade["share_class_id"] != record["share_class_id"]:
            continue
        if trade["trade_date"] != record["valuation_date"]:
            continue
        if trade["settlement_status"] != "SETTLED":
            continue
        if trade["execution_status"] != "PRICED_FINAL":
            continue
        previous = trade["shares_transacted"] or Decimal("0.000")
        if trade["trade_type"] in ("PURCHASE", "REINVESTMENT"):
            new_shares = q3(trade["net_invested_amount"] / corrected)
        else:
            new_shares = q3(Decimal(-1) * trade["shares_requested"])
        trade["nav_per_share_applied"] = corrected
        trade["shares_transacted"] = new_shares
        trade["restated_share_delta"] = q3(new_shares - previous)
        trade["execution_status"] = "RESTATED"
        db.touch(trade)
        restated.append(trade)

    # link 3 -- restatement ledger entries and position movement.
    touched_accounts = []
    touched_classes = set()
    for trade in restated:
        delta = trade["restated_share_delta"]
        position = positions_service.find(trade["account_id"], trade["share_class_id"])
        if position is not None and delta != 0:
            positions_service.move_shares(position, delta)
            positions_service.append_ledger_entry(
                position, trade["id"], delta, "NAV_CORRECTION_RESTATEMENT", trade["trade_date"])
            touched_classes.add(position["share_class_id"])
        account = db.store.accounts.get(trade["account_id"])
        if account is not None:
            touched_accounts.append(account)
    for share_class_id in touched_classes:
        positions_service.recompute_class_shares(share_class_id)

    # link 4 -- later preliminary strikes of the class are invalidated.
    invalidated = []
    for other in db.store.nav_records.values():
        if other["share_class_id"] != record["share_class_id"]:
            continue
        if other["valuation_date"] <= record["valuation_date"]:
            continue
        if other["status"] != "PRELIMINARY":
            continue
        other["status"] = "STALE_REPRICE_REQUIRED"
        db.touch(other)
        invalidated.append(other)

    # link 5 -- provisional trades priced on those strikes fall back to RECEIVED.
    invalid_keys = set((n["share_class_id"], n["valuation_date"]) for n in invalidated)
    for trade in db.store.trades.values():
        if trade["execution_status"] != "PRICED_PROVISIONAL":
            continue
        if (trade["share_class_id"], trade["trade_date"]) not in invalid_keys:
            continue
        pricing_service.clear_pricing_fields(trade)
        trade["execution_status"] = "RECEIVED"
        db.touch(trade)

    case["status"] = "REPROCESSED"
    case["reprocessed_by_user_id"] = caller.user_id
    case["restated_trade_count"] = len(restated)
    case["invalidated_nav_record_count"] = len(invalidated)
    db.touch(case)

    household.recompute_many(touched_accounts)
    return response.ok(serializers.case(case))
