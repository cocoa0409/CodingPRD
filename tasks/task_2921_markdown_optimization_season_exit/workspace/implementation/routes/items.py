"""Item registration, weekly sales history and elasticity (PRD 3.2, 3.4)."""

from flask import Blueprint

from common import add_days, dec, fmt_date, parse_date, r2
from db import db, new_row, touch
from errors import ApiError
from middleware import (ROLE_MERCHANDISE_DIRECTOR, ROLE_PRICING_ANALYST, body,
                        endpoint)
from response import created, ok
from serializers import estimate_json, item_json, sales_week_json
from services import calc, lookup
from services.lifecycle import (estimates_of_item, items_of_season,
                                refresh_item, sales_weeks_of_item)

bp = Blueprint("items", __name__)

METHODS = ("AUTO", "OWN_HISTORY", "CLUSTER_POOLED")


@endpoint(bp, "/items", ["POST"],
          (ROLE_PRICING_ANALYST, ROLE_MERCHANDISE_DIRECTOR))
def create_item(user_id, role):
    from validation import req_date, req_enum, req_int, req_str
    payload = body()
    sku = req_str(payload, "sku", min_len=1, max_len=64)
    season_id = req_str(payload, "season_id")
    category = req_enum(payload, "category", calc.CATEGORIES)
    cluster_code = req_str(payload, "cluster_code", min_len=1, max_len=64)
    vendor_code = req_str(payload, "vendor_code", min_len=1, max_len=64)
    first_receipt_date = req_date(payload, "first_receipt_date")
    original_retail_cents = req_int(payload, "original_retail_cents", minimum=1)
    unit_cost_cents = req_int(payload, "unit_cost_cents", minimum=0)
    units_received_total = req_int(payload, "units_received_total", minimum=1)

    season = lookup.season(season_id)
    if category != season["category"]:
        raise ApiError("ERR_VALIDATION",
                       "The item's category must equal its season's category.")
    lookup.gate_not_closed(season)

    for existing in db.items.values():
        if existing["sku"] == sku:
            raise ApiError("ERR_DUPLICATE_RESOURCE",
                           "SKU '%s' already exists." % sku)

    protected_until = add_days(first_receipt_date,
                               calc.protection_days(category))
    item = new_row(
        sku=sku,
        season_id=season["id"],
        category=category,
        cluster_code=cluster_code,
        vendor_code=vendor_code,
        first_receipt_date=fmt_date(first_receipt_date),
        protected_until_date=fmt_date(protected_until),
        original_retail_cents=original_retail_cents,
        current_retail_cents=original_retail_cents,
        unit_cost_cents=unit_cost_cents,
        units_received_total=units_received_total,
        units_sold_total=0,
        units_committed_disposition=0,
        units_disposed_total=0,
        on_hand_units=units_received_total,
        sample_weeks=0,
        sell_through_pct=r2(0),
        weeks_of_supply=float(calc.WEEKS_OF_SUPPLY_SENTINEL),
        lifecycle_stage="NEW_ARRIVAL",
        markdown_state="FULL_PRICE",
        permanent_markdown_reserve_cents=0,
        promo_discount_cents=0,
    )
    db.insert("items", item)
    refresh_item(item, silent=True)
    return created(item_json(item))


@endpoint(bp, "/items/<item_id>/sales-weeks", ["POST"], (ROLE_PRICING_ANALYST,))
def create_sales_week(user_id, role, item_id):
    from validation import req_date, req_int
    payload = body()
    week_ending_date = req_date(payload, "week_ending_date")
    units_sold = req_int(payload, "units_sold", minimum=0)
    ticket_price_cents = req_int(payload, "ticket_price_cents", minimum=1)

    item = lookup.item(item_id)
    if not week_ending_date > parse_date(item["first_receipt_date"]):
        raise ApiError("ERR_VALIDATION",
                       "week_ending_date must be strictly after the item's "
                       "first_receipt_date.")
    lookup.gate_not_closed(lookup.season(item["season_id"]))

    formatted = fmt_date(week_ending_date)
    for existing in sales_weeks_of_item(item):
        if existing["week_ending_date"] == formatted:
            raise ApiError("ERR_DUPLICATE_RESOURCE",
                           "A sales week already exists for %s." % formatted)

    if units_sold > item["on_hand_units"]:
        raise ApiError("ERR_INSUFFICIENT_AVAILABLE_UNITS",
                       "units_sold exceeds the item's on-hand units.")

    week = new_row(
        versioned=False,
        item_id=item["id"],
        week_ending_date=formatted,
        units_sold=units_sold,
        ticket_price_cents=ticket_price_cents,
        price_relative_pct=calc.price_relative_pct(
            ticket_price_cents, item["original_retail_cents"]),
    )
    db.insert("sales_weeks", week)
    refresh_item(item, force=True)
    return created(sales_week_json(week))


def _certified_estimate_of(item):
    for estimate in estimates_of_item(item):
        if estimate["status"] == "CERTIFIED":
            return estimate
    return None


def _peer_pool(item):
    peers = []
    for candidate in db.items.values():
        if candidate["id"] == item["id"]:
            continue
        if candidate["season_id"] != item["season_id"]:
            continue
        if candidate["category"] != item["category"]:
            continue
        if candidate["cluster_code"] != item["cluster_code"]:
            continue
        if candidate["units_sold_total"] < 1:
            continue
        certified = _certified_estimate_of(candidate)
        if certified is None:
            continue
        peers.append({
            "units_sold_total": candidate["units_sold_total"],
            "elasticity_coefficient": certified["elasticity_coefficient"],
            "created_at": candidate["created_at"],
        })
    return sorted(peers, key=lambda p: p["created_at"])


@endpoint(bp, "/elasticity-estimates", ["POST"], (ROLE_PRICING_ANALYST,))
def create_estimate(user_id, role):
    from validation import opt_enum, req_str
    payload = body()
    item_id = req_str(payload, "item_id")
    method = opt_enum(payload, "method", METHODS, default="AUTO")

    item = lookup.item(item_id)
    lookup.gate_not_closed(lookup.season(item["season_id"]))

    weeks = sales_weeks_of_item(item)
    own_ok = calc.own_history_ok(weeks)

    if method == "OWN_HISTORY" and not own_ok:
        raise ApiError("ERR_INSUFFICIENT_PRICE_HISTORY",
                       "The item's own price history cannot support a "
                       "log-log slope.")

    use_own = own_ok if method == "AUTO" else (method == "OWN_HISTORY")

    if use_own:
        resolved_method = "OWN_HISTORY"
        coefficient = calc.own_history_coefficient(weeks)
        sample_weeks_used = len(weeks)
        peer_items_used = 0
        confidence = "HIGH" if len(weeks) >= 4 else "LOW"
    else:
        peers = _peer_pool(item)
        if not peers:
            raise ApiError("ERR_EMPTY_PEER_POOL",
                           "No cluster peer carries a certified estimate.")
        resolved_method = "CLUSTER_POOLED"
        coefficient = calc.pooled_coefficient(peers)
        sample_weeks_used = 0
        peer_items_used = len(peers)
        confidence = "LOW"

    estimate = new_row(
        item_id=item["id"],
        method=method,
        resolved_method=resolved_method,
        elasticity_coefficient=coefficient,
        sample_weeks_used=sample_weeks_used,
        peer_items_used=peer_items_used,
        confidence=confidence,
        estimated_at=db.clock_instant(),
        certified_at=None,
        status="DRAFT",
    )
    db.insert("estimates", estimate)
    return created(estimate_json(estimate))


@endpoint(bp, "/elasticity-estimates/<estimate_id>/certify", ["POST"],
          (ROLE_PRICING_ANALYST, ROLE_MERCHANDISE_DIRECTOR))
def certify_estimate(user_id, role, estimate_id):
    from validation import opt_bool
    payload = body()
    override = opt_bool(payload, "override_low_confidence", default=False)
    estimate = lookup.estimate(estimate_id)

    if estimate["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE",
                       "Only a DRAFT estimate may be certified.")
    item = lookup.item(estimate["item_id"])
    lookup.gate_not_closed(lookup.season(item["season_id"]))

    if estimate["confidence"] != "HIGH" and not override:
        raise ApiError("ERR_LOW_CONFIDENCE_NOT_OVERRIDDEN",
                       "A low-confidence estimate needs "
                       "override_low_confidence.")

    estimate["status"] = "CERTIFIED"
    estimate["certified_at"] = db.clock_instant()
    touch(estimate)

    for sibling in estimates_of_item(item):
        if sibling["id"] == estimate["id"]:
            continue
        if sibling["status"] in ("DRAFT", "CERTIFIED"):
            sibling["status"] = "SUPERSEDED"
            touch(sibling)
    return ok(estimate_json(estimate))
