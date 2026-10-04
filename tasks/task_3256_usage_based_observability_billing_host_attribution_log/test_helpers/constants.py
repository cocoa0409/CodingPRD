"""Domain thresholds and default rates (PRD §2.7, §3.1, §3.3, §3.7)."""

# Cardinality abuse detection: soft cap of ten thousand units above the bundled
# quota (PRD §3.7).
CARDINALITY_SOFT_CAP = 10_000

# Log pricing conversions (PRD §3.3).
BYTES_PER_GB = 1_000_000_000
EVENTS_PER_MILLION = 1_000_000
BP_BASE = 10_000  # a multiplier of 10000 means exactly 1.0x the underlying rate

# Logical clock startup default (PRD §2.6).
CLOCK_START_UTC = "2026-09-01T00:00:00Z"

# Canonical September 2026 billing window used across fixtures.
SEPT_PERIOD_START = "2026-09-01T00:00:00Z"
SEPT_PERIOD_END = "2026-10-01T00:00:00Z"
SEPT_WINDOW_END = "2026-09-30T23:59:59Z"
OCT_START_UTC = "2026-10-01T00:00:00Z"

# Standard ENTERPRISE plan configuration used by the design-index recipes.
ENTERPRISE_PLAN = {
    "plan_tier": "ENTERPRISE",
    "max_monitors": 500,
    "included_custom_metrics": 200,
    "host_overage_rate_cents": 1500,
    "log_ingest_rate_cents_per_gb": 10,
    "log_index_rate_cents_per_million": 170,
    "custom_metric_rate_cents_per_unit": 5,
}

FREE_PLAN = {
    "plan_tier": "FREE",
    "max_monitors": 5,
    "included_custom_metrics": 10,
    "host_overage_rate_cents": 2000,
    "log_ingest_rate_cents_per_gb": 20,
    "log_index_rate_cents_per_million": 200,
    "custom_metric_rate_cents_per_unit": 10,
}
