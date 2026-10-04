"""Domain thresholds — numeric constants from the PRD's calculations (§3)."""

# Logical clock default before any set call (PRD §2.5).
DEFAULT_CLOCK = "2026-09-01T00:00:00Z"

# Conversion post cost estimate rates, keyed by target format (PRD §3.3).
CONVERSION_BASE_CENTS = {
    "PREMIUM_2D": 200000000,
    "PREMIUM_3D": 350000000,
    "PREMIUM_70MM": 500000000,
}
CONVERSION_PER_MINUTE_CENTS = {
    "PREMIUM_2D": 1200000,
    "PREMIUM_3D": 1800000,
    "PREMIUM_70MM": 2500000,
}

# Tiered marginal share weekly-gross boundaries per slot (PRD §3.6).
TIER1_CAP_CENTS = 10000000   # $100,000.00
TIER2_CAP_CENTS = 25000000   # $250,000.00

# Provisional forecast: unreported days at half the mean reported daily gross.
FORECAST_DAILY_FRACTION = 0.5

# Hold-over / attendance threshold (inclusive, PRD §3.5).
HOLD_OVER_ADMISSION_THRESHOLD = 0.65

# Auditorium quality-score severity weights (PRD §3.8).
SEVERITY_WEIGHTS = {"INFO": 1, "WARNING": 3, "CRITICAL": 10}
QUALITY_SCORE_WINDOW_DAYS = 30
QUALITY_SCORE_MAX_AGE_DAYS = 29
SECONDS_PER_DAY = 86400

# Calibration freshness window (PRD §3.1).
CALIBRATION_OVERDUE_DAYS = 90

# Film distribution window (PRD §3.2).
DISTRIBUTION_WINDOW_DAYS = 84

# Rework post-window reset length (PRD §3.3).
REWORK_POST_WINDOW_DAYS = 7

TEST_DEFAULTS = {
    "WINDOW_POOL_SECONDS": 10000000,
    "SHOWINGS_PER_DAY": 2,
    "RUNTIME_MINUTES": 100,
    "SEATING_CAPACITY": 200,
}
