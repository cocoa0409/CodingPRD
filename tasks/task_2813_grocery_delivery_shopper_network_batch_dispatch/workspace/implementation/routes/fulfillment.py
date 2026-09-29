"""Checkout, delivery, payouts, abandonment and the logical clock (PRD 3.7-3.9)."""
from flask import Blueprint

import calc
import derive
import lookup
import serializers
from auth import require_owner, require_roles
from errors import fail
from response import ok
from store import all_rows, db, hours, now, set_clock, touch
from validation import body_json, opt_str, query_str, req_ts

bp = Blueprint("fulfillment", __name__)


def _member_line_pairs(batch):
    pairs = []
    for order in derive.member_orders(batch["id"]):
        for line in derive.lines_of(order["id"]):
            pairs.append((order, line))
    return pairs


@bp.post("/batches/<bid>/checkout")
def checkout(bid):
    require_roles("Shopper")
    batch = lookup.batch(bid)
    if batch["status"] != "SHOPPING":
        fail("ERR_BATCH_NOT_SHOPPING", "The batch is not being shopped.")
    require_owner(batch["claimed_shopper_id"])
    orders = derive.member_orders(batch["id"])
    for order, line in _member_line_pairs(batch):
        if line["status"] == "REQUESTED":
            fail("ERR_LINE_NOT_PICKABLE", "Every member line must be resolved before checkout.")
    if int(batch["checkout_blocked_count"]) != 0:
        fail("ERR_ORDER_PAYMENT_HELD", "A member order is awaiting re-authorization.")

    member_line_ids = set(line["id"] for _, line in _member_line_pairs(batch))
    # Step 1 - the sweep comes first.
    swept_a_line = False
    for req in all_rows(db.replacements):
        if req["status"] != "PENDING" or req["order_line_id"] not in member_line_ids:
            continue
        req["status"] = "EXPIRED"
        req["resolution_effect"] = "LINE_REFUNDED"
        touch(req)
        line = db.order_lines.get(req["order_line_id"])
        if line is not None and line["status"] == "REPLACEMENT_PENDING":
            line["status"] = "REFUNDED"
            line["final_price_cents"] = 0
            touch(line)
            swept_a_line = True
    if swept_a_line:
        # PRD 2.10: "Whenever any input to a derived field changes, the field is
        # recomputed from its definition in the same operation." The sweep just
        # moved a member line to REFUNDED, and PRD 3.4 defines total_weight_lb as
        # a sum "skipping every line whose `status` is `REFUNDED`", so the batch's
        # composition must be re-derived before the register settles.
        derive.recompute_batch_aggregates(batch)

    # Step 2 - every member line is re-priced.
    for order in orders:
        for line in derive.lines_of(order["id"]):
            priced = derive.line_final_cents(line)
            if priced != line["final_price_cents"]:
                line["final_price_cents"] = priced
                touch(line)
        derive.recompute_captured_subtotal(order)

    # Step 3 - the split tender, benefit funds first, in membership sequence order.
    for order in orders:
        retailer = derive.retailer_of(order)
        customer = derive.customer_of(order)
        grand_total = (
            int(order["captured_subtotal_cents"])
            + calc.SERVICE_FEE_CENTS
            + int(order["tip_amount_cents"])
        )
        eligible_cart = 0
        for line in derive.lines_of(order["id"]):
            if line["ebt_eligible_snapshot"] and line["status"] in derive.PRICED_LINE_STATUSES:
                eligible_cart += int(line["final_price_cents"])
        if order["ebt_requested"] and retailer is not None and retailer["ebt_snap_enabled"]:
            balance = int(customer["ebt_snap_balance_cents"]) if customer else 0
            ebt = min(balance, eligible_cart, int(order["authorized_ebt_cents"]))
        else:
            ebt = 0
        order["ebt_captured_cents"] = ebt
        order["card_captured_cents"] = grand_total - ebt
        order["payment_status"] = "CAPTURED"
        order["fulfillment_status"] = "CHECKED_OUT"
        touch(order)
        if customer is not None:
            customer["ebt_snap_balance_cents"] = int(customer["ebt_snap_balance_cents"]) - ebt
            derive.recompute_customer_balances(customer)

    batch["status"] = "CHECKED_OUT"
    touch(batch)

    # Step 4 - price-parity accounting is the final step of checkout.
    for order in orders:
        retailer = derive.retailer_of(order)
        if retailer is not None:
            derive.apply_parity_at_checkout(order, retailer)
    return ok(serializers.batch(batch))


@bp.post("/batches/<bid>/deliver")
def deliver(bid):
    require_roles("Shopper")
    batch = lookup.batch(bid)
    if batch["status"] != "CHECKED_OUT":
        fail("ERR_BATCH_NOT_CHECKED_OUT", "The batch has not been checked out.")
    require_owner(batch["claimed_shopper_id"])
    shopper = db.shoppers.get(batch["claimed_shopper_id"])
    batch["status"] = "DELIVERED"
    touch(batch)
    instant = now()
    for order in derive.member_orders(batch["id"]):
        order["fulfillment_status"] = "DELIVERED"
        order["delivered_at"] = instant
        order["tip_original_cents"] = int(order["tip_amount_cents"])
        order["tip_window_closes_at"] = instant + hours(calc.TIP_WINDOW_HOURS)
        touch(order)
    if shopper is not None:
        shopper["_delivered_events"] = int(shopper["_delivered_events"]) + 1
        derive.refresh_shopper(shopper)
        derive.create_payout(batch, shopper["id"], "PROVISIONAL", "PROVISIONAL")
    return ok(serializers.batch(batch))


@bp.post("/batches/<bid>/abandon")
def abandon(bid):
    require_roles("Shopper")
    batch = lookup.batch(bid)
    if batch["status"] not in derive.HELD_BATCH_STATUSES:
        fail("ERR_BATCH_NOT_CLAIMED", "The batch may not be abandoned from its current state.")
    require_owner(batch["claimed_shopper_id"])
    body = body_json()
    opt_str(body, "reason_note", default=None)
    shopper = db.shoppers.get(batch["claimed_shopper_id"])
    if shopper is None:
        fail("ERR_NOT_RESOURCE_OWNER")
    derive.abandon_batch(batch, shopper)
    return ok(serializers.batch(batch))


@bp.post("/batches/<bid>/finalize-payout")
def finalize_payout(bid):
    require_roles("DispatchAdmin")
    batch = lookup.batch(bid)
    payout = None
    for row in all_rows(db.payouts):
        if row["batch_id"] == batch["id"] and row["status"] == "PROVISIONAL":
            payout = row
            break
    if payout is None:
        fail("ERR_PAYOUT_NOT_PROVISIONAL", "No provisional payout exists for this batch.")
    for order in derive.member_orders(batch["id"]):
        closes_at = order["tip_window_closes_at"]
        if closes_at is None or now() < closes_at:
            fail("ERR_PAYOUT_WINDOW_OPEN", "A member order's tip window is still open.")
    derive.apply_payout(payout, batch, "FINAL")
    payout["status"] = "FINAL"
    return ok(serializers.shopper_payout(payout))


@bp.get("/shopper-payouts/<pid>")
def get_payout(pid):
    require_roles("Shopper", "DispatchAdmin", "CustomerSupport")
    row = lookup.payout(pid)
    return ok(serializers.shopper_payout(row))


@bp.get("/shopper-payouts")
def list_payouts():
    require_roles("Shopper", "DispatchAdmin", "CustomerSupport")
    batch_id = query_str("batch_id")
    shopper_id = query_str("shopper_id")
    status = query_str("status")

    def keep(row):
        if batch_id is not None and row["batch_id"] != batch_id:
            return False
        if shopper_id is not None and row["shopper_id"] != shopper_id:
            return False
        if status is not None and row["status"] != status:
            return False
        return True

    return lookup.paged(db.payouts, serializers.shopper_payout, keep)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    require_roles("DispatchAdmin")
    body = body_json()
    instant = req_ts(body, "current_utc")
    set_clock(instant)
    return ok({})
