"""Domain thresholds and scenario defaults.

Numeric constants the PRD pins for the derived figures and deadlines, plus the
default offering economics used by the fixtures.
"""

# The logical clock's startup default (PRD: the clock's startup default is
# exactly 2026-09-01T00:00:00Z and it must never fall back to wall time).
CLOCK_EPOCH = "2026-09-01T00:00:00Z"

THRESHOLDS = {
    # Qualification window
    "QUALIFICATION_WINDOW_DAYS": 30,
    # Rescission right
    "RESCISSION_WINDOW_DAYS": 3,
    # Appraisal cadence
    "CADENCE_DUE_DAYS": 90,
    "CADENCE_REQUIRED_DAYS": 180,
    # Suitability
    "SUITABILITY_VALID_DAYS": 365,
    # Accredited-investor thresholds (EXEMPT_REG_D offerings)

    "ACCREDITED_MIN_INCOME_CENTS": 20_000_000,
    "ACCREDITED_MIN_NET_WORTH_CENTS": 100_000_000,
    # Insurance coverage band
    "COVERAGE_MAX_VALUE_PCT": 120,
    # Fee derivations
    "DAYS_PER_YEAR": 365,
    "FEE_BPS_BASE": 10_000,
    # Waitlist lapse sweep
    "OPEN_ORDER_LAPSE_DAYS": 30,
    # Minimum age for an investor
    "MIN_INVESTOR_AGE_YEARS": 18,
}

TEST_DEFAULTS = {
    # Default offering economics used across the fixtures.
    "TOTAL_SHARES": 40_000,
    "PRICE_PER_SHARE_CENTS": 1_500,
    "EXEMPTION_TYPE": "REG_D_506C",
    "REGISTRATION_CAP_PCT": 2_000,
    "LIQUIDITY_RATIO_BPS": 1_000,
    "HOLD_PERIOD_DAYS": 176,
    "MANAGEMENT_FEE_BPS": 150,
    "PROFIT_PARTICIPATION_BPS": 2_000,
    "COST_PASS_THROUGH_BPS": 10_000,
    "PREFERRED_RETURN_BPS": 800,
    "ACQUISITION_COST_CENTS": 60_000_000,
    "RESERVE_PRICE_CENTS": 100_000_000,
    "APPRAISED_VALUE_CENTS": 90_000_000,
    "COVERAGE_CENTS": 90_000_000,
    "ANNUAL_PREMIUM_CENTS": 450_000,
    # A default subscription-bearing investor. The residence rule refuses a
    # `residency_country_code` other than `US` outright, so the fixture persona
    # is a US resident: a US citizen/resident would trip the US/US jurisdiction
    # override, so citizenship is left non-US while residency is US.
    "DEFAULT_RESIDENCY_COUNTRY": "US",
    "DEFAULT_CITIZENSHIP_COUNTRY": "CA",
    "INVESTOR_BIRTH_DATE": "1966-04-02",
    "INVESTOR_INCOME_CENTS": 40_000_000,
    "INVESTOR_NET_WORTH_CENTS": 300_000_000,
}

# Custody transfer "custodian" used by the fixtures.
DEFAULT_CUSTODIAN = {
    "custodian_name": "Delaware Freeport Holdings",
    "facility_code": "DFH-A",
    "is_freeport": True,
    "custodian_dea_registered": True,
}