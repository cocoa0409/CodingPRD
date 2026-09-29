"""Promotions: planning, director review and the activation checkpoint."""

from flask import Blueprint, g

import calc
import services
from db import clock_date, clock_instant, db, new_row, touch
from errors import ApiError, bad_request
from response import created_response, object_response
from routes.common import (
    ALL_ROLES,
    ALL_ROLES_WITH_PORTAL,
    PREFIX,
    created_asc,
    get_allocation,
    get_brand,
    get_customer,
    get_promotion,
    page,
)
from validators import (
    authenticate,
    body_fields,
    get_date,
    get_enum,
    get_int,
    get_string,
    is_portal,
    no_body,
    pagination,
    portal_guard,
    query_enum,
    query_value,
)

bp = Blueprint("promotions", __name__)

DIRECTOR = "TradeMarketingDirector"
KAM = "KeyAccountManager"
ANALYST = "TradeFinanceAnalyst"

ACCRUAL_METHODS = ("SHIPMENT", "CONSUMPTION")
LIFECYCLES = ("DRAFT", "SUBMITTED", "CHANGES_REQUESTED", "APPROVED",
              "LIVE", "ENDED", "ANALYZED", "WITHDRAWN")
SPEND_STATUSES = ("WITHIN_BUDGET", "OVERSPEND_WARNING", "OVERSPENT")
PERFORMANCE_FLAGS = ("UNRATED", "ON_TRACK", "UNDERPERFORMING")


def check_week_window(start, end):
    """Rung 70: Monday-aligned, half-open, end strictly after start."""
    if start.weekday() != 0 or end.weekday() != 0 or end <= start:
        raise ApiError("ERR_WINDOW_NOT_WEEK_ALIGNED")


# --------------------------------------------------------------------------
# planning
# --------------------------------------------------------------------------

@bp.post(PREFIX + "/promotions")
def create_promotion():
    authenticate([KAM])
    data = body_fields(
        required=["allocation_id", "name", "window_start", "window_end",
                  "expected_allocation_version"],
        optional=["accrual_method"],
    )
    allocation_id = get_string(data, "allocation_id")
    name = get_string(data, "name", min_len=1, max_len=120)
    window_start = get_date(data, "window_start")
    window_end = get_date(data, "window_end")
    expected = get_int(data, "expected_allocation_version", minimum=0)
    method = get_enum(data, "accrual_method", ACCRUAL_METHODS, required=False)

    alloc = get_allocation(allocation_id)
    # rung 30
    if expected != alloc["version"]:
        raise ApiError("ERR_STALE_ALLOCATION_VERSION")
    # rung 41
    if alloc["status"] != "APPROVED":
        raise ApiError("ERR_ALLOCATION_NOT_APPROVED")
    # rung 42
    if calc.allocation_posture(alloc) != "OPEN":
        raise ApiError("ERR_ALLOCATION_POSTURE_RESTRICTED")
    # rung 53
    customer = db.customers.get(alloc["customer_id"])
    if customer is not None and customer["trading_status"] != "ACTIVE":
        raise ApiError("ERR_CUSTOMER_CREDIT_HOLD")
    # rung 70
    check_week_window(window_start, window_end)

    if method is None:
        program = db.programs.get(alloc["program_id"])
        method = program["accrual_method_default"] if program else "SHIPMENT"

    row = new_row()
    row.update({
        "allocation_id": allocation_id,
        "customer_id": alloc["customer_id"],
        "brand_id": alloc["brand_id"],
        "name": name,
        "window_start": window_start,
        "window_end": window_end,
        "accrual_method": method,
        "lifecycle_status": "DRAFT",
        "revision_round": 0,
        "approved_by_user_id": None,
        "change_notes": None,
        "withdraw_reason": None,
        "_ever_overspent": False,
    })
    db.promotions[row["id"]] = row
    touch(alloc)
    return created_response(calc.promotion_out(row))


@bp.get(PREFIX + "/promotions/<promotion_id>")
def read_promotion(promotion_id):
    authenticate(ALL_ROLES_WITH_PORTAL)
    no_body()
    promo = get_promotion(promotion_id)
    portal_guard(promo["customer_id"])
    return object_response(calc.promotion_out(promo))


@bp.get(PREFIX + "/promotions")
def list_promotions():
    authenticate(ALL_ROLES_WITH_PORTAL)
    limit, offset = pagination([
        "allocation_id", "customer_id", "brand_id", "lifecycle_status",
        "spend_status", "performance_flag",
    ])
    allocation_id = query_value("allocation_id")
    customer_id = query_value("customer_id")
    brand_id = query_value("brand_id")
    lifecycle = query_enum("lifecycle_status", LIFECYCLES)
    spend_status = query_enum("spend_status", SPEND_STATUSES)
    flag = query_enum("performance_flag", PERFORMANCE_FLAGS)
    if is_portal():
        if customer_id is None:
            customer_id = g.user_id
        else:
            portal_guard(customer_id)
    rows = list(db.promotions.values())
    if allocation_id is not None:
        get_allocation(allocation_id)
        rows = [r for r in rows if r["allocation_id"] == allocation_id]
    if brand_id is not None:
        get_brand(brand_id)
        rows = [r for r in rows if r["brand_id"] == brand_id]
    if customer_id is not None:
        if not is_portal():
            get_customer(customer_id)
        rows = [r for r in rows if r["customer_id"] == customer_id]
    if lifecycle is not None:
        rows = [r for r in rows if r["lifecycle_status"] == lifecycle]
    if spend_status is not None:
        rows = [r for r in rows if calc.promotion_spend(r)[1] == spend_status]
    if flag is not None:
        rows = [r for r in rows if calc.promotion_performance_flag(r) == flag]
    return page(created_asc(rows), limit, offset, calc.promotion_out)


# --------------------------------------------------------------------------
# director review
# --------------------------------------------------------------------------

@bp.post(PREFIX + "/promotions/<promotion_id>/submit")
def submit_promotion(promotion_id):
    authenticate([KAM])
    no_body()
    promo = get_promotion(promotion_id)
    alloc = db.allocations.get(promo["allocation_id"])
    # rung 41
    if alloc is not None and alloc["status"] != "APPROVED":
        raise ApiError("ERR_ALLOCATION_NOT_APPROVED")
    # rung 43
    if promo["lifecycle_status"] != "DRAFT":
        raise ApiError("ERR_PROMOTION_STATE_INVALID")
    # rung 84
    planned = [t for t in calc.tactics_of_promotion(promotion_id)
               if t["status"] == "PLANNED"]
    if not planned:
        raise ApiError("ERR_PROMOTION_HAS_NO_TACTICS")
    promo["lifecycle_status"] = "SUBMITTED"
    touch(promo)
    return object_response(calc.promotion_out(promo))


@bp.post(PREFIX + "/promotions/<promotion_id>/request-changes")
def request_changes(promotion_id):
    authenticate([DIRECTOR])
    data = body_fields(required=["change_notes"])
    notes = get_string(data, "change_notes", min_len=1)
    promo = get_promotion(promotion_id)
    if promo["lifecycle_status"] != "SUBMITTED":
        raise ApiError("ERR_PROMOTION_STATE_INVALID")
    promo["lifecycle_status"] = "CHANGES_REQUESTED"
    promo["change_notes"] = notes
    touch(promo)
    return object_response(calc.promotion_out(promo))


@bp.post(PREFIX + "/promotions/<promotion_id>/revise")
def revise_promotion(promotion_id):
    authenticate([KAM])
    no_body()
    promo = get_promotion(promotion_id)
    # rung 43
    if promo["lifecycle_status"] != "CHANGES_REQUESTED":
        raise ApiError("ERR_PROMOTION_STATE_INVALID")
    # rung 82
    if promo["revision_round"] >= calc.MAX_REVISION_ROUNDS:
        raise ApiError("ERR_MAX_REVISION_ROUNDS")
    promo["lifecycle_status"] = "DRAFT"
    promo["revision_round"] += 1
    touch(promo)
    return object_response(calc.promotion_out(promo))


@bp.post(PREFIX + "/promotions/<promotion_id>/approve")
def approve_promotion(promotion_id):
    authenticate([DIRECTOR])
    no_body()
    promo = get_promotion(promotion_id)
    alloc = db.allocations.get(promo["allocation_id"])
    # rung 42
    if alloc is not None and calc.allocation_posture(alloc) != "OPEN":
        raise ApiError("ERR_ALLOCATION_POSTURE_RESTRICTED")
    # rung 43
    if promo["lifecycle_status"] != "SUBMITTED":
        raise ApiError("ERR_PROMOTION_STATE_INVALID")
    # rung 53
    customer = db.customers.get(promo["customer_id"])
    if customer is not None and customer["trading_status"] != "ACTIVE":
        raise ApiError("ERR_CUSTOMER_CREDIT_HOLD")
    # rung 85
    if not calc.promotion_commitment_verified(promo):
        raise ApiError("ERR_COMMITMENT_DOCUMENTATION_MISSING")
    pricing = calc.promotion_pricing(promo)
    if alloc is not None:
        ledger = calc.allocation_ledger(alloc)
        # rung 95
        if ledger["available_amount"] < pricing["planned_total_spend"]:
            raise ApiError("ERR_ALLOCATION_BALANCE_INSUFFICIENT")
        # rung 96
        if pricing["committed_units"] > ledger["unreserved_units"]:
            raise ApiError("ERR_UNITS_EXCEED_UNRESERVED")
    promo["lifecycle_status"] = "APPROVED"
    promo["approved_by_user_id"] = g.user_id
    touch(promo)
    if alloc is not None:
        touch(alloc)
    return object_response(calc.promotion_out(promo))


@bp.post(PREFIX + "/promotions/<promotion_id>/withdraw")
def withdraw_promotion(promotion_id):
    authenticate([KAM])
    data = body_fields(optional=["withdraw_reason"])
    reason = get_string(data, "withdraw_reason", required=False, min_len=1)
    promo = get_promotion(promotion_id)
    # rung 43 - state and the un-accrued precondition share the code
    if promo["lifecycle_status"] != "APPROVED":
        raise ApiError("ERR_PROMOTION_STATE_INVALID")
    if calc.promotion_ledger(promo)["gross_accrued_amount"] != calc.ZERO:
        raise ApiError("ERR_PROMOTION_STATE_INVALID")
    promo["lifecycle_status"] = "WITHDRAWN"
    promo["withdraw_reason"] = reason
    touch(promo)
    for tactic in calc.tactics_of_promotion(promotion_id):
        if tactic["status"] in ("PLANNED", "ACTIVE"):
            tactic["status"] = "CANCELLED"
            touch(tactic)
    alloc = db.allocations.get(promo["allocation_id"])
    if alloc is not None:
        touch(alloc)
    return object_response(calc.promotion_out(promo))


# --------------------------------------------------------------------------
# operations checkpoint
# --------------------------------------------------------------------------

@bp.post(PREFIX + "/promotion-activation-runs")
def activation_run():
    authenticate([ANALYST, DIRECTOR])
    no_body()
    result = services.run_activation()
    body = {"run_at": clock_instant()}
    body.update(result)
    return object_response(body)
