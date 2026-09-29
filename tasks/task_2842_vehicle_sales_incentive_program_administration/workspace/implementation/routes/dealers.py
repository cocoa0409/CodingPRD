"""Dealer registration and standing."""

from flask import Blueprint

import db
import errors
import response
import serializers
import validate
from middleware import ROLE_CLAIMS_AUDITOR as AUDITOR
from middleware import ROLE_DEALER as DEALER
from middleware import ROLE_FIELD_SALES_MANAGER as FIELD
from middleware import ROLE_INCENTIVE_CONTROLLER as CONTROLLER
from middleware import ROLE_PROGRAM_DESIGNER as DESIGNER
from middleware import require_roles, touch
from routes import helpers

bp = Blueprint("dealers", __name__)

DEALER_STATUSES = ("ACTIVE", "SUSPENDED", "TERMINATED")


@bp.route("/dealers", methods=["POST"])
@require_roles(CONTROLLER)
def register_dealer():
    payload = validate.body()
    dealer_code = validate.get_string(payload, "dealer_code", min_len=1, max_len=16)
    name = validate.get_string(payload, "name", min_len=1)
    region_code = validate.get_string(payload, "region_code", min_len=1, max_len=8)
    historical_volume_units = validate.get_int(payload, "historical_volume_units", minimum=0)
    market_opportunity_bps = validate.get_int(
        payload, "market_opportunity_bps", minimum=0, maximum=20000
    )

    for existing in db.dealers.values():
        if existing["dealer_code"] == dealer_code:
            raise errors.ApiError("ERR_DUPLICATE_DEALER_CODE")

    dealer = db.insert(
        db.dealers,
        "dealer",
        {
            "dealer_code": dealer_code,
            "name": name,
            "region_code": region_code,
            "status": "ACTIVE",
            "historical_volume_units": historical_volume_units,
            "market_opportunity_bps": market_opportunity_bps,
            "paid_cents": 0,
            "open_chargeback_cents": 0,
        },
    )
    return response.object_response(serializers.dealer(dealer), 201)


@bp.route("/dealers/<dealer_id>", methods=["GET"])
@require_roles(CONTROLLER, FIELD, AUDITOR, DESIGNER, DEALER)
def read_dealer(dealer_id):
    dealer = helpers.get_dealer(dealer_id)
    return response.object_response(serializers.dealer(dealer))


@bp.route("/dealers/<dealer_id>/status", methods=["POST"])
@require_roles(CONTROLLER)
def set_dealer_status(dealer_id):
    dealer = helpers.get_dealer(dealer_id)
    payload = validate.body()
    status = validate.get_enum(payload, "status", DEALER_STATUSES)
    validate.get_string(payload, "note", required=False, default=None)
    dealer["status"] = status
    touch(dealer)
    return response.object_response(serializers.dealer(dealer))
