"""Domain thresholds and numeric constants stated by the PRD."""

# Basis points: 10000 bps is the whole.
BPS_DENOMINATOR = 10000

THRESHOLDS = {
    # Fee tier ceilings on average daily value (PRD §3.9)
    "TIER1_CEILING_CENTS": 25_000_000,       # $250,000
    "TIER2_CEILING_CENTS": 100_000_000,      # $1,000,000
    "TIER2_RATE_DISCOUNT_BPS": 10,
    "TIER3_RATE_DISCOUNT_BPS": 20,
    "DAYS_PER_YEAR": 365,
    # Revenue split (PRD §3.9)
    "PLATFORM_SHARE_BPS": 500,
    # Order generation (PRD §3.5)
    "MIN_CASH_RESERVE_CENTS": 10_000,        # $100 floor on the cash reserve
    "MIN_TRADE_NOTIONAL_CENTS": 5_000,       # $50 materiality floor
    # Wash-sale geometry (PRD §2.10)
    "WASH_WINDOW_DAYS": 30,
    # Delinquency (PRD §3.9)
    "PAYMENT_TERM_DAYS": 30,
}

# Field bounds declared by the PRD.
BOUNDS = {
    "TICKER_MIN_LEN": 1,
    "TICKER_MAX_LEN": 8,
    "PLATFORM_CODE_MIN_LEN": 2,
    "PLATFORM_CODE_MAX_LEN": 12,
    "STRATEGY_CODE_MIN_LEN": 2,
    "STRATEGY_CODE_MAX_LEN": 12,
    "ACCOUNT_NUMBER_MIN_LEN": 3,
    "ACCOUNT_NUMBER_MAX_LEN": 20,
    "REVENUE_SHARE_BPS_MAX": 9000,
    "IMPLEMENTATION_LAG_DAYS_MAX": 10,
    "BASE_FEE_BPS_MIN": 1,
    "BASE_FEE_BPS_MAX": 500,
    "DRIFT_THRESHOLD_BPS_MIN": 1,
    "DRIFT_THRESHOLD_BPS_MAX": 10000,
    "CASH_RESERVE_BPS_MAX": 2000,
    "MAX_POSITION_BPS_MIN": 1,
    "MAX_POSITION_BPS_MAX": 10000,
    "TARGET_WEIGHT_BPS_MIN": 1,
    "TARGET_WEIGHT_BPS_MAX": 10000,
    "TOTAL_TARGET_WEIGHT_BPS": 10000,
}

# Defaults the PRD declares for optional inputs.
DECLARED_DEFAULTS = {
    "restricted_globally": False,
    "implementation_lag_days": 2,
    "min_account_value_cents": 0,
    "drift_threshold_bps": 300,
    "cash_reserve_bps": 100,
    "drift_basis": "SETTLED",
    "tax_overlay_enabled": False,
    "harvest_budget_cents": 0,
    "sleeve_max_position_bps": 10000,
    "tax_lot_origin": "TRANSFER_IN",
    "dispersion_basis": "EQUAL_WEIGHTED",
}

# Pagination (PRD §2.3)
PAGINATION = {"DEFAULT_LIMIT": 10, "MIN_LIMIT": 1, "MAX_LIMIT": 100, "DEFAULT_OFFSET": 0}

# The logical clock reads exactly this before any caller sets it (PRD §2.5).
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

# Convenient test values reused across the suite.
TEST_DEFAULTS = {
    "SECURITY_PRICE_CENTS": 10_000,
    "REVENUE_SHARE_BPS": 3333,
    "BASE_FEE_BPS": 90,
}
