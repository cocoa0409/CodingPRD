"""Domain thresholds and monetary constants stated in the PRD."""

THRESHOLDS = {
    # Guarantee ratio: appraised dwelling cost against current replacement cost.
    "GUARANTEE_RATIO": 1.50,
    "EXTENDED_REPLACEMENT_FACTOR": 1.5,
    "BASE_APPRAISAL_CURRENCY_MONTHS": 24,
    # Wildfire risk score arithmetic.
    "BASE_SCORE": 300,
    "MAX_SCORE": 999,
    "TIER_MANAGED_MAX": 199,
    "TIER_REVIEW_MIN": 200,
    "TIER_SURCHARGE_MIN": 450,
    "TIER_REFER_MIN": 700,
    "BAND_POINTS": {"STANDARD": 0, "ELEVATED": 240, "EXTREME": 420},
    "MITIGATION_CREDIT": {"CLEARED": 420, "PARTIAL": 250, "FAILED": 60, "UNVERIFIED": 0},
    "AGENCY_POINTS": {"NORMAL": 0, "ELEVATED": 70, "CRITICAL": 150},
    # Concentration bands (percent).
    "BAND_ELEVATED_PCT": 18.0,
    "BAND_CRITICAL_PCT": 30.0,
    "MIN_PORTFOLIO_ACTIVE_COUNT": 2,
    "AGENCY_ELEVATED_PCT": 15.0,
    "AGENCY_CRITICAL_PCT": 25.0,
    # Premium arithmetic.
    "BASE_RATE": 0.0021,
    "CONTENTS_RATE": 0.0009,
    "MIN_EXTENDED_PREMIUM_CENTS": 12500,
    # Settlement arithmetic.
    "SCARCITY_FACTOR": 1.20,
    "DEDUCTIBLE_PCT": {
        "WILDFIRE": 0.02,
        "WIND": 0.01,
        "HALL": 0.01,
        "WATER": 0.005,
        "THEFT": 0.005,
        "OTHER": 0.005,
    },
    # Scheduled personal property aggregate cap (fraction of total insured value).
    "SCHEDULED_VALUE_CAP_FRACTION": 0.60,
    # Defense dispatch priority.
    "ZONE_RANK_CLEARED": 2,
    "ZONE_RANK_UNMITIGATED": 1,
    "EXPIRING_WINDOW_DAYS": 14,
    "ZONE_RANK_SCALE": 1000000,
    "EXPIRING_RANK_SCALE": 1000,
    "DISPATCH_WINDOW_HOURS": 24,
    "ZONE_DISPATCH_CAPACITY": 2,
    # Notice periods.
    "NOTICE_DAYS_NORMAL": 45,
    "NOTICE_DAYS_ELEVATED": 60,
    "NOTICE_DAYS_CRITICAL": 90,
    "MIN_POLICY_AGE_DAYS": 60,
    # Consultation overlap.
    "NO_SHOW_GRACE_DAYS": 7,
    # Appraisal provision baseline.
    "PROVISION_BASELINE_RATIO": 1.25,
}

TEST_DEFAULTS = {
    "REPLACEMENT_COST_CENTS": 200_000_000,
    "CONTENTS_COST_CENTS": 0,
    "DWELLING_COVERAGE_CENTS": 300_000_000,
    "SUSTAINED_WIND_MPH": 45,
    "MITIGATION_BAND_MULTIPLIER": 1.0,
    "MITIGATED_LOSS_MULTIPLIER": 1.0,
    "CLOCK_START": "2026-09-01T00:00:00Z",
    "APPRAISED_ON": "2026-08-15T00:00:00Z",
    "DOC_APPRAISAL_DATE": "2026-08-20T00:00:00Z",
    "CONSULTANT_USER_ID": "rc-dana",
}

# The instant the logical clock is pinned to at server startup.
CLOCK_START = "2026-09-01T00:00:00Z"