"""Domain thresholds — numeric constants from the PRD's schedule/calculation rules."""

# PRD: scheduled transit speed for every train plan is 25.0 miles per hour.
PLAN_SPEED_MPH = 25.0

# PRD: the hours-of-service maximum for a single crew assignment is 12.0 hours.
HOS_MAX_HOURS = 12.0

# PRD: a departure more than 30 minutes behind schedule raises delay exceptions.
DEPARTURE_DELAY_THRESHOLD_MINUTES = 30

# PRD: at server startup the logical clock is exactly 2026-09-01T00:00:00Z.
SERVER_DEFAULT_CLOCK = "2026-09-01T00:00:00Z"

THRESHOLDS = {
    "PLAN_SPEED_MPH": PLAN_SPEED_MPH,
    "HOS_MAX_HOURS": HOS_MAX_HOURS,
    "DEPARTURE_DELAY_THRESHOLD_MINUTES": DEPARTURE_DELAY_THRESHOLD_MINUTES,
}

TEST_DEFAULTS = {
    "DWELL_BENCHMARK_HOURS": 10,
    "CLASSIFICATION_CAPACITY": 100,
    "ROUTE_MILES": 300,
    "CREWS_AVAILABLE": 2,
    "HORSEPOWER": 4400,
}
