"""Domain thresholds — numeric constants from the PRD's calculation rules."""

THRESHOLDS = {
    # Revenue-share tier boundaries (inclusive-down, integer cents).
    "T0_MAX_CENTS": 100000000,
    "T1_MAX_CENTS": 1000000000,
    # Discount and revenue-share rates.
    "LAUNCH10_RATE": 0.10,
    "T0_SHARE_RATE": 0.00,
    "T1_SHARE_RATE": 0.15,
    "T2_SHARE_RATE": 0.20,
    # Usage proration window.
    "PRORATION_WINDOW_DAYS": 30,
    # Storefront performance budget.
    "BUDGET_MS": 200,
    "IMPACT_MULTIPLIER": 2,
    "BREACH_STRIKES_TO_DELIST": 3,
    # Support SLAs in hours by severity.
    "SLA_LOW_HOURS": 72,
    "SLA_MEDIUM_HOURS": 48,
    "SLA_HIGH_HOURS": 24,
    # Uninstall data-deletion window.
    "DELETION_WINDOW_DAYS": 30,
    # Support dispute window.
    "DISPUTE_WINDOW_DAYS": 14,
    # Governance strike delisting threshold.
    "DELIST_STRIKE_THRESHOLD": 5,
}

TEST_DEFAULTS = {
    "CLOCK_START": "2026-09-01T00:00:00Z",
    "DEFAULT_CYCLE": "2026-09",
    "REVIEWER_ID": "rev-1",
    "HIGH_SCOPE_JUSTIFICATION": "needed to fulfill orders end to end",
}
