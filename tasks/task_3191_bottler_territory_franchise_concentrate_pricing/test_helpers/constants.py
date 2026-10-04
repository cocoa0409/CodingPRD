"""Domain thresholds — numeric constants from PRD calculations."""

THRESHOLDS = {
    # concentrate_unit_price
    "MAX_DISCOUNT": 0.03,
    "TIER1_MIN_GAL": 25000,
    "TIER2_MIN_GAL": 50000,
    "TIER1_PCT": 0.02,
    "TIER2_PCT": 0.035,
    "MIN_ORDER_GALLONS": 1000,
    # marketing_fund_accrual
    "PER_CASE_RATE_CENTS": 40,
    "REVENUE_ACCRUAL_PCT": 0.025,
    # territory_transfer_valuation
    "EBITDA_MULTIPLE": 7,
    "LOW_BAND_RATE": 0.04,
    "HIGH_BAND_RATE": 0.06,
    "BAND_THRESHOLD_CENTS": 500000000,
    # nca_price_band_check
    "MAX_DEVIATION": 0.05,
    # innovation_min_volume_penalty
    "PENALTY_TIER1_MAX_PCT": 0.10,
    "PENALTY_TIER2_MAX_PCT": 0.25,
    "PENALTY_TIER1_RATE_CENTS": 5,
    "PENALTY_TIER2_RATE_CENTS": 12,
    "PENALTY_TIER3_RATE_CENTS": 25,
    # fountain maintenance window (days)
    "MAINTENANCE_WINDOW_DAYS": 90,
}

TEST_DEFAULTS = {
    "CLOCK_DEFAULT": "2026-09-01T00:00:00Z",
    "INDEX_VALUE_Q2": 110.00,
    "LINE_BASE_PRICE": 12.0,
    "BASE_INDEX": 100.0,
}
