"""Position bookkeeping and the derived price of a share class."""
from decimal import Decimal

import db
from constants import NAV_PRICED
from money import ZERO, q2, q3, q4


def find(account_id, share_class_id):
    for position in db.store.positions.values():
        if position["account_id"] == account_id and position["share_class_id"] == share_class_id:
            return position
    return None


def ensure(account_id, share_class_id):
    position = find(account_id, share_class_id)
    if position is not None:
        return position
    return db.create(db.store.positions, {
        "account_id": account_id,
        "share_class_id": share_class_id,
        "shares": Decimal("0.000"),
        "cost_basis_amount": Decimal("0.00"),
        "reinvested_shares": Decimal("0.000"),
        "first_purchase_date": None,
        "current_roa_tier_pct": Decimal("0.0000"),
    })


def for_account(account_id):
    return [p for p in db.store.positions.values() if p["account_id"] == account_id]


def for_class(share_class_id):
    return [p for p in db.store.positions.values() if p["share_class_id"] == share_class_id]


def latest_price(share_class_id, on_date=None):
    """nav_per_share of the FINAL/CORRECTED record with the greatest valuation_date
    (optionally on or before on_date, an ISO date string); ties broken by created_at."""
    best = None
    for record in db.store.nav_records.values():
        if record["share_class_id"] != share_class_id:
            continue
        if record["status"] not in NAV_PRICED:
            continue
        if on_date is not None and record["valuation_date"] > on_date:
            continue
        if best is None:
            best = record
            continue
        if record["valuation_date"] > best["valuation_date"]:
            best = record
        elif record["valuation_date"] == best["valuation_date"] and record["created_at"] < best["created_at"]:
            best = record
    return best["nav_per_share"] if best is not None else None


def avg_cost_per_share(position):
    shares = position["shares"]
    if shares is None or shares == 0:
        return Decimal("0.0000")
    return q4(position["cost_basis_amount"] / shares)


def market_value_amount(position):
    price = latest_price(position["share_class_id"])
    if price is None:
        return Decimal("0.00")
    return q2(position["shares"] * price)


def recompute_class_shares(share_class_id):
    share_class = db.store.share_classes.get(share_class_id)
    if share_class is None:
        return
    total = ZERO
    for position in db.store.positions.values():
        if position["share_class_id"] == share_class_id:
            total += position["shares"]
    db.set_field(share_class, "total_shares_outstanding", q3(total))


def append_ledger_entry(position, trade_id, share_delta, entry_reason, effective_date):
    """Append-only ledger row.  A zero delta is never written."""
    if share_delta == 0:
        return None
    return db.create(db.store.ledger_entries, {
        "position_id": position["id"],
        "trade_id": trade_id,
        "share_delta": q3(share_delta),
        "entry_reason": entry_reason,
        "effective_date": effective_date,
        "resulting_share_balance": q3(position["shares"]),
    }, versioned=False)


def move_shares(position, delta):
    db.set_field(position, "shares", q3(position["shares"] + delta))
