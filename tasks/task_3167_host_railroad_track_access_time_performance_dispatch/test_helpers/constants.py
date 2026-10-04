"""Domain thresholds and standing constants from the PRD."""

BASE_CLOCK = "2026-09-01T00:00:00Z"

THRESHOLDS = {
    # A window's lock is allowed up to and including exactly 40.00 equipment hours per ISO week.
    "WEEKLY_EQUIPMENT_ALLOWANCE_HOURS": 40.00,
    # Default clearance applied on both sides of a maintenance window.
    "DEFAULT_CLEARANCE_BUFFER_MINUTES": 15,
    # Penalty tier bands measured as fractions below the OTP target.
    "TIER1_BAND": 0.05,
    "TIER2_BAND": 0.15,
}

# Canonical two-segment corridor geometry used across the suite:
#   segment 1: IL, mileposts 0.0-10.0, SINGLE, capacity 20, pure run 21 min
#   segment 2: MO, mileposts 10.0-40.0, SINGLE, capacity 20, pure run 40 min
#   agreement: threshold 15 min, penalty 50 c/min, incentive 12 c/train-mile,
#              OTP target 0.80, running-time allowance 0.25
# Padded running times: segment 1 -> ceil(21 * 1.25) = 27 min, segment 2 -> ceil(40 * 1.25) = 50 min.
CANONICAL = {
    "SEG1_MILEPOST_START": 0.0,
    "SEG1_MILEPOST_END": 10.0,
    "SEG1_STATE": "IL",
    "SEG1_PURE_RUN_MINUTES": 21,
    "SEG1_PADDED_MINUTES": 27,
    "SEG2_MILEPOST_START": 10.0,
    "SEG2_MILEPOST_END": 40.0,
    "SEG2_STATE": "MO",
    "SEG2_PURE_RUN_MINUTES": 40,
    "SEG2_PADDED_MINUTES": 50,
    "CORRIDOR_TOTAL_MILES": 40.0,
    "ON_TIME_THRESHOLD_MINUTES": 15,
    "PENALTY_RATE_CENTS_PER_MINUTE": 50,
    "INCENTIVE_RATE_CENTS_PER_TRAIN_MILE": 12,
    "OTP_TARGET_PCT": 0.80,
    "RUNNING_TIME_ALLOWANCE_PCT": 0.25,
    "ANNUAL_COST_CENTS": 10_000_000,
}
