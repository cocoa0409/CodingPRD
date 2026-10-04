"""Pure calculation rules from SCAFFOLD.yaml SS1.3.

Each function mirrors one named calculation. Rounding is half up throughout
(Decimal ROUND_HALF_UP); money is integer cents and never float.
"""

import math
from decimal import Decimal, ROUND_HALF_UP

import clock
import db
import serializers
from services.constants import (
    AMBIENT_EXPECTED_C,
    COOLING_BURDEN_HOURS_PER_DEGREE_C,
    DAILY_CADENCE_DAYS,
    DEFERRED_CADENCE_DAYS,
    DEGRADATION_HOURS_PER_DEGREE_C,
    HALF_PRICE_LINE_FACTOR,
    PACK_TARGET_TEMPERATURE_C,
    PACKING_BUFFER_HOURS,
    TRANSIT_BUFFER_DAYS,
    TRANSIT_DAYS,
    UNIT_PRICE_DEFERRAL_THRESHOLD_CENTS,
)


def round_half_up(value, places=0):
    quant = Decimal(1).scaleb(-places)
    return int(Decimal(str(value)).quantize(quant, rounding=ROUND_HALF_UP))


def round_half_up_decimal(value, places=0):
    quant = Decimal(1).scaleb(-places)
    return Decimal(str(value)).quantize(quant, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# cold_pack_units  (SS1.3)
# ---------------------------------------------------------------------------

def cold_pack_units(order_id):
    """Thermal reserve over the order's cold-pack-required lines."""
    quantity_sum = 0
    for line in db.ORDER_LINES.values():
        if line.get("order_id") != order_id:
            continue
        product = db.PRODUCTS.get(line.get("product_id"))
        if product and product.get("cold_pack_required"):
            quantity_sum += int(line.get("quantity", 0) or 0)
    if quantity_sum == 0:
        return 0, 0

    site_load_units = 0
    shipment = next(
        (s for s in db.SHIPMENTS.values() if s.get("order_id") == order_id), None
    )
    if shipment is not None:
        site_load_units = serializers.committed_units(shipment.get("origin_site_id"))

    thermal = (
        PACKING_BUFFER_HOURS
        + max(0.0, AMBIENT_EXPECTED_C - PACK_TARGET_TEMPERATURE_C)
        * DEGRADATION_HOURS_PER_DEGREE_C
        + site_load_units
        * (AMBIENT_EXPECTED_C - PACK_TARGET_TEMPERATURE_C)
        / COOLING_BURDEN_HOURS_PER_DEGREE_C
        + (quantity_sum - 1) / 4.0
    )
    return int(math.ceil(thermal)), quantity_sum


def reservation_units_for(shipment_id):
    """Sum of this shipment's reservation units still in a holding state."""
    return sum(
        int(r.get("units", 0))
        for r in db.COLD_PACK_RESERVATIONS.values()
        if r.get("shipment_id") == shipment_id and r.get("reservation_status") == "HELD"
    )


# ---------------------------------------------------------------------------
# transit_window_dates  (SS1.3)
# ---------------------------------------------------------------------------

def transit_window(dispatch_instant):
    return clock.add_days(dispatch_instant, TRANSIT_DAYS)


def transit_conflicts_blackout(start, end, plan):
    """Buffered half-open test: [start, end+BUFFER) vs [blackout_start, blackout_end)."""
    b_start = plan.get("blackout_start_date")
    b_end = plan.get("blackout_end_date")
    if b_start is None or b_end is None:
        return False
    extended_end = clock.add_days(end, TRANSIT_BUFFER_DAYS)
    return start < b_end and b_start < extended_end


def cadence_window_conflicts(start, end, plan):
    """Unbuffered half-open test: [start, end) vs [blackout_start, blackout_end)."""
    b_start = plan.get("blackout_start_date")
    b_end = plan.get("blackout_end_date")
    if b_start is None or b_end is None:
        return False
    return start < b_end and b_start < end


# ---------------------------------------------------------------------------
# advance_item_cadence  (SS1.3)
# ---------------------------------------------------------------------------

def advance_item_cadence(item):
    """One step per composed order; 14-day cheap items stretch to 28 days."""
    step_days = int(item.get("cadence_days", 0))
    if (
        step_days == DAILY_CADENCE_DAYS
        and int(item.get("unit_price_cents", 0) or 0) < UNIT_PRICE_DEFERRAL_THRESHOLD_CENTS
    ):
        step_days = DEFERRED_CADENCE_DAYS
    item["autoship_item_next_due_date"] = clock.add_days(
        item.get("autoship_item_next_due_date"), step_days
    )
    return item["autoship_item_next_due_date"]


def due_items_for_plan(plan_id, include_blocked=False):
    """Items due at the current logical date, in ascending (due, created_at)."""
    now = clock.current()
    due = []
    for item in db.AUTOSHIP_ITEMS.values():
        if item.get("autoship_plan_id") != plan_id:
            continue
        if item.get("item_status") != "ACTIVE":
            continue
        due_date = item.get("autoship_item_next_due_date")
        if due_date is None or due_date > now:
            continue
        if not include_blocked and item.get("verification_state") == "BLOCKED":
            continue
        due.append(item)
    return sorted(
        due,
        key=lambda i: (i.get("autoship_item_next_due_date"), i.get("created_at") or ""),
    )


# ---------------------------------------------------------------------------
# origin_site_selection  (SS1.3)
# ---------------------------------------------------------------------------

def eligible_sites(destination_state, cold_pack_units_required):
    """ACTIVE sites licensed for the destination with enough headroom, ranked."""
    candidates = []
    for site in db.PHARMACY_SITES.values():
        if site.get("site_status") != "ACTIVE":
            continue
        if destination_state not in (site.get("licensed_states") or []):
            continue
        committed = serializers.committed_units(site["id"])
        if cold_pack_units_required and cold_pack_units_required > 0:
            if int(site.get("cold_pack_capacity_units", 0)) - committed < cold_pack_units_required:
                continue
        candidates.append((committed, site.get("site_code") or "", site))
    candidates.sort(key=lambda t: (t[0], t[1]))
    return [site for _committed, _code, site in candidates]


def select_origin_site(destination_state, cold_pack_units_required):
    ranked = eligible_sites(destination_state, cold_pack_units_required)
    return ranked[0] if ranked else None


# ---------------------------------------------------------------------------
# order_cancellation_settlement  (SS1.3)
# ---------------------------------------------------------------------------

def settlement_for_order(order):
    """Refund components for one CANCELED order; DELIVERED orders contribute 0."""
    if order.get("order_status") != "CANCELED":
        return 0
    lines = [
        line
        for line in db.ORDER_LINES.values()
        if line.get("order_id") == order["id"]
    ]
    lines.sort(key=lambda l: (l.get("line_position", 0), l.get("created_at") or ""))

    component_refund_cents = 0
    cold_index = 0
    for line in lines:
        product = db.PRODUCTS.get(line.get("product_id"))
        if not (product and product.get("cold_pack_required")):
            continue
        subtotal = int(line.get("line_item_subtotal_cents", 0) or 0)
        if cold_index == 0:
            component_refund_cents += subtotal
        elif cold_index == 1:
            component_refund_cents += round_half_up(subtotal * HALF_PRICE_LINE_FACTOR)
        cold_index += 1

    packing_fee_refund_cents = 0.0 * int(order.get("cold_pack_fee_cents", 0) or 0)
    payable_total_cents = (
        int(order.get("merchandise_subtotal_cents", 0) or 0)
        - int(order.get("autoship_discount_cents", 0) or 0)
        + int(order.get("cold_pack_fee_cents", 0) or 0)
    )
    return int(min(component_refund_cents + packing_fee_refund_cents, payable_total_cents))


def settle_orders_of_pet(pet_id):
    """Write refunded_amount_cents on every CANCELED order of the pet's plans."""
    for plan in db.AUTOSHIP_PLANS.values():
        if plan.get("pet_id") != pet_id:
            continue
        for order in orders_of_plan(plan["id"]):
            order["refunded_amount_cents"] = settlement_for_order(order)
            order["settlement_net_cents"] = int(
                order.get("order_total_cents", 0) or 0
            ) - order["refunded_amount_cents"]
    return None


def review_refund_total(pet_id):
    """CompassionateReview.refunded_amount_cents := sum over the pet's plans."""
    total = 0
    for plan in db.AUTOSHIP_PLANS.values():
        if plan.get("pet_id") != pet_id:
            continue
        for order in orders_of_plan(plan["id"]):
            total += int(order.get("refunded_amount_cents", 0) or 0)
    return total


# ---------------------------------------------------------------------------
# payment_settlement_net  (SS1.3)
# ---------------------------------------------------------------------------

def orders_of_plan(plan_id):
    """Plan orders in ascending (composed_at, created_at) order."""
    rows = [
        o for o in db.ORDERS.values() if o.get("autoship_plan_id") == plan_id
    ]
    return sorted(
        rows,
        key=lambda o: (o.get("composed_at") or o.get("created_at") or "", o.get("created_at") or ""),
    )


def payment_settlement_net(plan):
    released_refunds_cents = 0
    transaction_adjustments_cents = 0
    for order in orders_of_plan(plan["id"]):
        net = int(order.get("order_total_cents", 0) or 0) - int(
            order.get("refunded_amount_cents", 0) or 0
        )
        order["settlement_net_cents"] = net
        released_refunds_cents += int(order.get("refunded_amount_cents", 0) or 0)
        transaction_adjustments_cents += net
        order["settlement_payment_balance_cents"] = int(
            order.get("settlement_payment_balance_cents", 0) or 0
        ) + net
    plan["released_refunds_cents"] = released_refunds_cents
    plan["transaction_adjustments_cents"] = transaction_adjustments_cents
    return plan