"""Domain thresholds and logical-clock anchors from the PRD."""

# Logical clock (PRD §2.4): before any call the clock reads exactly this.
CLOCK_START = "2026-09-01T00:00:00Z"
# Convenience working instant used by most setups (one day after start).
WORK_DATE = "2026-09-02T00:00:00Z"

THRESHOLDS = {
    # Step-chain inclusion boundaries (PRD §3.6)
    "HEADCOUNT_TIER_THRESHOLD": 50,
    "AMOUNT_THRESHOLD": 1000,
    # Definition escalation floor (PRD §3.5: escalation_after_hours must be >= 24)
    "MIN_ESCALATION_HOURS": 24,
    # Adoption health score (PRD §3.7)
    "HEALTH_BASE": 100,
    "ENROLLED_PENALTY": 5,
    "DEFERRED_PENALTY": 15,
    "LATE_PENALTY": 10,
    "PREMIUM_EXTENSION_DAYS": 14,
    # Integration run retry cap (PRD §3.8)
    "MAX_RUN_ATTEMPTS": 3,
    # Provisional drift weights (PRD §3.9)
    "NEW_DEFINITION_WEIGHT": 2,
    "STALE_DEFINITION_WEIGHT": 1,
    "NEW_GROUP_WEIGHT": 1,
}

TEST_DEFAULTS = {
    "MAINTENANCE_SLOT_UTC": 2,
    "BLACKOUT_START": 3,
    "BLACKOUT_END": 4,
    "MIN_APPROVERS": 1,
}
