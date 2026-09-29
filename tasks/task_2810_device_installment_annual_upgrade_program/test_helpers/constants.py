"""Domain thresholds, the reference catalog fixture, and cents/clock utilities.

Every monetary value in this module is an integer count of cents, exactly as the
PRD requires. Nothing here is a float.
"""
import calendar
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

# --- The logical clock ----------------------------------------------------
# "Before any call moves it, the logical clock reads exactly 2026-08-01T00:00:00Z".
CLOCK_ORIGIN = "2026-08-01T00:00:00Z"

# --- Credit decision ------------------------------------------------------
CREDIT_LIMITS = {"PRIME": 250_000, "NEAR_PRIME": 150_000, "SUBPRIME": 80_000}
CONDITIONAL_BAND_BPS = 12_500

# --- Servicing calendar ---------------------------------------------------
GRACE_PERIOD_DAYS = 10
DELINQUENT_MIN_DPD = 11
DEFAULT_MIN_DPD = 90
LATE_FEE_CENTS = 500

# --- Payoff quotes --------------------------------------------------------
PRORATA_REBATE_BPS = 9_000
CANCELLATION_ADMIN_FEE_CENTS = 2_500
QUOTE_VALIDITY_DAYS = 7

# --- Trade-in grading ----------------------------------------------------
CONDITION_MULTIPLIERS_BPS = {"EXCELLENT": 10_000, "GOOD": 8_500, "FAIR": 6_000, "POOR": 3_000}
SCREEN_DEDUCTION_CENTS = {"PRISTINE": 0, "SCRATCHED": 2_500, "CRACKED": 9_500}
BATTERY_DEDUCTION_AT_OR_ABOVE_80_CENTS = 0
BATTERY_DEDUCTION_60_TO_79_CENTS = 4_000
BATTERY_DEDUCTION_BELOW_60_CENTS = 8_000
DIAGNOSTIC_FAIL_CREDIT_BPS = 1_000
TRADE_IN_CREDIT_FLOOR_CENTS = 0
MAX_TRADE_IN_DISPUTES = 2
CREDIT_BAND_DOWNGRADE_LADDER = {
    "PRIME": "NEAR_PRIME",
    "NEAR_PRIME": "SUBPRIME",
    "SUBPRIME": "SUBPRIME",
}

# --- Upgrade, unlock, reservation ----------------------------------------
UPGRADE_PAID_RATIO_BPS = 5_000
UPGRADE_MIN_LOAN_AGE_DAYS = 330
UNLOCK_MIN_PAID_INSTALLMENTS = 6
FULFILLMENT_WINDOW_DAYS = 7

# --- Successor loan origination fee tiers --------------------------------
ORIGINATION_FEE_TIER_1_MAX = 60_000
ORIGINATION_FEE_TIER_2_MAX = 100_000
ORIGINATION_FEE_TIER_1_CENTS = 0
ORIGINATION_FEE_TIER_2_CENTS = 1_500
ORIGINATION_FEE_TIER_3_CENTS = 2_500
ROLLOVER_SHORTFALL_LIMIT_CENTS = 30_000

DEFAULT_TERM_MONTHS = 24

THRESHOLDS = {
    "GRACE_PERIOD_DAYS": GRACE_PERIOD_DAYS,
    "DELINQUENT_MIN_DPD": DELINQUENT_MIN_DPD,
    "DEFAULT_MIN_DPD": DEFAULT_MIN_DPD,
    "LATE_FEE_CENTS": LATE_FEE_CENTS,
    "UPGRADE_PAID_RATIO_BPS": UPGRADE_PAID_RATIO_BPS,
    "UPGRADE_MIN_LOAN_AGE_DAYS": UPGRADE_MIN_LOAN_AGE_DAYS,
    "UNLOCK_MIN_PAID_INSTALLMENTS": UNLOCK_MIN_PAID_INSTALLMENTS,
    "FULFILLMENT_WINDOW_DAYS": FULFILLMENT_WINDOW_DAYS,
    "QUOTE_VALIDITY_DAYS": QUOTE_VALIDITY_DAYS,
    "ROLLOVER_SHORTFALL_LIMIT_CENTS": ROLLOVER_SHORTFALL_LIMIT_CENTS,
    "MAX_TRADE_IN_DISPUTES": MAX_TRADE_IN_DISPUTES,
}

# --- The reference catalog fixture ---------------------------------------
# "Handset B" is the financed model used by most setups; "Handset A" is the
# upgrade target. All amounts are integer cents.
MODEL_B = {
    "display_name": "Handset B",
    "retail_price_cents": 89_900,
    "monthly_protection_premium_cents": 999,
    "trade_in_base_credit_cents": 45_000,
    "generation_year": 2026,
}
MODEL_A = {
    "display_name": "Handset A",
    "retail_price_cents": 119_900,
    "monthly_protection_premium_cents": 1_199,
    "trade_in_base_credit_cents": 60_000,
    "generation_year": 2027,
    "concurrent_reservation_capacity": 2,
}

# Derived facts about a 24-month loan on Handset B with no down payment:
#   principal_cents 89900; base principal component 3746; installment 24 -> 3742;
#   amount_due 4745 per installment (installment 24 -> 4741);
#   premium_total_cents 23976; obligation_balance_cents 113876.
MODEL_B_LOAN_PRINCIPAL_CENTS = 89_900
MODEL_B_BASE_PRINCIPAL_COMPONENT_CENTS = 3_746
MODEL_B_LAST_PRINCIPAL_COMPONENT_CENTS = 3_742
MODEL_B_MONTHLY_INSTALLMENT_CENTS = 4_745
MODEL_B_LAST_INSTALLMENT_AMOUNT_CENTS = 4_741
MODEL_B_PREMIUM_TOTAL_CENTS = 23_976
MODEL_B_OBLIGATION_BALANCE_CENTS = 113_876

TEST_DEFAULTS = {
    "MODEL_B_RETAIL_PRICE_CENTS": 89_900,
    "MODEL_A_RETAIL_PRICE_CENTS": 119_900,
    "TERM_MONTHS": 24,
    "MONTHLY_INSTALLMENT_CENTS": MODEL_B_MONTHLY_INSTALLMENT_CENTS,
}


# --- Cents arithmetic -----------------------------------------------------
def round_half_up(numerator: int, denominator: int) -> int:
    """Integer division rounded half up, as the PRD's rounding discipline requires."""
    return int((Decimal(numerator) / Decimal(denominator)).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP))


def apply_bps(amount_cents: int, bps: int) -> int:
    """amount * bps / 10000, rounded half up to whole cents."""
    return round_half_up(amount_cents * bps, 10_000)


def floor_div(numerator: int, denominator: int) -> int:
    """Truncating (floor) division, used for every basis-point ratio."""
    return numerator // denominator


# --- Logical clock arithmetic --------------------------------------------
def parse_iso(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant, tolerating 'Z' and any sub-second width."""
    assert isinstance(value, str) and value, f"expected an ISO 8601 string, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def iso(moment: datetime) -> str:
    """Render a datetime as an ISO 8601 UTC instant with three fractional digits."""
    moment = moment.astimezone(timezone.utc)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def iso_norm(value: str) -> str:
    """Canonical form of an ISO 8601 UTC instant: sub-second precision normalised
    to exactly three fractional digits so '...:00Z' and '...:00.000Z' compare equal."""
    return iso(parse_iso(value))


def iso_equal(left: str, right: str) -> bool:
    """True when both instants denote the same moment, whatever their precision."""
    return parse_iso(left) == parse_iso(right)


def plus_days(value: str, days: int) -> str:
    """The instant `days` whole days after `value`."""
    return iso(parse_iso(value) + timedelta(days=days))


def plus_months(value: str, months: int) -> str:
    """`value` advanced by whole calendar months, preserving day-of-month and
    clamping to the last day of the target month where that day does not exist."""
    base = parse_iso(value)
    total = base.month - 1 + months
    year = base.year + total // 12
    month = total % 12 + 1
    day = min(base.day, calendar.monthrange(year, month)[1])
    return iso(base.replace(year=year, month=month, day=day))


def at_midnight(value: str) -> str:
    """`value` normalised to 00:00:00.000Z on its own UTC calendar date."""
    base = parse_iso(value)
    return iso(base.replace(hour=0, minute=0, second=0, microsecond=0))


def day_diff(later: str, earlier: str) -> int:
    """Whole-day difference between two UTC calendar dates."""
    return (parse_iso(later).date() - parse_iso(earlier).date()).days


def due_date_for(origination_date: str, installment_number: int) -> str:
    """The due_date the PRD's schedule generator assigns to one installment:
    origination_date advanced by installment_number calendar months, normalised
    to 00:00:00.000Z."""
    return at_midnight(plus_months(origination_date, installment_number))


def expected_condition_multiplier_bps(condition: str) -> int:
    return CONDITION_MULTIPLIERS_BPS[condition]


def expected_battery_deduction_cents(battery_health_pct: int) -> int:
    if battery_health_pct >= 80:
        return BATTERY_DEDUCTION_AT_OR_ABOVE_80_CENTS
    if battery_health_pct >= 60:
        return BATTERY_DEDUCTION_60_TO_79_CENTS
    return BATTERY_DEDUCTION_BELOW_60_CENTS


def expected_origination_fee_cents(pre_fee_base_cents: int) -> int:
    """The tiered successor-loan fee, keyed on the pre-fee base and nothing else."""
    if pre_fee_base_cents < ORIGINATION_FEE_TIER_1_MAX:
        return ORIGINATION_FEE_TIER_1_CENTS
    if pre_fee_base_cents < ORIGINATION_FEE_TIER_2_MAX:
        return ORIGINATION_FEE_TIER_2_CENTS
    return ORIGINATION_FEE_TIER_3_CENTS


def expected_schedule_components(principal_cents: int, term_months: int):
    """(base_component_cents, last_component_cents) for one loan's schedule."""
    base = round_half_up(principal_cents, term_months)
    last = principal_cents - base * (term_months - 1)
    return base, last


def unearned_premium_rule_of_78(premium_total_cents: int, term_months: int,
                                paid_installment_count: int) -> int:
    """Rule-of-78 unearned premium, rounded half up to whole cents."""
    unexpired = term_months - paid_installment_count
    return round_half_up(premium_total_cents * unexpired * (unexpired + 1),
                         term_months * (term_months + 1))


def unearned_premium_pro_rata(premium_total_cents: int, paid_premium_cents: int) -> int:
    """Straight-line unearned premium: the total premium less what has been paid."""
    return premium_total_cents - paid_premium_cents
