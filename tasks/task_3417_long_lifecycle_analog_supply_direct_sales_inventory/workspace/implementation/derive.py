# Derived/computed fields (PRD 2.4 consistency: recomputed on every read):
#   Part.reserved_units / posture / inventory position (calc_buffer_position)
#   Customer.open_exposure_cents (calc_credit_exposure) / at_risk_design_win_count
#   CapacityPool.status / qualified_for_automotive
#   DesignWin.at_risk / recognized_*_cents (calc_revenue_tail)
#   calc_unit_price_quote / calc_priority_score helpers
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP

import constants as C
from store import store
from timeutil import years_elapsed


# ---------------------------------------------------------------------------
# Order lines
# ---------------------------------------------------------------------------

def order_lines_of(order_id):
    lines = [l for l in store.order_lines.values() if l["order_id"] == order_id]
    lines.sort(key=lambda l: l["seq"])
    return lines


# ---------------------------------------------------------------------------
# Part derived fields
# ---------------------------------------------------------------------------

def part_reserved_units(part_id):
    """Awarded units on ALLOCATED/BACKORDERED order lines plus APPROVED
    lifetime-buy quantities (PRD 3.4: a BACKORDERED order still holds its
    reservations)."""
    total = 0
    for order in store.orders.values():
        if order["status"] in ("ALLOCATED", "BACKORDERED"):
            for line in store.order_lines.values():
                if line["order_id"] == order["id"] and line["part_id"] == part_id:
                    total += line["awarded_units"]
    for buy in store.lifetime_buys.values():
        if buy["part_id"] == part_id and buy["status"] == "APPROVED":
            total += buy["quantity"]
    return total


def weekly_pipeline(part_id):
    """Sum over ACTIVE design wins of (annual_volume_units / 52) * 0.5."""
    total = Decimal(0)
    weight = Decimal(str(C.DESIGN_WIN_PIPELINE_WEIGHT))
    for win in store.design_wins.values():
        if win["part_id"] == part_id and win["status"] == "ACTIVE":
            total += (Decimal(win["annual_volume_units"]) / Decimal(52)) * weight
    return total


def buffer_targets(part):
    """(target_trailing_units, target_forward_units), ceil to whole units."""
    demand = Decimal(part["demand_rate_units_per_week"])
    mult = Decimal(str(part["buffer_multiple"]))
    horizon = Decimal(C.BUFFER_HORIZON_WEEKS)
    trailing_raw = demand * mult * horizon
    forward_raw = (demand + weekly_pipeline(part["id"])) * mult * horizon
    target_trailing = int(trailing_raw.to_integral_value(rounding=ROUND_CEILING))
    target_forward = int(forward_raw.to_integral_value(rounding=ROUND_CEILING))
    return target_trailing, target_forward


def coverage_and_posture(part, extra_reserved=0):
    """(coverage_trailing or None when unbounded, posture).

    coverage is available / target_trailing rounded half-up to 4 decimals;
    posture compares the rounded coverage against the inclusive thresholds.
    extra_reserved models pending same-request reservations (submit fork).
    """
    target_trailing, _ = buffer_targets(part)
    reserved = part_reserved_units(part["id"]) + extra_reserved
    available = part["on_hand_units"] - reserved
    if target_trailing == 0:
        return None, "NORMAL"
    coverage = (Decimal(available) / Decimal(target_trailing)).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP
    )
    if coverage >= Decimal(str(C.WATCH_COVERAGE_THRESHOLD)):
        posture = "NORMAL"
    elif coverage >= Decimal(str(C.SHORTAGE_COVERAGE_THRESHOLD)):
        posture = "WATCH"
    else:
        posture = "SHORTAGE"
    return float(coverage), posture


def inventory_position(part):
    reserved = part_reserved_units(part["id"])
    target_trailing, target_forward = buffer_targets(part)
    coverage, posture = coverage_and_posture(part)
    return {
        "part_id": part["id"],
        "on_hand_units": part["on_hand_units"],
        "reserved_units": reserved,
        "available_units": part["on_hand_units"] - reserved,
        "target_trailing_units": target_trailing,
        "target_forward_units": target_forward,
        "coverage_trailing": coverage,
        "posture": posture,
    }


# ---------------------------------------------------------------------------
# Customer derived fields
# ---------------------------------------------------------------------------

def customer_open_exposure(customer_id):
    total = 0
    for order in store.orders.values():
        if order["customer_id"] == customer_id and order["status"] in ("ALLOCATED", "BACKORDERED"):
            total += order["total_cents"] or 0
    for buy in store.lifetime_buys.values():
        if buy["customer_id"] == customer_id and buy["status"] == "APPROVED":
            total += buy["ltb_value_cents"]
    return total


def win_at_risk(win):
    part = store.parts.get(win["part_id"])
    return bool(part) and part["lifecycle_status"] in ("EOL_ANNOUNCED", "LAST_TIME_BUY", "DISCONTINUED")


def customer_at_risk_count(customer_id):
    return sum(
        1
        for w in store.design_wins.values()
        if w["customer_id"] == customer_id and w["status"] == "ACTIVE" and win_at_risk(w)
    )


# ---------------------------------------------------------------------------
# Capacity pool derived fields
# ---------------------------------------------------------------------------

def pool_status(pool):
    now = store.now()
    if now < pool["period_start"]:
        return "PLANNED"
    if now < pool["period_end"]:
        return "OPEN"
    return "CLOSED"


def site_qualified_for_automotive(site_name):
    return any(
        q["site_name"] == site_name and q["segment"] == "AUTOMOTIVE" and q["status"] == "QUALIFIED"
        for q in store.site_qualifications.values()
    )


# ---------------------------------------------------------------------------
# Pricing (calc_unit_price_quote / calc_ltb_unit_price)
# ---------------------------------------------------------------------------

def published_schedule(part_id):
    """The part's PUBLISHED schedule effective at the current clock, or None.
    At most one PUBLISHED schedule exists per part."""
    for sched in store.pricing_schedules.values():
        if sched["part_id"] == part_id and sched["status"] == "PUBLISHED":
            if sched["effective_from"] <= store.now():
                return sched
            return None
    return None


def tier_for_quantity(schedule, quantity):
    """All-units tier rule: last tier whose min_qty <= quantity (inclusive)."""
    chosen = schedule["tiers"][0]
    for tier in schedule["tiers"]:
        if tier["min_qty"] <= quantity:
            chosen = tier
        else:
            break
    return chosen


def ltb_price_schedule(part_id, notice_date):
    """All schedules (any status) with effective_from <= notice_date; the one
    with the latest effective_from wins, ties break to earliest created."""
    candidates = [
        s for s in store.pricing_schedules.values()
        if s["part_id"] == part_id and s["effective_from"] <= notice_date
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda s: (s["effective_from"], -s["seq"]))
    return candidates[-1]


# ---------------------------------------------------------------------------
# Allocation (calc_priority_score)
# ---------------------------------------------------------------------------

def priority_score(line):
    order = store.orders.get(line["order_id"])
    customer = store.customers.get(order["customer_id"]) if order else None
    score = C.TIER_WEIGHTS[customer["tier"]] if customer else 0
    if customer:
        for win in store.design_wins.values():
            if (
                win["customer_id"] == customer["id"]
                and win["part_id"] == line["part_id"]
                and win["status"] == "ACTIVE"
                and not win_at_risk(win)
            ):
                score += C.DESIGN_WIN_PRIORITY_BONUS
                break
    return score


# ---------------------------------------------------------------------------
# Design win derived fields (calc_revenue_tail)
# ---------------------------------------------------------------------------

def _recognized_for_profile(expected_cents, profile, years):
    year_values = []
    for i in range(3):
        amount = (Decimal(expected_cents) * Decimal(profile[i])).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
        year_values.append(int(amount))
    year_values.append(expected_cents - sum(year_values))
    return sum(year_values[: min(years, C.TAIL_YEARS)])


def recognized_revenue(win):
    """(recognized_ramped_cents, recognized_flat_cents, recognized_revenue_cents)."""
    years = years_elapsed(win["start_date"], store.now())
    expected = win["expected_lifetime_revenue_cents"]
    ramped = _recognized_for_profile(expected, C.RAMP_PROFILE, years)
    flat = _recognized_for_profile(expected, C.FLAT_PROFILE, years)
    part = store.parts.get(win["part_id"])
    canonical = ramped if (part and part["automotive_grade"]) else flat
    return ramped, flat, canonical


# ---------------------------------------------------------------------------
# EOL helpers
# ---------------------------------------------------------------------------

def announced_notice_for_part(part_id):
    """The ANNOUNCED notice driving the part's sweep (earliest last_order_date)."""
    candidates = [
        n for n in store.eol_notices.values()
        if n["part_id"] == part_id and n["status"] == "ANNOUNCED"
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda n: (n["last_order_date"], n["seq"]))
    return candidates[0]
