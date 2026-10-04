"""Secondary market: transfer orders (§3.7)."""
from envelope import ApiError, invalid_request, invalid_state, not_found, forbidden, stale
from catalog import HOLD_LAPSE_DAYS
from store import DB, parse_dt, to_ms, add_days
from models import make_transfer_order, insert_index
from svc_common import (body, require, as_int, recompute_offering_shares,
                        investor_holding)
from svc_lots import suspend_pass_through
from calc import share_cap, minimum_secondary_lot, day_gap
import views


def _offering(offering_id):
    row = DB.offerings.get(offering_id)
    if row is None:
        raise not_found("Offering %s does not exist." % offering_id)
    return row


def _occ(data, offering):
    expected = as_int(data, "expected_offering_version")
    if expected is not None and int(expected) != int(offering["version"]):
        raise stale("expected_offering_version does not match the offering's version.")


def _open_order_count(offering_id, exclude_id=None):
    return sum(1 for o in DB.transfer_orders.values()
               if o["offering_id"] == offering_id and o["status"] == "OPEN"
               and o["id"] != exclude_id)


def post_transfer_order(actor):
    data = body()
    require(data, ["offering_id", "seller_id", "shares", "limit_price_cents"])
    as_int(data, "shares", minimum=1)
    as_int(data, "limit_price_cents", minimum=0)
    offering = _offering(data.get("offering_id"))
    seller = DB.investors.get(data.get("seller_id"))
    if seller is None:
        raise not_found("Investor %s does not exist." % data.get("seller_id"))
    if actor.role == "Investor" and actor.user_id != seller["id"]:
        raise forbidden("An investor may only post its own order.")
    if offering["status"] not in ("ALLOCATED", "HELD"):
        raise invalid_state("The offering is not ALLOCATED or HELD.")
    row = make_transfer_order(offering, data, actor.user_id)
    suspend_pass_through(offering["id"])
    return views.transfer_order(row), 201


def get_transfer_order(order_id):
    row = DB.transfer_orders.get(order_id)
    if row is None:
        raise not_found("TransferOrder %s does not exist." % order_id)
    return views.transfer_order(row)


def list_transfer_orders(query, actor):
    rows = DB.ordered("transfer_orders")
    for field in ("offering_id", "seller_id", "buyer_id", "status"):
        value = query.get(field)
        if value:
            rows = [r for r in rows if r.get(field) == value]
    if actor.role == "Investor":
        rows = [r for r in rows
                if r.get("seller_id") == actor.user_id
                or r.get("buyer_id") == actor.user_id]
    return rows


def accept_transfer(order_id, actor):
    order = DB.transfer_orders.get(order_id)
    if order is None:
        raise not_found("TransferOrder %s does not exist." % order_id)
    if order["status"] != "OPEN":
        raise invalid_state("Only an OPEN order can be accepted.")
    data = body()
    require(data, ["buyer_id", "bid_price_cents"])
    bid = as_int(data, "bid_price_cents", minimum=0)
    offering = _offering(order["offering_id"])
    buyer = DB.investors.get(data.get("buyer_id"))
    if buyer is None:
        raise not_found("Investor %s does not exist." % data.get("buyer_id"))
    if buyer["id"] == order["seller_id"]:
        raise invalid_state("The buyer must not be the seller.")

    minimum = minimum_secondary_lot(offering["total_shares"],
                                    offering["liquidity_ratio_bps"])
    if int(order["shares"]) < minimum:
        raise ApiError("ERR_LIQUIDITY_WINDOW_LOCKED",
                       "The order is below the offering's minimum secondary lot.")

    held = investor_holding(offering["id"], buyer["id"])
    if held < 1:
        raise invalid_state("The buyer holds no accepted share of this offering.")
    if offering["status"] != "ALLOCATED":
        raise invalid_state("The offering is not ALLOCATED.")
    restriction = parse_dt(buyer.get("restriction_until"))
    if restriction is not None and parse_dt(DB.now()) < restriction:
        raise invalid_state("The buyer is still inside its transfer restriction.")
    if offering.get("holding_period_end_at") is not None:
        raise ApiError("ERR_HOLD_PERIOD_ACTIVE",
                       "The holding clock has started; the secondary market is closed.")
    if int(bid) < int(order["limit_price_cents"]):
        raise invalid_state("bid_price_cents is below the resting limit.")

    if actor.role == "Investor" and actor.user_id != buyer["id"]:
        raise forbidden("An investor may only accept as itself.")

    cap = share_cap(offering["total_shares"], offering["registration_cap_pct"])
    projected = held + int(order["shares"])
    # the empty-queue fallback: when no other order rests on the book this
    # accepting counterparty is not subject to the projection cap
    empty_queue = _open_order_count(offering["id"], order["id"]) == 0
    if projected > cap and not empty_queue:
        raise ApiError("ERR_OFFERING_FULL",
                       "The acceptance would push the buyer above its registration cap.")

    now = to_ms(DB.now())
    order["status"] = "MATCHED"
    order["buyer_id"] = buyer["id"]
    order["bid_price_cents"] = int(bid)
    order["execution_price_cents"] = int(order["limit_price_cents"])
    order["updated_at"] = now
    order["version"] = int(order.get("version") or 1) + 1
    return views.transfer_order(order)


def repost_transfer(order_id, actor):
    order = DB.transfer_orders.get(order_id)
    if order is None:
        raise not_found("TransferOrder %s does not exist." % order_id)
    state = order["status"]
    if state not in ("MATCHED", "LAPSED"):
        raise invalid_state("Only a MATCHED or LAPSED order can be reposted.")
    if state == "LAPSED":
        if actor.role == "Investor" and actor.user_id != order["seller_id"]:
            raise forbidden("Only the order's seller may repost a lapsed order.")
    now = to_ms(DB.now())
    order["status"] = "OPEN"
    order["buyer_id"] = None
    order["bid_price_cents"] = None
    order["execution_price_cents"] = None
    order["updated_at"] = now
    order["version"] = int(order.get("version") or 1) + 1
    suspend_pass_through(order["offering_id"])
    return views.transfer_order(order)


def approve_transfer(order_id):
    order = DB.transfer_orders.get(order_id)
    if order is None:
        raise not_found("TransferOrder %s does not exist." % order_id)
    data = body()
    offering = _offering(order["offering_id"])
    if order["status"] not in ("OPEN", "MATCHED"):
        raise invalid_state("Only an OPEN or MATCHED order can be settled.")
    if order.get("buyer_id") is None:
        raise invalid_state("The order has no bound buyer.")
    if order.get("created_by_user_id") == _actor_user():
        raise invalid_state("The approving officer must differ from the posting officer.")
    if offering.get("holding_period_end_at") is not None:
        raise ApiError("ERR_HOLD_PERIOD_ACTIVE",
                       "The holding clock has started; the secondary market is closed.")
    _occ(data, offering)

    price = (int(order["limit_price_cents"]) if order["status"] == "MATCHED"
             else max(int(order.get("bid_price_cents") or 0),
                      int(order["limit_price_cents"])))
    now = to_ms(DB.now())
    shares = int(order["shares"])
    seller_id = order["seller_id"]
    buyer_id = order["buyer_id"]

    seller_subs = [s for s in DB.subscriptions.values()
                   if s["offering_id"] == offering["id"] and s["investor_id"] == seller_id
                   and int(s.get("accepted_shares") or 0) > 0]
    seller_subs.sort(key=lambda s: (s.get("created_at") or "",
                                    s.get("created_at_seq") or 0))
    remaining = shares
    for sub in seller_subs:
        if remaining <= 0:
            break
        take = min(remaining, int(sub["accepted_shares"]))
        sub["accepted_shares"] = int(sub["accepted_shares"]) - take
        sub["amount_due_cents"] = int(sub["accepted_shares"]) * int(offering["price_per_share_cents"])
        sub["updated_at"] = now
        sub["version"] = int(sub.get("version") or 1) + 1
        remaining -= take
    if remaining > 0:
        # the seller's ledger cannot cover the order: refuse wholesale
        raise invalid_state("The seller does not hold enough accepted shares.")

    buyer_subs = [s for s in DB.subscriptions.values()
                  if s["offering_id"] == offering["id"] and s["investor_id"] == buyer_id
                  and int(s.get("accepted_shares") or 0) > 0]
    buyer_subs.sort(key=lambda s: (s.get("created_at") or "",
                                   s.get("created_at_seq") or 0))
    if buyer_subs:
        target = buyer_subs[0]
        target["accepted_shares"] = int(target["accepted_shares"]) + shares
        target["amount_due_cents"] = int(target["accepted_shares"]) * int(offering["price_per_share_cents"])
        target["updated_at"] = now
        target["version"] = int(target.get("version") or 1) + 1
    else:
        from models import make_subscription
        top_up = make_subscription(offering, {"investor_id": buyer_id})
        top_up["requested_shares"] = shares
        top_up["accepted_shares"] = shares
        top_up["amount_due_cents"] = shares * int(offering["price_per_share_cents"])
        top_up["status"] = "SUBSCRIBED"

    order["status"] = "EXECUTED"
    order["execution_price_cents"] = price
    order["updated_at"] = now
    order["version"] = int(order.get("version") or 1) + 1
    offering["updated_at"] = now
    offering["version"] = int(offering["version"]) + 1
    recompute_offering_shares(offering)
    return views.transfer_order(order)


def cancel_transfer(order_id, actor):
    order = DB.transfer_orders.get(order_id)
    if order is None:
        raise not_found("TransferOrder %s does not exist." % order_id)
    state = order["status"]
    if state not in ("OPEN", "MATCHED"):
        raise invalid_state("Only an OPEN or MATCHED order can be cancelled.")
    if actor.role == "Investor":
        if actor.user_id != order["seller_id"]:
            raise forbidden("An investor may only cancel its own order.")
    now = to_ms(DB.now())
    order["status"] = "CANCELLED"
    order["updated_at"] = now
    order["version"] = int(order.get("version") or 1) + 1
    suspend_pass_through(order["offering_id"])
    return views.transfer_order(order)


def _actor_user():
    from flask import g
    return getattr(g, "user_id", None)