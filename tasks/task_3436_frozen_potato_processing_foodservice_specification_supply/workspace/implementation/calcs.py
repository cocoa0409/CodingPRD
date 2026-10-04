"""Pure calculation rules (scaffold section 1.3 / PRD section 3).

All money math uses exact Decimals; rounding is round-half-up everywhere.
Two rounding orders are pinned: per-lot rounding for lot payments (contract
totals sum already-rounded lots, never re-round), and per-line rounding for
shipment invoice/credit amounts (lines rounded then summed).
"""

from decimal import Decimal

from constants import (
    BYPRODUCT_TARIFF,
    DEFECT_A_MAX,
    DEFECT_B_MAX,
    DAILY_LOSS_PCT,
    DOWNGRADE_LOSS_PCT,
    EXCURSION_DISCOUNT_MULT,
    GRADE_MULT,
    GRAVITY_A_MIN,
    GRAVITY_B_MIN,
    GRAVITY_C_MIN,
    MAX_LOSS_PCT,
    POSTURE_FACTOR,
    QUARANTINE_DISEASE_PCT,
    QUARANTINE_SPROUT,
    REJECT_DEFECT_PCT,
    REWORK_RETENTION,
    SALVAGE_CREDIT_MULT,
    SUGAR_A_MAX,
    SUGAR_B_MAX,
    SUGAR_C_MAX,
    WATCH_DISEASE_PCT,
    WATCH_SPROUT,
    YIELD_CASES_PER_CWT,
)
from util import D, floor_int, round_half_up

_TIER_RANK = {"A": 0, "B": 1, "C": 2, "REJECT": 3}
_DOWNGRADE = {"A": "B", "B": "C", "C": "C", "REJECT": "REJECT"}


# ------------------------------------------------------------ lot receiving

def compute_net_weight(gross_cwt, tare_cwt):
    """net_weight_cwt = round_half_up(gross - tare, 2)."""
    return round_half_up(gross_cwt - tare_cwt, 2)


def compute_grade(defect_pct, specific_gravity, sugar_end_rating):
    """lot_quality_grade: defect override first, then worst of three tiers."""
    defect = D(defect_pct)
    gravity = D(specific_gravity)
    sugar = D(sugar_end_rating)

    if defect >= Decimal(REJECT_DEFECT_PCT):
        return "REJECT"

    if defect < Decimal(DEFECT_A_MAX):
        defect_tier = "A"
    elif defect < Decimal(DEFECT_B_MAX):
        defect_tier = "B"
    else:
        defect_tier = "C"

    if gravity >= Decimal(GRAVITY_A_MIN):
        gravity_tier = "A"
    elif gravity >= Decimal(GRAVITY_B_MIN):
        gravity_tier = "B"
    elif gravity >= Decimal(GRAVITY_C_MIN):
        gravity_tier = "C"
    else:
        gravity_tier = "REJECT"

    if sugar <= Decimal(SUGAR_A_MAX):
        sugar_tier = "A"
    elif sugar <= Decimal(SUGAR_B_MAX):
        sugar_tier = "B"
    elif sugar <= Decimal(SUGAR_C_MAX):
        sugar_tier = "C"
    else:
        sugar_tier = "REJECT"

    return max((defect_tier, gravity_tier, sugar_tier), key=lambda t: _TIER_RANK[t])


def grade_mult(grade):
    return Decimal(GRADE_MULT[grade])


def provisional_payment(net_weight_cwt, base_price_per_cwt_cents, grade):
    """round_half_up(net * base_price * GRADE_MULT[grade], 0) — per-lot rounded."""
    return int(round_half_up(
        net_weight_cwt * Decimal(base_price_per_cwt_cents) * grade_mult(grade), 0
    ))


# ------------------------------------------------------- contract settlement

def storage_loss_pct(days_in_storage, posture):
    """min(days * 0.02 * posture_factor, 15.0), rounded half-up to 2dp."""
    raw = Decimal(days_in_storage) * Decimal(DAILY_LOSS_PCT) * Decimal(POSTURE_FACTOR[posture])
    return round_half_up(min(raw, Decimal(MAX_LOSS_PCT)), 2)


def downgrade_tier(grade):
    return _DOWNGRADE[grade]


def shrinkage_cwt(net_weight_cwt, storage_loss):
    return round_half_up(net_weight_cwt * storage_loss / Decimal(100), 2)


def final_payment(final_net_cwt, base_price_per_cwt_cents, final_grade):
    return int(round_half_up(
        final_net_cwt * Decimal(base_price_per_cwt_cents) * grade_mult(final_grade), 0
    ))


def loss_exceeds_downgrade_threshold(storage_loss):
    return storage_loss > Decimal(DOWNGRADE_LOSS_PCT)


# ---------------------------------------------------------- facility posture

def posture_from_reading(reading):
    """facility_posture from one reading (the latest). Boundaries inclusive."""
    disease = D(reading["disease_incidence_pct"])
    sprout = D(reading["sprout_index"])
    if disease >= Decimal(QUARANTINE_DISEASE_PCT) or sprout >= Decimal(QUARANTINE_SPROUT):
        return "QUARANTINED"
    if disease >= Decimal(WATCH_DISEASE_PCT) or sprout >= Decimal(WATCH_SPROUT):
        return "WATCH"
    return "NORMAL"


# ------------------------------------------------------------- run yields

def actual_cases_first_pass(total_input_cwt, cut_family):
    return floor_int(total_input_cwt * Decimal(YIELD_CASES_PER_CWT[cut_family]))


def actual_cases_rework_pass(previous_actual_cases):
    return floor_int(Decimal(previous_actual_cases) * Decimal(REWORK_RETENTION))


# ------------------------------------------------------ shipment billing

def invoice_cents(lines, price_per_case_cents, excursion_flag):
    """Per-line rounding pinned: each line rounded half-up to whole cents,
    then the rounded lines are summed."""
    total = 0
    mult = Decimal(EXCURSION_DISCOUNT_MULT) if excursion_flag else None
    for line in lines:
        line_amt = Decimal(line["cases"]) * Decimal(price_per_case_cents)
        if mult is not None:
            line_amt = line_amt * mult
        total += int(round_half_up(line_amt, 0))
    return total


def credit_memo_cents(lines, price_per_case_cents):
    total = 0
    mult = Decimal(SALVAGE_CREDIT_MULT)
    for line in lines:
        line_amt = Decimal(line["cases"]) * Decimal(price_per_case_cents) * mult
        total += int(round_half_up(line_amt, 0))
    return total


# ------------------------------------------------------------- fill rate

def fill_rate_pct(delivered_cases, rejected_cases):
    """round_half_up(100 * delivered / (delivered + rejected), 1); None if the
    denominator is zero."""
    denom = delivered_cases + rejected_cases
    if denom == 0:
        return None
    return round_half_up(Decimal(100) * Decimal(delivered_cases) / Decimal(denom), 1)


# ------------------------------------------------------------ byproduct

def byproduct_total_revenue(weight_cwt, routing):
    return int(round_half_up(weight_cwt * Decimal(BYPRODUCT_TARIFF[routing]), 0))


def byproduct_unit_revenue(routing):
    return BYPRODUCT_TARIFF[routing]
