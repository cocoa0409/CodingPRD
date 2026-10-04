"""Domain thresholds — numeric constants from the PRD's calculations."""

# Demurrage tier tables (cents per billable day, marginal allocation)
DEMURRAGE_STANDARD = {
    "T1_DAYS": 3,
    "T1_RATE": 15000,
    "T2_DAYS": 7,
    "T2_RATE": 30000,
    "T3_RATE": 45000,
}
DEMURRAGE_EXTENDED_TIERED = {
    "T1_DAYS": 5,
    "T1_RATE": 12000,
    "T2_DAYS": 10,
    "T2_RATE": 24000,
    "T3_DAYS": 15,
    "T3_RATE": 36000,
    "T4_RATE": 50000,
}

# Detention tier tables (cents per billable day, marginal allocation)
DETENTION_STANDARD = {
    "T1_DAYS": 4,
    "T1_RATE": 9000,
    "T2_DAYS": 9,
    "T2_RATE": 18000,
    "T3_RATE": 27000,
}
DETENTION_EXTENDED_TIERED = {
    "T1_DAYS": 6,
    "T1_RATE": 7000,
    "T2_DAYS": 13,
    "T2_RATE": 15000,
    "T3_RATE": 22000,
}

# Aging / posture thresholds
AGING_BUCKET_1_MAX_DAYS = 30
AGING_BUCKET_2_MAX_DAYS = 60
CREDIT_HOLD_GRACE_DAYS = 7
PAYMENT_TERMS_DAYS = 30
DISPUTE_SLA_DAYS = 14

# Waiver authority tier limits (cents, inclusive downward)
TIER1_LIMIT_CENTS = 50000
TIER2_LIMIT_CENTS = 500000

# Contract free-day input range
FREE_DAYS_MIN = 0
FREE_DAYS_MAX = 30

# Pagination
PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MAX = 100

# Logical clock startup instant
CLOCK_START_ISO = "2026-09-01T00:00:00Z"

TEST_DEFAULTS = {
    "TERMINAL_CODE": "OAK",
    "TERMINAL_TIMEZONE": "Pacific/Honolulu",
    "TERMINAL_DAILY_CAPACITY": 5,
    "LOCATION_CODE": "LOC-1",
    "LOCATION_DAILY_CAPACITY": 10,
    "EQUIPMENT_TYPE": "DRY40",
    "RATE_SCHEDULE": "STANDARD",
}
