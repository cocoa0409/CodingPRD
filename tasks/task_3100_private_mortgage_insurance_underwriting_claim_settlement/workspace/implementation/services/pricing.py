"""Pricing: loan-to-value banding, rate-card lookup, coverage base, premiums.

Implements calculations `rate_lookup`, `borrower_monthly_premium`,
`single_premium` and `annual_premium_interest` from SCAFFOLD section 1.3 and the
matching prose in PRD 3.2 / 3.3.
"""

from common import (
    ceil_int,
    clock_dt,
    d,
    floor_int,
    parse_utc,
    round4,
    round_half_up_int,
)

ALLOWED_COVERAGE_PERCENTS = (12, 25, 30)
CREDIT_GRADES = ("A", "B", "C", "D")
CREDIT_ORDINAL = {"A": 0, "B": 1, "C": 2, "D": 3}
LTV_BANDS = ("831_TO_85", "851_TO_90", "901_TO_95")

# SCAFFOLD single_premium constants.
TERM_MONTHS = 120
PRESENT_VALUE_FACTOR = 0.92

# SCAFFOLD annual_premium_interest: master-policy constant, not a loan field.
MASTER_POLICY_PREMIUM_INTEREST_RATE = 0.0450


def loan_to_value(loan_amount_cents, property_value_cents):
    """100 * note amount / appraised value, carried to 4dp, rounded half up."""
    if not property_value_cents:
        return None
    return round4(d(loan_amount_cents) * 100 / d(property_value_cents))


def ltv_band_for(ltv):
    """Upper bound inclusive, lower bound exclusive (PRD 3.2)."""
    if ltv <= 85.0:
        return "831_TO_85"
    if ltv <= 90.0:
        return "851_TO_90"
    if ltv <= 95.0:
        return "901_TO_95"
    return None


def coverage_base_cents(loan_amount_cents, coverage_percent):
    """floor(note amount * coverage percent / 100) - never rounded up."""
    return floor_int(d(loan_amount_cents) * d(coverage_percent) / 100)


def find_rate_card(db, master_policy_id, credit_grade, ltv, coverage_percent, premium_plan):
    band = ltv_band_for(ltv)
    for card in db.rate_cards.values():
        if card["master_policy_id"] != master_policy_id:
            continue
        if card["credit_grade"] != credit_grade:
            continue
        if card["ltv_band"] != band:
            continue
        if card["coverage_percent"] != coverage_percent:
            continue
        if card["premium_plan"] != premium_plan:
            continue
        return card
    return None


# --- borrower monthly premium -------------------------------------------------

def compute_borrower_monthly_premium(base_upb_cents, rate_bps_applied):
    """The pinned rounding order of PRD 3.3 / SCAFFOLD borrower_monthly_premium:
    the annual amount is rounded ONCE, the periodic amount is the ceiling of the
    annual amount over twelve, and the twelfth period absorbs the remainder.
    """
    annual = round_half_up_int(d(base_upb_cents) * d(rate_bps_applied) / 10000)
    monthly = ceil_int(d(annual) / 12)
    final = annual - 11 * monthly
    return annual, monthly, final


def compute_single_premium(base_upb_cents, rate_bps_applied, financed_premium):
    """SPM: an annuity over the term when financed into the note, otherwise a
    plain one-time premium. Both forms ceiling rather than round."""
    if financed_premium:
        value = (
            d(base_upb_cents)
            * d(rate_bps_applied)
            / 10000
            * d(TERM_MONTHS)
            / 12
            * d(PRESENT_VALUE_FACTOR)
        )
        return ceil_int(value)
    return ceil_int(d(base_upb_cents) * d(rate_bps_applied) / 10000)


def compute_annual_premium_interest(annual_premium_cents):
    """Simple interest on the whole annual premium at the master-policy rate."""
    return round_half_up_int(d(annual_premium_cents) * d(MASTER_POLICY_PREMIUM_INTEREST_RATE))


# --- effective coverage percentage on the non-delegated approval --------------

def effective_coverage_percent(application, card, grade_worse, reserves_short,
                               policy_minimum, requested):
    """PRD 3.1: five points per failing condition, added rather than compounded,
    and floored at the lowest coverage percentage the master policy permits -
    the application is approved at the minimum rather than declined."""
    effective = requested
    if grade_worse:
        effective -= 5
    if reserves_short:
        effective -= 5
    if effective < policy_minimum:
        return policy_minimum
    return effective


def grade_worse_than_card(application_grade, card_grade):
    return CREDIT_ORDINAL.get(application_grade, 0) > CREDIT_ORDINAL.get(card_grade, 0)


def as_dt(value):
    if value is None:
        return None
    return parse_utc(value)


def current_clock():
    return clock_dt()