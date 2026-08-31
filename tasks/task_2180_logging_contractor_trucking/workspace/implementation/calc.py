"""The eight calculation rules of SCAFFOLD.yaml Table 3 / PRD section 3.

Every rounding step sits exactly where the PRD puts it; money is whole cents
carried as int, tonnage is a 2-decimal Decimal, and rounding is always half-up.
"""

import math
from decimal import Decimal

from core import D, rhu, rhu_int, tons

# --- move_in_cost (PRD 3.3) ------------------------------------------------
PIECES_PER_LOWBOY = 2
MILE_RATE_T1 = 900
MILE_RATE_T2 = 725
MILE_RATE_T3 = 610
ACCESS_MULTIPLIER = {
    "ALL_SEASON": D("1.00"),
    "SUMMER_ONLY": D("1.15"),
    "FROZEN_ONLY": D("1.35"),
}
CREW_TYPE_SURCHARGE_CENTS = {
    "HAND_FALLING": 0,
    "MECHANIZED_GROUND": 120000,
    "CABLE_YARDING": 275000,
}
MIN_MOVE_IN_CENTS = 185000
MAX_MOVE_IN_CENTS = 1250000

# --- effective_max_gross_weight (PRD 3.7) ----------------------------------
FROST_LAW_REDUCTION_PCT = D("0.20")
PERMIT_UPLIFT_LBS = 10000
AXLE_CAP_LBS = {"FIVE_AXLE": 80000, "SIX_AXLE": 91000, "SEVEN_AXLE": 105500}

# --- ticket_net_tons (PRD 3.7) ---------------------------------------------
LBS_PER_TON = 2000

# --- load_haul_pay (PRD 3.6 / 3.8) -----------------------------------------
RATE_BAND_1_MAX_MILES = 30
RATE_BAND_2_MAX_MILES = 70
RATE_BAND_1_CENTS = 26
RATE_BAND_2_CENTS = 22
RATE_BAND_3_CENTS = 19
FUEL_SURCHARGE_PCT = D("0.075")
FREE_WAIT_MINUTES = 45
DEMURRAGE_CENTS_PER_MINUTE = 150
INCENTIVE_TIER_1_MIN_CENTS = 60000
INCENTIVE_TIER_1_PCT = D("0.02")
INCENTIVE_TIER_2_MIN_CENTS = 120000
INCENTIVE_TIER_2_PCT = D("0.04")
REGRADE_PENALTY_PCT = D("0.05")

# --- contractor_compliance_score (PRD 3.2) ---------------------------------
BASE_SCORE = 100
SCORE_FLOOR = 0
SAFETY_LOOKBACK_DAYS = 180
INSURANCE_PENALTY_POINTS = 25
REJECT_PENALTY_POINTS = 3
MIN_DISPATCH_SCORE = 70

# --- settlement_statement_rollup (PRD 3.9) ---------------------------------
REJECT_DEDUCTION_PCT = D("0.35")
HOLDBACK_TIER_A_MIN_SCORE = 90
HOLDBACK_TIER_A_PCT = D("0.00")
HOLDBACK_TIER_B_MIN_SCORE = 80
HOLDBACK_TIER_B_PCT = D("0.02")
HOLDBACK_TIER_C_MIN_SCORE = 70
HOLDBACK_TIER_C_PCT = D("0.05")
HOLDBACK_TIER_D_PCT = D("0.10")

# --- rehaul_alternate_selection (PRD 3.8) ----------------------------------
REHAUL_MILE_COST_CENTS = 85
REHAUL_SPEED_MPH = 45


def lowboy_trips(equipment_pieces):
    return int(math.ceil(equipment_pieces / float(PIECES_PER_LOWBOY)))


def move_in_cost(equipment_pieces, crew_type, access_class, move_in_miles):
    """PRD 3.3 -- pinned evaluation order, floor applied before the cap."""
    trips = lowboy_trips(equipment_pieces)
    miles = int(move_in_miles)
    tiered_mileage = (
        MILE_RATE_T1 * min(miles, 25)
        + MILE_RATE_T2 * max(0, min(miles, 75) - 25)
        + MILE_RATE_T3 * max(0, miles - 75)
    )
    base_cents = trips * tiered_mileage
    scaled_cents = rhu_int(D(base_cents) * ACCESS_MULTIPLIER[access_class])
    subtotal_cents = scaled_cents + CREW_TYPE_SURCHARGE_CENTS[crew_type]
    cost = min(max(subtotal_cents, MIN_MOVE_IN_CENTS), MAX_MOVE_IN_CENTS)
    return trips, cost


def frost_active(route, clock_date):
    """PRD 3.7 -- POSTED_RESTRICTED is always posted; the window is closed."""
    if route["status"] == "POSTED_RESTRICTED":
        return True
    start = route.get("frost_law_start_on")
    end = route.get("frost_law_end_on")
    if start is None:
        return False
    iso = clock_date.isoformat()
    if end is None:
        return start <= iso
    return start <= iso <= end


def effective_max_gross_weight(route, truck, clock_date):
    if frost_active(route, clock_date):
        effective_legal = int(
            (D(route["legal_gross_weight_lbs"]) * (D(1) - FROST_LAW_REDUCTION_PCT)).to_integral_value(
                rounding="ROUND_FLOOR"
            )
        )
    else:
        effective_legal = int(route["legal_gross_weight_lbs"])
    if truck["permit_class"] == "LONGER_COMBINATION" and route["permit_class_required"] == "LONGER_COMBINATION":
        uplift = PERMIT_UPLIFT_LBS
    else:
        uplift = 0
    return min(effective_legal + uplift, AXLE_CAP_LBS[truck["axle_config"]])


def ticket_net_tons(gross_weight_lbs, tare_weight_lbs, defect_deduction_pct):
    """PRD 3.7 -- deduct in whole pounds first, convert to tons afterwards."""
    net_weight_lbs = int(gross_weight_lbs) - int(tare_weight_lbs)
    defect_deducted_lbs = rhu_int(D(net_weight_lbs) * D(defect_deduction_pct))
    payable_lbs = net_weight_lbs - defect_deducted_lbs
    net_tons = tons(D(payable_lbs) / D(LBS_PER_TON))
    return net_weight_lbs, defect_deducted_lbs, payable_lbs, net_tons


def rate_band(distance_miles):
    if distance_miles <= RATE_BAND_1_MAX_MILES:
        return RATE_BAND_1_CENTS
    if distance_miles <= RATE_BAND_2_MAX_MILES:
        return RATE_BAND_2_CENTS
    return RATE_BAND_3_CENTS


def load_haul_pay(net_tons, distance_miles, wait_minutes=0, regrade_applies=False):
    """PRD 3.6 / 3.8 -- one pass; the incentive tier keys on the subtotal."""
    rate = rate_band(int(distance_miles))
    line_haul_cents = rhu_int(D(net_tons) * D(rate) * D(int(distance_miles)))
    fuel_surcharge_cents = rhu_int(D(line_haul_cents) * FUEL_SURCHARGE_PCT)
    demurrage_cents = max(0, int(wait_minutes) - FREE_WAIT_MINUTES) * DEMURRAGE_CENTS_PER_MINUTE
    subtotal_cents = line_haul_cents + fuel_surcharge_cents + demurrage_cents
    if subtotal_cents >= INCENTIVE_TIER_2_MIN_CENTS:
        incentive_pct = INCENTIVE_TIER_2_PCT
    elif subtotal_cents >= INCENTIVE_TIER_1_MIN_CENTS:
        incentive_pct = INCENTIVE_TIER_1_PCT
    else:
        incentive_pct = D("0.00")
    incentive_cents = rhu_int(D(subtotal_cents) * incentive_pct)
    if regrade_applies:
        regrade_adjustment_cents = rhu_int(D(line_haul_cents) * REGRADE_PENALTY_PCT)
    else:
        regrade_adjustment_cents = 0
    haul_pay_cents = subtotal_cents + incentive_cents - regrade_adjustment_cents
    return {
        "rate_cents_per_ton_mile": rate,
        "line_haul_cents": line_haul_cents,
        "fuel_surcharge_cents": fuel_surcharge_cents,
        "demurrage_cents": demurrage_cents,
        "incentive_cents": incentive_cents,
        "regrade_adjustment_cents": regrade_adjustment_cents,
        "haul_pay_cents": haul_pay_cents,
    }


def holdback_pct_for(score):
    if score >= HOLDBACK_TIER_A_MIN_SCORE:
        return HOLDBACK_TIER_A_PCT
    if score >= HOLDBACK_TIER_B_MIN_SCORE:
        return HOLDBACK_TIER_B_PCT
    if score >= HOLDBACK_TIER_C_MIN_SCORE:
        return HOLDBACK_TIER_C_PCT
    return HOLDBACK_TIER_D_PCT


def reject_deduction_cents(provisional_haul_pay_cents):
    return rhu_int(D(provisional_haul_pay_cents) * REJECT_DEDUCTION_PCT)


def rehaul_net_yield_cents(base_rate_cents_per_ton, net_tons, distance_miles):
    revenue = rhu_int(D(base_rate_cents_per_ton) * D(net_tons))
    return revenue - int(distance_miles) * REHAUL_MILE_COST_CENTS


def rehaul_travel_minutes(distance_miles):
    return int(math.ceil(int(distance_miles) * 60 / float(REHAUL_SPEED_MPH)))
