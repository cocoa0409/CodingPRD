"""Domain constants: thresholds, windows and canonical scenario inputs.

Every value here is stated in the PRD — either as a literal or as business
prose ("exceeds 20 percent of its ``committed_cents``, rounded half-up"). The
pure helpers at the bottom mirror the PRD's pinned arithmetic so a boundary
test can compute its target without re-deriving the formula by hand.
"""

from decimal import Decimal, ROUND_HALF_UP
from typing import Dict

__all__ = [
    # logical clock
    "LOGICAL_CLOCK_START",
    "CLOCK_2026_09_02",
    "CLOCK_2026_10_01",
    "CLOCK_2026_10_05",
    "CLOCK_2026_10_10",
    "CLOCK_2026_11_20",
    "CLOCK_2026_11_30",
    "CLOCK_2026_12_05",
    "CLOCK_2027_01_15",
    "CLOCK_2027_02_05",
    "CLOCK_2027_04_10",
    "CLOCK_2027_12_01",
    "CLOCK_2028_06_05",
    "CLOCK_2029_01_15",
    "CLOCK_2031_01_05",
    # windows
    "SUBSCRIPTION_OPEN_DEFAULT",
    "SUBSCRIPTION_CLOSE_DEFAULT",
    "ROFR_WINDOW_DAYS_DEFAULT",
    "COMPLIANCE_PERIOD_MONTHS_DEFAULT",
    "CALL_BUFFER_DAYS",
    "EXIT_YEAR_DEFAULT",
    # fund thresholds
    "FUND_CLOSE_THRESHOLD_DEFAULT",
    "SUBSCRIPTION_SHORTFALL_BAND_PCT",
    "FUNDED_EQUITY_ZERO",
    # underwriting
    "QUALITY_UPLIFT_RATE",
    "SPONSOR_MONTHS_CAP",
    "SPONSOR_UPLIFT_DIVISOR",
    "DSCR_COMMIT_MIN",
    "ABSORPTION_COMMIT_MIN",
    "SPONSOR_EXPERIENCE_COMMIT_MIN",
    # capital call bands
    "BAND_FULL_DELIVERY",
    "BAND_NEAR_FULL",
    "BAND_PARTIAL",
    "ADJUSTER_FULL_DELIVERY",
    "ADJUSTER_NEAR_FULL",
    "ADJUSTER_PARTIAL",
    "ADJUSTER_SEVERE",
    # sponsor eligibility
    "COVERAGE_MIN_RATIO",
    "EXPERIENCE_MONTHS_MIN",
    "PROJECTS_COMPLETED_MIN",
    "SUSPENSION_ESCALATION_COUNT",
    # fund posture
    "FROZEN_DISTRESSED_COUNT",
    "FROZEN_FAILURE_COUNT",
    "WATCH_DISTRESSED_COUNT",
    # investor tier buckets
    "TIER_1_CEILING",
    "TIER_2_CEILING",
    "TIER_1_CAP",
    "TIER_2_CAP",
    "TIER_ORDER",
    # watch-list risk score
    "OCCUPANCY_WEIGHT",
    "DSCR_WEIGHT",
    "DSCR_CEILING",
    "RESERVE_TARGET_CENTS",
    "RESERVE_POINTS",
    "TERM_POINTS",
    "SCORE_FLOOR",
    "SCORE_CEILING",
    "RISK_COMPLIANT_MAX",
    "RISK_WATCH_MIN",
    "RISK_ESCALATE_MIN",
    # operating deficit coverage
    "MONTHS_DIVISOR",
    "COVERAGE_MONTHS_MIN",
    # exit pricing
    "EQUITY_STEP_UP",
    "SHORTFALL_SURCHARGE_PER_CALL",
    # pagination
    "DEFAULT_LIMIT",
    "MIN_LIMIT",
    "MAX_LIMIT",
    "DEFAULT_OFFSET",
    "PAGINATION_FIELDS",
    # canonical scenario inputs
    "SCENARIO",
    # helpers
    "round_half_up",
    "fund_close_threshold_cents",
    "shortfall_default_band_cents",
    "delivery_adjuster_band",
    "dscr_from",
    "operating_deficit_cents",
    "monthly_deficit_cents",
    "coverage_months",
]


# =============================================================================
# Logical clock (PRD §2.4)
# =============================================================================

#: The clock reads exactly this value at server startup and never tracks
#: wall-clock time.
LOGICAL_CLOCK_START = "2026-09-01T00:00:00Z"

# Convenience instants used by the setup scenarios.
CLOCK_2026_09_02 = "2026-09-02T00:00:00Z"
CLOCK_2026_10_01 = "2026-10-01T00:00:00Z"
CLOCK_2026_10_05 = "2026-10-05T00:00:00Z"
CLOCK_2026_10_10 = "2026-10-10T00:00:00Z"
CLOCK_2026_11_20 = "2026-11-20T00:00:00Z"
CLOCK_2026_11_30 = "2026-11-30T00:00:00Z"
CLOCK_2026_12_05 = "2026-12-05T00:00:00Z"
CLOCK_2027_01_15 = "2027-01-15T00:00:00Z"
CLOCK_2027_02_05 = "2027-02-05T00:00:00Z"
CLOCK_2027_04_10 = "2027-04-10T00:00:00Z"
CLOCK_2027_12_01 = "2027-12-01T00:00:00Z"
CLOCK_2028_06_05 = "2028-06-05T00:00:00Z"
CLOCK_2029_01_15 = "2029-01-15T00:00:00Z"
CLOCK_2031_01_05 = "2031-01-05T00:00:00Z"


# =============================================================================
# Windows and defaults
# =============================================================================

SUBSCRIPTION_OPEN_DEFAULT = "2026-09-01T00:00:00Z"
SUBSCRIPTION_CLOSE_DEFAULT = "2026-12-31T00:00:00Z"
ROFR_WINDOW_DAYS_DEFAULT = 90
COMPLIANCE_PERIOD_MONTHS_DEFAULT = 180
#: An ISSUED call must start at least this many days after the previous PAID or
#: DEFICIENT call's due date.
CALL_BUFFER_DAYS = 30
EXIT_YEAR_DEFAULT = 15


# =============================================================================
# Fund thresholds (PRD §3.3, §3.5)
# =============================================================================

#: ``close_threshold_pct`` applies when the client omits it.
FUND_CLOSE_THRESHOLD_DEFAULT = 0.85

#: A subscription whose accumulated shortfall exceeds this fraction of its
#: commitment — rounded half-up — becomes DEFAULTED.
SUBSCRIPTION_SHORTFALL_BAND_PCT = 0.20

FUNDED_EQUITY_ZERO = 0


# =============================================================================
# Underwriting (PRD §3.4)
# =============================================================================

QUALITY_UPLIFT_RATE = 0.10
SPONSOR_MONTHS_CAP = 120
SPONSOR_UPLIFT_DIVISOR = 10000.0
DSCR_COMMIT_MIN = 1.15
ABSORPTION_COMMIT_MIN = 0.60
SPONSOR_EXPERIENCE_COMMIT_MIN = 24


# =============================================================================
# Capital-call credit-delivery bands (PRD §3.5)
# =============================================================================

BAND_FULL_DELIVERY = 0.99
BAND_NEAR_FULL = 0.95
BAND_PARTIAL = 0.90
ADJUSTER_FULL_DELIVERY = 0.00
ADJUSTER_NEAR_FULL = 0.05
ADJUSTER_PARTIAL = 0.12
ADJUSTER_SEVERE = 0.20


# =============================================================================
# Sponsor eligibility (PRD §3.1)
# =============================================================================

COVERAGE_MIN_RATIO = 2.0
EXPERIENCE_MONTHS_MIN = 120
PROJECTS_COMPLETED_MIN = 5
SUSPENSION_ESCALATION_COUNT = 2


# =============================================================================
# Fund posture (PRD §3.8)
# =============================================================================

FROZEN_DISTRESSED_COUNT = 2
FROZEN_FAILURE_COUNT = 2
WATCH_DISTRESSED_COUNT = 1


# =============================================================================
# Investor tier buckets (PRD §3.2)
# =============================================================================

TIER_1_CEILING = 800_000_000
TIER_2_CEILING = 600_000_000
TIER_1_CAP = 300_000_000
TIER_2_CAP = 400_000_000

TIER_ORDER: Dict[str, int] = {"TIER_1": 1, "TIER_2": 2, "TIER_3": 3}


# =============================================================================
# Watch-list risk score (PRD §3.7)
# =============================================================================

OCCUPANCY_WEIGHT = 35
DSCR_WEIGHT = 30
DSCR_CEILING = 1.5
RESERVE_TARGET_CENTS = 50_000_000
RESERVE_POINTS = 20
TERM_POINTS = 15
SCORE_FLOOR = 0
SCORE_CEILING = 100
RISK_COMPLIANT_MAX = 70
RISK_WATCH_MIN = 70
RISK_ESCALATE_MIN = 85


# =============================================================================
# Operating deficit coverage (PRD §3.6)
# =============================================================================

MONTHS_DIVISOR = 12
COVERAGE_MONTHS_MIN = 12


# =============================================================================
# Exit option pricing (PRD §3.9)
# =============================================================================

EQUITY_STEP_UP = 1.05
SHORTFALL_SURCHARGE_PER_CALL = 0.01


# =============================================================================
# Pagination (PRD §2.3)
# =============================================================================

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0
PAGINATION_FIELDS = ("limit", "offset", "total_count", "has_more")


# =============================================================================
# Canonical scenario inputs
# =============================================================================
#
# These are the input literals the setup scenarios build from. They are inputs,
# never expected outputs — a test asserting a computed value must carry its own
# literal.

SCENARIO: Dict[str, Dict[str, object]] = {
    "developer_cedar": {
        "name": "Cedar Ridge Communities",
        "developer_type": "FOR_PROFIT",
        "sponsor_experience_months": 96,
        "projects_completed": 4,
        "net_worth_cents": 2_000_000_000,
        "liquid_assets_cents": 30_000_000,
    },
    "developer_willow": {
        "name": "Willow Bend Partners",
        "developer_type": "NONPROFIT",
        "sponsor_experience_months": 60,
        "projects_completed": 2,
        "net_worth_cents": 400_000_000,
        "liquid_assets_cents": 5_000_000,
    },
    "developer_riverstone": {
        "name": "Riverstone Housing Group",
        "developer_type": "FOR_PROFIT",
        "sponsor_experience_months": 60,
        "projects_completed": 3,
        "net_worth_cents": 2_000_000_000,
        "liquid_assets_cents": 40_000_000,
    },
    "investor_meridian": {
        "name": "Meridian Capital Group",
        "investor_type": "BANK",
        "committed_capacity_cents": 500_000_000,
        "risk_tier": "TIER_3",
    },
    "investor_northline": {
        "name": "Northline Mutual",
        "investor_type": "INSURANCE",
        "committed_capacity_cents": 500_000_000,
        "risk_tier": "TIER_2",
    },
    "investor_arbor": {
        "name": "Arbor Pension Trust",
        "investor_type": "PENSION",
        "committed_capacity_cents": 500_000_000,
        "risk_tier": "TIER_1",
    },
    "fund_iv": {
        "fund_name": "ECP Housing Fund IV",
        "target_equity_cents": 500_000_000,
        "price_per_credit_dollar": 0.9123,
        "target_yield_pct": 0.07,
        "close_threshold_pct": 0.85,
        "subscription_open_date": SUBSCRIPTION_OPEN_DEFAULT,
        "subscription_close_date": SUBSCRIPTION_CLOSE_DEFAULT,
    },
    "fund_v": {
        "fund_name": "ECP Housing Fund V",
        "target_equity_cents": 400_000_000,
        "price_per_credit_dollar": 0.9050,
        "target_yield_pct": 0.065,
        "close_threshold_pct": 0.85,
        "subscription_open_date": SUBSCRIPTION_OPEN_DEFAULT,
        "subscription_close_date": "2027-06-30T00:00:00Z",
    },
    "fund_ix": {
        "fund_name": "ECP Housing Fund IX",
        "target_equity_cents": 500_000_000,
        "price_per_credit_dollar": 0.9100,
        "target_yield_pct": 0.068,
        "close_threshold_pct": 0.85,
        "subscription_open_date": SUBSCRIPTION_OPEN_DEFAULT,
        "subscription_close_date": SUBSCRIPTION_CLOSE_DEFAULT,
    },
    "project_riverside": {
        "project_name": "Riverside Commons",
        "state_code": "OR",
        "total_credit_dollars_cents": 912_345_678,
        "construction_budget_cents": 1_234_567_890,
        "construction_loan_cents": 700_000_000,
        "operating_pro_forma_noi_cents": 72_000_000,
        "debt_service_cents": 60_000_000,
        "market_study_absorption_score": 0.83,
        "sponsor_experience_months": 96,
        "placed_in_service_deadline": "2028-12-31T00:00:00Z",
        "compliance_period_months": 180,
    },
    "project_juniper": {
        "project_name": "Juniper Flats",
        "state_code": "OR",
        "total_credit_dollars_cents": 600_000_000,
        "construction_budget_cents": 800_000_000,
        "construction_loan_cents": 400_000_000,
        "operating_pro_forma_noi_cents": 80_000_000,
        "debt_service_cents": 60_000_000,
        "market_study_absorption_score": 0.85,
        "sponsor_experience_months": 96,
        "placed_in_service_deadline": "2028-12-31T00:00:00Z",
        "compliance_period_months": 180,
    },
    "project_cedar_point": {
        "project_name": "Cedar Point",
        "state_code": "OR",
        "total_credit_dollars_cents": 400_000_000,
        "construction_budget_cents": 700_000_000,
        "construction_loan_cents": 300_000_000,
        "operating_pro_forma_noi_cents": 50_000_000,
        "debt_service_cents": 40_000_000,
        "market_study_absorption_score": 0.75,
        "sponsor_experience_months": 60,
        "placed_in_service_deadline": "2029-12-31T00:00:00Z",
        "compliance_period_months": 180,
    },
    "project_uptown": {
        "project_name": "Uptown Yards",
        "state_code": "OR",
        "total_credit_dollars_cents": 600_000_000,
        "construction_budget_cents": 950_000_000,
        "construction_loan_cents": 400_000_000,
        "operating_pro_forma_noi_cents": 70_000_000,
        "debt_service_cents": 55_000_000,
        "market_study_absorption_score": 0.81,
        "sponsor_experience_months": 60,
        "placed_in_service_deadline": "2029-12-31T00:00:00Z",
        "compliance_period_months": 180,
    },
    "project_harbor_light": {
        "project_name": "Harbor Light",
        "state_code": "WA",
        "total_credit_dollars_cents": 500_000_000,
        "construction_budget_cents": 900_000_000,
        "construction_loan_cents": 400_000_000,
        "operating_pro_forma_noi_cents": 60_000_000,
        "debt_service_cents": 50_000_000,
        "market_study_absorption_score": 0.77,
        "sponsor_experience_months": 96,
        "placed_in_service_deadline": "2029-12-31T00:00:00Z",
        "compliance_period_months": 180,
    },
    "allocation_oregon": {
        "state_agency": "Oregon Housing and Community Services",
        "awarded_credit_dollars_cents": 912_345_678,
        "commitment_fee_pct": 0.014,
        "awarded_date": "2026-08-15T00:00:00Z",
        "placed_in_service_deadline": "2028-12-31T00:00:00Z",
    },
    "subscription_meridian": {
        "committed_cents": 460_000_000,
    },
    "subscription_northline": {
        "committed_cents": 100_000_000,
    },
    "subscription_exact_threshold": {
        "committed_cents": 425_000_000,
    },
}


# =============================================================================
# Pure helpers mirroring the PRD's pinned arithmetic
# =============================================================================

def round_half_up(value, places: int = 0):
    """Round ``value`` half-up (a midpoint rounds away from zero).

    Returns an ``int`` when ``places`` is 0, otherwise a ``float``.
    """
    quantizer = Decimal(1).scaleb(-places)
    rounded = Decimal(str(value)).quantize(quantizer, rounding=ROUND_HALF_UP)
    return int(rounded) if places == 0 else float(rounded)


def fund_close_threshold_cents(
    target_equity_cents: int, close_threshold_pct: float = FUND_CLOSE_THRESHOLD_DEFAULT
) -> int:
    """``target_equity_cents * close_threshold_pct``, rounded half-up.

    The fund reaches CLOSING when ``subscribed_equity_cents`` is at or above
    this value.
    """
    return round_half_up(Decimal(target_equity_cents) * Decimal(str(close_threshold_pct)))


def shortfall_default_band_cents(
    committed_cents: int, band_pct: float = SUBSCRIPTION_SHORTFALL_BAND_PCT
) -> int:
    """The shortfall amount above which a subscription defaults.

    A subscription defaults when its ``shortfall_cents`` is *strictly greater*
    than this value.
    """
    return round_half_up(Decimal(committed_cents) * Decimal(str(band_pct)))


def delivery_adjuster_band(delivery_ratio: float) -> float:
    """Select the credit-delivery adjuster for a delivery ratio.

    Boundaries are half-open on the low side: a ratio of exactly 0.90 selects
    0.12, and exactly 0.99 selects 0.00.
    """
    if delivery_ratio >= BAND_FULL_DELIVERY:
        return ADJUSTER_FULL_DELIVERY
    if delivery_ratio >= BAND_NEAR_FULL:
        return ADJUSTER_NEAR_FULL
    if delivery_ratio >= BAND_PARTIAL:
        return ADJUSTER_PARTIAL
    return ADJUSTER_SEVERE


def dscr_from(operating_pro_forma_noi_cents: int, debt_service_cents: int) -> float:
    """``noi / debt_service`` held to 4 decimal places."""
    return round(float(operating_pro_forma_noi_cents) / float(debt_service_cents), 4)


def operating_deficit_cents(
    operating_pro_forma_noi_cents: int, debt_service_cents: int
) -> int:
    """``max(0, debt_service_cents - operating_pro_forma_noi_cents)``."""
    return max(0, int(debt_service_cents) - int(operating_pro_forma_noi_cents))


def monthly_deficit_cents(operating_deficit: int) -> int:
    """The annual deficit divided by 12, rounded half-up."""
    return round_half_up(Decimal(int(operating_deficit)) / Decimal(MONTHS_DIVISOR))


def coverage_months(liquid_assets_cents: int, monthly_deficit: int) -> int:
    """Integer floor division of liquid assets by the monthly deficit.

    The divisor is never below one cent.
    """
    return int(liquid_assets_cents) // max(int(monthly_deficit), 1)
