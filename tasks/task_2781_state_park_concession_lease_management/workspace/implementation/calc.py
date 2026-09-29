"""Every calculation rule, with its rounding locations pinned."""
from decimal import Decimal

from money import (add_days, add_years, dec, inclusive_days, month_span_inclusive,
                   pct_of, rhu, rhu_int, whole_months)

# --- constants -------------------------------------------------------------
MIN_VIABLE_ANNUAL_RECEIPTS_CENTS = 10000000
MARKET_CAPTURE_MAX_PCT = Decimal("200.00")

BOND_MAG_FACTOR_PCT = Decimal("25.00")
BOND_CAPEX_FACTOR_PCT = Decimal("10.00")
BOND_FLOOR_CENTS = 2500000
BOND_LONG_TERM_MULTIPLIER = Decimal("1.50")
BOND_LONG_TERM_YEARS = 10
BOND_SUFFICIENCY_PCT = Decimal("50.00")

REQUIRED_PANELIST_COUNT = 2
MAX_REVISION_ROUNDS = 2

CATEGORY_DIFF_LODGING_PCT = Decimal("1.50")
CATEGORY_DIFF_FOOD_PCT = Decimal("0.00")
CATEGORY_DIFF_RETAIL_PCT = Decimal("-0.50")
CATEGORY_DIFF_ACTIVITY_PCT = Decimal("2.00")

MAINTENANCE_RESERVE_PCT = Decimal("0.50")

TIER1_CEILING_CENTS = 50000000
TIER2_CEILING_CENTS = 150000000
TIER2_UPLIFT_PCT = Decimal("2.50")
TIER3_UPLIFT_PCT = Decimal("5.00")
DAYS_IN_MAG_YEAR = 365
RECONCILIATION_GRACE_DAYS = 30

UNDERREPORT_PENALTY_THRESHOLD_PCT = Decimal("5.00")
UNDERREPORT_PENALTY_PCT = Decimal("10.00")
INTEREST_PCT_PER_MONTH = Decimal("1.00")
DEFICIENCY_NOTICE_THRESHOLD_CENTS = 2000000
CURE_PERIOD_DAYS = 30

MAX_OVERLAPPING_PARK_CLOSURES = 2
RATE_CEILING_MULTIPLIER = Decimal("1.15")

TRANSFER_ADMIN_FEE_PCT = Decimal("3.00")

CRITERIA = (
    ("score_experience", "weight_experience"),
    ("score_operating_plan", "weight_operating_plan"),
    ("score_capital_investment", "weight_capital_investment"),
    ("score_financial_capacity", "weight_financial_capacity"),
    ("score_fee_offer", "weight_fee_offer"),
)


# --- market analysis -------------------------------------------------------
def market_projection(comparable_cents, capture_pct):
    return pct_of(comparable_cents, capture_pct)


# --- lease calendar --------------------------------------------------------
def term_end(term_start, term_years):
    return add_days(add_years(term_start, term_years), -1)


def lease_year_window(term_start, n):
    start = add_years(term_start, n - 1)
    end = add_days(add_years(term_start, n), -1)
    return start, end


def lease_year_number(term_start, term_years, day):
    """The 1-based index of the lease year whose closed window contains `day`."""
    for n in range(1, max(term_years, 1) + 61):
        start, end = lease_year_window(term_start, n)
        if start <= day <= end:
            return n
        if start > day:
            break
    return 1


# --- performance bond ------------------------------------------------------
def required_bond_amount(mag_cents, capex_cents, term_years):
    mag_component = pct_of(mag_cents, BOND_MAG_FACTOR_PCT)
    capex_component = pct_of(capex_cents, BOND_CAPEX_FACTOR_PCT)
    base = max(mag_component, capex_component, BOND_FLOOR_CENTS)
    if term_years > BOND_LONG_TERM_YEARS:
        return rhu_int(dec(base) * BOND_LONG_TERM_MULTIPLIER)
    return base


def bond_sufficiency_floor(required_amount_cents):
    return pct_of(required_amount_cents, BOND_SUFFICIENCY_PCT)


# --- panel scoring ---------------------------------------------------------
def composite_score(evaluations, prospectus):
    count = len(evaluations)
    if count == 0:
        return None
    if prospectus["scoring_mode"] == "PER_CRITERION_ROUNDING":
        total = Decimal("0.00")
        for score_field, weight_field in CRITERIA:
            raw_mean = Decimal(sum(e[score_field] for e in evaluations)) / Decimal(count)
            criterion_mean = rhu(raw_mean, 2)
            contribution = rhu(criterion_mean * Decimal(prospectus[weight_field]) / Decimal(100), 2)
            total = total + contribution
        return total
    total = Decimal(0)
    for score_field, weight_field in CRITERIA:
        raw_mean = Decimal(sum(e[score_field] for e in evaluations)) / Decimal(count)
        total = total + raw_mean * Decimal(prospectus[weight_field]) / Decimal(100)
    return rhu(total, 2)


# --- period franchise fee --------------------------------------------------
def period_fee(base_fee_pct, lodging, food_beverage, retail, activity):
    base = dec(base_fee_pct)
    fee = pct_of(lodging, base + CATEGORY_DIFF_LODGING_PCT)
    fee = fee + pct_of(food_beverage, base + CATEGORY_DIFF_FOOD_PCT)
    fee = fee + pct_of(retail, base + CATEGORY_DIFF_RETAIL_PCT)
    fee = fee + pct_of(activity, base + CATEGORY_DIFF_ACTIVITY_PCT)
    return fee


def maintenance_reserve_due(total_receipts_cents):
    return pct_of(total_receipts_cents, MAINTENANCE_RESERVE_PCT)


# --- annual reconciliation -------------------------------------------------
def tiered_annual_fee(annual_gross_cents, base_fee_pct):
    base = dec(base_fee_pct)
    slice1 = min(annual_gross_cents, TIER1_CEILING_CENTS)
    slice2 = max(0, min(annual_gross_cents, TIER2_CEILING_CENTS) - TIER1_CEILING_CENTS)
    slice3 = max(0, annual_gross_cents - TIER2_CEILING_CENTS)
    fee = pct_of(slice1, base)
    fee = fee + pct_of(slice2, base + TIER2_UPLIFT_PCT)
    fee = fee + pct_of(slice3, base + TIER3_UPLIFT_PCT)
    return fee


def mag_applied(lease, ly_start, ly_end, term_start):
    """Full guarantee for an exact lease-year window; prorated otherwise."""
    guarantee = lease["minimum_annual_guarantee_cents"]
    number = lease_year_number(term_start, lease["term_years"], ly_start)
    exact_start, exact_end = lease_year_window(term_start, number)
    if ly_start == exact_start and ly_end == exact_end:
        return guarantee
    days = inclusive_days(ly_start, ly_end)
    return rhu_int(dec(guarantee) * Decimal(days) / Decimal(DAYS_IN_MAG_YEAR))


def report_receipts(report):
    if report["status"] == "RESTATED":
        return report["restated_receipts_cents"] or 0
    return report["total_receipts_cents"]


def penalty_amount(base_delta_cents, penalty_applies):
    if penalty_applies and base_delta_cents > 0:
        return pct_of(base_delta_cents, UNDERREPORT_PENALTY_PCT)
    return 0


def interest_amount(base_delta_cents, due_date, clock_date):
    if base_delta_cents <= 0:
        return 0
    months = whole_months(due_date, clock_date)
    return rhu_int(dec(base_delta_cents) * INTEREST_PCT_PER_MONTH / Decimal(100) * Decimal(months))


# --- audit ----------------------------------------------------------------
def underreport_pct(reported_cents, adjusted_cents):
    if reported_cents == 0:
        return Decimal("0.00")
    return rhu(Decimal(adjusted_cents - reported_cents) * Decimal(100) / Decimal(reported_cents), 2)


def penalty_applies(pct_value):
    return dec(pct_value) >= UNDERREPORT_PENALTY_THRESHOLD_PCT


def allocate_restatement(reports, reported_total, adjusted_total):
    """Proportional allocation; the chronologically last report absorbs the
    remainder so the restated figures sum to `adjusted_total` exactly."""
    shares = []
    running = 0
    for index, report in enumerate(reports):
        if index == len(reports) - 1:
            shares.append(adjusted_total - running)
        else:
            if reported_total == 0:
                share = 0
            else:
                share = rhu_int(dec(adjusted_total) * dec(report["total_receipts_cents"])
                                / dec(reported_total))
            shares.append(share)
            running = running + share
    return shares


# --- improvements and close-out -------------------------------------------
def unamortized_value(approved_cost_cents, in_service_date, term_end_date, useful_life_years):
    useful_life_months = useful_life_years * 12
    if useful_life_months <= 0 or in_service_date is None or approved_cost_cents is None:
        return 0
    months_elapsed = month_span_inclusive(in_service_date, term_end_date)
    months_elapsed = min(max(months_elapsed, 0), useful_life_months)
    amortized = rhu_int(dec(approved_cost_cents) * Decimal(months_elapsed)
                        / Decimal(useful_life_months))
    return max(approved_cost_cents - amortized, 0)


def transfer_settlement(gross_cents, outstanding_cents):
    admin_fee = pct_of(gross_cents, TRANSFER_ADMIN_FEE_PCT)
    raw_net = gross_cents - admin_fee - outstanding_cents
    return max(raw_net, 0), max(-raw_net, 0)


def rate_ceiling(benchmark_cents):
    return rhu_int(dec(benchmark_cents) * RATE_CEILING_MULTIPLIER)
