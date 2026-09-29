"""Domain constants for the Consulting Bench Management API test suite.

Every value here is declared verbatim by PRD.md; nothing is inferred.
"""

# --- Logical clock -----------------------------------------------------------
# PRD §2.5: the clock is initialised to 2026-08-01T00:00:00Z on a fresh server.
CLOCK_INITIAL_UTC = "2026-08-01T00:00:00Z"

# Calendar anchors used throughout the suite (all verified weekday facts).
DATE_MON_AUG_03 = "2026-08-03"   # Monday
DATE_MON_AUG_10 = "2026-08-10"   # Monday
DATE_FRI_AUG_14 = "2026-08-14"   # Friday
DATE_SAT_AUG_15 = "2026-08-15"   # Saturday
DATE_SUN_AUG_16 = "2026-08-16"   # Sunday
DATE_MON_AUG_17 = "2026-08-17"   # Monday
DATE_FRI_AUG_28 = "2026-08-28"   # Friday
DATE_SAT_AUG_29 = "2026-08-29"   # Saturday
DATE_MON_AUG_31 = "2026-08-31"   # Monday
DATE_TUE_SEP_01 = "2026-09-01"   # Tuesday
DATE_WED_SEP_02 = "2026-09-02"   # Wednesday
DATE_MON_SEP_14 = "2026-09-14"   # Monday
DATE_TUE_SEP_15 = "2026-09-15"   # Tuesday
DATE_WED_SEP_30 = "2026-09-30"   # Wednesday

INSTANT_AUG_03 = "2026-08-03T00:00:00Z"
INSTANT_AUG_10 = "2026-08-10T00:00:00Z"
INSTANT_AUG_11 = "2026-08-11T00:00:00Z"
INSTANT_AUG_16 = "2026-08-16T00:00:00Z"
INSTANT_AUG_17 = "2026-08-17T00:00:00Z"
INSTANT_AUG_28 = "2026-08-28T00:00:00Z"
INSTANT_AUG_29 = "2026-08-29T00:00:00Z"
INSTANT_AUG_31 = "2026-08-31T00:00:00Z"
INSTANT_SEP_01 = "2026-09-01T00:00:00Z"
INSTANT_SEP_02 = "2026-09-02T00:00:00Z"
INSTANT_SEP_15 = "2026-09-15T00:00:00Z"
INSTANT_SEP_30 = "2026-09-30T00:00:00Z"

# --- Workday model (PRD §2.5) ------------------------------------------------
WORKDAY_HOURS = 8

# --- Posture thresholds (PRD §2.10) -----------------------------------------
POSTURE_FROZEN_RATIO = 0.5000
POSTURE_CONSTRAINED_RATIO = 0.3000
POSTURE_FROZEN_L2_COUNT = 3
SCARCITY_CARVE_OUT_INDEX = 0.7000

# --- Discount / margin thresholds (PRD §2.9, §3.7) --------------------------
DISCOUNT_HARD_CAP_PCT = 35.00
MARGIN_FLOOR_PCT = 20.00
DISCOUNT_TIER_NONE_MAX_PCT = 5.00
DISCOUNT_TIER_L1_MAX_PCT = 15.00

# LEVEL_FLOOR proxy cost rates by min_proficiency_level (PRD §3.7 step S3).
LEVEL_FLOOR_COST_RATES = {
    1: 45.00,
    2: 60.00,
    3: 80.00,
    4: 105.00,
    5: 130.00,
}

# --- Match score weights and constants (PRD §3.5) ---------------------------
MATCH_WEIGHT_SKILL = 0.35
MATCH_WEIGHT_INDUSTRY = 0.15
MATCH_WEIGHT_DEV_GOAL = 0.15
MATCH_WEIGHT_TRAVEL = 0.20
MATCH_WEIGHT_COST = 0.15
CERTIFICATION_BONUS = 0.10
INDUSTRY_FIT_FULL_YEARS = 3
MAX_PROFICIENCY_LEVEL = 5
MAX_TRAVEL_NIGHTS = 5

# --- Forecast (PRD §3.9) -----------------------------------------------------
HIRE_YIELD_FTE = 0.85
COMMITTED_PROBABILITY_FLOOR_PCT = 70
FORECAST_INTERNAL_SUPPLY_MIN_PROFICIENCY = 3

# --- Level target defaults (PRD §2.10) --------------------------------------
# target_utilization_pct, bench_escalation_l1_days, bench_escalation_l2_days,
# max_investment_pct
LEVEL_TARGET_DEFAULTS = {
    "ANALYST": {
        "target_utilization_pct": 70.00,
        "bench_escalation_l1_days": 21,
        "bench_escalation_l2_days": 45,
        "max_investment_pct": 20.00,
    },
    "CONSULTANT": {
        "target_utilization_pct": 75.00,
        "bench_escalation_l1_days": 14,
        "bench_escalation_l2_days": 30,
        "max_investment_pct": 15.00,
    },
    "SENIOR_CONSULTANT": {
        "target_utilization_pct": 80.00,
        "bench_escalation_l1_days": 14,
        "bench_escalation_l2_days": 28,
        "max_investment_pct": 12.00,
    },
    "MANAGER": {
        "target_utilization_pct": 70.00,
        "bench_escalation_l1_days": 30,
        "bench_escalation_l2_days": 60,
        "max_investment_pct": 25.00,
    },
    "PRINCIPAL": {
        "target_utilization_pct": 55.00,
        "bench_escalation_l1_days": 45,
        "bench_escalation_l2_days": 90,
        "max_investment_pct": 35.00,
    },
}

# --- Entity defaults (PRD §3) -----------------------------------------------
DEFAULT_EXTERNAL_SOURCING_CAP_PCT = 20.00
DEFAULT_SCARCITY_INDEX = 0.5000
DEFAULT_TRAVEL_MAX_NIGHTS_PER_WEEK = 3
DEFAULT_MARKUP_PCT = 15.00
DEFAULT_COOLDOWN_DAYS = 3
DEFAULT_HOLIDAY_HOURS = 0.00

# --- Pagination (PRD §2.2) --------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# --- Reserved identity literal (PRD §2.11) ---------------------------------
SYSTEM_AUTO_USER_ID = "SYSTEM_AUTO"

# --- Geographies and enums used by factories -------------------------------
GEOGRAPHY_CODES = ("NA", "EMEA", "APAC", "LATAM")
SKILL_FAMILIES = ("CLOUD", "DATA", "SECURITY", "ERP", "AI")
CONSULTANT_LEVELS = (
    "ANALYST",
    "CONSULTANT",
    "SENIOR_CONSULTANT",
    "MANAGER",
    "PRINCIPAL",
)

# A syntactically valid UUID that is never minted by the server.
UNKNOWN_UUID = "00000000-0000-4000-8000-000000000000"
UNKNOWN_UUID_ALT = "00000000-0000-4000-8000-0000000000ff"
