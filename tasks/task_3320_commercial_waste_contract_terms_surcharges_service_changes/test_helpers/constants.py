"""Domain thresholds — numeric constants from the PRD's calculations."""

# Logical-clock starting point, before any clock-setting call (PRD section 2.4).
LOGICAL_CLOCK_START = "2026-09-01T00:00:00Z"

THRESHOLDS = {
    # Right-of-first-refusal undercut subtracted from the competitor offer.
    "ROFR_UNDERCUT_CENTS": 500,
    # Service-change quoting multipliers.
    "UPGRADE_MULT": 1.10,
    "DOWNGRADE_MULT": 0.95,
    # Liquidated damages fraction of base per remaining month.
    "LD_FRACTION": 0.5,
    # Days a pickup dispute may be filed after occurred_date.
    "DISPUTE_WINDOW_DAYS": 30,
    # Days a missed-pickup service credit may be filed after occurred_date.
    "CREDIT_FILING_WINDOW_DAYS": 14,
    # Trailing window used by the monthly invoice for event fees.
    "INVOICE_FEE_WINDOW_DAYS": 30,
    # Max roll-off rental length in days.
    "MAX_RENTAL_DAYS": 30,
    # Max pickups per week on a service line.
    "MAX_FREQUENCY_PER_WEEK": 6,
}

TEST_DEFAULTS = {
    "BASE_RATE_CENTS": 100000,
    "CONTAMINATION_FEE_CENTS": 15000,
    "OVERWEIGHT_FEE_CENTS": 20000,
}
