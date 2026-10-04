"""Profit period and statement line item routes (PRD §3.5, §3.6)."""

from datetime import timedelta
from flask import Blueprint, request

import db
from errors import (
    ERR_INVALID_STATE,
    ERR_NO_ACTIVE_CONTRACT_FOR_RESTAURANT,
    ERR_OPEN_DISPUTE_BLOCKS_LOCK,
    ERR_PERIOD_CLOSED_FOR_ENTRIES,
    ERR_PERIOD_OVERLAP,
    ERR_RESTAURANT_NOT_ACTIVE,
    ERR_UNFINALIZED_LINE_ITEMS,
    conflict,
    invalid_request,
    unprocessable,
)
from middleware import require_roles
from response import success_list, success_object
from services import calculations, domain
from util import (
    base_entity,
    check_occ,
    get_json_body,
    logical_date,
    logical_dt,
    paginate,
    req_date,
    req_field,
    req_int,
    req_string,
    touch,
)

bp = Blueprint("periods", __name__)

PERIOD_READ_ROLES = (
    "PlatformAdmin",
    "CorporateController",
    "OperationsAuditor",
    "ManagingPartner",
    "MarketPartner",
)
LINE_ITEM_READ_ROLES = ("PlatformAdmin", "CorporateController", "OperationsAuditor", "ManagingPartner")


# ---------------- profit periods ----------------

@bp.route("/profit-periods", methods=["POST"])
def create_period():
    require_roles("OperationsAuditor")
    body = get_json_body()
    restaurant_id = req_field(body, "restaurant_id")
    # Body FK existence (tier 4).
    domain.ref_restaurant(restaurant_id)
    # Structural constraints (tier 8) before the overlap business check.
    period_start = req_date(body, "period_start_date")
    period_end = req_date(body, "period_end_date")
    if period_end <= period_start:
        raise invalid_request("period_end_date must be after period_start_date")
    # Overlap over half-open intervals against non-LOCKED periods of the restaurant.
    start_iso = period_start.isoformat()
    end_iso = period_end.isoformat()
    for other in db.periods.values():
        if other["restaurant_id"] != restaurant_id or other["status"] == "LOCKED":
            continue
        if other["period_start_date"] < end_iso and start_iso < other["period_end_date"]:
            raise unprocessable(
                ERR_PERIOD_OVERLAP,
                "Period interval intersects an existing non-LOCKED period of the restaurant",
            )
    p = base_entity()
    p.update({
        "restaurant_id": restaurant_id,
        "period_start_date": start_iso,
        "period_end_date": end_iso,
        "status": "OPEN",
        "provisional_profit_cents": None,
        "final_distributable_profit_cents": None,
        "partner_share_cents": None,
        "market_override_cents": None,
        "corporate_retained_cents": None,
        "partner_share_paid": False,
        "finalized_at": None,
        "dispute_deadline": None,
    })
    db.periods[p["id"]] = p
    return success_object(domain.ser_period(p), 201)


@bp.route("/profit-periods", methods=["GET"])
def list_periods():
    require_roles(*PERIOD_READ_ROLES)
    items = list(db.periods.values())
    restaurant_id = request.args.get("restaurant_id")
    if restaurant_id is not None:
        items = [p for p in items if p["restaurant_id"] == restaurant_id]
    status = request.args.get("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    page, limit, offset, total = paginate(items)
    return success_list([domain.ser_period(p) for p in page], limit, offset, total)


@bp.route("/profit-periods/<pid>", methods=["GET"])
def get_period(pid):
    require_roles(*PERIOD_READ_ROLES)
    return success_object(domain.ser_period(domain.get_period(pid)))


@bp.route("/profit-periods/<pid>/line-items", methods=["POST"])
def post_line_item(pid):
    require_roles("OperationsAuditor")
    period = domain.get_period(pid)
    body = get_json_body()
    # State gate (tier 5), then OCC (§2.7), then temporal (tier 6).
    if period["status"] != "OPEN":
        raise conflict(ERR_INVALID_STATE, "Line items may only be posted to an OPEN period")
    check_occ(body, period, "expected_profit_period_version", "ProfitPeriod")
    if logical_date().isoformat() >= period["period_end_date"]:
        raise unprocessable(
            ERR_PERIOD_CLOSED_FOR_ENTRIES,
            "Logical clock date is on or after the period end date",
        )
    category = req_string(body, "category")
    if category not in domain.LINE_ITEM_CATEGORIES:
        raise invalid_request("category must be one of %s" % ", ".join(domain.LINE_ITEM_CATEGORIES))
    amount = req_int(body, "amount_cents")
    entry_status = req_string(body, "entry_status")
    if entry_status not in ("PROVISIONAL", "FINALIZED"):
        raise invalid_request("entry_status must be PROVISIONAL or FINALIZED")
    li = base_entity()
    li.update({
        "period_id": period["id"],
        "category": category,
        "amount_cents": amount,
        "entry_status": entry_status,
        "actual_amount_cents": amount,
        # partner_basis is computed (§2.9): CORPORATE_ADMIN_FEE is the excluded charge.
        "partner_basis": "EXCLUDED" if category == "CORPORATE_ADMIN_FEE" else "INCLUDED",
    })
    db.line_items[li["id"]] = li
    # Posting a line item mutates the parent period (§3.5).
    touch(period)
    return success_object(domain.ser_line_item(li), 201)


@bp.route("/profit-periods/<pid>/line-items", methods=["GET"])
def list_line_items(pid):
    require_roles(*LINE_ITEM_READ_ROLES)
    period = domain.get_period(pid)
    items = [li for li in db.line_items.values() if li["period_id"] == period["id"]]
    category = request.args.get("category")
    if category is not None:
        items = [li for li in items if li["category"] == category]
    entry_status = request.args.get("entry_status")
    if entry_status is not None:
        items = [li for li in items if li["entry_status"] == entry_status]
    page, limit, offset, total = paginate(items)
    return success_list([domain.ser_line_item(li) for li in page], limit, offset, total)


@bp.route("/line-items/<lid>/finalize", methods=["POST"])
def finalize_line_item(lid):
    require_roles("OperationsAuditor")
    li = domain.get_line_item(lid)
    if li["entry_status"] != "PROVISIONAL":
        raise conflict(ERR_INVALID_STATE, "Line item must be PROVISIONAL to finalize")
    body = get_json_body()
    actual = req_int(body, "actual_amount_cents")
    li["actual_amount_cents"] = actual
    li["entry_status"] = "FINALIZED"
    touch(li)
    return success_object(domain.ser_line_item(li))


@bp.route("/profit-periods/<pid>/compute", methods=["POST"])
def compute_period(pid):
    require_roles("OperationsAuditor")
    period = domain.get_period(pid)
    body = get_json_body()
    # State gate (tier 5), then OCC (§2.7), then referential gates (tier 7).
    if period["status"] not in ("OPEN", "REOPENED"):
        raise conflict(ERR_INVALID_STATE, "Period must be OPEN or REOPENED to compute")
    check_occ(body, period, "expected_profit_period_version", "ProfitPeriod")
    restaurant = db.restaurants.get(period["restaurant_id"])
    if restaurant is None or restaurant["status"] != "ACTIVE":
        raise unprocessable(ERR_RESTAURANT_NOT_ACTIVE, "Restaurant must be ACTIVE to compute")
    if domain.active_family_contract(period["restaurant_id"]) is None:
        raise unprocessable(
            ERR_NO_ACTIVE_CONTRACT_FOR_RESTAURANT,
            "No active-family contract exists on the restaurant",
        )
    period["provisional_profit_cents"] = calculations.restaurant_profit(period, "provisional")
    period["status"] = "COMPUTED"
    touch(period)
    return success_object(domain.ser_period(period))


@bp.route("/profit-periods/<pid>/finalize", methods=["POST"])
def finalize_period(pid):
    require_roles("CorporateController")
    period = domain.get_period(pid)
    if period["status"] != "COMPUTED":
        raise conflict(ERR_INVALID_STATE, "Period must be COMPUTED to finalize")
    # Referential gate (tier 7) before the aggregate check (tier 9).
    if domain.active_family_contract(period["restaurant_id"]) is None:
        raise unprocessable(
            ERR_NO_ACTIVE_CONTRACT_FOR_RESTAURANT,
            "No active-family contract exists on the restaurant",
        )
    unfinalized = any(
        li["period_id"] == period["id"] and li["entry_status"] == "PROVISIONAL"
        for li in db.line_items.values()
    )
    if unfinalized:
        raise unprocessable(ERR_UNFINALIZED_LINE_ITEMS, "Period has PROVISIONAL line items")
    final_profit = calculations.restaurant_profit(period, "final")
    share = calculations.partner_share(final_profit)
    period["final_distributable_profit_cents"] = final_profit
    period["partner_share_cents"] = share
    restaurant = db.restaurants.get(period["restaurant_id"])
    override = calculations.market_override(period, restaurant) if restaurant is not None else 0
    period["market_override_cents"] = override
    period["corporate_retained_cents"] = final_profit - share - override
    finalized_at = logical_dt()
    period["finalized_at"] = finalized_at
    period["dispute_deadline"] = finalized_at + timedelta(days=domain.DISPUTE_WINDOW_DAYS)
    period["status"] = "FINALIZED"
    touch(period)
    return success_object(domain.ser_period(period))


@bp.route("/profit-periods/<pid>/lock", methods=["POST"])
def lock_period(pid):
    require_roles("CorporateController")
    period = domain.get_period(pid)
    if period["status"] != "FINALIZED":
        raise conflict(ERR_INVALID_STATE, "Period must be FINALIZED to lock")
    open_dispute = any(
        d["period_id"] == period["id"] and d["status"] in domain.DISPUTE_OPEN_STATUSES
        for d in db.disputes.values()
    )
    if open_dispute:
        raise unprocessable(ERR_OPEN_DISPUTE_BLOCKS_LOCK, "An open dispute blocks the period lock")
    period["status"] = "LOCKED"
    touch(period)
    return success_object(domain.ser_period(period))
