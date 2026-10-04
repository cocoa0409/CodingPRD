"""Domain thresholds — numeric constants from PRD calculations."""

# Reseller tier discount percentages (PRD monthly-charge calculation)
CERTIFIED_DISCOUNT_PCT = 5
GOLD_DISCOUNT_PCT = 10
PLATINUM_DISCOUNT_PCT = 15

# Commitment lengths in months (PRD subscription activation)
MONTHS_MONTHLY = 1
MONTHS_PER_ANNUAL = 12

# Reclaim grace period is 24 hours (PRD seat reclamation)
RECLAIM_GRACE_HOURS = 24

# Transfer request approval expiry is 72 hours (PRD seat transfer)
TRANSFER_EXPIRY_HOURS = 72

# Logical clock bootstrap instant (PRD logical-clock section)
CLOCK_DEFAULT_ISO = "2026-09-01T00:00:00Z"

# Storage unit conversion (PRD storage precision: 1024 MB per GB)
MB_PER_GB = 1024

TEST_DEFAULTS = {
    "PLAN_MONTHLY_PRICE_CENTS": 3000,
    "PLAN_ANNUAL_MONTHLY_PRICE_CENTS": 3000,
    "STORAGE_GB_PER_SEAT": 20,
    "SEAT_LIMIT": -1,
    "MAX_DEVICES_PER_SEAT": 2,
    "CANCELLATION_WINDOW_DAYS": 14,
    "ETF_RATE_PCT": 0,
}
