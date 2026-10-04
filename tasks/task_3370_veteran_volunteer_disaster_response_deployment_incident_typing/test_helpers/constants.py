"""Domain constants — every threshold, weight, cap, and standard fixture
timestamp named in the PRD (logical clock, readiness, stipend, lodging,
priority, fatigue, deployment timing, wellness, and capacity caps)."""

# --- Logical clock (PRD: startup default before any clock-setting call) ---
CLOCK_START = "2026-09-01T00:00:00Z"

# --- Readiness scoring (PRD readiness doctrine) ---
READINESS_BASE = 10
CERT_WEIGHTS = {
    "CHAINSAW": 30,
    "HEAVY_EQUIPMENT": 25,
    "STRUCTURAL": 25,
    "MEDICAL": 20,
}
FATIGUE_PENALTY_PER_HOUR = 2
READINESS_FLOOR = 0
MIN_VERIFIED_CERTS_FOR_DEPLOYABLE = 1

# --- Deployment stipend (integer cents) ---
PER_DIEM_DAILY_CENTS = 6500
TRAVEL_TIER_THRESHOLD_CENTS = 200000
TRAVEL_TIER_SHORT_CENTS = 15000
TRAVEL_TIER_LONG_CENTS = 45000

# --- FOB lodging ledger ---
FOB_UTILITY_SURCHARGE_PCT = 0.07

# --- Work-order priority scoring ---
HAZARD_BASE = {
    "STRUCTURAL": 60,
    "TREE_REMOVAL": 50,
    "TARPING": 35,
    "MUCK_OUT": 30,
    "DEBRIS": 20,
}
VULNERABLE_RESIDENT_BONUS = 40
AGE_BOOST_PER_DAY = 5
AGE_BOOST_CAP = 20
PRIORITY_SCORE_CAP = 100
P1_THRESHOLD = 80
P2_THRESHOLD = 50

# --- Pinned hazard -> capability map (MUCK_OUT maps to none) ---
HAZARD_CAPABILITY_MAP = {
    "TREE_REMOVAL": "CHAINSAW",
    "DEBRIS": "HEAVY_EQUIPMENT",
    "STRUCTURAL": "STRUCTURAL",
    "TARPING": "STRUCTURAL",
    "MUCK_OUT": None,
}

# --- Fatigue / duty shifts ---
REST_RESET_HOURS = 24
MAX_FATIGUE_HOURS = 40
MAX_SHIFT_HOURS = 12

# --- Deployment timing ---
REST_BUFFER_HOURS = 24
CALL_UP_RESPONSE_HOURS = 48
NO_SHOW_GRACE_HOURS = 24

# --- Wellness screen at demobilization ---
WELLNESS_FATIGUE_THRESHOLD_HOURS = 30
WELLNESS_LONG_DEPLOYMENT_DAYS = 10

# --- Operation / course caps ---
MAX_TEAM_SIZE = 40
MIN_TEAM_SIZE = 2
MAX_OPERATION_DURATION_DAYS = 30
MAX_COURSE_CAPACITY = 50
CERT_GRANT_VALIDITY_DAYS = 730

# --- Standard fixture timestamps (all forward-reachable from CLOCK_START) ---
CERT_ISSUED_AT = "2026-09-01T00:00:00Z"
CERT_EXPIRES_AT = "2027-03-01T00:00:00Z"
AVAILABILITY_START = "2026-09-05T00:00:00Z"
AVAILABILITY_END = "2026-09-30T00:00:00Z"
AVAILABILITY_WINDOW = {
    "start_iso8601": AVAILABILITY_START,
    "end_iso8601": AVAILABILITY_END,
}
OP_START_DATE = "2026-09-10"
PLANNED_START = "2026-09-10T08:00:00Z"
PLANNED_END = "2026-09-14T08:00:00Z"
CHECK_IN_CLOCK = "2026-09-10T08:00:00Z"

# --- Standard money values used by lodging fixtures ---
FOB_NIGHTLY_RATE_ROUNDING = 1235   # x1.07 -> 1321.45 -> per-night round_half_up 1321
FOB_NIGHTLY_RATE_PLAIN = 1000      # x1.07 -> 1070 exactly
