"""Maturity tranches: the schedule and yield-to-worst pricing (PRD 3.2)."""
from decimal import Decimal

from flask import Blueprint

import db
import lookup
import response
import serializers
from errors import ApiError
from middleware import ALL_ROLES, authenticate, require_deal_ownership
from services import calc
from validation import (
    dec,
    parse_body,
    query_bool,
    query_value,
    semiannual_periods,
    sorted_rows,
    spec,
)

bp = Blueprint("tranches", __name__)

TRANCHE_SPECS = [
    spec("sequence_number", "integer", minimum=1, maximum=40),
    spec("maturity_date", "datetime"),
    spec("principal_amount_usd", "number"),
    spec("coupon_rate_pct", "number", minimum=0, maximum=12, max_decimals=3),
    spec("yield_pct", "number", exclusive_minimum=0, maximum=12, max_decimals=3),
    spec("is_callable", "boolean", required=False, default=False),
    spec("first_call_date", "datetime", required=False, default=None),
    spec("call_price_pct", "number", required=False, default=None, max_decimals=3),
    spec("refunded_tranche_id", "string", required=False, default=None),
]

CALL_PRICE_MIN = Decimal("100.000")
CALL_PRICE_MAX = Decimal("103.000")


@bp.route("/bond-offerings/deals/<deal_id>/maturity-tranches", methods=["POST"])
def create_tranche(deal_id):
    actor = authenticate(["MunicipalAdvisor"])
    deal = lookup.get_deal(deal_id)
    body = parse_body(TRANCHE_SPECS)
    # tier 7: body references must name existing rows
    refunded = None
    if body["refunded_tranche_id"] is not None:
        refunded = lookup.get_tranche(body["refunded_tranche_id"])
    # tier 8: actor ownership
    require_deal_ownership(actor, deal)
    # tier 9: a refunding maturity refunds another deal of the same issuer
    if refunded is not None:
        other = db.db.deals[refunded["deal_id"]]
        if other["id"] == deal_id or other["issuer_id"] != deal["issuer_id"]:
            raise ApiError("ERR_CROSS_DEAL_REFERENCE")
    # tier 14: temporal alignment
    periods_to_maturity = semiannual_periods(deal["dated_date"], body["maturity_date"])
    if periods_to_maturity is None:
        raise ApiError("ERR_MATURITY_DATE_UNALIGNED")
    periods_to_call = None
    if body["first_call_date"] is not None:
        periods_to_call = semiannual_periods(deal["dated_date"], body["first_call_date"])
        if periods_to_call is None:
            raise ApiError("ERR_MATURITY_DATE_UNALIGNED")
    # tier 15: call-feature coherence
    if body["is_callable"]:
        if body["first_call_date"] is None or body["call_price_pct"] is None:
            raise ApiError("ERR_CALL_FEATURE_INVALID")
        if body["first_call_date"] >= body["maturity_date"]:
            raise ApiError("ERR_CALL_FEATURE_INVALID")
        price = dec(body["call_price_pct"])
        if price < CALL_PRICE_MIN or price > CALL_PRICE_MAX:
            raise ApiError("ERR_CALL_FEATURE_INVALID")
    else:
        if body["first_call_date"] is not None or body["call_price_pct"] is not None:
            raise ApiError("ERR_CALL_FEATURE_INVALID")
        periods_to_call = None
    # tier 15: denomination
    principal = dec(body["principal_amount_usd"])
    if principal <= 0 or principal % calc.MIN_DENOMINATION_USD != 0:
        raise ApiError("ERR_DENOMINATION_INVALID")
    # tier 15: sequence uniqueness and monotone schedule
    for existing in lookup.tranches_of_deal(deal_id):
        if existing["sequence_number"] == body["sequence_number"]:
            raise ApiError("ERR_TRANCHE_SEQUENCE_CONFLICT")
        if existing["sequence_number"] < body["sequence_number"]:
            if existing["maturity_date"] >= body["maturity_date"]:
                raise ApiError("ERR_TRANCHE_SEQUENCE_CONFLICT")
        else:
            if existing["maturity_date"] <= body["maturity_date"]:
                raise ApiError("ERR_TRANCHE_SEQUENCE_CONFLICT")
    # tier 15: refunded tranche eligibility
    if refunded is not None:
        refunded_deal = db.db.deals[refunded["deal_id"]]
        if refunded_deal["status"] != "CLOSED":
            raise ApiError("ERR_REFUNDED_TRANCHE_INVALID")
        for other in db.db.tranches.values():
            if other["refunded_tranche_id"] == refunded["id"]:
                raise ApiError("ERR_REFUNDED_TRANCHE_INVALID")
    row = db.new_row(
        deal_id=deal_id,
        sequence_number=body["sequence_number"],
        maturity_date=body["maturity_date"],
        principal_amount_usd=principal,
        coupon_rate_pct=body["coupon_rate_pct"],
        yield_pct=body["yield_pct"],
        is_callable=body["is_callable"],
        first_call_date=body["first_call_date"],
        call_price_pct=body["call_price_pct"],
        periods_to_maturity=periods_to_maturity,
        periods_to_call=periods_to_call,
        is_insured=False,
        rating_basis="UNDERLYING",
        par_allotted_usd=Decimal(0),
        par_unsold_usd=Decimal(0),
        refunded_tranche_id=body["refunded_tranche_id"],
    )
    priced = calc.tranche_reoffering_price(row)
    row.update(priced)
    db.db.tranches[row["id"]] = row
    return response.created(serializers.tranche(row))


@bp.route("/bond-offerings/deals/<deal_id>/maturity-tranches", methods=["GET"])
def list_deal_tranches(deal_id):
    authenticate(ALL_ROLES)
    lookup.get_deal(deal_id)
    rows = lookup.tranches_of_deal(deal_id)
    callable_filter = query_bool("is_callable")
    if callable_filter is not None:
        rows = [row for row in rows if row["is_callable"] == callable_filter]
    insured_filter = query_bool("is_insured")
    if insured_filter is not None:
        rows = [row for row in rows if row["is_insured"] == insured_filter]
    return response.paginated(rows, serializers.tranche)


@bp.route("/bond-offerings/maturity-tranches", methods=["GET"])
def list_tranches():
    authenticate(["MunicipalAdvisor", "Underwriter", "ComplianceOfficer"])
    rows = sorted_rows(list(db.db.tranches.values()))
    deal_id = query_value("deal_id")
    if deal_id is not None:
        rows = [row for row in rows if row["deal_id"] == deal_id]
    refunded_id = query_value("refunded_tranche_id")
    if refunded_id is not None:
        rows = [row for row in rows if row["refunded_tranche_id"] == refunded_id]
    return response.paginated(rows, serializers.tranche)


@bp.route("/bond-offerings/maturity-tranches/<tranche_id>", methods=["GET"])
def read_tranche(tranche_id):
    authenticate(ALL_ROLES)
    row = lookup.get_tranche(tranche_id)
    return response.ok(serializers.tranche(row))
