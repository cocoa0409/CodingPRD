"""Fail marking.

Calculation `fail_mark_to_market` (SCAFFOLD section 1.3):
  signed_failed_qty  = SUM over settled LOCKED_IN trades of the participant on
                       the security of (BUY ? +qty : -qty), visited in
                       trade_date ASC then created_at ASC
  price_move_cents   = security.prev_settlement_price_cents - np.failed_at_price_cents
  mark_to_market     = round_half_up(signed_failed_qty * price_move_cents, 0)

The pinned order: the signed quantity sum is formed first, then multiplied once
by the price move, then rounded once.
"""

from decimal import Decimal, ROUND_HALF_UP

from db import db, touch
from lookups import is_settled_trade, trade_sort_key

ONE = Decimal("1")


def signed_failed_quantity(participant_id, security_id):
    trades = [
        t for t in db.trade_submissions.values()
        if t["participant_id"] == participant_id
        and t["security_id"] == security_id
        and is_settled_trade(t)
    ]
    trades.sort(key=trade_sort_key)
    total = 0
    for trade in trades:
        total += trade["quantity"] if trade["side"] == "BUY" else -trade["quantity"]
    return total


def fail_mark_to_market(net_position):
    security = db.securities.get(net_position["security_id"])
    if security is None or net_position["failed_at_price_cents"] is None:
        return 0
    price_move = security["prev_settlement_price_cents"] - net_position["failed_at_price_cents"]
    quantity = signed_failed_quantity(net_position["participant_id"], net_position["security_id"])
    rounded = (Decimal(quantity * price_move)).quantize(ONE, rounding=ROUND_HALF_UP)
    return int(rounded)


def mark_failed(net_position, clock):
    """Stamp the fail ledger fields exactly once and recompute the mark."""
    net_position["dvp_status"] = "FAILED"
    net_position["failed_at"] = clock
    security = db.securities.get(net_position["security_id"])
    net_position["failed_at_price_cents"] = (
        security["prev_settlement_price_cents"] if security is not None else 0
    )
    net_position["mark_to_market_cents"] = fail_mark_to_market(net_position)
    touch(net_position)
    return net_position


def recompute_marks(net_positions):
    for net_position in net_positions:
        if net_position["dvp_status"] == "FAILED":
            net_position["mark_to_market_cents"] = fail_mark_to_market(net_position)
            touch(net_position)