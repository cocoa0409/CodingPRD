"""Domain thresholds — numeric constants from the PRD's calculation rules."""

# Forecast attainment gate (PRD §3.3): inclusive >= 80.00 opens SELLING;
# above 120.00 is the advisory over-commit threshold.
SELLING_GATE_PCT = 80.00
OVER_COMMIT_PCT = 120.00

# Participant incentive tier thresholds (PRD §3.7), inclusive lower bounds.
BRONZE_MIN = 20
SILVER_MIN = 50
GOLD_MIN = 100

# Logical clock startup default (PRD §2.9).
CLOCK_DEFAULT = "2026-09-01T00:00:00Z"

# Lottery eligibility ceiling: rank > 2 is ineligible at draw time (PRD §3.5).
LOTTERY_MAX_ELIGIBLE_RANK = 2

# Booth lottery decision reasons (PRD §3.5).
REASON_LOTTERY_LOST = "LOTTERY_LOST"
REASON_RANK_GT_2 = "RANK_GT_2"

# Ordering window used by test fixtures.
DEFAULT_WINDOW = {
    "opens": "2027-01-01T00:00:00Z",
    "closes": "2027-02-01T00:00:00Z",
    "inside": "2027-01-10T00:00:00Z",
}
