"""Domain thresholds — numeric constants from PRD rules (§2.3, §2.5, §3)."""

# Shop logical clock startup value (PRD §2.5).
SHOP_CLOCK_INIT_ISO = "2026-08-01T00:00:00Z"

# Welder continuity window (PRD §3.2: qualified baseline plus 183 days).
CONTINUITY_WINDOW_DAYS = 183

# SMAW low-hydrogen cumulative atmospheric exposure limit (PRD §3.3).
SMAW_EXPOSURE_LIMIT_MINUTES = 240

# AWS D1.1 single-rebake allowance (PRD §3.3).
REBAKE_MAX_COUNT = 1

# AWS D1.1 repair-cycle hard cap on a joint (PRD §3.6/§3.7).
REPAIR_CYCLE_HARD_CAP = 2

# Distortion reports needed (with an NDT_FAILED joint) to freeze a weldment.
FROZEN_DISTORTION_THRESHOLD = 2

# Shop creation default for repair_rate_limit_pct (PRD §3.1).
DEFAULT_REPAIR_RATE_LIMIT_PCT = 5

# Oven holding-temperature acceptance window, inclusive (PRD §3.3).
OVEN_HOLDING_TEMP_MIN_C = 120
OVEN_HOLDING_TEMP_MAX_C = 300

# Pagination (PRD §2.3).
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MAX_LIMIT = 100

# Percentages are stored at two decimals, rounded half-up (PRD §2.9).
PCT_TOLERANCE = 0.005
