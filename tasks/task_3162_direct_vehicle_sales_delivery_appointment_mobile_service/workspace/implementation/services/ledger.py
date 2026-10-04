"""The append-only fee ledger and the derived balances it drives (PRD 2.8)."""

from db import DB, new_id
from errors import fmt
from repository import find

ORDER_FEE_TYPES = ("ORDER_FEE_PAYMENT",)


def write_entry(order_id, entry_type, amount_cents, reason_code):
    order = find("order", order_id)
    buyer_id = order["buyer_id"] if order is not None else None
    entry = {
        "id": new_id(),
        "order_id": order_id,
        "buyer_id": buyer_id,
        "entry_type": entry_type,
        "amount_cents": amount_cents,
        "reason_code": reason_code,
        "created_at": fmt(DB.now),
    }
    DB.ledger[entry["id"]] = entry
    refresh_balances(order_id, buyer_id)
    return entry


def refresh_balances(order_id, buyer_id=None):
    """Recomputed on every ledger mutation and on every compensating reversal."""
    order = find("order", order_id)
    if order is not None:
        order["order_fee_paid_cents"] = sum(
            entry["amount_cents"] for entry in DB.ledger.values()
            if entry["order_id"] == order_id and entry["entry_type"] in ORDER_FEE_TYPES)
        from services.calculation import order_total_due_cents
        order["order_total_due_cents"] = order_total_due_cents(order)
        refresh_posture(order)
    if buyer_id is None and order is not None:
        buyer_id = order["buyer_id"]
    buyer = find("buyer", buyer_id)
    if buyer is not None:
        buyer["order_credit_balance_cents"] = sum(
            entry["amount_cents"] for entry in DB.ledger.values()
            if entry["buyer_id"] == buyer_id)


def refresh_posture(order):
    from services.calculation import delivery_readiness_posture
    order["delivery_readiness_posture"] = delivery_readiness_posture(order)


def entries_for(order_id=None, buyer_id=None, entry_type=None):
    rows = list(DB.ledger.values())
    if order_id is not None:
        rows = [r for r in rows if r["order_id"] == order_id]
    if buyer_id is not None:
        rows = [r for r in rows if r["buyer_id"] == buyer_id]
    if entry_type:
        rows = [r for r in rows if r["entry_type"] == entry_type]
    return sorted(rows, key=lambda r: r["created_at"])