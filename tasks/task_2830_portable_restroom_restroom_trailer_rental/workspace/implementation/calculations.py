"""Calculation rules (scaffold 1.3 / PRD 3.3-3.9).

All money is integer cents. Every division names its fractional disposal
explicitly; monetary roundings use round-half-up and are never collapsed.
"""
from decimal import Decimal, ROUND_HALF_UP

import constants as C


def round_half_up(value):
    """Round a Decimal to a whole integer, ties away from zero."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def floor_div(numerator, denominator):
    return numerator // denominator


def ceil_div(numerator, denominator):
    return -((-numerator) // denominator)


# ---------------------------------------------------------------- unit_mix_quote

def provisional_mix(contract):
    """Variant provisional_projection; returns [(unit_class, quantity), ...]."""
    # step 1: demand, by contract_kind
    if contract["contract_kind"] == "EVENT":
        demand_person_hours = floor_div(
            contract["headcount"] * contract["event_duration_hours"]
            * C.EVENT_PEAK_FACTOR_NUM,
            C.EVENT_PEAK_FACTOR_DEN,
        )
    else:
        service_interval_days = ceil_div(7, contract["service_frequency_per_week"])
        demand_person_hours = (
            contract["headcount"] * C.CONSTRUCTION_SHIFT_HOURS * service_interval_days
        )

    # step 2: raw capacity in standard-unit equivalents
    base_capacity_units = ceil_div(demand_person_hours, C.STANDARD_SERVICE_PERSON_HOURS)

    # step 3: trailer tier selection -- hard threshold on headcount
    if contract["headcount"] >= C.TRAILER_HEADCOUNT_FLOOR:
        trailer_8stall_qty = floor_div(base_capacity_units, 8)
        remainder_units = base_capacity_units - trailer_8stall_qty * 8
        trailer_2stall_qty = ceil_div(remainder_units, 2)
        standard_qty = 0
    else:
        trailer_8stall_qty = 0
        trailer_2stall_qty = 0
        standard_qty = base_capacity_units

    # step 4: restroom equivalents actually placed
    restroom_units = standard_qty + trailer_2stall_qty * 2 + trailer_8stall_qty * 8

    # step 5: ADA overlay
    if contract["ada_required"]:
        ada_qty = max(C.ADA_MIN_UNITS, ceil_div(restroom_units, C.ADA_RATIO_DIVISOR))
    else:
        ada_qty = 0

    # step 6: handwash overlay, keyed on step 4 PLUS step 5
    handwash_qty = ceil_div(restroom_units + ada_qty, C.HANDWASH_RATIO_DIVISOR)

    quantities = {
        "STANDARD_PORTABLE": standard_qty,
        "ADA_PORTABLE": ada_qty,
        "HANDWASH_STATION": handwash_qty,
        "TRAILER_2STALL": trailer_2stall_qty,
        "TRAILER_8STALL": trailer_8stall_qty,
    }
    # step 7: fixed class order, skipping any quantity == 0
    return [(uc, quantities[uc]) for uc in C.UNIT_CLASSES if quantities[uc] >= 1]


def reconciled_mix(unit_classes):
    """Variant reconciled_actual: counts of actual deployments per unit_class.

    `unit_classes` is the list of AssetUnit.unit_class values of the
    contract's deployments in state DEPLOYED or RETURNED. No overlays apply.
    """
    counts = {}
    for unit_class in unit_classes:
        counts[unit_class] = counts.get(unit_class, 0) + 1
    return [(uc, counts.get(uc, 0)) for uc in C.UNIT_CLASSES if counts.get(uc, 0) >= 1]


def unit_rate_cents(unit_class):
    return C.RATE_CENTS_BY_CLASS[unit_class]


def extended_cents(quantity, rate_cents):
    return quantity * rate_cents


# --------------------------------------------------------- line escalation

def combined_escalation_pct(contract):
    return (
        C.SEASONAL_ESCALATION_PCT[contract["season_code"]]
        + C.PHASE_ESCALATION_PCT[contract["construction_phase"]]
        + C.FUEL_SURCHARGE_PCT
    )


def escalated_line_cents(line_extended_cents, combined_pct):
    return round_half_up(
        Decimal(line_extended_cents) * (Decimal(100) + combined_pct) / Decimal(100)
    )


# ------------------------------------------------------------- route density

def density_pct(units, truck_capacity_units):
    if not truck_capacity_units:
        return 0
    return floor_div(units * 100, truck_capacity_units)


# ------------------------------------------------------ missed service credit

def density_surcharge_pct(density_planned_pct):
    for max_density_pct, surcharge_pct in C.DENSITY_SURCHARGE_TIERS:
        if density_planned_pct <= max_density_pct:
            return surcharge_pct
    return C.DENSITY_SURCHARGE_TIERS[-1][1]


def missed_service_credit_cents(density_snapshot_pct, lines):
    """`lines` are the contract's non-superseded QuoteLine rows."""
    surcharge_pct = density_surcharge_pct(density_snapshot_pct)
    base_visit_cents = 0
    for line in lines:
        base_visit_cents += (
            line["quantity"]
            * C.BASE_PER_VISIT_SERVICE_CENTS_BY_CLASS[line["unit_class"]]
        )
    per_visit_service_cents = round_half_up(
        Decimal(base_visit_cents) * (Decimal(100) + surcharge_pct) / Decimal(100)
    )
    return round_half_up(
        Decimal(per_visit_service_cents) * C.MISSED_SERVICE_CREDIT_PCT / Decimal(100)
    )


# ---------------------------------------------------- damage / tip-over charge

def strike_multiplier_pct(prior_strikes):
    if prior_strikes <= 1:
        return 100
    if prior_strikes == 2:
        return 150
    return 200


def damage_tip_over_cents(unit_class, charge_kind, severity, prior_strikes):
    strike_mult_pct = strike_multiplier_pct(prior_strikes)
    if charge_kind == "DAMAGE":
        base_cents = C.DAMAGE_BASE_CENTS_BY_CLASS[unit_class]
        severity_pct = C.SEVERITY_PCT[severity]
    else:
        base_cents = C.TIP_OVER_BASE_CENTS
        severity_pct = 100
    # single rounding at the end, both factors applied to the exact product
    return round_half_up(
        Decimal(base_cents) * Decimal(severity_pct) * Decimal(strike_mult_pct)
        / Decimal(10000)
    )


# ------------------------------------------------------------ relocation charge

def relocation_cents(destination_access_class, same_day):
    access_mult_pct = C.ACCESS_CLASS_MULTIPLIER_PCT[destination_access_class]
    uplift_pct = C.SAME_DAY_UPLIFT_PCT if same_day else 0
    access_adjusted_cents = round_half_up(
        Decimal(C.RELOCATION_BASE_CENTS) * Decimal(access_mult_pct) / Decimal(100)
    )
    return round_half_up(
        Decimal(access_adjusted_cents) * (Decimal(100) + Decimal(uplift_pct))
        / Decimal(100)
    )
