"""Calculation rules (scaffold table 1.3 / PRD sections 3.4-3.8).

Pinned orders honored here:
- expected_good_units: floor(planned_units * provisional yield)
- campaign unit cost: each component ceilinged separately, THEN summed
- provisional royalty: round half up PER LINE, then sum
- final royalty: sum raw revenues, then round half up ONCE
- commitment coverage: tier derives from pre-bonus base_coverage only
- realized_yield: 6dp round half up; supply/effective coverage: 4dp half up
"""
from decimal import Decimal, ROUND_FLOOR, ROUND_CEILING, ROUND_HALF_UP

import constants as C


def provisional_yield_rate(planned_units):
    if planned_units < C.YIELD_STEP1_MAX_UNITS:
        return C.YIELD_STEP1_RATE
    if planned_units < C.YIELD_STEP2_MAX_UNITS:
        return C.YIELD_STEP2_RATE
    return C.YIELD_STEP3_RATE


def expected_good_units(planned_units):
    product = Decimal(planned_units) * provisional_yield_rate(planned_units)
    return int(product.to_integral_value(rounding=ROUND_FLOOR))


def campaign_days(start_date, end_date):
    return (end_date - start_date).days


def energy_surcharge_cents(basis_units):
    if basis_units >= C.ENERGY_SURCHARGE_T1_MAX_UNITS:
        return C.ENERGY_SURCHARGE_T2_CENTS
    return C.ENERGY_SURCHARGE_T1_CENTS


def changeover_total_cents(prior_campaign, composition_id, days):
    """Zero when there is no prior campaign or the prior melts the same glass."""
    if prior_campaign is None or prior_campaign["composition_id"] == composition_id:
        return 0
    return C.CHANGEOVER_AMORTIZATION_CENTS_PER_DAY * days


def unit_cost_cents(complexity_multiplier, basis_units, yield_basis, changeover_total):
    """ceil((base*multiplier + energy)/yield) + ceil(changeover/basis_units).

    The two ceilings are applied per component and only then summed; the order
    is pinned. Returns None when the final variant is undefined (no usable
    production: zero good units or zero realized yield).
    """
    if yield_basis is None or basis_units is None or basis_units <= 0:
        return None
    if yield_basis <= 0:
        return None
    energy = energy_surcharge_cents(basis_units)
    first = (
        Decimal(C.BASE_MELT_COST_CENTS_PER_UNIT) * Decimal(str(complexity_multiplier))
        + Decimal(energy)
    ) / yield_basis
    second = Decimal(changeover_total) / Decimal(basis_units)
    return int(first.to_integral_value(rounding=ROUND_CEILING)) + int(
        second.to_integral_value(rounding=ROUND_CEILING)
    )


def realized_yield_value(good_units, scrap_units):
    """6dp round half up; None until at least one production record exists."""
    if good_units + scrap_units <= 0:
        return None
    ratio = Decimal(good_units) / Decimal(good_units + scrap_units)
    return ratio.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


def royalty_rate(total_units):
    """Average rate selected by total units across ALL lines (not marginal)."""
    if total_units <= C.ROYALTY_T1_MAX_UNITS:
        return C.ROYALTY_T1_RATE
    if total_units <= C.ROYALTY_T2_MAX_UNITS:
        return C.ROYALTY_T2_RATE
    return C.ROYALTY_T3_RATE


def royalty_provisional_cents(lines, rate):
    """Round half up each line first, then sum the rounded line amounts."""
    total = 0
    for line in lines:
        amount = (Decimal(line["net_revenue_cents"]) * rate).to_integral_value(
            rounding=ROUND_HALF_UP
        )
        total += int(amount)
    return total


def royalty_final_cents(lines, rate):
    """Sum raw line revenues unrounded, then round half up exactly once."""
    total_revenue = sum(line["net_revenue_cents"] for line in lines)
    return int(
        (Decimal(total_revenue) * rate).to_integral_value(rounding=ROUND_HALF_UP)
    )


def coverage_snapshot(committed_units, required_units, prepayment_cents):
    """commitment_coverage: pinned 7-step order; later steps never feed back."""
    credit_units = prepayment_cents // C.PREPAYMENT_UNIT_CREDIT_CENTS  # step 1
    base_units = committed_units + credit_units  # step 2
    base_coverage = Decimal(base_units) / Decimal(required_units)  # step 3, unrounded
    if base_coverage >= C.TIER_A_COVERAGE_MIN:  # step 4: pre-bonus coverage only
        tier, bonus_rate = "TIER_A", C.TIER_A_BONUS_RATE
    elif base_coverage >= C.TIER_B_COVERAGE_MIN:
        tier, bonus_rate = "TIER_B", C.TIER_B_BONUS_RATE
    else:
        tier, bonus_rate = "TIER_C", Decimal("0")  # step 5
    effective_units = int(
        (Decimal(base_units) * (1 + bonus_rate)).to_integral_value(rounding=ROUND_FLOOR)
    )  # step 6
    effective_coverage = (Decimal(effective_units) / Decimal(required_units)).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP
    )  # step 7
    return {
        "base_coverage": base_coverage,
        "tier": tier,
        "effective_units": effective_units,
        "effective_coverage": effective_coverage,
    }


def supply_coverage_value(commitment, all_allocations):
    """sum(units of RESERVED/FULFILLED allocations) / committed_units, 4dp half up."""
    used = sum(
        a["units"]
        for a in all_allocations
        if a["commitment_id"] == commitment["id"]
        and a["status"] in ("RESERVED", "FULFILLED")
    )
    ratio = Decimal(used) / Decimal(commitment["committed_units"])
    return ratio.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def allocated_units(commitment_id, all_allocations):
    return sum(
        a["units"]
        for a in all_allocations
        if a["commitment_id"] == commitment_id
        and a["status"] in ("RESERVED", "FULFILLED")
    )
