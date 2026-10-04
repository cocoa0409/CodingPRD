"""Domain thresholds — numeric constants from the PRD calculations."""

GB_BYTES = 1_000_000_000
INVOCATION_MILLION = 1_000_000
DEFAULT_ESTIMATE_MINUTES = 2
SECONDS_PER_MINUTE = 60
CERT_VALIDITY_DAYS = 90
CLOCK_DEFAULT_ISO = "2026-09-01T00:00:00Z"
SLUG_BASE_MAX_LEN = 40
PREVIEW_URL_SUFFIX = ".preview.example.com"

# Regional edge execution multipliers (per million invocations, cents).
REGION_EDGE_MULTIPLIER = {"IAD": 1, "SFO": 1, "FRA": 2, "SIN": 3}

# Common period window used across fixtures.
PERIOD_START = "2026-09-01T00:00:00Z"
PERIOD_END = "2026-10-01T00:00:00Z"
