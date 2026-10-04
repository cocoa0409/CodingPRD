"""Domain thresholds — numeric constants from the PRD's metering and review rules."""

THRESHOLDS = {
    # Metering factors (PRD §2.6)
    "POLLING_FACTOR": 4,
    "WEBHOOK_FACTOR": 1,
    "INSTANT_WEBHOOK_FACTOR": 0.25,
    # Latency multipliers (PRD §2.6)
    "LATENCY_BAND_1_MAX": 60,
    "LATENCY_BAND_1_FACTOR": 1,
    "LATENCY_BAND_2_MAX": 300,
    "LATENCY_BAND_2_FACTOR": 1.5,
    "LATENCY_BAND_3_MAX": 900,
    "LATENCY_BAND_3_FACTOR": 2,
    "LATENCY_BAND_4_FACTOR": 3,
    # Computed trigger latency by trigger type (PRD §2.6)
    "POLLING_LATENCY_SECONDS": 900,
    "WEBHOOK_LATENCY_SECONDS": 30,
    "INSTANT_WEBHOOK_LATENCY_SECONDS": 0,
    "POLL_INTERVAL_DEFAULT": 900,
    "POLL_INTERVAL_MIN": 60,
    # Charge task (PRD §2.5 / §2.7)
    "RETRY_SURCHARGE_CENTS": 50,
    "USD_CENTS": 100,
    "MAX_RETRIES_DEFAULT": 3,
    # Retry envelope (PRD §2.7)
    "RETRY_ENVELOPE_BASE_ATTEMPTS": 5,
    "FAILED_PERMANENT_MIN_CENTS": 100,
    "REPLAYABLE_FAILED_MAX_CENTS": 99,
    # Review gate / coverage (PRD §2.9)
    "COVERAGE_MIN": 0.8,
    "COVERAGE_PRECISION": 2,
    # Workflow run ceiling (PRD §3.3)
    "WORKFLOW_MAX_STEPS": 10,
    # Connection refresh cap (PRD §3.6)
    "REFRESH_CAP": 5,
}

TEST_DEFAULTS = {
    "TASK_ALLOWANCE": 100,
    "CLOSER_COST_PER_TASK_CENTS": 1,
    "OPENING_COST_PER_TASK_CENTS": 1,
    "OVERAGE_ENABLED": True,
    "PLAN_CODE": "TEAM_PRO",
}

# The polling charge of a single-attempt, default-cadence action: ceil(4 * 2) == 8.
POLLING_CHARGE_TASKS = 8