"""Domain thresholds and counters — numeric constants from the PRD's calculations."""

THRESHOLDS = {
    # Autoclave batch ceiling and sterilization backlog ceiling (PRD §2.8).
    "AUTOCLAVE_BATCH_MAX": 24,
    "STERILIZATION_BACKLOG_MAX": 6,
    # Coverage floor for the READY posture gate (PRD §3.4).
    "COVERAGE_MIN": 60,
    # Host cost share base costs in cents per site type (PRD §3.2).
    "ARENA_BASE_CENTS": 800000,
    "FAIRGROUND_BASE_CENTS": 500000,
    "SCHOOL_BASE_CENTS": 300000,
    # Coverage demand weights (PRD §3.4).
    "WEIGHT_DENTAL": 0.5,
    "WEIGHT_VISION": 0.3,
    "WEIGHT_MEDICAL": 0.2,
    # Minimum venue square footage for vetting (PRD §3.1).
    "SITE_MIN_SQUARE_FOOTAGE": 2000,
    # Half-capacity divisor applied to DEGRADED stations in the projection.
    "DEGRADED_CAPACITY_DIVISOR": 2,
}

# Logical clock value at server startup (PRD §2.9).
CLOCK_START_UTC = "2026-09-01T00:00:00Z"
