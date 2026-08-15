"""Domain thresholds and numeric constants from the PRD calculations."""

# Payload validation (PRD §3.4): minimum payload margin percentage.
MIN_PAYLOAD_MARGIN_PCT = 20.0

# Safety budget thresholds (PRD §3.3): PL derivation cutoffs.
PLE_THRESHOLD_POINTS = 9.0
PLD_THRESHOLD_POINTS = 6.0
BUDGET_FULL_POINTS = 10.0

# Training pass thresholds (PRD §3.8).
OPERATOR_PASS_SCORE_PCT = 80.0
TECHNICIAN_PASS_SCORE_PCT = 85.0

# Retention release schedule pinned percentages (PRD §3.6).
FAT_RELEASE_PCT = 30
SAT_RELEASE_PCT = 40
GUARANTEE_RELEASE_PCT = 30  # residual bucket

# Logical clock server-startup default (PRD §2.10).
CLOCK_DEFAULT_ISO = "2026-08-01T00:00:00Z"

# Pagination (PRD §2.3).
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MAX_LIMIT = 100

# Common test defaults.
DEFAULT_CONTRACTED_CYCLE_TIME_S = 10.0
DEFAULT_CONTRACT_VALUE_CENTS = 1_000_000
DEFAULT_GUARANTEED_OEE_PCT = 80.0
DEFAULT_RETENTION_RATE_BPS = 1000
