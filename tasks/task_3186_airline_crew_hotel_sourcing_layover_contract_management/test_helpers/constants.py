"""Domain thresholds — numeric constants from the PRD's business rules."""

THRESHOLDS = {
    # Transport pickup buffer (PRD §3.9): HOTEL_TO_AIRPORT pickup subtracts transport + 90 min
    "PICKUP_BUFFER_MINUTES": 90,
    # Irregular-ops pickup floor (PRD §3.9): never schedule in the past; clock + 30 min
    "IROPS_PICKUP_PUSH_MINUTES": 30,
    # Distressed surge tiers (PRD §3.7): pre-existing distressed-count bands
    "DISTRESSED_TIER1_MAX": 5,
    "DISTRESSED_TIER2_MAX": 10,
    "DISTRESSED_MULT_TIER1": 1.25,
    "DISTRESSED_MULT_TIER2": 1.50,
    "DISTRESSED_MULT_TIER3": 2.00,
    # Late-cancel charge fraction (PRD §3.10): 50 percent of the line amount
    "LATE_CANCEL_FRACTION": 0.50,
    # Three-strike termination gate (PRD §3.4): low-rated (<= 2) feedback rows required
    "TERMINATION_STRIKES": 3,
    # Remediation window (PRD §3.8): logical clock + 168 hours (one week)
    "REMEDIATION_HOURS": 168,
    # Pagination defaults (PRD §2.3)
    "PAGE_DEFAULT_LIMIT": 10,
    "PAGE_MAX_LIMIT": 100,
}

TEST_DEFAULTS = {
    "DEFAULT_RATE_CENTS": 9000,
    "DEFAULT_BLOCK_SIZE": 5,
    "DEFAULT_BUDGET_CAP": 1_000_000,
    "DEFAULT_LATE_CANCEL_HOURS": 24,
    "CLOCK_START": "2026-09-01T00:00:00Z",
}
