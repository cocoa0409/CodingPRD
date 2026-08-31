"""Domain thresholds and pinned numeric constants taken from the PRD."""

# Policy dial defaults applied when an association is registered without them.
POLICY_DEFAULTS = {
    "temp_code_daily_limit": 3,
    "temp_code_overage_fee_cents": 500,
    "removal_grace_days": 3,
    "late_removal_daily_fee_cents": 1500,
    "late_removal_cap_cents": 15000,
    "credential_cap_per_member": 2,
    "grant_buffer_minutes": 15,
    "recovery_target_pct": 95.00,
}

# Member statement balance: each open line is grossed up by 2.5 percent and rounded
# half up to a whole cent individually before the line totals are added.
ADMIN_SURCHARGE_RATE = 0.025

# Replacement charge.
MONTHLY_DEPRECIATION_RATE = 0.02
DEPRECIATION_CAP = 0.60
THEFT_SECURITY_OFFSET = 0.50
REPEAT_MULTIPLIER_FIRST_LOSS = 1.00
REPEAT_MULTIPLIER_SECOND_LOSS = 1.50
REPEAT_MULTIPLIER_THIRD_LOSS = 2.00

# Late-removal penalty tiers, keyed on the base component alone.
TIER_1_CEILING_CENTS = 4500
TIER_2_CEILING_CENTS = 10500
TIER_FEE_PCT = {"T1": 0.00, "T2": 0.05, "T3": 0.10}

# Association posture.
FROZEN_MISSING_BOXES = 3
FROZEN_DELINQUENT_RATIO = 0.50
RESTRICTED_MISSING_BOXES = 1
RESTRICTED_DELINQUENT_RATIO = 0.25

# Incident risk score.
OUTCOME_WEIGHT = {
    "GRANTED": 2,
    "DENIED_OUTSIDE_WINDOW": 9,
    "DENIED_NO_CREDENTIAL": 12,
    "DENIED_CREDENTIAL_INACTIVE": 18,
    "DENIED_BOX_MISSING": 25,
}
ACTOR_MULTIPLIER = {"MEMBER": 1.0, "CONTRACTOR": 1.25, "UNKNOWN": 2.0}
AFTER_HOURS_MULTIPLIER = 1.5
UNMATCHED_SHOWING_PENALTY = 10
SCORE_FLOOR = 0.00
SCORE_CEILING = 100.00
ELEVATED_THRESHOLD = 35.00
CRITICAL_THRESHOLD = 70.00

# Access outcome resolution.
AFTER_HOURS_START_HOUR = 8
AFTER_HOURS_END_HOUR = 20

# Recovery reporting.
DEFAULT_WINDOW_DAYS = 90

# The logical clock reads exactly this instant before any caller sets it.
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

# Values reused across test setups.
TEST_DEFAULTS = {
    "ASSOCIATION_NAME": "Cascade Regional Association",
    "JURISDICTION_CODE": "WA-KING",
    "FUTURE_DUES_DATE": "2027-01-31",
    "IN_SERVICE_SINCE": "2025-08-01",
    "CREDENTIAL_EXPIRES_AT": "2027-06-30T00:00:00Z",
    "LB_PRO_COST_CENTS": 12000,
    "LB_STD_COST_CENTS": 9000,
}
