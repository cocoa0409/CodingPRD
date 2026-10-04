"""Domain thresholds — numeric constants from the PRD's calculations and settings."""

# --- logical clock -----------------------------------------------------------
CLOCK_DEFAULT = "2026-09-01T00:00:00Z"
DAY_1 = "2026-09-02T00:00:00Z"

# --- promotional switch credit (§3.4) ---------------------------------------
PROMO_BASE_CREDIT_CENTS = 20000
PROMO_MONTHLY_BASE_CENTS = 1000
PROMO_WINDOW_BUFFER_DAYS = 30
PROMO_DEFAULT_RETENTION_CYCLES = 12

# --- trade-in condition values in cents (§3.5) -------------------------------
CONDITION_VALUE_CENTS = {
    "FLAWLESS": 60000,
    "GOOD": 42000,
    "FAIR": 24000,
    "POOR": 8000,
    "BROKEN": 0,
}

# --- credit class determination (§3.6) ---------------------------------------
SCORE_BLOCKED_CEILING = 299
SCORE_CLASS_D_FLOOR = 300
SCORE_CLASS_C_FLOOR = 500
SCORE_CLASS_B_FLOOR = 650
SCORE_CLASS_A_FLOOR = 800
FAMILY_TIER_LINE_THRESHOLD = 5
LINE_LIMIT_CEILING = 10

CLASS_DEPOSIT_CENTS = {
    "CLASS_A": 0,
    "CLASS_B": 10000,
    "CLASS_C": 25000,
    "CLASS_D": 50000,
    "BLOCKED": 0,
}

# --- device financing (§3.5) -------------------------------------------------
DAYS_PER_BILLING_CYCLE = 30

# --- migration proration credit (§3.3) ---------------------------------------
DAYS_IN_CYCLE = 30
CARRY_WEIGHT = 0.50
TIER_RATE_CENTS = {1: 5000, 2: 4000, 3: 3000, 4: 2500}

# --- number reservations (§3.9) ----------------------------------------------
DEFAULT_HOLD_DAYS = 45

# --- system config defaults (§2.4) -------------------------------------------
DEFAULT_LINE_CANCELLATION_GRACE_HOURS = 24
DEFAULT_OPS_RUN_EPOCH = 1

# --- common test defaults ----------------------------------------------------
TEST_DEFAULTS = {
    "ACCOUNT_TYPE": "FAMILY",
    "TAX_ID_LAST4": "1234",
    "PAYMENT_HISTORY_SCORE": 720,
    "EXISTING_DEPOSIT_CENTS": 50000,
    "DEVICE_PRICE_CENTS": 60000,
    "DOWN_PAYMENT_CENTS": 0,
    "INSTALLMENT_MONTHS": 24,
    "MONTHLY_CREDIT_CENTS": 1000,
    "INSTALLMENT_MONTHS_PROMO": 12,
    "RETENTION_REQUIREMENT_CYCLES": 12,
    "PREPAID_BALANCE_CENTS": 0,
    "POOL_CODE": "POOL-A",
}