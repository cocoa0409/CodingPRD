"""Money: line pricing variants, the charge waterfall, surge, transport cost."""

from decimal import Decimal
from fractions import Fraction

import db as store
from db import db
from services import derive


# --------------------------------------------------------------------------
# Line pricing (PRD 3.2)
# --------------------------------------------------------------------------
def provisional_price(sku, ordered_qty):
    if not sku["is_catchweight"]:
        return sku["unit_price_cents"] * ordered_qty
    nominal_total = sku["nominal_weight_grams"] * ordered_qty
    return store.round_cents(
        Decimal(sku["price_per_kg_cents"]) * Decimal(nominal_total)
        / Decimal(store.GRAMS_PER_KG)
    )


def final_price_from_pick(sku, picked_units, actual_weight_grams):
    if not sku["is_catchweight"]:
        return sku["unit_price_cents"] * picked_units
    return store.round_cents(
        Decimal(sku["price_per_kg_cents"]) * Decimal(actual_weight_grams)
        / Decimal(store.GRAMS_PER_KG)
    )


def final_price_from_substitution(substitute_sku, ordered_qty):
    return substitute_sku["unit_price_cents"] * ordered_qty


def deviation_ratio(actual_grams, nominal_total_grams):
    return Fraction(abs(actual_grams - nominal_total_grams), nominal_total_grams)


# --------------------------------------------------------------------------
# The order charge waterfall (PRD 3.2) -- steps 1,2,3,4, never re-entered
# --------------------------------------------------------------------------
def run_waterfall(order, apply_billing=True):
    # Step 1 -- merchandise subtotal
    subtotal = 0
    for line in derive.order_lines(order):
        if line["line_status"] not in ("PENDING", "PICKED"):
            continue
        if line["final_line_price_cents"] is not None:
            subtotal += line["final_line_price_cents"]
        else:
            subtotal += line["provisional_line_price_cents"]
    order["merchandise_subtotal_cents"] = subtotal

    # Step 2 -- delivery fee
    booking = derive.live_booking_of(order)
    if booking is None:
        order["delivery_fee_cents"] = None
        order["loyalty_discount_cents"] = None
        _apply_total(order, None, apply_billing)
        return
    slot = db.slots[booking["delivery_slot_id"]]
    route = db.routes[slot["route_id"]]
    fee = store.round_cents(
        Decimal(route["base_delivery_fee_cents"]) * booking["surge_multiplier_at_booking"]
    )
    if subtotal >= store.FREE_DELIVERY_THRESHOLD_CENTS:
        fee = 0
    order["delivery_fee_cents"] = fee

    # Step 3 -- loyalty discount
    pre_discount = subtotal + fee
    account = db.accounts.get(order["customer_id"])
    tier = account["loyalty_tier"] if account else "BASIC"
    rate = Decimal("0")
    if tier == "PLUS":
        if pre_discount >= store.LOYALTY_TIER_THRESHOLD_CENTS:
            rate = Decimal("0.05")
    elif tier == "PREMIER":
        if pre_discount >= store.LOYALTY_TIER_THRESHOLD_CENTS:
            rate = Decimal("0.10")
        else:
            rate = Decimal("0.05")
    discount = store.round_cents(Decimal(pre_discount) * rate)
    order["loyalty_discount_cents"] = discount

    # Step 4 -- total
    _apply_total(order, pre_discount - discount, apply_billing)


def _apply_total(order, total, apply_billing):
    previous = order["order_total_cents"]
    order["order_total_cents"] = total
    if not apply_billing:
        return
    if total != previous and order["billing_status"] in ("AUTHORIZED", "ADJUSTED"):
        order["billing_status"] = "ADJUSTED"


def authorize(order):
    """PENDING_AUTH -> AUTHORIZED; only when the waterfall produced a total."""
    if order["billing_status"] == "PENDING_AUTH" and order["order_total_cents"] is not None:
        order["billing_status"] = "AUTHORIZED"
        order["authorized_amount_cents"] = order["order_total_cents"]


# --------------------------------------------------------------------------
# Surge pricing (PRD 3.3)
# --------------------------------------------------------------------------
def recompute_surge(slot):
    effective = slot["total_capacity_units"] - slot["withheld_units"]
    if effective < 1:
        effective = 1
    utilisation = Fraction(slot["held_units"] + slot["confirmed_units"], effective)
    if utilisation >= Fraction(85, 100):
        utilisation_premium = Decimal("0.35")
    elif utilisation >= Fraction(60, 100):
        utilisation_premium = Decimal("0.15")
    else:
        utilisation_premium = Decimal("0.00")

    microseconds = (slot["window_start"] - db.clock) // store.timedelta(microseconds=1)
    lead_hours = microseconds // 3600000000
    if lead_hours < 12:
        lead_premium = Decimal("0.20")
    elif lead_hours < 36:
        lead_premium = Decimal("0.10")
    else:
        lead_premium = Decimal("0.00")

    active_waves = len([
        w for w in db.waves.values()
        if w["route_id"] == slot["route_id"] and w["status"] in ("FORMING", "PICKING")
    ])
    congestion_premium = Decimal("0.05") * min(3, active_waves)

    raw = Decimal("1.00") + utilisation_premium + lead_premium + congestion_premium
    value = store.round_half_up(raw, 2)
    if value < store.SURGE_FLOOR:
        value = store.SURGE_FLOOR
    elif value > store.SURGE_CEILING:
        value = store.SURGE_CEILING
    slot["surge_multiplier"] = value


def recompute_surge_for_route(route_id):
    for slot in db.slots.values():
        if slot["route_id"] == route_id:
            recompute_surge(slot)


def recompute_surge_all():
    for slot in db.slots.values():
        recompute_surge(slot)


def quoted_fee(route, multiplier):
    return store.round_cents(Decimal(route["base_delivery_fee_cents"]) * multiplier)


# --------------------------------------------------------------------------
# Wave transport cost (PRD 3.7)
# --------------------------------------------------------------------------
def wave_transport_cost(wave, stop_orders):
    route = db.routes[wave["route_id"]]
    total = 0
    for order in stop_orders:
        total += store.round_cents(
            Decimal(route["per_km_cost_cents"]) * order["stop_distance_km"]
        )
    return total
