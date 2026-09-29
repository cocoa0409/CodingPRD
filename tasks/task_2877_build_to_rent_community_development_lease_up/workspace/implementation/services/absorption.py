"""The absorption pacing index and the tier it selects (PRD section 3.5)."""
from __future__ import annotations

from decimal import Decimal

from calc import rhu4

SUPPLY_FACTOR_FLOOR = Decimal("0.75")
SUPPLY_FACTOR_CEILING = Decimal("1.25")
RESTRICTED_POSTURE_PENALTY = Decimal("0.90")
NEUTRAL_POSTURE_PENALTY = Decimal("1.00")

# Inclusive lower bounds, evaluated from the top down.
TIER_BANDS = (
    (Decimal("1.2000"), "NONE", 250),
    (Decimal("1.0000"), "LIGHT", 125),
    (Decimal("0.8000"), "MODERATE", 0),
)
LOWEST_TIER = ("AGGRESSIVE", -150)


def pacing_index(actual_units, planned_units, available_supply_units, posture_at_review):
    """Zero absorption short-circuits to exactly 0.0000 with no division attempted."""
    if actual_units == 0:
        return rhu4(Decimal(0))
    raw_pace = Decimal(actual_units) / Decimal(planned_units)
    divisor = Decimal(planned_units) if planned_units >= 1 else Decimal(1)
    supply_factor = Decimal(available_supply_units) / divisor
    if supply_factor < SUPPLY_FACTOR_FLOOR:
        supply_factor = SUPPLY_FACTOR_FLOOR
    elif supply_factor > SUPPLY_FACTOR_CEILING:
        supply_factor = SUPPLY_FACTOR_CEILING
    penalty = (RESTRICTED_POSTURE_PENALTY if posture_at_review == "RESTRICTED"
               else NEUTRAL_POSTURE_PENALTY)
    return rhu4(raw_pace * supply_factor * penalty)


def tier_for(index):
    for lower_bound, tier, growth_bps in TIER_BANDS:
        if index >= lower_bound:
            return tier, growth_bps
    return LOWEST_TIER
