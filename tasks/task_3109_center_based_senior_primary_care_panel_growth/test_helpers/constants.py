"""Domain thresholds and default constants from the PRD."""

# Logical clock default before any clock-setting call (PRD §2.4).
DEFAULT_CLOCK_UTC = "2026-09-01T00:00:00Z"

THRESHOLDS = {
    # ED diversion monthly floor: strictly above 10 flags profitability review.
    "ED_DIVERSION_FLOOR": 10,
    # Profitability ramp: maturity months below 12 keeps the center in RAMP.
    "RAMP_MONTHS": 12,
    # Fill ratio exactly 0.7500 qualifies for MATURE.
    "MATURE_FILL_RATIO": 0.75,
    # No-show strikes at or above 3 suspend transport privilege.
    "NO_SHOW_STRIKE_LIMIT": 3,
    # Diversion-rate tiers for the outcome-adjusted panel value.
    "DIVERSION_RATE_HIGH": 0.80,
    "DIVERSION_RATE_MID": 0.60,
}

COST = {
    # Internal visit base cost by kind, in cents.
    "PRIMARY": 18000,
    "BEHAVIORAL": 22000,
    "CHW_OUTREACH": 9000,
    # Flat transport booking per DELIVERED or FAILED_NO_SHOW ride.
    "RIDE_FLAT_CENTS": 3200,
    # No-show books at half the scaled amount.
    "NO_SHOW_FACTOR": 0.5,
}

TIER_MULTIPLIERS = {
    "RAMP": 0.95,
    "BREAKEVEN": 1.00,
    "MATURE": 1.05,
}

# Staffing bonus: sum of staffing_score across the center's teams times 150 cents.
STAFFING_SCORE_CENTS = 150
