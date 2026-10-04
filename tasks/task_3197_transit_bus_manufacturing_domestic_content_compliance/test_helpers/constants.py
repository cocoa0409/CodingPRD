"""Domain thresholds — numeric constants from the PRD's calculations."""

# Logical clock epoch: before any admin clock call the clock reads this instant.
CLOCK_EPOCH_ISO = "2026-09-01T00:00:00Z"

THRESHOLDS = {
    # Option escalation (PRD section 3.2)
    "ESCALATION_PPI_1413": 1.031,
    "ESCALATION_CPI_U": 1.024,
    "TIER1_QTY": 5,
    "TIER2_QTY": 20,
    "TIER1_DISCOUNT": 0.02,
    "TIER2_DISCOUNT": 0.05,
    # Domestic content certification (PRD section 3.6)
    "DEFAULT_THRESHOLD_PCT": 70,
    # Warranty approval tiers (PRD section 3.9)
    "WARRANTY_T1_DAYS": 180,
    "WARRANTY_T2_DAYS": 365,
    "WARRANTY_CAP_CENTS": 2_500_000,
    # Bus acceptance window (PRD section 3.8)
    "ACCEPTANCE_WINDOW_DAYS": 30,
    # Configuration freeze gate (PRD section 3.3)
    "MIN_SEAT_COUNT": 10,
}

TEST_DEFAULTS = {
    "BASE_UNIT_PRICE_CENTS": 50_000_000,
    "BASE_CONTRACT_YEAR": 2027,
    "COMPONENT_COST": 800_000,
    "TRANSITION_TARGET_YEAR": 2035,
}
