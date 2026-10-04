"""Calculation rules: release cap, surge, pricing, refunds, exchanges, ranking."""

import math
from decimal import Decimal, ROUND_HALF_UP

from clock import CLOCK, parse_iso
from db import DB

MARKET_RUSH_SHARE_CAP_BP = 4000
SURGE_CAP_BP = 5000
SURGE_A_BP = 2500
SURGE_B_BP = 1500
SURGE_C_BP = 1000
SURGE_A_MIN_ACTIVE_ORDERS = 12
SURGE_B_MIN_RELEASED_OFF = 0.90
SURGE_C_MIN_FILL = 0.80
GROUP_MIN_QUANTITY = 4
GROUP_DISCOUNT_BP = 1000
REFUND_PROCESSING_FEE_CENTS = 200
EXCHANGE_FEE_CAP_CENTS = 500
WAITLIST_MULTIPLIER = 2
QUOTA_DENOMINATOR = 2
QUOTA_FLOOR_MIN_CAP = 2
ADMISSION_WINDOW_MINUTES = 20
QUOTE_SURGE_BP = 5000


def rhu(value):
    """Round half-up to a whole integer."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _hours(iso_later, iso_earlier):
    return (parse_iso(iso_later) - parse_iso(iso_earlier)).total_seconds() / 3600.0


def non_standard_released(performance_id, exclude_allocation_id=None):
    """Sum of quantity_released_today over non-STANDARD allocations of a performance."""
    total = 0
    for alloc in DB.all("allocation"):
        if alloc["performance_id"] != performance_id:
            continue
        if exclude_allocation_id is not None and alloc["id"] == exclude_allocation_id:
            continue
        if alloc["ticket_type"] == "STANDARD":
            continue
        if alloc["status"] not in ("RELEASED", "EXHAUSTED"):
            continue
        total += int(alloc.get("quantity_released_today") or 0)
    return total


def rush_daily_release_cap(allocation, performance):
    """Smallest of the producer grant, the carried-forward candidate and the market cap."""
    daily_quantity = int(allocation["daily_quantity"])
    c_requested = daily_quantity
    c_forward = max(0, daily_quantity - int(allocation.get("quantity_carried_forward") or 0))
    market_seats = (MARKET_RUSH_SHARE_CAP_BP * int(performance["total_seat_capacity"])) // 10000
    others = non_standard_released(performance["id"], exclude_allocation_id=allocation["id"])
    c_market = max(0, market_seats - others)
    return min(c_requested, c_forward, c_market)


def active_order_count(performance_id):
    count = 0
    for purchase in DB.all("purchase"):
        if purchase["performance_id"] != performance_id:
            continue
        if purchase["payment_status"] in ("PENDING", "AUTHORIZED"):
            count += 1
    return count


def demand_surge_bp(allocation, performance, billable=None):
    """Demand surge in basis points; RUSH and DRAW never surge.

    ``billable`` is the seats this order is about to dispense: the surge is
    recomputed from the epoch's live state with the order's own seats counted in
    the sold tally, because the price a seat carries is the price the epoch's fill
    supports at the instant the seat is taken.
    """
    if allocation["ticket_type"] in ("RUSH", "DRAW"):
        return 0
    released = int(allocation.get("quantity_released_today") or 0)
    carried = int(allocation.get("quantity_carried_forward") or 0)
    sold = int(allocation.get("quantity_sold_today") or 0) + int(billable or 0)
    released_effective = released + carried
    if released_effective == 0:
        fill_fraction = 0.0
        released_off_fraction = 0.0
    else:
        fill_fraction = sold / float(released_effective)
        released_off_fraction = (released_effective - sold) / float(released_effective)
    surge = 0
    if active_order_count(performance["id"]) > SURGE_A_MIN_ACTIVE_ORDERS:
        surge += SURGE_A_BP
    if released_off_fraction > SURGE_B_MIN_RELEASED_OFF:
        surge += SURGE_B_BP
    if fill_fraction > SURGE_C_MIN_FILL:
        surge += SURGE_C_BP
    return min(SURGE_CAP_BP, surge)


def per_seat_price(performance, allocation, billable=None):
    """Two-step price: discount then round, surge then round."""
    face = Decimal(int(performance["face_value_cents"]))
    discount = Decimal(str(allocation["discount_pct"]))
    base_price_cents = rhu(face * (Decimal(1) - discount))
    surge_bp = demand_surge_bp(allocation, performance, billable=billable)
    unit_price_cents = rhu(
        Decimal(base_price_cents) * (Decimal(10000) + Decimal(surge_bp)) / Decimal(10000)
    )
    return unit_price_cents, base_price_cents, surge_bp


def purchase_line_subtotal(unit_price_cents, quantity):
    """Extend the rounded unit price, apply the group discount, round once."""
    group_discount_bp = GROUP_DISCOUNT_BP if int(quantity) >= GROUP_MIN_QUANTITY else 0
    return rhu(
        Decimal(int(unit_price_cents))
        * Decimal(int(quantity))
        * (Decimal(10000) - Decimal(group_discount_bp))
        / Decimal(10000)
    )


def producer_quote(unit_price_cents, quantity):
    """Forward-looking producer projection; per-seat surge rounding before extension."""
    per_seat = rhu(
        Decimal(int(unit_price_cents)) * (Decimal(10000) + Decimal(QUOTE_SURGE_BP)) / Decimal(10000)
    )
    return per_seat * int(quantity)


def refund_amount(purchase, allocation, production, performance):
    """Base refund figure under the whole-order variant, fee applied only when terminal."""
    subtotal = int(purchase.get("subtotal_cents") or 0)
    window = int(production.get("refund_window_hours") or 0)
    hours_before_start = _hours(performance["starts_at"], CLOCK.stamp())
    refundable = bool(allocation.get("refundable"))
    if not refundable and hours_before_start < window:
        base = 0
    elif hours_before_start >= window:
        base = subtotal
    else:
        base = rhu(Decimal(subtotal) * Decimal("0.50"))
    status = purchase.get("_refund_status") or "REQUESTED"
    fee = REFUND_PROCESSING_FEE_CENTS if status in ("SETTLED", "COMPENSATED") else 0
    return max(0, base - fee)


def exchange_cost(purchase, target_allocation, production, performance, exchange_status):
    """Target price, time band and cap assembled into fee and value returned."""
    subtotal = int(purchase.get("subtotal_cents") or 0)
    quantity = int(purchase.get("quantity") or 1)
    face = Decimal(int(performance["face_value_cents"]))
    target_discount = Decimal(str(target_allocation["discount_pct"]))
    target_price_cents = rhu(face * (Decimal(1) - target_discount))
    per_seat_paid = Decimal(subtotal) / Decimal(quantity)
    price_difference = Decimal(target_price_cents) - per_seat_paid
    hours_before_start = _hours(performance["starts_at"], CLOCK.stamp())
    fee_cents_production = int(production.get("exchange_fee_cents") or 0)
    if hours_before_start >= 24:
        base_fee = Decimal(0)
    elif hours_before_start >= 2:
        base_fee = Decimal(fee_cents_production)
    else:
        base_fee = Decimal(fee_cents_production * 2)
    if price_difference <= 0:
        fee_cents = rhu(min(Decimal(EXCHANGE_FEE_CAP_CENTS), base_fee))
    else:
        fee_cents = rhu(base_fee + price_difference)
    if exchange_status == "APPLIED":
        value_returned_cents = 0
    else:
        value_returned_cents = max(0, rhu(Decimal(subtotal) - Decimal(fee_cents)))
    return fee_cents, value_returned_cents


def redemption_lifecycle_cost(patron_id):
    """Chronological walk of every entry reachable from the patron; recomputed."""
    entries = [e for e in DB.all("draw_entry") if e["patron_id"] == patron_id]
    entries.sort(key=lambda e: (e.get("entered_at") or "", e.get("created_at") or ""))
    now = CLOCK.stamp()
    total = 0.0
    for entry in entries:
        status = entry["status"]
        if status in ("ENTERED", "WAITLISTED", "LOSER"):
            continue
        if status == "WINNER":
            deadline = entry.get("claim_deadline_at")
            if deadline is not None and now >= deadline:
                total += 1.0
            continue
        if status == "FORFEITED":
            total += 1.0
            continue
        if status == "CANCELLED":
            if not entry.get("reclaimed_by_exchange"):
                total += 1.0
            continue
        if status == "PURCHASED":
            total += 0.25
    return total


def winner_selection(allocation_id):
    """Eligible entries ordered by entered_at asc, created_at asc; ids never rank."""
    eligible = []
    for entry in DB.all("draw_entry"):
        if entry["allocation_id"] != allocation_id:
            continue
        if entry["status"] != "ENTERED":
            continue
        patron = DB.get("patron", entry["patron_id"])
        if patron is None or patron["status"] != "ACTIVE":
            continue
        eligible.append(entry)
    eligible.sort(key=lambda e: (e.get("entered_at") or "", e.get("created_at") or ""))
    return eligible


def waitlist_count_for(daily_release_cap):
    return WAITLIST_MULTIPLIER * int(daily_release_cap)


def queue_admit_quota(admitted_so_far, release_cap):
    """Floor band gives at most one slot; otherwise half the cap, rounded up."""
    if int(release_cap) < QUOTA_FLOOR_MIN_CAP:
        return min(int(admitted_so_far), 1)
    return int(math.ceil(int(release_cap) * 1.0 / QUOTA_DENOMINATOR))


def handoff_candidates(performance):
    """Open desks of the performance's market with room left, best-first."""
    market_code = performance["market_code"]
    candidates = []
    for desk in DB.all("desk"):
        if desk["market_code"] != market_code:
            continue
        if desk["status"] != "OPEN":
            continue
        if int(desk["handoffs_today"]) >= int(desk["daily_capacity"]):
            continue
        candidates.append(desk)
    candidates.sort(
        key=lambda d: (-(int(d["daily_capacity"]) - int(d["handoffs_today"])), d["desk_code"])
    )
    return candidates