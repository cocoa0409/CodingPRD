"""Domain thresholds and defaults from the PRD's calculation rules."""

# Logical clock startup default (PRD: the clock reads exactly this instant at
# server startup and never falls back to wall-clock time).
CLOCK_DEFAULT = "2026-09-01T00:00:00Z"
CLOCK_DEFAULT_MS = "2026-09-01T00:00:00.000Z"

# Institution health rolling window and thresholds.
BREAKAGE_WINDOW_SECONDS = 86400
DEGRADED_THRESHOLD = 3
BROKEN_THRESHOLD = 5

# Refresh rate limiting and cadence.
RATE_LIMIT_WINDOW_SECONDS = 3600
INCREMENTAL_MIN_INTERVAL_SECONDS = 3600

# Per-rate-class unit costs and free allowances for monthly refresh cost.
UNIT_COST = {
    "LOW": {"FULL": 2, "INCREMENTAL": 1},
    "MEDIUM": {"FULL": 4, "INCREMENTAL": 2},
    "HIGH": {"FULL": 8, "INCREMENTAL": 3},
}
FREE_UNITS = {"LOW": 10, "MEDIUM": 20, "HIGH": 40}
CENTS_PER_BILLABLE_UNIT = 100

# Minimization policy forbidden-scope sets.
STRICT_FORBIDDEN = {"IDENTITY", "INCOME", "ASSETS"}
STANDARD_FORBIDDEN = {"INCOME", "ASSETS"}
BROAD_FORBIDDEN: set = set()

# Standard consent expiry used by fixtures (far in the future relative to the
# clock default).
FAR_EXPIRY = "2026-12-31T00:00:00Z"

TEST_DEFAULTS = {
    "RATE_LIMIT_PER_HOUR": 100,
    "CONSUMER_REF": "cons_default",
}
