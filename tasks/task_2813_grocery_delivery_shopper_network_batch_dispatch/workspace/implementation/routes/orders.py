"""Orders, lines, placement, re-authorization, tips and parity reads (PRD 3.2)."""
from decimal import Decimal

from flask import Blueprint

import calc
import derive
import lookup
import serializers
from auth import require_owner, require_roles
from db_helpers import touch_if
from errors import fail
from response import created, ok
from store import base_row, db, hours, now, touch
from validation import (
    body_json,
    opt_bool,
    opt_int,
    opt_num,
    query_str,
    req_int,
    req_num,
    req_str,
    req_ts,
)

bp = Blueprint("orders", __name__)


@bp.post("/orders")
def create_order():
    require_roles("Customer")
    body = body_json()
    customer_id = req_str(body, "customer_id")
    retailer_id = req_str(body, "retailer_id")
    distance = req_num(body, "delivery_distance_mi", minimum=0.0, maximum=60.0)
    deadline = req_ts(body, "delivery_deadline")
    ebt_requested = opt_bool(body, "ebt_requested", default=False)
    tip = opt_int(body, "tip_amount_cents", default=0, minimum=0, maximum=20000)
    customer = lookup.customer(customer_id)
    retailer = lookup.retailer(retailer_id)
    require_owner(customer["id"])
    row = base_row()
    row.update(
        {
            "customer_id": customer["id"],
            "retailer_id": retailer["id"],
            "delivery_distance_mi": calc.one_dp(distance),
            "delivery_deadline": deadline,
            "ebt_requested": ebt_requested,
            "tip_amount_cents": tip,
            "fulfillment_status": "DRAFT",
            "payment_status": "UNAUTHORIZED",
            "estimated_subtotal_cents": 0,
            "authorization_ceiling_cents": 0,
            "authorized_ebt_cents": 0,
            "authorized_card_cents": 0,
            "captured_subtotal_cents": 0,
            "ebt_captured_cents": 0,
            "card_captured_cents": 0,
            "refunded_cents": 0,
            "tip_original_cents": 0,
            "tip_adjustment_count": 0,
            "delivered_at": None,
            "tip_window_closes_at": None,
            "parity_markup_cents": 0,
            "parity_disclosed": False,
        }
    )
    db.orders[row["id"]] = row
    return created(serializers.order(row))


@bp.get("/orders/<oid>")
def get_order(oid):
    require_roles("Customer", "Shopper", "DispatchAdmin", "CustomerSupport")
    row = lookup.order(oid)
    return ok(serializers.order(row))


@bp.get("/orders")
def list_orders():
    require_roles("Customer", "Shopper", "DispatchAdmin", "CustomerSupport")
    customer_id = query_str("customer_id")
    retailer_id = query_str("retailer_id")
    fulfillment_status = query_str("fulfillment_status")
    payment_status = query_str("payment_status")

    def keep(row):
        if customer_id is not None and row["customer_id"] != customer_id:
            return False
        if retailer_id is not None and row["retailer_id"] != retailer_id:
            return False
        if fulfillment_status is not None and row["fulfillment_status"] != fulfillment_status:
            return False
        if payment_status is not None and row["payment_status"] != payment_status:
            return False
        return True

    return lookup.paged(db.orders, serializers.order, keep)


@bp.post("/orders/<oid>/lines")
def create_line(oid):
    require_roles("Customer")
    order = lookup.order(oid)
    require_owner(order["customer_id"])
    body = body_json()
    catalog_item_id = req_str(body, "catalog_item_id")
    qty = opt_int(body, "requested_qty", default=None, minimum=1, maximum=50)
    weight = opt_num(body, "requested_weight_lb", default=None)
    item = lookup.catalog_item(catalog_item_id)
    # The pairing rules of PRD 3.2 depend on the item's pricing_unit, so they are
    # applied once the body foreign key has resolved.
    if item["pricing_unit"] == "PER_LB":
        if qty is not None and qty != 1:
            fail("ERR_INVALID_REQUEST", "requested_qty must be exactly 1 for a PER_LB item.")
        qty = 1
        if weight is None:
            weight = calc.dec(item["estimated_weight_lb"])
        if weight <= 0:
            fail("ERR_INVALID_REQUEST", "requested_weight_lb must be greater than 0.")
    else:
        if weight is not None and weight != 0:
            fail("ERR_INVALID_REQUEST", "requested_weight_lb must be 0 for an EACH item.")
        weight = Decimal("0")
        if qty is None:
            qty = 1
    if order["fulfillment_status"] != "DRAFT":
        fail("ERR_ORDER_NOT_DRAFT", "Lines may only be added while the order is a draft.")
    row = base_row()
    row.update(
        {
            "order_id": order["id"],
            "catalog_item_id": item["id"],
            "requested_qty": qty,
            "requested_weight_lb": calc.one_dp(weight),
            "unit_price_cents_snapshot": item["catalog_price_cents"],
            "in_store_price_cents_snapshot": item["in_store_price_cents"],
            "ebt_eligible_snapshot": item["is_ebt_eligible"],
            "picked_qty": 0,
            "final_weight_lb": Decimal("0"),
            "final_price_cents": 0,
            "status": "REQUESTED",
        }
    )
    db.order_lines[row["id"]] = row
    return created(serializers.order_line(row))


@bp.get("/order-lines/<lid>")
def get_line(lid):
    require_roles("Customer", "Shopper", "DispatchAdmin", "CustomerSupport")
    row = lookup.order_line(lid)
    return ok(serializers.order_line(row))


@bp.get("/order-lines")
def list_lines():
    require_roles("Customer", "Shopper", "DispatchAdmin", "CustomerSupport")
    order_id = query_str("order_id")
    catalog_item_id = query_str("catalog_item_id")
    status = query_str("status")

    def keep(row):
        if order_id is not None and row["order_id"] != order_id:
            return False
        if catalog_item_id is not None and row["catalog_item_id"] != catalog_item_id:
            return False
        if status is not None and row["status"] != status:
            return False
        return True

    return lookup.paged(db.order_lines, serializers.order_line, keep)


@bp.post("/orders/<oid>/submit")
def submit_order(oid):
    require_roles("Customer")
    order = lookup.order(oid)
    require_owner(order["customer_id"])
    if order["fulfillment_status"] != "DRAFT":
        fail("ERR_ORDER_NOT_DRAFT", "Only a draft order may be placed.")
    lines = derive.lines_of(order["id"])
    if not lines:
        fail("ERR_INVALID_REQUEST", "The order must have at least one line.")
    retailer = derive.retailer_of(order)
    if retailer is None or retailer["status"] != "ACTIVE":
        fail("ERR_INVALID_REQUEST", "The owning retailer is not ACTIVE.")
    if order["ebt_requested"] and not retailer["ebt_snap_enabled"]:
        fail("ERR_EBT_NOT_ENABLED", "The retailer does not accept EBT SNAP tender.")
    # The three snapshot fields are re-taken from the catalog at placement.
    for line in lines:
        item = derive.item_of(line)
        if item is None:
            continue
        changed = (
            line["unit_price_cents_snapshot"] != item["catalog_price_cents"]
            or line["in_store_price_cents_snapshot"] != item["in_store_price_cents"]
            or line["ebt_eligible_snapshot"] != item["is_ebt_eligible"]
        )
        line["unit_price_cents_snapshot"] = item["catalog_price_cents"]
        line["in_store_price_cents_snapshot"] = item["in_store_price_cents"]
        line["ebt_eligible_snapshot"] = item["is_ebt_eligible"]
        touch_if(line, changed)
    derive.run_estimate_authorization(order)
    order["tip_original_cents"] = int(order["tip_amount_cents"])
    order["fulfillment_status"] = "PLACED"
    order["payment_status"] = "AUTHORIZED"
    touch(order)
    return ok(serializers.order(order))


@bp.post("/orders/<oid>/tip-adjustments")
def adjust_tip(oid):
    require_roles("Customer")
    order = lookup.order(oid)
    require_owner(order["customer_id"])
    body = body_json()
    tip = req_int(body, "tip_amount_cents", minimum=0, maximum=20000)
    expected = req_int(body, "expected_order_version")
    if expected != order["version"]:
        fail("ERR_STALE_ORDER_VERSION", "The order has changed since it was last read.")
    if order["fulfillment_status"] != "DELIVERED":
        fail("ERR_ORDER_NOT_DELIVERED", "Tips may only be adjusted after delivery.")
    closes_at = order["tip_window_closes_at"]
    if closes_at is None or now() >= closes_at:
        fail("ERR_TIP_WINDOW_CLOSED", "The tip adjustment window has closed.")
    if int(order["tip_adjustment_count"]) >= calc.TIP_ADJUSTMENT_MAX_COUNT:
        fail("ERR_TIP_ADJUSTMENT_LIMIT", "The tip adjustment limit has been reached.")
    order["tip_amount_cents"] = tip
    order["tip_adjustment_count"] = int(order["tip_adjustment_count"]) + 1
    touch(order)
    batch = derive.batch_of_order(order["id"])
    if batch is not None:
        payout = derive.payout_of_batch(batch["id"])
        if payout is not None and payout["status"] == "PROVISIONAL":
            derive.apply_payout(payout, batch, "PROVISIONAL")
    return ok(serializers.order(order))


@bp.post("/orders/<oid>/reauthorize")
def reauthorize(oid):
    require_roles("Customer")
    order = lookup.order(oid)
    require_owner(order["customer_id"])
    if order["payment_status"] != "REAUTH_HELD":
        fail("ERR_REAUTH_NOT_REQUIRED", "The order does not require re-authorization.")
    derive.run_estimate_authorization(order)
    order["payment_status"] = "AUTHORIZED"
    touch(order)
    batch = derive.batch_of_order(order["id"])
    if batch is not None:
        derive.recompute_batch_aggregates(batch)
    return ok(serializers.order(order))


@bp.get("/orders/<oid>/parity-disclosure")
def parity_disclosure(oid):
    require_roles("Customer", "CustomerSupport", "DispatchAdmin", "RetailerManager")
    order = lookup.order(oid)
    catalog_total, in_store_total = derive.parity_totals(order)
    markup = catalog_total - in_store_total
    pct = calc.effective_markup_pct(markup, in_store_total)
    retailer = derive.retailer_of(order)
    disclosure_required = bool(
        retailer is not None
        and retailer["parity_disclosure_required"]
        and pct > calc.PARITY_DISCLOSURE_THRESHOLD_PCT
    )
    disclosure_satisfied = True if not disclosure_required else bool(order["parity_disclosed"])
    return ok(
        {
            "order_id": order["id"],
            "catalog_total_cents": catalog_total,
            "in_store_total_cents": in_store_total,
            "markup_cents": markup,
            "effective_markup_pct": float(pct),
            "disclosure_required": disclosure_required,
            "disclosure_satisfied": disclosure_satisfied,
        }
    )
