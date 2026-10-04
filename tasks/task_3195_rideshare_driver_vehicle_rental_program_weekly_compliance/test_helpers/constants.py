"""Domain thresholds and programme constants.

Monetary amounts are integer cents throughout the contract; the only rounding
convention is round half up to the nearest whole cent.
"""

# ─── Platform activity credit ─────────────────────────
PROGRAM_ACTIVITY_FLOOR = 50
PLATFORM_CREDIT_PER_ACTIVITY_POINT_CENTS = 10
PLATFORM_CREDIT_CAP_CENTS = 600
TIER_3_CREDIT_MULTIPLIER_NUM = 3
TIER_3_CREDIT_MULTIPLIER_DEN = 2
TIER_3_MULTIPLIER_NUM = 5
TIER_3_MULTIPLIER_DEN = 4

# ─── Weekly renewal charge ────────────────────────────
MILEAGE_OVERAGE_RATE_CENTS_PER_MILE = 25

# ─── Damage apportionment ─────────────────────────────
DAMAGE_ALLOWANCE_CENTS_PER_MILE = 2
DRIVER_DAMAGE_CAP_CENTS = 50_000

# ─── Eligibility score ────────────────────────────────
BONUS_REQUIRES_SCORE_AT_OR_BELOW = 40
BONUS_REQUIRES_ACTIVITY_AT_OR_ABOVE = 90
BONUS_POINTS = 15
APPROVE_SCORE_AT_OR_ABOVE = 60
APPROVE_ACTIVITY_AT_OR_ABOVE = 70

# ─── Delinquency posture ──────────────────────────────
POSTURE_RESTRICTED_AT = 1
POSTURE_FROZEN_AT = 2

# ─── Equity credit and escrow ─────────────────────────
EQUITY_SHARE_NUM = 1
EQUITY_SHARE_DEN = 10
EQUITY_CENTS_DIVISOR = 100

# ─── Time windows ─────────────────────────────────────
GRACE_PERIOD_HOURS = 72
RECOVERY_QUIET_PERIOD_HOURS = 24
LOANER_MIN_DOWNTIME_HOURS = 24
LOANER_ALLOWANCE_DIVISOR_HOURS = 8

# ─── Logical clock ────────────────────────────────────
DEFAULT_CLOCK = "2026-09-01T00:00:00Z"
CLOCK_AT_GRACE_LAPSE = "2026-09-11T00:00:00Z"
LONG_TERM_END = "2027-08-31T00:00:00Z"

# ─── Test fixture defaults ────────────────────────────
TEST_DEFAULTS = {
    "WEEKLY_RATE_CENTS": 35_000,
    "INSURANCE_PREMIUM_CENTS": 4_000,
    "MILEAGE_CAP_MILES": 2_000,
    "MAINTENANCE_ALLOWANCE_MILES": 200,
    "ACTIVITY_SCORE": 95,
    "DRIVING_RECORD_POINTS": 2,
    "REGION_CODE": "CA",
    "ODOMETER_MILES": 40_000,
    # Provisional charge at open for the default agreement: 35000 + 4000 - 565
    "PROVISIONAL_DUE_CENTS": 38_435,
    # Settled charge for a metered week driving 2200 miles against a 2000 cap
    "SETTLED_DUE_CENTS": 43_735,
    "PLATFORM_CREDIT_AT_95": 565,
}