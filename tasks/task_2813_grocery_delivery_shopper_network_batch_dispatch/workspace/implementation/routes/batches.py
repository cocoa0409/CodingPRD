"""Batch construction, membership, dispatch and the claim gate (PRD 3.4, 3.5)."""
from decimal import Decimal

from flask import Blueprint, g

import calc
import derive
import lookup
import serializers
from auth import require_owner, require_roles
from errors import fail
from response import created, ok
from store import base_row, db, minutes, now, touch
from validation import body_json, opt_enum, query_str, req_int, req_str, req_ts

bp = Blueprint("batches", __name__)

TIERS = ("PROBATION", "STANDARD", "PLATINUM", "DIAMOND")


@bp.post("/batches")
def create_batch():
    require_roles("DispatchAdmin")
    body = body_json()
    service_area_code = req_str(body, "service_area_code")
    start = req_ts(body, "shop_window_start")
    end = req_ts(body, "shop_window_end")
    floor = opt_enum(body, "tier_access_floor", TIERS, default="STANDARD")
    if end <= start:
        fail("ERR_INVALID_REQUEST", "shop_window_end must be strictly after shop_window_start.")
    row = base_row()
    row.update(
        {
            "service_area_code": service_area_code,
            "shop_window_start": start,
            "shop_window_end": end,
            "tier_access_floor": floor,
            "status": "BUILDING",
            "offered_shopper_id": None,
            "claimed_shopper_id": None,
            "declined_shopper_ids": [],
            "offer_expires_at": None,
            "delivery_deadline": None,
            "total_units": 0,
            "total_weight_lb": Decimal("0.0"),
            "total_distance_mi": Decimal("0.0"),
            "store_count": 0,
            "checkout_blocked_count": 0,
            "reassignment_count": 0,
            "abandoned_at": None,
        }
    )
    db.batches[row["id"]] = row
    return created(serializers.batch(row))


@bp.get("/batches/<bid>")
def get_batch(bid):
    require_roles("DispatchAdmin", "Shopper", "CustomerSupport")
    row = lookup.batch(bid)
    return ok(serializers.batch(row))


@bp.get("/batches")
def list_batches():
    require_roles("DispatchAdmin", "Shopper", "CustomerSupport")
    status = query_str("status")
    service_area_code = query_str("service_area_code")
    offered_shopper_id = query_str("offered_shopper_id")
    claimed_shopper_id = query_str("claimed_shopper_id")

    def keep(row):
        if status is not None and row["status"] != status:
            return False
        if service_area_code is not None and row["service_area_code"] != service_area_code:
            return False
        if offered_shopper_id is not None and row["offered_shopper_id"] != offered_shopper_id:
            return False
        if claimed_shopper_id is not None and row["claimed_shopper_id"] != claimed_shopper_id:
            return False
        return True

    return lookup.paged(db.batches, serializers.batch, keep)


@bp.post("/batches/<bid>/orders")
def attach_order(bid):
    require_roles("DispatchAdmin")
    batch = lookup.batch(bid)
    body = body_json()
    order_id = req_str(body, "order_id")
    expected = req_int(body, "expected_batch_version")
    order = lookup.order(order_id)
    if expected != batch["version"]:
        fail("ERR_STALE_BATCH_VERSION", "The batch has changed since it was last read.")
    if derive.membership_of_order(order["id"]) is not None:
        fail("ERR_ORDER_ALREADY_BATCHED", "The order already holds a batch membership row.")
    if order["fulfillment_status"] != "PLACED":
        fail("ERR_ORDER_NOT_PLACED", "Only a PLACED order may be attached to a batch.")
    if batch["status"] != "BUILDING":
        fail("ERR_BATCH_NOT_BUILDING", "Orders may only be attached while the batch is BUILDING.")
    retailer = derive.retailer_of(order)
    if retailer is not None:
        overlapping = derive.retailer_concurrency_count(retailer["id"], batch)
        if overlapping >= int(retailer["concurrent_shopper_cap"]):
            fail(
                "ERR_RETAILER_CONCURRENCY_CAP_REACHED",
                "The retailer's concurrent shopper cap has been reached.",
            )
    highest = 0
    for existing in derive.memberships_of_batch(batch["id"]):
        if existing["sequence_no"] > highest:
            highest = existing["sequence_no"]
    row = base_row(with_version=False)
    row.update(
        {
            "batch_id": batch["id"],
            "order_id": order["id"],
            "sequence_no": highest + 1,
            "units": derive.membership_units(order),
        }
    )
    db.batch_orders[row["id"]] = row
    order["fulfillment_status"] = "IN_BATCH"
    touch(order)
    derive.recompute_batch_aggregates(batch)
    return created(serializers.batch_order(row))


@bp.get("/batches/<bid>/batch-orders")
def list_batch_memberships(bid):
    require_roles("DispatchAdmin", "Shopper", "CustomerSupport")
    batch = lookup.batch(bid)
    rows = [r for r in db.batch_orders.values() if r["batch_id"] == batch["id"]]
    return lookup.paged(rows, serializers.batch_order)


@bp.get("/orders/<oid>/batch-orders")
def list_order_memberships(oid):
    require_roles("DispatchAdmin", "Shopper", "Customer", "CustomerSupport")
    order = lookup.order(oid)
    rows = [r for r in db.batch_orders.values() if r["order_id"] == order["id"]]
    return lookup.paged(rows, serializers.batch_order)


def _offer(batch, winner, first_dispatch):
    batch["offered_shopper_id"] = winner["id"]
    batch["offer_expires_at"] = now() + minutes(calc.OFFER_TTL_MINUTES)
    batch["status"] = "OFFERED"
    touch(batch)


@bp.post("/batches/<bid>/dispatch")
def dispatch(bid):
    require_roles("DispatchAdmin")
    batch = lookup.batch(bid)
    first_dispatch = batch["status"] == "BUILDING"
    re_offer = (
        batch["status"] == "OFFERED"
        and batch["offer_expires_at"] is not None
        and now() >= batch["offer_expires_at"]
    )
    if not first_dispatch and not re_offer:
        fail("ERR_BATCH_NOT_OFFERED", "The batch is not awaiting a first offer or a re-offer.")
    if int(batch["total_units"]) < 1:
        fail("ERR_BATCH_EMPTY", "The batch carries no member order.")
    declined = list(batch["declined_shopper_ids"])
    lapsed = batch["offered_shopper_id"] if re_offer else None
    if lapsed is not None and lapsed not in declined:
        declined.append(lapsed)
    winner = derive.select_shopper(batch, declined)
    if winner is None:
        fail("ERR_NO_ELIGIBLE_SHOPPER", "No shopper is eligible for this batch.")
    if lapsed is not None and lapsed not in batch["declined_shopper_ids"]:
        batch["declined_shopper_ids"].append(lapsed)
    _offer(batch, winner, first_dispatch)
    return ok(serializers.batch(batch))


@bp.post("/batches/<bid>/claim")
def claim(bid):
    require_roles("Shopper")
    batch = lookup.batch(bid)
    if batch["status"] != "OFFERED":
        fail("ERR_BATCH_NOT_OFFERED", "The batch has no standing offer.")
    require_owner(batch["offered_shopper_id"])
    shopper = lookup.shopper(g.user_id)
    if batch["offer_expires_at"] is None or now() >= batch["offer_expires_at"]:
        fail("ERR_OFFER_EXPIRED", "The offer has expired.")
    if derive.window_conflict(batch, shopper):
        fail("ERR_SHOPPER_WINDOW_CONFLICT", "The batch conflicts with a window already held.")
    if shopper["status"] != "ACTIVE":
        fail("ERR_SHOPPER_SUSPENDED", "The shopper is suspended.")
    if calc.TIER_RANK[shopper["tier"]] < calc.TIER_RANK[batch["tier_access_floor"]]:
        fail("ERR_TIER_BELOW_BATCH_FLOOR", "The shopper's tier is below the batch access floor.")
    if int(shopper["committed_units"]) + int(batch["total_units"]) > int(
        shopper["vehicle_capacity_units"]
    ):
        fail("ERR_SHOPPER_CAPACITY_EXCEEDED", "The batch exceeds the shopper's vehicle capacity.")
    batch["status"] = "CLAIMED"
    batch["claimed_shopper_id"] = shopper["id"]
    batch["offered_shopper_id"] = None
    touch(batch)
    derive.recompute_committed_units(shopper)
    touch(shopper)
    return ok(serializers.batch(batch))


@bp.post("/batches/<bid>/start-shopping")
def start_shopping(bid):
    require_roles("Shopper")
    batch = lookup.batch(bid)
    if batch["status"] != "CLAIMED":
        fail("ERR_BATCH_NOT_CLAIMED", "The batch is not claimed.")
    require_owner(batch["claimed_shopper_id"])
    if now() < batch["shop_window_start"]:
        fail("ERR_SHOP_WINDOW_NOT_OPEN", "The shopping window has not opened.")
    batch["status"] = "SHOPPING"
    touch(batch)
    for order in derive.member_orders(batch["id"]):
        if order["fulfillment_status"] == "IN_BATCH":
            order["fulfillment_status"] = "SHOPPING"
            touch(order)
    return ok(serializers.batch(batch))


@bp.post("/batches/<bid>/reassign")
def reassign(bid):
    require_roles("DispatchAdmin")
    batch = lookup.batch(bid)
    if batch["status"] != "ABANDONED":
        fail("ERR_BATCH_NOT_ABANDONED", "Only an abandoned batch may be reassigned.")
    if int(batch["total_units"]) < 1:
        fail("ERR_BATCH_EMPTY", "The batch carries no member order.")
    winner = derive.select_shopper(batch, list(batch["declined_shopper_ids"]))
    if winner is None:
        fail("ERR_NO_ELIGIBLE_SHOPPER", "No shopper is eligible for this batch.")
    batch["reassignment_count"] = int(batch["reassignment_count"]) + 1
    for order in derive.member_orders(batch["id"]):
        if order["fulfillment_status"] == "REASSIGN_PENDING":
            order["fulfillment_status"] = "IN_BATCH"
            touch(order)
    _offer(batch, winner, False)
    return ok(serializers.batch(batch))
