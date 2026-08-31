"""Domain thresholds and default fixture values, in integer cents."""

API_PREFIX = "/plan-admin"

# Statutory limits and thresholds stated in the PRD.
THRESHOLDS = {
    # Elective deferral basic limit: 24,500 dollars.
    "BASIC_ELECTIVE_DEFERRAL_LIMIT_CENTS": 2_450_000,
    # 403(b) fifteen-year service catch-up.
    "SERVICE_15YR_MIN_YEARS": 15,
    "SERVICE_15YR_ANNUAL_CAP_CENTS": 300_000,
    "SERVICE_15YR_LIFETIME_CAP_CENTS": 1_500_000,
    "SERVICE_15YR_PER_YEAR_FACTOR_CENTS": 500_000,
    # Age-50 catch-up: 8,000 dollars.
    "AGE_50_CATCHUP_LIMIT_CENTS": 800_000,
    # 457(b) final-three-year window.
    "NORMAL_RETIREMENT_AGE": 65,
    "FINAL_3YR_MULTIPLIER": 2,
    # Section 415(c) annual additions: 72,000 dollars.
    "ANNUAL_ADDITIONS_LIMIT_415C_CENTS": 7_200_000,
    # Loans.
    "LOAN_ABSOLUTE_CAP_CENTS": 5_000_000,
    "LOAN_MINIMUM_FLOOR_CENTS": 1_000_000,
    "LOAN_VESTED_PERCENT_BPS": 5_000,
    "LOAN_LOOKBACK_DAYS": 365,
    # Universal availability / part-time exclusion.
    "PART_TIME_HOURS_PER_WEEK_THRESHOLD": 20,
    "PART_TIME_PRIOR_YEAR_HOURS_THRESHOLD": 1000,
    # Information sharing perimeter.
    "ISA_DATA_STALENESS_DAYS": 45,
    # Remittance.
    "SMALL_PLAN_PARTICIPANT_THRESHOLD": 100,
    "SMALL_PLAN_SAFE_HARBOR_BUSINESS_DAYS": 7,
    "LARGE_PLAN_DEADLINE_BUSINESS_DAY": 15,
    "LOST_EARNINGS_ANNUAL_RATE_BPS": 600,
    "DAYS_PER_YEAR": 365,
    "EXCISE_TAX_RATE_BPS": 1500,
    # Vesting.
    "FULLY_VESTED_BPS": 10_000,
}

FEDERAL_HOLIDAYS_2026 = [
    "2026-01-01",
    "2026-01-19",
    "2026-02-16",
    "2026-05-25",
    "2026-06-19",
    "2026-07-03",
    "2026-09-07",
    "2026-10-12",
    "2026-11-11",
    "2026-11-26",
    "2026-12-25",
]

# Fixture defaults.
TEST_DEFAULTS = {
    "CLOCK_DEFAULT": "2026-08-01T00:00:00Z",
    "PLAN_YEAR": 2026,
    "LARGE_PLAN_PARTICIPANT_COUNT": 250,
    "SMALL_PLAN_PARTICIPANT_COUNT": 50,
    "NOTICE_ISSUED_DATE": "2026-01-05",
    "FRESH_FEED_DATE": "2026-07-31",
    "STALE_FEED_DATE": "2026-05-01",
    "AGREEMENT_FROM": "2026-01-01",
    "AGREEMENT_THROUGH": "2026-12-31",
}

# Compliance officer identities. Segregation of duties is structural, so the
# suite always keeps at least two distinct officer identities available.
OFFICER_ONE = "co-1"
OFFICER_TWO = "co-2"
