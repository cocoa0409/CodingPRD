"""Domain thresholds and defaults for the smart licensing platform (PRD §2.4, §3.2, §3.7)."""

# Logical clock startup default (PRD §2.4)
CLOCK_DEFAULT = "2026-09-01T00:00:00Z"

# Grace window (PRD §3.2): grace_deadline = overage_detected_at + 90 days
GRACE_PERIOD_DAYS = 90
GRACE_PERIOD_SECONDS = 90 * 86400

# RMA ship-by SLA (PRD §3.7)
ADVANCE_4H_SECONDS = 14400
ADVANCE_NBD_SECONDS = 86400

# Depot return window on advance branches (PRD §3.7)
DEPOT_RETURN_WINDOW_DAYS = 30

THRESHOLDS = {
    "GRACE_PERIOD_DAYS": GRACE_PERIOD_DAYS,
    "ADVANCE_4H_SECONDS": ADVANCE_4H_SECONDS,
    "ADVANCE_NBD_SECONDS": ADVANCE_NBD_SECONDS,
    "DEPOT_RETURN_WINDOW_DAYS": DEPOT_RETURN_WINDOW_DAYS,
}

# Standard contract window used across fixtures (in-window at the default clock)
CONTRACT_START = "2026-09-01T00:00:00Z"
CONTRACT_END = "2027-09-01T00:00:00Z"

TEST_DEFAULTS = {
    "PURCHASED_QUANTITY": 10,
    "SERVICE_LEVEL": "ADVANCE_NBD",
    "SUPPORT_TIER": "FULL",
}
