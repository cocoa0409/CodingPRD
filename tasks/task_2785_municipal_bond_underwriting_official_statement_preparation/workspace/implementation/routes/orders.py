"""Order periods and the order book (PRD 3.7)."""
from decimal import Decimal

from flask import Blueprint

import db
import lookup
import response
import serializers
from errors import ApiError
from middleware import ALL_ROLES, authenticate, require_deal_ownership
from services import calc, derive
from validation import dec, parse_body, query_value, sorted_rows, spec

bp = Blueprint("orders", __name__)

PERIOD_TYPES = ["RETAIL", "INSTITUTIONAL"]
PRIORITY_POLICIES = ["STANDARD_PRIORITY", "RETAIL_ONLY"]
ORDER_TYPES = ["RETAIL", "INSTITUTIONAL_PRIORITY", "MEMBER", "STOCK"]
PRICING_STATUSES = ("PRICING_COMPETITIVE", "PRICING_NEGOTIATED")
SYNDICATE_ORDER_ROLES = ("SENIOR_MANAGER", "CO_MANAGER")

PERIOD_SPECS = [
    spec("period_type", "enum", values=PERIOD_TYPES),
    spec("opens_at", "datetime"),
    spec("closes_at", "datetime"),
    spec(
        "priority_policy",
        "enum",
        values=PRIORITY_POLICIES,
        required=False,
        default="STANDARD_PRIORITY",
    ),
]


@bp.route("/bond-offerings/deals/<deal_id>/order-periods", methods=["POST"])
def create_period(deal_id):
    actor = authenticate(["Underwriter", "MunicipalAdvisor"])
    deal = lookup.get_deal(deal_id)
    body = parse_body(PERIOD_SPECS)
    require_deal_ownership(actor, deal)
    # tier 12: a competitive sale runs a single institutional book
    if body["period_type"] == "RETAIL" and deal["sale_method"] == "COMPETITIVE":
        raise ApiError("ERR_SALE_METHOD_CONFLICT")
    # tier 14: the half-open windows of one deal may not overlap
    opens_at = body["opens_at"]
    closes_at = body["closes_at"]
    if opens_at >= closes_at:
        raise ApiError("ERR_ORDER_PERIOD_OVERLAP")
    for existing in lookup.periods_of_deal(deal_id):
        if existing["status"] == "CANCELLED":
            continue
        if opens_at < existing["closes_at"] and existing["opens_at"] < closes_at:
            raise ApiError("ERR_ORDER_PERIOD_OVERLAP")
    row = db.new_row(
        deal_id=deal_id,
        period_type=body["period_type"],
        opens_at=opens_at,
        closes_at=closes_at,
        priority_policy=body["priority_policy"],
        status="SCHEDULED",
        allotment_run_count=0,
        orders_received_count=0,
        allotted_order_count=0,
        reopen_reason=None,
    )
    db.db.periods[row["id"]] = row
    return response.created(serializers.period(row))


@bp.route("/bond-offerings/deals/<deal_id>/order-periods", methods=["GET"])
def list_deal_periods(deal_id):
    authenticate(ALL_ROLES)
    lookup.get_deal(deal_id)
    rows = sorted_rows(lookup.periods_of_deal(deal_id))
    period_type = query_value("period_type")
    if period_type is not None:
        rows = [row for row in rows if row["period_type"] == period_type]
    status = query_value("status")
    if status is not None:
        rows = [row for row in rows if row["status"] == status]
    return response.paginated(rows, serializers.period)


@bp.route("/bond-offerings/order-periods/<period_id>", methods=["GET"])
def read_period(period_id):
    authenticate(ALL_ROLES)
    row = lookup.get_period(period_id)
    return response.ok(serializers.period(row))


@bp.route("/bond-offerings/order-periods/<period_id>/open", methods=["POST"])
def open_period(period_id):
    actor = authenticate(["Underwriter"])
    period = lookup.get_period(period_id)
    parse_body([])
    deal = lookup.deal_of_period(period)
    require_deal_ownership(actor, deal)
    # tier 11: state legality
    if period["status"] != "SCHEDULED":
        raise ApiError("ERR_ORDER_PERIOD_INVALID_STATE")
    if deal["status"] not in PRICING_STATUSES:
        raise ApiError("ERR_DEAL_INVALID_STATE")
    for other in lookup.periods_of_deal(deal["id"]):
        if other["id"] != period_id and other["status"] == "OPEN":
            raise ApiError("ERR_ORDER_PERIOD_INVALID_STATE")
    # tier 14: the logical clock must lie inside the window
    now = db.now()
    if now < period["opens_at"] or now >= period["closes_at"]:
        raise ApiError("ERR_ORDER_PERIOD_WINDOW_CLOSED")
    period["status"] = "OPEN"
    db.touch(period)
    return response.ok(serializers.period(period))


@bp.route("/bond-offerings/order-periods/<period_id>/close", methods=["POST"])
def close_period(period_id):
    actor = authenticate(["Underwriter"])
    period = lookup.get_period(period_id)
    parse_body([])
    deal = lookup.deal_of_period(period)
    require_deal_ownership(actor, deal)
    if period["status"] != "OPEN":
        raise ApiError("ERR_ORDER_PERIOD_INVALID_STATE")
    tranches = lookup.tranches_of_deal(deal["id"])
    for tranche in tranches:
        orders = lookup.orders_of_tranche(tranche["id"])
        touched = calc.allot_tranche(tranche, period, orders)
        for order in touched:
            db.touch(order)
    period["status"] = "CLOSED"
    period["allotment_run_count"] = period["allotment_run_count"] + 1
    derive.recompute_period_counters(period)
    db.touch(period)
    for tranche in tranches:
        derive.recompute_tranche_par(tranche)
    derive.recompute_deal_par_allotted_total(deal)
    db.touch(deal)
    return response.ok(serializers.period(period))


@bp.route("/bond-offerings/order-periods/<period_id>/reopen", methods=["POST"])
def reopen_period(period_id):
    authenticate(["ComplianceOfficer"])
    period = lookup.get_period(period_id)
    body = parse_body([spec("reopen_reason", "string", min_len=1)])
    deal = lookup.deal_of_period(period)
    if period["status"] != "CLOSED":
        raise ApiError("ERR_ORDER_PERIOD_INVALID_STATE")
    if deal["status"] not in PRICING_STATUSES:
        raise ApiError("ERR_DEAL_INVALID_STATE")
    if db.now() >= period["closes_at"]:
        raise ApiError("ERR_ORDER_PERIOD_WINDOW_CLOSED")
    # hop 1
    period["status"] = "OPEN"
    period["reopen_reason"] = body["reopen_reason"]
    # hop 2
    affected_tranche_ids = set()
    for order in lookup.orders_of_period(period_id):
        if order["status"] not in ("ALLOTTED", "PARTIALLY_ALLOTTED", "UNFILLED"):
            continue
        order["status"] = "PENDING"
        order["par_allotted_usd"] = Decimal(0)
        db.touch(order)
        affected_tranche_ids.add(order["maturity_tranche_id"])
    derive.recompute_period_counters(period)
    db.touch(period)
    # hop 3
    for tranche in lookup.tranches_of_deal(deal["id"]):
        if tranche["id"] in affected_tranche_ids:
            derive.recompute_tranche_par(tranche)
    # hop 4
    derive.recompute_deal_par_allotted_total(deal)
    derive.recompute_takedown_credits(deal)
    db.touch(deal)
    return response.ok(serializers.period(period))


ORDER_SPECS = [
    spec("maturity_tranche_id", "string"),
    spec("syndicate_member_id", "string"),
    spec("order_type", "enum", values=ORDER_TYPES),
    spec("par_requested_usd", "number"),
    spec("price_or_yield_pct", "number", exclusive_minimum=0, maximum=130, max_decimals=3),
    spec("expected_order_period_version", "integer"),
]


@bp.route("/bond-offerings/order-periods/<period_id>/orders", methods=["POST"])
def create_order(period_id):
    actor = authenticate(["Underwriter"])
    period = lookup.get_period(period_id)
    body = parse_body(ORDER_SPECS)
    deal = lookup.deal_of_period(period)
    # tier 7: both referenced rows must exist
    tranche = lookup.get_tranche(body["maturity_tranche_id"])
    member = db.db.members.get(body["syndicate_member_id"])
    if member is None:
        raise ApiError("ERR_CROSS_DEAL_REFERENCE")
    # tier 8: actor ownership
    require_deal_ownership(actor, deal)
    # tier 9: both referenced rows belong to the period's deal
    if tranche["deal_id"] != deal["id"] or member["deal_id"] != deal["id"]:
        raise ApiError("ERR_CROSS_DEAL_REFERENCE")
    # tier 10: optimistic concurrency on the order period
    if body["expected_order_period_version"] != period["version"]:
        raise ApiError("ERR_STALE_ORDER_PERIOD_VERSION")
    # tier 11: the book must be open
    if period["status"] != "OPEN":
        raise ApiError("ERR_ORDER_PERIOD_INVALID_STATE")
    # tier 14: the window must not have elapsed on the logical clock
    now = db.now()
    if now >= period["closes_at"]:
        raise ApiError("ERR_ORDER_PERIOD_WINDOW_CLOSED")
    # tier 15: denomination, then the three placement rules
    par_requested = dec(body["par_requested_usd"])
    if par_requested <= 0 or par_requested % calc.MIN_DENOMINATION_USD != 0:
        raise ApiError("ERR_DENOMINATION_INVALID")
    order_type = body["order_type"]
    if order_type == "RETAIL" and period["period_type"] != "RETAIL":
        raise ApiError("ERR_ORDER_TYPE_NOT_PERMITTED")
    if period["priority_policy"] == "RETAIL_ONLY" and order_type != "RETAIL":
        raise ApiError("ERR_ORDER_TYPE_NOT_PERMITTED")
    if order_type in ("MEMBER", "STOCK") and member["member_role"] not in SYNDICATE_ORDER_ROLES:
        raise ApiError("ERR_ORDER_TYPE_NOT_PERMITTED")
    row = db.new_row(
        order_period_id=period_id,
        maturity_tranche_id=tranche["id"],
        syndicate_member_id=member["id"],
        order_type=order_type,
        par_requested_usd=par_requested,
        price_or_yield_pct=body["price_or_yield_pct"],
        status="PENDING",
        par_allotted_usd=Decimal(0),
        submitted_at=now,
        cancellation_reason=None,
    )
    db.db.orders[row["id"]] = row
    derive.recompute_period_counters(period)
    db.touch(period)
    return response.created(serializers.order(row))


def _order_sorted(rows):
    return sorted(rows, key=lambda row: (row["submitted_at"], row["created_at"], row["_seq"]))


@bp.route("/bond-offerings/order-periods/<period_id>/orders", methods=["GET"])
def list_period_orders(period_id):
    authenticate(["IssuerOfficial", "MunicipalAdvisor", "Underwriter", "ComplianceOfficer"])
    lookup.get_period(period_id)
    rows = _order_sorted(lookup.orders_of_period(period_id))
    order_type = query_value("order_type")
    if order_type is not None:
        rows = [row for row in rows if row["order_type"] == order_type]
    status = query_value("status")
    if status is not None:
        rows = [row for row in rows if row["status"] == status]
    return response.paginated(rows, serializers.order)


@bp.route("/bond-offerings/orders", methods=["GET"])
def list_orders():
    authenticate(["MunicipalAdvisor", "Underwriter", "ComplianceOfficer"])
    rows = sorted_rows(list(db.db.orders.values()))
    tranche_id = query_value("maturity_tranche_id")
    if tranche_id is not None:
        rows = [row for row in rows if row["maturity_tranche_id"] == tranche_id]
    member_id = query_value("syndicate_member_id")
    if member_id is not None:
        rows = [row for row in rows if row["syndicate_member_id"] == member_id]
    period_id = query_value("order_period_id")
    if period_id is not None:
        rows = [row for row in rows if row["order_period_id"] == period_id]
    status = query_value("status")
    if status is not None:
        rows = [row for row in rows if row["status"] == status]
    return response.paginated(rows, serializers.order)


@bp.route("/bond-offerings/orders/<order_id>", methods=["GET"])
def read_order(order_id):
    authenticate(["IssuerOfficial", "MunicipalAdvisor", "Underwriter", "ComplianceOfficer"])
    row = lookup.get_order(order_id)
    return response.ok(serializers.order(row))


@bp.route("/bond-offerings/orders/<order_id>/cancel", methods=["POST"])
def cancel_order(order_id):
    actor = authenticate(["Underwriter"])
    order = lookup.get_order(order_id)
    body = parse_body([spec("cancellation_reason", "string", min_len=1)])
    period = db.db.periods[order["order_period_id"]]
    deal = lookup.deal_of_order(order)
    require_deal_ownership(actor, deal)
    # tier 11: a pending order in a live book
    if order["status"] != "PENDING":
        raise ApiError("ERR_ORDER_INVALID_STATE")
    if period["status"] != "OPEN":
        raise ApiError("ERR_ORDER_PERIOD_INVALID_STATE")
    # tier 14: the window must still be running
    if db.now() >= period["closes_at"]:
        raise ApiError("ERR_ORDER_PERIOD_WINDOW_CLOSED")
    order["status"] = "CANCELLED"
    order["par_allotted_usd"] = Decimal(0)
    order["cancellation_reason"] = body["cancellation_reason"]
    db.touch(order)
    derive.recompute_period_counters(period)
    db.touch(period)
    return response.ok(serializers.order(order))
