"""Domain thresholds and logical-clock constants pinned by the PRD."""

# Logical clock default (PRD section 2.4: before any clock operation the
# logical clock stands at exactly this instant).
DEFAULT_CLOCK_ISO = "2026-09-01T00:00:00Z"

# Waiting-period and deferred-action day counts (PRD sections 3.3, 3.6, 3.7).
INJURY_WAITING_DAYS = 5
ILLNESS_WAITING_DAYS = 14
SETTLE_DELAY_DAYS = 3
RECORDS_WINDOW_DAYS = 14

# Common test inputs.
TERRITORY_CODE = "941"
STATE_CODE = "CA"

TEST_DEFAULTS = {
    "BASE_MONTHLY_PREMIUM_CENTS": 100000,
    "PER_CONDITION_DEDUCTIBLE_CENTS": 20000,
    "REIMBURSEMENT_RATE": 0.9,
    "COVERAGE_START": "2026-09-01",
    "PET_DATE_OF_BIRTH": "2025-09-01",
}
