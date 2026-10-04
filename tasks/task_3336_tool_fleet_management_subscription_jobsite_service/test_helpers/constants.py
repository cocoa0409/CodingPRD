"""Domain thresholds — numeric constants from the PRD calculation rules."""

THRESHOLDS = {
    # repair_turnaround_penalty (PRD §3.6)
    "SLA_DAYS_LIGHT": 3,
    "SLA_DAYS_HEAVY": 5,
    "DAILY_CREDIT_LIGHT_CENTS": 2500,
    "DAILY_CREDIT_HEAVY_CENTS": 9000,
    "CREDIT_CAP_CENTS": 50000,
    # theft_replacement_cost (PRD §3.7)
    "DEDUCTIBLE_FLOOR_CENTS": 50000,
    "DEDUCTIBLE_CAP_CENTS": 250000,
    "COVERAGE_CAP_CENTS": 1000000,
    # fleet_utilization (PRD §3.5)
    "WORKDAY_MINUTES": 480,
    # end_of_term_settlement (PRD §3.9) — 20 percent per billable asset
    "BUYOUT_PCT_NUM": 20,
    "BUYOUT_PCT_DEN": 100,
}

CLOCK_DEFAULT = "2026-09-01T00:00:00Z"
