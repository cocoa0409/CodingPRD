"""Domain thresholds — numeric constants from PRD calculations."""

THRESHOLDS = {
    "TIER1_RATE": 0.07,
    "TIER1_CAP_CENTS": 50000000,
    "TIER2_RATE": 0.05,
    "HOLD_THRESHOLD_CENTS": 5000,
    "DEPARTURE_NOTICE_DAYS": 180,
    "NON_COMPETE_TERM_MONTHS": 24,
    "EARLY_EXIT_BASE_CENTS": 2500000,
    "PER_MONTH_SHORTFALL_CENTS": 250000,
    "INSUFFICIENT_NOTICE_CENTS": 500000,
    "MIN_AVG_UPLIFT": 0.08,
    "STANDARD_LAG_DAYS": 90,
    "EXPEDITED_LAG_DAYS": 30,
    "EXPEDITED_MAX_REQUEST_SPAN_DAYS": 45,
    "DEFAULT_QUALITY_THRESHOLD": 60,
    "DEFAULT_MARKET_WEIGHT": 1.0,
}

TEST_DEFAULTS = {
    "GROUP_TIN": "76-0001111",
    "GROUP_NAME": "Unified Medical Group",
    "MARKET_NAME": "North Texas",
    "MARKET_STATE": "TX",
    "MARKET_MAX_PRACTICES": 10,
    "WAVE_CODE": "W1",
    "WAVE_START": "2026-08-01",
    "WAVE_END": "2026-12-31",
    "PRACTICE_LEGAL_NAME": "Oak Cliff Family Medicine",
    "PRACTICE_LEGACY_TIN": "75-9999999",
    "PRACTICE_ORG_NPI": "1234567890",
    "PROVIDER_NPI": "1112223334",
    "PROVIDER_NAME": "Dr. Ada Fields",
    "PROVIDER_SPECIALTY": "Family Medicine",
    "PROVIDER_START": "2026-01-15",
    "PAYER_NAME": "Lone Star Health Plan",
    "CONTRACT_TYPE": "HYBRID",
    "CONTRACT_EFFECTIVE": "2026-09-01",
    "RATE_CPT": "99213",
    "RATE_LEGACY": 10000,
    "RATE_GROUP": 10800,
    "PERIOD_SEP": "2026-09",
    "POOL_AMOUNT_CENTS": 1000000,
    # Well-known logical-clock values used by the suite.
    "CLOCK_DEFAULT": "2026-09-01T00:00:00Z",
    "CLOCK_MID": "2027-06-01T00:00:00Z",
    "CLOCK_EXIT": "2027-12-01T00:00:00Z",
    "CLOCK_ENROLL_LATER": "2026-12-03T00:00:00Z",
}

# Opaque operator user ids (PRD §2.1: not tied to any persisted entity).
USER_IDS = {
    "GROUP_ADMIN": "ga-root",
    "PAYER_CONTRACTING_OFFICER": "pco-marsha",
    "CREDENTIALING_COORDINATOR": "cc-jules",
    "DISTRIBUTION_ACCOUNTANT": "da-roy",
    "GROUP_FINANCIAL_CONTROLLER": "gfc-lena",
    "COMPLIANCE_OFFICER": "co-irene",
}
