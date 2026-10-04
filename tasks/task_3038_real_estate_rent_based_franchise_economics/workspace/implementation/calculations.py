"""Business calculations per SCAFFOLD 1.3 / PRD 3.

All monetary results are whole cents via round-half-up. Rounding order is
pinned by the PRD and implemented literally:

- escalated base rent: single composite rounding of
  base * (1 + escalation_rate) ** escalation_count (iterative rounding forbidden)
- monthly royalty split: occupancy share rounds FIRST; royalty base is the
  un-rounded remainder; royalty and ad-fund round per line from the remainder
- capacity composite: round-half-up on the final weighted sum only
"""

from datetime import date, timedelta
from decimal import Decimal

import store as st

RENEWAL_WINDOW_DAYS = 180

# operator_capacity_score constants (SCAFFOLD 1.3)
NET_WORTH_FULL_CREDIT = 200000000
OPM_FULL_CREDIT = Decimal("0.25")
PORTFOLIO_FULL_CREDIT = 10
DEFAULT_PENALTY = 30
REINVEST_PENALTY = 20
DELINQ_PENALTY = 20
DELINQ_FULL_PENALTY = 5000000

# reinvestment_min_spend constant
MIN_COVERAGE_RATE = Decimal("0.70")


# ---------------------------------------------------------------------------
# escalated_base_rent (SCAFFOLD 1.3)
# ---------------------------------------------------------------------------

def escalation_count(escalation_month, escalation_day, period_start, period_end):
    """Count anniversaries (month, day) inside [period_start, period_end],
    scanning each year from year(period_start) through year(period_end)."""
    count = 0
    for year in range(period_start.year, period_end.year + 1):
        try:
            d = date(year, escalation_month, escalation_day)
        except ValueError:
            continue
        if period_start <= d <= period_end:
            count += 1
    return count


def effective_base_rent_cents(base_rent_cents, escalation_rate, count):
    """round_half_up(base * (1 + rate) ** count) -- single composite rounding."""
    factor = (Decimal(1) + st.dec(escalation_rate)) ** count
    return st.round_half_up_cents(st.dec(base_rent_cents) * factor)


def percentage_rent_cents(annual_sales_cents, pct_rent_rate):
    return st.round_half_up_cents(st.dec(annual_sales_cents) * st.dec(pct_rent_rate))


# ---------------------------------------------------------------------------
# monthly_royalty_ad_split (SCAFFOLD 1.3) -- pinned rounding order
# ---------------------------------------------------------------------------

def monthly_royalty_ad_split(gross_sales_cents, occupancy_allocation_pct,
                             royalty_rate, ad_fund_rate):
    occupancy_share = st.round_half_up_cents(
        st.dec(gross_sales_cents) * st.dec(occupancy_allocation_pct)
    )
    royalty_sales = int(gross_sales_cents) - occupancy_share
    royalty = st.round_half_up_cents(st.dec(royalty_sales) * st.dec(royalty_rate))
    ad_fund = st.round_half_up_cents(st.dec(royalty_sales) * st.dec(ad_fund_rate))
    return {
        "occupancy_share_cents": occupancy_share,
        "royalty_sales_cents": royalty_sales,
        "royalty_cents": royalty,
        "ad_fund_cents": ad_fund,
    }


# ---------------------------------------------------------------------------
# operator_capacity_score (SCAFFOLD 1.3)
# ---------------------------------------------------------------------------

def capacity_score_components(operator, active_defaults_count, pending_reinvestment_count):
    """Compute the weighted composite score per SCAFFOLD 1.3.

    active_defaults_count / pending_reinvestment_count are counted at review
    submission time; delinquency and stores_operated_count are read from the
    operator's synchronously maintained aggregates.
    """
    net_worth = st.dec(operator["fy_net_worth_cents"])
    op_income = st.dec(operator["fy_operating_income_cents"])
    stores_open = st.dec(operator.get("stores_operated_count", 0))
    delinquency = st.dec(operator.get("delinquency_balance_cents", 0))

    net_component = Decimal(100) * min(Decimal(1), net_worth / Decimal(NET_WORTH_FULL_CREDIT))

    if net_worth > 0:
        margin = op_income / net_worth
    else:
        margin = Decimal(0)
    margin = max(Decimal(0), margin)
    opm_component = Decimal(100) * min(Decimal(1), margin / OPM_FULL_CREDIT)

    port_component = Decimal(100) * min(
        Decimal(1), stores_open / Decimal(PORTFOLIO_FULL_CREDIT)
    )

    delinq_ratio = min(Decimal(1), delinquency / Decimal(DELINQ_FULL_PENALTY))
    compliance = (
        Decimal(100)
        - Decimal(DEFAULT_PENALTY) * st.dec(active_defaults_count)
        - Decimal(REINVEST_PENALTY) * st.dec(pending_reinvestment_count)
        - Decimal(DELINQ_PENALTY) * delinq_ratio
    )

    composite = st.round_half_up_int(
        Decimal("0.35") * net_component
        + Decimal("0.25") * opm_component
        + Decimal("0.20") * port_component
        + Decimal("0.20") * compliance
    )
    # PRD 3.2: the composite is an integer from 0 to 100
    if composite < 0:
        composite = 0
    if composite > 100:
        composite = 100
    return composite


def grade_for_score(score):
    """Banded with low edge inclusive: >=80 STRONG, 60..79 ADEQUATE, 40..59 WEAK, <40 FAILING."""
    if score >= 80:
        return "STRONG"
    if score >= 60:
        return "ADEQUATE"
    if score >= 40:
        return "WEAK"
    return "FAILING"


def max_stores_for_grade(grade):
    return {"STRONG": 12, "ADEQUATE": 6, "WEAK": 2, "FAILING": 0}.get(grade, 0)


# ---------------------------------------------------------------------------
# reinvestment_min_spend (SCAFFOLD 1.3)
# ---------------------------------------------------------------------------

def min_spend_cents(required_budget_cents):
    return st.round_half_up_cents(st.dec(required_budget_cents) * MIN_COVERAGE_RATE)


# ---------------------------------------------------------------------------
# term_end_date (PRD 3.3): term_start_date + term_years, same calendar day
# minus one day.
# ---------------------------------------------------------------------------

def compute_term_end_date(term_start_date, term_years):
    start = st.parse_date(term_start_date)
    try:
        anniversary = start.replace(year=start.year + int(term_years))
    except ValueError:
        # Feb 29 -> Feb 28 on non-leap years
        anniversary = start.replace(year=start.year + int(term_years), day=28)
    return (anniversary - timedelta(days=1)).isoformat()
