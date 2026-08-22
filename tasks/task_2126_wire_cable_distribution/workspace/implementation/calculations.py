"""The eleven calculation rules of SCAFFOLD 1.3 / PRD Section 3.

Money is carried in whole cents as integers; the only fractional value allowed
to live anywhere is the copper pass-through per foot, held at exactly four
decimal places and deliberately left unrounded.  Every conversion of a
fractional amount into cents uses ROUND_HALF_UP to zero decimal places, and each
such conversion happens exactly once at the point the PRD names it.
"""
import math
from decimal import Decimal, ROUND_HALF_UP

import clock
import constants as C
from errors import ApiError

FOUR_PLACES = Decimal("0.0001")
ZERO_PLACES = Decimal("1")


def half_up(value):
    """ROUND_HALF_UP to whole cents."""
    return int(Decimal(value).quantize(ZERO_PLACES, rounding=ROUND_HALF_UP))


def dec(value):
    return Decimal(str(value))


def as_number(value):
    """Footage stays integral wherever it is whole."""
    if isinstance(value, Decimal):
        value = float(value)
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


# ---------------------------------------------------------------------------
# 1. cut_charge_and_billable_length
# ---------------------------------------------------------------------------

def cut_charge_and_billable_length(product, put_up, requested_length_ft, parallel_set_size):
    """Per-conductor billable length, reel count, tiered cut charge and deposit.

    The tier is keyed on the per-conductor billable_length_ft, NEVER on
    billable_length_ft * parallel_set_size; paralleling multiplies the resulting
    charge rather than the tier.
    """
    if put_up == "CUT":
        billable_length_ft = max(dec(requested_length_ft), dec(product["min_cut_length_ft"]))
        reel_count = 1
    else:  # MASTER_REEL
        reel_count = int(math.ceil(dec(requested_length_ft) / dec(product["master_reel_length_ft"])))
        billable_length_ft = dec(reel_count) * dec(product["master_reel_length_ft"])

    if put_up == "MASTER_REEL":
        cut_charge_per_conductor = 0
    elif billable_length_ft < C.SHORT_CUT_TIER_FT:
        cut_charge_per_conductor = 2 * product["cut_charge_cents"]
    elif billable_length_ft < C.FREE_CUT_TIER_FT:
        cut_charge_per_conductor = 1 * product["cut_charge_cents"]
    else:
        cut_charge_per_conductor = 0

    cut_charge_cents_total = cut_charge_per_conductor * parallel_set_size

    if put_up == "MASTER_REEL":
        deposit_cents_total = product["reel_deposit_cents"] * reel_count * parallel_set_size
    else:
        deposit_cents_total = 0

    return {
        "billable_length_ft": as_number(billable_length_ft),
        "reel_count": reel_count,
        "cut_charge_per_conductor_cents": cut_charge_per_conductor,
        "cut_charge_cents_total": cut_charge_cents_total,
        "deposit_cents_total": deposit_cents_total,
    }


def cut_charge_tier(billable_length_ft, cut_charge_cents):
    """Re-confirmation of the tiered per-conductor charge at commit time."""
    length = dec(billable_length_ft)
    if length < C.SHORT_CUT_TIER_FT:
        return 2 * cut_charge_cents
    if length < C.FREE_CUT_TIER_FT:
        return 1 * cut_charge_cents
    return 0


# ---------------------------------------------------------------------------
# 2. quote_line_pricing (variants QUOTED and INVOICED)
# ---------------------------------------------------------------------------

def copper_adder_cents_per_ft(product, index_entry):
    """Exactly four decimal places, unrounded."""
    if product["conductor_metal"] == "ALUMINUM":
        return Decimal("0.0000")
    value = dec(index_entry["price_cents_per_lb"]) * (dec(product["copper_lbs_per_1000ft"]) / Decimal(1000))
    return value.quantize(FOUR_PLACES, rounding=ROUND_HALF_UP)


def price_line(product, index_entry, billable_length_ft, parallel_set_size, cut_charge_cents_total):
    """Per-line pricing; the metal component is rounded HALF_UP exactly once, here."""
    adder = copper_adder_cents_per_ft(product, index_entry)
    total_billable_ft = dec(billable_length_ft) * dec(parallel_set_size)
    metal_cents = half_up(adder * total_billable_ft)
    base_cents = int(dec(product["base_price_cents_per_ft"]) * total_billable_ft)
    extended_cents = base_cents + metal_cents + cut_charge_cents_total
    return {
        "copper_adder_cents_per_ft": float(adder),
        "metal_cents": metal_cents,
        "base_cents": base_cents,
        "extended_cents": extended_cents,
    }


# ---------------------------------------------------------------------------
# 3. order_money_rollup
# ---------------------------------------------------------------------------

def order_money_rollup(line_values, branch):
    """The pinned six-step evaluation order.  No step is re-run after step 5."""
    # 1. line subtotal -- sum of already-rounded per-line values
    line_subtotal_cents = sum(item["extended_cents"] for item in line_values)

    # 2. gross freight
    physical_reel_count = sum(item["reel_count"] * item["parallel_set_size"] for item in line_values)
    gross_freight_cents = (
        C.FREIGHT_BASE_CENTS
        + C.FREIGHT_PER_REEL_CENTS * physical_reel_count
        + branch["delivery_surcharge_cents"]
    )

    # 3. rebate tier keyed on subtotal PLUS gross freight
    rebate_basis_cents = line_subtotal_cents + gross_freight_cents
    if rebate_basis_cents < C.REBATE_TIER1_CENTS:
        rebate_pct = Decimal("0.000")
    elif rebate_basis_cents < C.REBATE_TIER2_CENTS:
        rebate_pct = Decimal("0.015")
    else:
        rebate_pct = Decimal("0.030")

    # 4. rebate applies to the SUBTOTAL ONLY, never to freight
    rebate_cents = half_up(dec(line_subtotal_cents) * rebate_pct)

    # 5. free-freight waiver on the post-rebate net, INCLUSIVE
    net_before_waiver_cents = line_subtotal_cents + gross_freight_cents - rebate_cents
    freight_cents = 0 if net_before_waiver_cents >= C.FREE_FREIGHT_THRESHOLD_CENTS else gross_freight_cents

    # 6. total -- rebate_pct is NOT recomputed after the waiver zeroes freight
    total_cents = line_subtotal_cents + freight_cents - rebate_cents

    deposit_total_cents = sum(item.get("deposit_cents_total", 0) for item in line_values)

    return {
        "line_subtotal_cents": line_subtotal_cents,
        "physical_reel_count": physical_reel_count,
        "gross_freight_cents": gross_freight_cents,
        "rebate_pct": float(rebate_pct),
        "rebate_cents": rebate_cents,
        "freight_cents": freight_cents,
        "total_cents": total_cents,
        "deposit_total_cents": deposit_total_cents,
    }


# ---------------------------------------------------------------------------
# 4. quote_validity_and_index_shock
# ---------------------------------------------------------------------------

def valid_until(issued_at):
    return clock.plus_hours(issued_at, C.QUOTE_VALIDITY_HOURS)


def is_index_shock(new_entry, pinned_entry):
    """Strictly greater than the tolerance; equality is NOT a shock."""
    if new_entry["effective_date"] <= pinned_entry["effective_date"]:
        return False
    deviation = (
        abs(dec(new_entry["price_cents_per_lb"]) - dec(pinned_entry["price_cents_per_lb"]))
        / dec(pinned_entry["price_cents_per_lb"])
    )
    return deviation > Decimal(C.COPPER_VOLATILITY_TOLERANCE_PCT)


# ---------------------------------------------------------------------------
# 5. reel_allocation_plan -- see services/allocation.py (needs the store)
# ---------------------------------------------------------------------------

def rank_candidates(candidates, need, policy, avail_of, key_of):
    """rank() is the only place the two allocation policies differ.

    Both tie-break on created_at ASC, never on identifier.
    """
    if policy == "MINIMIZE_REMNANT":
        fitting = [reel for reel in candidates if dec(avail_of(reel)) >= dec(need)]
        if fitting:
            return sorted(fitting, key=lambda r: (dec(avail_of(r)), key_of(r)))
        return sorted(candidates, key=lambda r: (-dec(avail_of(r)), key_of(r)))
    return sorted(candidates, key=lambda r: (-dec(avail_of(r)), key_of(r)))


def line_allocation_status(allocated, required):
    if dec(allocated) == dec(required):
        return "FULLY_ALLOCATED"
    if dec(allocated) > 0:
        return "SHORT"
    return "UNALLOCATED"


# ---------------------------------------------------------------------------
# 6. branch_available_footage
# ---------------------------------------------------------------------------

def reel_available_length(reel):
    return as_number(dec(reel["current_length_ft"]) - dec(reel["allocated_length_ft"]))


def branch_product_available_ft(reels, branch_id, product_id):
    total = Decimal(0)
    for reel in reels:
        if reel["branch_id"] == branch_id and reel["product_id"] == product_id \
                and reel["status"] in ("IN_STOCK", "ALLOCATED_PARTIAL"):
            total += dec(reel["current_length_ft"]) - dec(reel["allocated_length_ft"])
    return as_number(total)


# ---------------------------------------------------------------------------
# 7. reel_deposit_credit
# ---------------------------------------------------------------------------

def reel_deposit_credit(product, delivered_at, current_utc, condition):
    """Inclusive sixty-day window; the FULL deposit always leaves the liability."""
    days = clock.elapsed_days(delivered_at, current_utc)
    if days <= C.DEPOSIT_RETURN_WINDOW_DAYS and condition == "GOOD":
        credit_pct = Decimal("1.00")
    elif days <= C.DEPOSIT_RETURN_WINDOW_DAYS and condition == "DAMAGED":
        credit_pct = Decimal("0.50")
    else:
        credit_pct = Decimal("0.00")
    return half_up(dec(product["reel_deposit_cents"]) * credit_pct)


# ---------------------------------------------------------------------------
# 8. cut_floor_occupancy
# ---------------------------------------------------------------------------

def cut_floor_overlap_count(occupied_allocations, requested_start, requested_end):
    """CLOSED intervals plus a trailing thirty-minute cleanup buffer.

    Touching endpoints COLLIDE -- both comparisons are inclusive.
    """
    requested_buffered_end = clock.plus_minutes(requested_end, C.CUT_BAY_CLEANUP_BUFFER_MIN)
    count = 0
    for alloc in occupied_allocations:
        existing_start = clock.parse_dt(alloc["cut_window_start"])
        existing_buffered_end = clock.plus_minutes(
            clock.parse_dt(alloc["cut_window_end"]), C.CUT_BAY_CLEANUP_BUFFER_MIN
        )
        if requested_start <= existing_buffered_end and existing_start <= requested_buffered_end:
            count += 1
    return count


# ---------------------------------------------------------------------------
# 9. truck_window_conflict
# ---------------------------------------------------------------------------

def truck_window_conflicts(existing_runs, requested_start, requested_end):
    """HALF-OPEN intervals, exclusive occupation, no buffer; strict comparisons."""
    for run in existing_runs:
        existing_start = clock.parse_dt(run["window_start"])
        existing_end = clock.parse_dt(run["window_end"])
        if requested_start < existing_end and existing_start < requested_end:
            return True
    return False


# ---------------------------------------------------------------------------
# 10. jobsite_reel_handling
# ---------------------------------------------------------------------------

def jobsite_reel_handling(heaviest_reel_lbs, jobsite_has_forklift):
    """The forklift branch wins outright."""
    if jobsite_has_forklift:
        return "FORKLIFT"
    if dec(heaviest_reel_lbs) > C.MAX_MANUAL_REEL_LBS:
        return "BOOM_LIFT"
    return "TAILGATE"


# ---------------------------------------------------------------------------
# 11. customer_credit_posture
# ---------------------------------------------------------------------------

def available_credit_cents(customer):
    return customer["credit_limit_cents"] - customer["open_balance_cents"]


def posture_transition(customer):
    """ACTIVE -> CREDIT_HOLD below zero; CREDIT_HOLD -> ACTIVE at zero or above."""
    available = available_credit_cents(customer)
    if customer["credit_status"] == "ACTIVE" and available < 0:
        return "CREDIT_HOLD"
    if customer["credit_status"] == "CREDIT_HOLD" and available >= 0:
        return "ACTIVE"
    return None
