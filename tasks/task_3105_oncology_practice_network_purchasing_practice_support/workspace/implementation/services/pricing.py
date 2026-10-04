"""Pricing resolution and the spend / cost aggregates.

practice_observed_unit_price_cents and network_spend_provisional_and_final from
the scaffold's calculation table (S1.3), plus the draw-unit-cost rate the claim
assembly reads. The three price variants are distinguished by the
`pricing_tier_applied` value committed on each order, because that is the only
place the fallback variant is observable after the fact.
"""

from decimal import Decimal

import db
from services import helpers
from utils import num, parse_iso, utc_now_dt

FALLBACK_TIER_APPLIED = "__LIST_PRICE_FALLBACK__"

# Order statuses that have posted to the trailing-window basis.
REPORTABLE_ORDER_STATUSES = ("SHIPPED", "RECEIVED")


def resolve_unit_price(network, practice, instant, base_price_cents):
    """Resolve the unit price and the tier recorded on the order.

    The base is the DrugProduct's own network_base_price_cents; the agreement
    only nominates the off-invoice discount applied to it.
    """
    from utils import half_up

    agreement = helpers.resolve_active_agreement(practice["id"], instant)
    base = int(base_price_cents or 0)
    if agreement is None:
        return base, FALLBACK_TIER_APPLIED
    if network.get("is_commercial_terms_frozen"):
        # The agreement stays ACTIVE; the price is the list price because the
        # intended discount is deliberately not credited in a frozen window.
        return base, agreement.get("tier_level")
    discount = num(agreement.get("discount_pct")) or Decimal(0)
    return half_up(Decimal(base) * (Decimal(1) - discount)), agreement.get("tier_level")


def price_order(order, network, practice, instant, base_price_cents):
    unit_price, tier_applied = resolve_unit_price(
        network, practice, instant, base_price_cents
    )
    order["unit_price_cents"] = unit_price
    order["extended_cost_cents"] = unit_price * int(order.get("quantity_units") or 0)
    order["pricing_tier_applied"] = tier_applied


def is_fallback_priced(order):
    return order.get("pricing_tier_applied") == FALLBACK_TIER_APPLIED


def _in_window(instant, start, end):
    if instant is None:
        return False
    if start is not None and instant < start:
        return False
    if end is not None and not (instant < end):
        return False
    return True


def orders_for_practice(practice_id, statuses=REPORTABLE_ORDER_STATUSES, window=None):
    rows = db.where("purchase_orders", practice_id=practice_id)
    out = []
    for order in rows:
        if order["status"] not in statuses:
            continue
        received_at = parse_iso(order.get("received_at"))
        if received_at is None:
            continue
        if window is not None and not _in_window(received_at, window[0], window[1]):
            continue
        out.append(order)
    return out


def spend_variants(practice_id, drug_ndc_scope, window):
    """Provisional and final network spend over the same rows and window.

    The final variant strips out every order whose pricing came from the
    list-price fallback; both exclude orders that have not posted to the
    trailing-window basis.
    """
    provisional = 0
    fallback = 0
    for order in orders_for_practice(practice_id, window=window):
        if drug_ndc_scope != "ALL":
            product = db.get("drug_products", order.get("drug_product_id"))
            if product is None or product.get("ndc") != drug_ndc_scope:
                continue
        cents = int(order.get("extended_cost_cents") or 0)
        provisional += cents
        if is_fallback_priced(order):
            fallback += cents
    return provisional, provisional - fallback, fallback


def routing_denominator(practice, window):
    """The practice's total drug spend in the window, deliberately including
    products outside the rebate program's scope; when the ACTIVE agreement
    carries the out-of-scope routing rider, ADJUDICATED_PAID billed amounts in
    the window join the denominator."""
    total = 0
    for order in orders_for_practice(practice["id"], window=window):
        total += int(order.get("extended_cost_cents") or 0)
    rider = False
    instant = window[1] if window and window[1] is not None else utc_now_dt()
    agreement = helpers.resolve_active_agreement(practice["id"], instant)
    if agreement is not None and agreement.get("routing_includes_out_of_scope"):
        rider = True
    if rider:
        for claim in db.where("claims", practice_id=practice["id"]):
            if claim["status"] != "ADJUDICATED_PAID":
                continue
            settled = parse_iso(claim.get("updated_at")) or parse_iso(claim.get("created_at"))
            if settled is None:
                continue
            if window is not None and not _in_window(settled, window[0], window[1]):
                continue
            total += int(claim.get("billed_amount_cents") or 0)
    return total, rider


def market_share_for(practice, program, window):
    """market_share_pct to four decimal places; a zero denominator yields zero."""
    from utils import ratio4

    provisional, final, fallback = spend_variants(
        practice["id"], program.get("drug_ndc_scope") or "ALL", window
    )
    denominator, _ = routing_denominator(practice, window)
    if denominator == 0:
        return 0.0
    return ratio4(Decimal(provisional) / Decimal(denominator))


def draw_unit_cost_cents(practice_id, drug_product_id):
    """Quantity-weighted average acquisition cost per unit across every
    InventoryLot of the practice for the drug, in integer cents (half up)."""
    from utils import half_up

    lots = db.where("inventory_lots", practice_id=practice_id, drug_product_id=drug_product_id)
    total_qty = 0
    total_cost = 0
    for lot in lots:
        qty = int(lot.get("quantity_received") or 0)
        if qty <= 0:
            continue
        total_qty += qty
        total_cost += qty * int(lot.get("acquisition_cost_cents_per_unit") or 0)
    if total_qty == 0:
        return 0
    return half_up(Decimal(total_cost) / Decimal(total_qty))