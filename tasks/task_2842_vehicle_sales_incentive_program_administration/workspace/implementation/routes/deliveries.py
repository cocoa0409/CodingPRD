"""Retail delivery reporting, back-dated detection, validation and unwinds."""

from flask import Blueprint, request

import clock
import db
import errors
import response
import serializers
import validate
from middleware import ROLE_CLAIMS_AUDITOR as AUDITOR
from middleware import ROLE_DEALER as DEALER
from middleware import ROLE_FIELD_SALES_MANAGER as FIELD
from middleware import ROLE_INCENTIVE_CONTROLLER as CONTROLLER
from middleware import caller_id, require_roles, touch
from routes import helpers
from services import calc, ledger

bp = Blueprint("deliveries", __name__)

DEAL_TYPES = ("CASH", "FINANCE", "LEASE")
DELIVERY_STATUSES = ("REPORTED", "VALIDATED", "REJECTED", "UNWOUND")


@bp.route("/deliveries", methods=["POST"])
@require_roles(DEALER)
def report_delivery():
    payload = validate.body()
    # Rung 4 precedes payload shape: a dealer reporting for someone else learns
    # only that the delivery is not theirs.
    raw_dealer_id = payload.get("dealer_id")
    if isinstance(raw_dealer_id, str):
        helpers.require_dealer_ownership(raw_dealer_id)

    dealer_id = validate.get_string(payload, "dealer_id", min_len=1)
    helpers.require_dealer_ownership(dealer_id)
    vin = validate.get_string(payload, "vin", min_len=17, max_len=17)
    model_code = validate.get_string(payload, "model_code", min_len=1, max_len=16)
    trim_code = validate.get_string(payload, "trim_code", min_len=1, max_len=16)
    build_date = validate.get_instant(payload, "build_date")
    msrp_cents = validate.get_int(payload, "msrp_cents", minimum=1)
    sale_date = validate.get_instant(payload, "sale_date")
    customer_region_code = validate.get_string(
        payload, "customer_region_code", min_len=1, max_len=8
    )
    deal_type = validate.get_enum(payload, "deal_type", DEAL_TYPES)
    term_months = validate.get_int(payload, "term_months", required=False, default=0, minimum=0)
    contract_apr_bps = validate.get_int(
        payload, "contract_apr_bps", required=False, default=0, minimum=0
    )
    base_residual_bps = validate.get_int(
        payload, "base_residual_bps", required=False, default=0, minimum=0
    )
    if deal_type in ("FINANCE", "LEASE") and term_months <= 0:
        raise errors.ApiError(
            "ERR_INVALID_REQUEST", "term_months must be above 0 for a financed or leased deal."
        )
    if deal_type == "LEASE" and base_residual_bps <= 0:
        raise errors.ApiError(
            "ERR_INVALID_REQUEST", "base_residual_bps must be above 0 for a leased deal."
        )

    dealer = helpers.get_dealer(dealer_id)

    for existing in db.deliveries.values():
        if existing["vin"] == vin:
            raise errors.ApiError("ERR_DUPLICATE_VIN")

    helpers.require_good_standing(dealer)

    reported_at = clock.now()
    lag_days, flagged = calc.back_dated_detection(sale_date, reported_at)
    delivery = db.insert(
        db.deliveries,
        "delivery",
        {
            "dealer_id": dealer_id,
            "vin": vin,
            "model_code": model_code,
            "trim_code": trim_code,
            "build_date": build_date,
            "msrp_cents": msrp_cents,
            "sale_date": sale_date,
            "reported_at": reported_at,
            "customer_region_code": customer_region_code,
            "deal_type": deal_type,
            "term_months": term_months,
            "contract_apr_bps": contract_apr_bps,
            "base_residual_bps": base_residual_bps,
            "status": "REPORTED",
            "reporting_lag_days": lag_days,
            "back_dated_flag": flagged,
            "validated_by_user_id": None,
            "unwound_at": None,
        },
    )
    return response.object_response(serializers.delivery(delivery), 201)


@bp.route("/deliveries", methods=["GET"])
@require_roles(AUDITOR, CONTROLLER, FIELD, DEALER)
def list_deliveries():
    dealer_id = validate.query_string("dealer_id")
    status = validate.query_enum("status", DELIVERY_STATUSES)
    back_dated_flag = validate.query_bool("back_dated_flag")
    rows = db.ordered(list(db.deliveries.values()))
    if dealer_id is not None:
        rows = [r for r in rows if r["dealer_id"] == dealer_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if back_dated_flag is not None:
        rows = [r for r in rows if r["back_dated_flag"] is back_dated_flag]
    return response.listing(rows, request.args, serializers.delivery)


@bp.route("/deliveries/<delivery_id>", methods=["GET"])
@require_roles(AUDITOR, CONTROLLER, FIELD, DEALER)
def read_delivery(delivery_id):
    delivery = helpers.get_delivery(delivery_id)
    return response.object_response(serializers.delivery(delivery))


@bp.route("/deliveries/<delivery_id>/validate", methods=["POST"])
@require_roles(AUDITOR)
def validate_delivery(delivery_id):
    delivery = helpers.get_delivery(delivery_id)
    validate.body()
    if delivery["status"] != "REPORTED":
        raise errors.ApiError("ERR_DELIVERY_INVALID_STATE")
    if delivery["back_dated_flag"]:
        raise errors.ApiError("ERR_BACK_DATED_SALE_DETECTED")
    dealer = db.dealers.get(delivery["dealer_id"])
    if dealer is not None:
        helpers.require_good_standing(dealer)

    delivery["status"] = "VALIDATED"
    delivery["validated_by_user_id"] = caller_id()
    touch(delivery)

    for objective in ledger.credited_objectives(delivery):
        ledger.recompute_objective(objective)

    return response.object_response(serializers.delivery(delivery))


@bp.route("/deliveries/<delivery_id>/reject", methods=["POST"])
@require_roles(AUDITOR)
def reject_delivery(delivery_id):
    delivery = helpers.get_delivery(delivery_id)
    payload = validate.body()
    validate.get_string(payload, "reason", min_len=1)
    if delivery["status"] != "REPORTED":
        raise errors.ApiError("ERR_DELIVERY_INVALID_STATE")
    delivery["status"] = "REJECTED"
    touch(delivery)
    return response.object_response(serializers.delivery(delivery))


@bp.route("/deliveries/<delivery_id>/unwind", methods=["POST"])
@require_roles(AUDITOR)
def unwind_delivery(delivery_id):
    delivery = helpers.get_delivery(delivery_id)
    payload = validate.body()
    validate.get_string(payload, "reason", required=False, default=None)
    if delivery["status"] != "VALIDATED":
        raise errors.ApiError("ERR_DELIVERY_INVALID_STATE")

    delivery["status"] = "UNWOUND"
    delivery["unwound_at"] = clock.now()
    touch(delivery)
    ledger.unwind_cascade(delivery)
    return response.object_response(serializers.delivery(delivery))


@bp.route("/deliveries/<delivery_id>/eligible-programs", methods=["GET"])
@require_roles(AUDITOR, CONTROLLER, DEALER)
def eligible_programs(delivery_id):
    delivery = helpers.get_delivery(delivery_id)
    return response.object_response(calc.stack_allocation(delivery))
