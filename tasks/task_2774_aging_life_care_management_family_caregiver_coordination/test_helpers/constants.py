"""Domain thresholds and numeric constants drawn from the PRD's calculations."""

# --- time-entry rating -------------------------------------------------------
CRISIS_MULTIPLIER = 1.5
AFTER_HOURS_START_UTC_HOUR = 18
AFTER_HOURS_END_UTC_HOUR = 8
AFTER_HOURS_FACTOR = 1.20
NORMAL_HOURS_FACTOR = 1.00
DAILY_BILLABLE_CAP_MINUTES = 600
TRAVEL_BUFFER_MINUTES = 30

# --- invoicing ---------------------------------------------------------------
ADMIN_FEE_PCT = 7

# --- acuity ------------------------------------------------------------------
DOMAIN_SCALE = 20
DOMAIN_KEYS = [
    "adl",
    "cognition",
    "medical_complexity",
    "social_support",
    "safety",
    "finances",
]
COMPREHENSIVE_WEIGHTS = {
    "safety": 0.30,
    "cognition": 0.25,
    "adl": 0.20,
    "medical_complexity": 0.15,
    "social_support": 0.05,
    "finances": 0.05,
}
ACUITY_ELEVATED_THRESHOLD = 70
ACUITY_MIN = 0
ACUITY_MAX = 100
DOMAIN_SCORE_MIN = 0
DOMAIN_SCORE_MAX = 5

# --- coordination-fee tiers, selected from base_cost_cents -------------------
TIER_1_CEILING_CENTS = 200_000
TIER_2_CEILING_CENTS = 500_000
TIER_1_PCT = 8
TIER_2_PCT = 6
TIER_3_PCT = 4

# --- long-distance family reporting cadence ----------------------------------
GRACE_DAYS = 7
DEFAULT_REPORTING_CADENCE_DAYS = 30
MIN_REPORTING_CADENCE_DAYS = 1
MAX_REPORTING_CADENCE_DAYS = 180

# --- conference quorum -------------------------------------------------------
QUORUM_NUMERATOR = 1
QUORUM_DENOMINATOR = 2
MIN_INVITED_CONTACTS = 1
MAX_INVITED_CONTACTS = 12

# --- client registration defaults -------------------------------------------
DEFAULT_BILLING_INCREMENT_MIN = 15
ALLOWED_BILLING_INCREMENTS = [6, 15]
DEFAULT_TRAVEL_BILLING_PCT = 50
DEFAULT_RETAINER_FLOOR_CENTS = 50_000
DEFAULT_AUTHORIZED_CONCURRENT_CAREGIVERS = 2

# --- care plan ---------------------------------------------------------------
DEFAULT_REVIEW_INTERVAL_DAYS = 90
MIN_REVIEW_INTERVAL_DAYS = 30
MAX_REVIEW_INTERVAL_DAYS = 365
MIN_GOALS = 1
MAX_GOALS = 12

# --- service authorization ---------------------------------------------------
MIN_CONCURRENT_CAREGIVERS = 1
MAX_CONCURRENT_CAREGIVERS = 10

# --- pagination --------------------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# --- the logical clock -------------------------------------------------------
CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"

# --- rates used across the generated fixtures --------------------------------
CARE_MANAGER_HOURLY_RATE_CENTS = 22_500
SUPERVISOR_HOURLY_RATE_CENTS = 30_000
