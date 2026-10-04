"""Domain thresholds — numeric constants from the PRD's calculation rules."""

THRESHOLDS = {
    # Fleet reliability score
    "RELIABILITY_SCORE_INITIAL": 1000,
    "DOWNTIME_PENALTY_THRESHOLD_HOURS": 24.0,
    "DOWNTIME_PENALTY": 10,
    "NOT_FIXED_PENALTY": 15,
    "REPEAT_PENALTY": 25,
    "CAMPAIGN_OVERDUE_PENALTY": 5,
    # Repeat repair window
    "REPEAT_THRESHOLD": 3,
    "REPEAT_WINDOW_DAYS": 90,
    # Critical fault response window (minutes)
    "CRITICAL_FAULT_WINDOW_MINUTES": 30,
    # Part return windows (days)
    "RETURN_WINDOW_DAYS_BASE_WARRANTY": 30,
    "RETURN_WINDOW_DAYS_OTHER": 45,
    # Work order window minimum duration (minutes)
    "WORK_ORDER_MIN_DURATION_MINUTES": 30,
    # Campaign close gate
    "CAMPAIGN_CLOSE_COMPLETION_PCT": 95.00,
    "CAMPAIGN_CLOSE_GRACE_DAYS": 90,
    # Labor time standard (hours)
    "LABOR_BASE_SPN3216_FMI4": 4.0,
    "LABOR_BASE_SPN3226_FMI4": 3.5,
    "LABOR_BASE_SPN168_FMI4": 2.0,
    "LABOR_BASE_DEFAULT": 2.5,
    "LABOR_MULT_BASE_WARRANTY": 1.0,
    "LABOR_MULT_CAMPAIGN": 0.9,
    "LABOR_MULT_EXTENDED_COVERAGE": 1.1,
    "LABOR_MULT_GOODWILL": 0.0,
    # Expedite freight rate table: {band: (base_cents, per_kg_cents)}
    "RATE_INTRA_REGION_BASE": 15000,
    "RATE_INTRA_REGION_PER_KG": 300,
    "RATE_CROSS_COUNTRY_BASE": 45000,
    "RATE_CROSS_COUNTRY_PER_KG": 900,
    "RATE_INTERNATIONAL_BASE": 150000,
    "RATE_INTERNATIONAL_PER_KG": 3000,
    "STANDARD_GAIN_FACTOR": 0.6,
    "STANDARD_FREIGHT_FACTOR": 0.4,
}

TEST_DEFAULTS = {
    "CLOCK_START": "2026-09-01T00:00:00Z",
    "REGION": "SE",
    "LABOR_RATE_CENTS": 18500,
    "PART_RETURN_SUPPLIER": "supplier-A",
}
