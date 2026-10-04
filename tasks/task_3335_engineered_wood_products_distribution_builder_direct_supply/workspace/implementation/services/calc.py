"""Calculation services: waterfall, valuation, pricing, delivery fee, lien deadline."""
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

import db
import errors
import helpers


def round_half_up_int(value):
    """Round Decimal to integer cents, half-up."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_4(value):
    return float(Decimal(value).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


def on_hand_mbf(branch_id):
    total = 0
    for lot in db.inventory_lots.values():
        if lot["branch_id"] == branch_id:
            total += lot["qty_available_mbf"] + lot["qty_reserved_mbf"]
    return total


def capacity_close_waterfall(week):
    """Mutates week in place: internal_grants, committed_*, fill_rate_pct."""
    candidates = [b for b in db.branches.values() if b["replenishment_enabled"]]
    candidates.sort(key=lambda b: (-b["activity_score"], b["created_at"], b["id"]))
    pool = week["internal_alloc_mbf"]
    grants = []
    for b in candidates:
        demand = max(0, b["target_stock_mbf"] - on_hand_mbf(b["id"]))
        grant = min(demand, pool)
        grants.append({"branch_id": b["id"], "granted_mbf": grant})
        pool -= grant
    week["internal_grants"] = grants
    week["committed_internal_mbf"] = week["internal_alloc_mbf"] - pool
    week["committed_market_mbf"] = week["market_alloc_mbf"]
    total = week["total_capacity_mbf"]
    committed = week["committed_internal_mbf"] + week["committed_market_mbf"]
    if total > 0:
        week["fill_rate_pct"] = round_half_up_4(Decimal(committed) / Decimal(total))
    else:
        week["fill_rate_pct"] = 0.0


def branch_valuation(branch_id):
    """Return (fifo_value_cents, weighted_avg_value_cents, delta_cents)."""
    lots = [l for l in db.inventory_lots.values() if l["branch_id"] == branch_id]
    lots.sort(key=lambda l: (l["received_at"], l["created_at"], l["id"]))
    remaining_lots = [
        l for l in lots if (l["qty_available_mbf"] + l["qty_reserved_mbf"]) > 0
    ]
    fifo = sum(
        (l["qty_available_mbf"] + l["qty_reserved_mbf"]) * l["unit_cost_cents_per_mbf"]
        for l in remaining_lots
    )
    # Weighted average over all lots EVER received at the branch
    total_received_qty = sum(l["qty_received_mbf"] for l in lots)
    total_received_cost = sum(
        l["qty_received_mbf"] * l["unit_cost_cents_per_mbf"] for l in lots
    )
    total_remaining = sum(
        l["qty_available_mbf"] + l["qty_reserved_mbf"] for l in remaining_lots
    )
    if total_received_qty > 0:
        pool_avg = Decimal(total_received_cost) / Decimal(total_received_qty)
        wavg = int((pool_avg * Decimal(total_remaining)).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP))
    else:
        wavg = 0
    return fifo, wavg, fifo - wavg


def find_index_entry(product, pricing_week_start):
    """Latest effective_week_start <= pricing_week_start; ties by later created_at."""
    candidates = []
    for e in db.price_index_entries.values():
        if (e["product_family"] == product["product_family"]
                and e["species"] == product["species"]
                and e["effective_week_start"] <= pricing_week_start):
            candidates.append(e)
    if not candidates:
        raise errors.err_price_index_missing()
    candidates.sort(key=lambda e: (e["effective_week_start"], e["created_at"], e["id"]))
    return candidates[-1]


def line_discount_rate(qty_mbf):
    if qty_mbf >= 100:
        return Decimal("0.05")
    if qty_mbf >= 50:
        return Decimal("0.03")
    return Decimal("0")


def price_line(line, pricing_week_start):
    """Return line_total_cents (integer, round-half-up per line)."""
    product = helpers.get_or_404(db.products, line["product_id"])
    if line["price_basis"] == "FIXED":
        unit = line["fixed_unit_price_cents_per_mbf"]
    else:  # INDEX
        entry = find_index_entry(product, pricing_week_start)
        unit = entry["index_price_cents_per_mbf"] + product["index_premium_cents"]
    qty = Decimal(line["qty_mbf"])
    rate = line_discount_rate(line["qty_mbf"])
    raw = qty * Decimal(unit) * (Decimal("1") - rate)
    return int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def price_order(order, pricing_week_start):
    """Recompute order_total_cents for the order's lines at the given week."""
    total = 0
    for line in order["lines"]:
        total += price_line(line, pricing_week_start)
    return total


DELIVERY_FEE_BASE_CENTS = 7501
DELIVERY_FEE_BOOM_CENTS = 4003
PLACEMENT_MULTIPLIER = {
    "STANDARD": Decimal("1.0"),
    "TIGHT_ACCESS": Decimal("1.25"),
    "CRANE_ASSIST": Decimal("1.5"),
}


def delivery_fee_cents(placement_difficulty, boom_required):
    mult = PLACEMENT_MULTIPLIER[placement_difficulty]
    base = (Decimal(DELIVERY_FEE_BASE_CENTS) * mult).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP)
    fee = int(base)
    if boom_required:
        boom = (Decimal(DELIVERY_FEE_BOOM_CENTS) * mult).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP)
        fee += int(boom)
    return fee


def lien_deadline_date(last_completed_delivery_date):
    """last_completed_delivery_date is an ISO date string (YYYY-MM-DD)."""
    d = date.fromisoformat(last_completed_delivery_date[:10])
    return (d + timedelta(days=90)).isoformat()
