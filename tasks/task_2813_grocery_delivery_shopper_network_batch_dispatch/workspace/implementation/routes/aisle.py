"""In-aisle execution: picks, weights and substitutions (PRD 3.6)."""
from decimal import Decimal

from flask import Blueprint

import calc
import derive
import lookup
import serializers
from auth import require_owner, require_roles
from errors import fail
from response import created, ok
from store import base_row, db, minutes, now, touch
from validation import body_json, opt_int, opt_num, query_str, req_str

bp = Blueprint("aisle", __name__)


def proposed_line_cents(item, proposed_qty, proposed_weight_lb):
    if item["pricing_unit"] == "PER_LB":
        return calc.cents(calc.dec(item["catalog_price_cents"]) * calc.dec(proposed_weight_lb))
    return int(item["catalog_price_cents"]) * int(proposed_qty)


@bp.post("/order-lines/<lid>/pick")
def pick_line(lid):
    require_roles("Shopper")
    line = lookup.order_line(lid)
    batch = derive.batch_of_order(line["order_id"])
    if batch is None or batch["status"] != "SHOPPING":
        fail("ERR_BATCH_NOT_SHOPPING", "The owning batch is not being shopped.")
    require_owner(batch["claimed_shopper_id"])
    body = body_json()
    picked_qty = opt_int(body, "picked_qty", default=None, minimum=1, maximum=50)
    final_weight = opt_num(body, "final_weight_lb", default=None, minimum=0)
    if line["status"] != "REQUESTED":
        fail("ERR_LINE_NOT_PICKABLE", "The line is not pickable.")
    item = derive.item_of(line)
    if item is None or item["availability"] != "IN_STOCK":
        fail("ERR_ITEM_OUT_OF_STOCK", "The catalog item is out of stock.")
    if item["pricing_unit"] == "PER_LB":
        weight = final_weight if final_weight is not None else calc.dec(line["requested_weight_lb"])
        if not calc.weight_variance_ok(weight, line["requested_weight_lb"]):
            fail("ERR_WEIGHT_VARIANCE_EXCEEDED", "The scanned weight exceeds the 20% tolerance.")
        line["final_weight_lb"] = calc.one_dp(weight)
    else:
        line["picked_qty"] = picked_qty if picked_qty is not None else int(line["requested_qty"])
    line["status"] = "PICKED"
    line["final_price_cents"] = derive.line_final_cents(line)
    touch(line)
    derive.recompute_batch_aggregates(batch)
    return ok(serializers.order_line(line))


@bp.post("/replacement-requests")
def create_replacement():
    require_roles("Shopper")
    body = body_json()
    batch_id = req_str(body, "batch_id")
    order_line_id = req_str(body, "order_line_id")
    proposed_item_id = req_str(body, "proposed_catalog_item_id")
    proposed_qty = opt_int(body, "proposed_qty", default=1, minimum=1, maximum=50)
    proposed_weight = opt_num(body, "proposed_weight_lb", default=None, minimum=0)
    if proposed_weight is None:
        proposed_weight = Decimal("0")
    batch = lookup.batch(batch_id)
    line = lookup.order_line(order_line_id)
    proposed = lookup.catalog_item(proposed_item_id)
    if batch["status"] != "SHOPPING":
        fail("ERR_BATCH_NOT_SHOPPING", "The batch is not being shopped.")
    require_owner(batch["claimed_shopper_id"])
    if line["status"] != "REQUESTED":
        fail("ERR_LINE_NOT_PICKABLE", "The line is not pickable.")
    order = derive.order_of(line)
    if order is None or proposed["retailer_id"] != order["retailer_id"]:
        fail("ERR_REPLACEMENT_RETAILER_MISMATCH", "The substitute belongs to another retailer.")
    if (
        line["ebt_eligible_snapshot"]
        and int(order["authorized_ebt_cents"]) > 0
        and not proposed["is_ebt_eligible"]
    ):
        fail("ERR_EBT_INELIGIBLE_REPLACEMENT", "Benefit funds may not migrate to an ineligible item.")
    row = base_row()
    row.update(
        {
            "batch_id": batch["id"],
            "order_line_id": line["id"],
            "proposed_catalog_item_id": proposed["id"],
            "proposed_qty": proposed_qty,
            "proposed_weight_lb": calc.one_dp(proposed_weight),
            "price_delta_cents": proposed_line_cents(proposed, proposed_qty, proposed_weight)
            - derive.line_estimate_cents(line),
            "expires_at": now() + minutes(calc.REPLACEMENT_TTL_MINUTES),
            "status": "PENDING",
            "resolution_effect": "NONE",
        }
    )
    db.replacements[row["id"]] = row
    line["status"] = "REPLACEMENT_PENDING"
    touch(line)
    return created(serializers.replacement_request(row))


@bp.get("/replacement-requests/<rid>")
def get_replacement(rid):
    require_roles("Shopper", "Customer", "DispatchAdmin", "CustomerSupport")
    row = lookup.replacement(rid)
    return ok(serializers.replacement_request(row))


@bp.get("/replacement-requests")
def list_replacements():
    require_roles("Shopper", "Customer", "DispatchAdmin", "CustomerSupport")
    batch_id = query_str("batch_id")
    order_line_id = query_str("order_line_id")
    proposed_item_id = query_str("proposed_catalog_item_id")
    status = query_str("status")

    def keep(row):
        if batch_id is not None and row["batch_id"] != batch_id:
            return False
        if order_line_id is not None and row["order_line_id"] != order_line_id:
            return False
        if proposed_item_id is not None and row["proposed_catalog_item_id"] != proposed_item_id:
            return False
        if status is not None and row["status"] != status:
            return False
        return True

    return lookup.paged(db.replacements, serializers.replacement_request, keep)


@bp.post("/replacement-requests/<rid>/approve")
def approve_replacement(rid):
    require_roles("Customer")
    req = lookup.replacement(rid)
    line = db.order_lines.get(req["order_line_id"])
    order = derive.order_of(line) if line is not None else None
    require_owner(order["customer_id"] if order is not None else None)
    if req["status"] != "PENDING":
        fail("ERR_REPLACEMENT_NOT_PENDING", "The replacement request is not pending.")
    if req["expires_at"] is None or now() >= req["expires_at"]:
        fail("ERR_REPLACEMENT_NOT_PENDING", "The replacement request has lapsed.")
    req["status"] = "APPROVED"
    req["resolution_effect"] = "LINE_REPLACED"
    touch(req)
    proposed = db.catalog_items.get(req["proposed_catalog_item_id"])
    # Link 1: the line is repointed at the substitute and re-priced.
    line["catalog_item_id"] = proposed["id"]
    line["unit_price_cents_snapshot"] = proposed["catalog_price_cents"]
    line["in_store_price_cents_snapshot"] = proposed["in_store_price_cents"]
    line["ebt_eligible_snapshot"] = proposed["is_ebt_eligible"]
    if proposed["pricing_unit"] == "PER_LB":
        line["final_weight_lb"] = calc.one_dp(req["proposed_weight_lb"])
        line["picked_qty"] = 0
    else:
        line["picked_qty"] = int(req["proposed_qty"])
        line["final_weight_lb"] = Decimal("0")
    line["status"] = "REPLACED"
    line["final_price_cents"] = derive.line_final_cents(line)
    touch(line)
    # Link 2: the order is re-estimated and may fall into a re-authorization hold.
    derive.recompute_estimated_subtotal(order)
    projected = (
        int(order["estimated_subtotal_cents"])
        + calc.SERVICE_FEE_CENTS
        + int(order["tip_amount_cents"])
    )
    if projected > int(order["authorization_ceiling_cents"]) and order["payment_status"] == "AUTHORIZED":
        order["payment_status"] = "REAUTH_HELD"
    touch(order)
    # Link 3: the batch's blocked-order counter is re-derived.
    batch = derive.batch_of_order(order["id"])
    if batch is not None:
        derive.recompute_batch_aggregates(batch)
    return ok(serializers.replacement_request(req))


@bp.post("/replacement-requests/<rid>/reject")
def reject_replacement(rid):
    require_roles("Customer")
    req = lookup.replacement(rid)
    line = db.order_lines.get(req["order_line_id"])
    order = derive.order_of(line) if line is not None else None
    require_owner(order["customer_id"] if order is not None else None)
    if req["status"] != "PENDING":
        fail("ERR_REPLACEMENT_NOT_PENDING", "The replacement request is not pending.")
    req["status"] = "REJECTED"
    req["resolution_effect"] = "LINE_REFUNDED"
    touch(req)
    refunded = derive.line_estimate_cents(line)
    line["status"] = "REFUNDED"
    line["picked_qty"] = 0
    line["final_weight_lb"] = Decimal("0")
    line["final_price_cents"] = 0
    touch(line)
    order["refunded_cents"] = int(order["refunded_cents"]) + refunded
    derive.recompute_estimated_subtotal(order)
    touch(order)
    batch = derive.batch_of_order(order["id"])
    if batch is not None:
        derive.recompute_batch_aggregates(batch)
    return ok(serializers.replacement_request(req))
