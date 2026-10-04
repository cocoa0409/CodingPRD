"""Domain thresholds and numeric constants from the PRD business rules."""

# Capacity-review scoring constants (PRD §3.2)
CAPACITY = {
    "NET_WORTH_FULL_CREDIT_CENTS": 200_000_000,
    "OPM_FULL_CREDIT": 0.25,
    "PORTFOLIO_FULL_CREDIT": 10,
    "DEFAULT_PENALTY": 30,
    "REINVEST_PENALTY": 20,
    "DELINQ_PENALTY": 20,
    "DELINQ_FULL_PENALTY_CENTS": 5_000_000,
    "GRADE_STRONG_MIN": 80,
    "GRADE_ADEQUATE_MIN": 60,
    "GRADE_WEAK_MIN": 40,
}

# max_stores derived from capacity_grade (PRD §3.2)
MAX_STORES_BY_GRADE = {
    "STRONG": 12,
    "ADEQUATE": 6,
    "WEAK": 2,
    "FAILING": 0,
}

# Reinvestment minimum coverage (PRD §3.6)
MIN_COVERAGE_RATE = 0.70

# Renewal window in days (PRD §3.3)
RENEWAL_WINDOW_DAYS = 180

# Default logical clock at server startup (PRD §2.5)
DEFAULT_CLOCK_UTC = "2026-09-01T00:00:00Z"

# Standard economic terms reused across fixtures
TERMS = {
    "INITIAL_FEE_CENTS": 4_500_000,
    "ROYALTY_RATE": 0.04,
    "AD_FUND_RATE": 0.02,
    "OCCUPANCY_ALLOCATION_PCT": 0.60,
    "TERM_YEARS": 5,
    "TERM_START_DATE": "2026-04-01",
    "BASE_RENT_CENTS": 2_400_000,
    "PCT_RENT_RATE": 0.08,
    "ESCALATION_RATE": 0.02,
    "ESCALATION_MONTH": 4,
    "ESCALATION_DAY": 1,
    "SUBLEASE_START_DATE": "2026-04-01",
    "SUBLEASE_END_DATE": "2031-03-31",
    "STRONG_NET_WORTH_CENTS": 400_000_000,
    "STRONG_OPERATING_INCOME_CENTS": 100_000_000,
}
