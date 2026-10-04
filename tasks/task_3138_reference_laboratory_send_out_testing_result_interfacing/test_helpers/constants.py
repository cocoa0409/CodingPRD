"""Domain thresholds and pinned numeric constants from the PRD's calculation rules."""

# Logical clock startup default (PRD 2.4): the service's only notion of "now".
CLOCK_START = "2026-09-01T00:00:00Z"

# --- volume_tier_price -------------------------------------------------------
TIER_RATE_THROUGH_2 = 1.00
TIER_RATE_3_TO_5 = 0.85
TIER_RATE_6_PLUS = 0.72
TIER_LOWER_BOUND_2 = 2
TIER_LOWER_BOUND_3 = 3
TIER_LOWER_BOUND_6 = 6

# --- order_price_reconciliation ---------------------------------------------
TIER_SURCHARGE_RATE = {"STANDARD": 0.00, "RUSH": 0.15, "CRITICAL": 0.40}
CEILING_MULTIPLIER = 4

# --- rush_priority_surcharge -------------------------------------------------
TIER_TAT_FACTOR = {"STANDARD": 1.0, "RUSH": 0.5, "CRITICAL": 0.25}
RUSH_TAT_THRESHOLD_HOURS = 24

# --- turnaround_credit_per_line ---------------------------------------------
LATE_CREDIT_RATE_PER_HOUR = 0.015

# --- client_utilization_dual_metric -----------------------------------------
UTILIZATION_BAND_PER_MONTH = 4
WINDOW_DAYS = 30

# --- interface_retry_backoff -------------------------------------------------
BASE_RETRY_MINUTES = 5
MAX_RETRY_MINUTES = 60
RETRY_COUNT_LIMIT = 5

# --- billing_route_attribution ----------------------------------------------
DEFAULT_ARRANGEMENT = "CLIENT"

# --- specimen_aliquot_volume_conservation -----------------------------------
VOID_TOLERANCE_CENTS = 0

THRESHOLDS = {
    "TIER_RATE_THROUGH_2": TIER_RATE_THROUGH_2,
    "TIER_RATE_3_TO_5": TIER_RATE_3_TO_5,
    "TIER_RATE_6_PLUS": TIER_RATE_6_PLUS,
    "TIER_LOWER_BOUND_2": TIER_LOWER_BOUND_2,
    "TIER_LOWER_BOUND_3": TIER_LOWER_BOUND_3,
    "TIER_LOWER_BOUND_6": TIER_LOWER_BOUND_6,
    "TIER_SURCHARGE_RATE": TIER_SURCHARGE_RATE,
    "CEILING_MULTIPLIER": CEILING_MULTIPLIER,
    "TIER_TAT_FACTOR": TIER_TAT_FACTOR,
    "RUSH_TAT_THRESHOLD_HOURS": RUSH_TAT_THRESHOLD_HOURS,
    "LATE_CREDIT_RATE_PER_HOUR": LATE_CREDIT_RATE_PER_HOUR,
    "UTILIZATION_BAND_PER_MONTH": UTILIZATION_BAND_PER_MONTH,
    "WINDOW_DAYS": WINDOW_DAYS,
    "BASE_RETRY_MINUTES": BASE_RETRY_MINUTES,
    "MAX_RETRY_MINUTES": MAX_RETRY_MINUTES,
    "RETRY_COUNT_LIMIT": RETRY_COUNT_LIMIT,
}

TEST_DEFAULTS = {
    "CLOCK": CLOCK_START,
    "CREDIT_LIMIT_CENTS": 5_000_000,
    "SETTLEMENT_CENTS": 1150,
}