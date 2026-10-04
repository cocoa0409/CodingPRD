"""Domain thresholds — numeric constants from the PRD calculations."""

# Logical clock default (PRD §2.6): the clock reads exactly this before any call.
DEFAULT_CLOCK_ISO = "2026-09-01T00:00:00Z"

THRESHOLDS = {
    # Impact study (PRD §3.2)
    "DEGREES_PER_MILE": 0.0145,
    "BUCKET_NEAR_PCT": 0.12,   # distance < 0.01 deg
    "BUCKET_MID_PCT": 0.07,    # 0.01 <= distance < 0.02 deg
    "BUCKET_FAR_PCT": 0.03,    # 0.02 <= distance < 0.04 deg
    # Inspection scoring (PRD §3.6)
    "W_FOOD_SAFETY": 0.40,
    "W_CLEANLINESS": 0.30,
    "W_OPERATIONS": 0.30,
    "CRITICAL_PENALTY_POINTS": 2.50,
    "PASS_THRESHOLD": 60.00,
    "FAIL_CRITICAL_MIN_VIOLATIONS": 3,
    # Training (PRD §3.4)
    "TRAINING_PASS_SCORE": 80,
    # Remodel downtime (PRD §3.5)
    "ALLOW_SELF_FINANCED_DAYS": 21,
    "ALLOW_DA_LOAN_DAYS": 28,
    "ALLOW_FRANCHISOR_DEFERRAL_DAYS": 14,
    "OVERAGE_PER_DAY_CENTS": 150_000,
    "CLOSURE_BUFFER_DAYS": 7,
    # Transfer fee (PRD §3.4)
    "TRANSFER_TIER_LOW_CAP_CENTS": 25_000_000,
    "TRANSFER_TIER_HIGH_CAP_CENTS": 75_000_000,
    "TRANSFER_FEE_FLAT_CENTS": 500_000,
    "TRANSFER_RATE_MID": 0.02,
    "TRANSFER_RATE_HIGH": 0.015,
    "TRANSFER_AGE_DISCOUNT_MIN_YEARS": 10,
    "TRANSFER_AGE_DISCOUNT_FACTOR": 0.90,
    # Fee split (PRD §3.8)
    "TIER_HIGH_MIN_STORES": 5,
    "DA_SHARE_LOW": 0.40,
    "DA_SHARE_HIGH": 0.45,
    # Promotion subsidy (PRD §3.7)
    "SUBSIDY_TIER_HIGH_MIN": 12,
    "SUBSIDY_TIER_MID_MIN": 6,
    "SUBSIDY_HIGH": 0.15,
    "SUBSIDY_MID": 0.10,
    "SUBSIDY_LOW": 0.05,
    # Protest / mediation windows (PRD §3.3)
    "PROTEST_WINDOW_DAYS": 30,
    # Agent performance (PRD §3.1)
    "STRIKE_THRESHOLD": 60.00,
    # Promotion capacity (PRD §3.7)
    "MAX_OVERLAPPING_ACTIVE_PROMOTIONS": 2,
}

TEST_DEFAULTS = {
    "ROYALTY_RATE_PCT": 0.08,
    "DEVELOPMENT_QUOTA_STORES": 3,
    "WEEKLY_SALES_CENTS": 1_000_000,
    "BASE_COST_PER_STORE_CENTS": 200_000,
    "SALE_PRICE_CENTS": 40_000_000,
    "ESTIMATED_REMODEL_COST_CENTS": 5_000_000,
}
