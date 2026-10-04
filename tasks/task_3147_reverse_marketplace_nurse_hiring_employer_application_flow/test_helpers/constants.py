"""Domain thresholds and seeded constants.

Every value below is a number or date the requirement document pins explicitly.
"""

# --- Logical clock ---------------------------------------------------------
DEFAULT_CLOCK = "2026-09-01T00:00:00Z"

# --- Nurse profile ---------------------------------------------------------
HOURLY_RATE_FLOOR_CENTS = 2000
YEARS_EXPERIENCE_MIN = 0
YEARS_EXPERIENCE_MAX = 60
MAX_COMMUTE_MILES_MIN = 1
MAX_COMMUTE_MILES_MAX = 500

# --- Employer registration -------------------------------------------------
SLA_RESPONSE_HOURS_MIN = 24
SLA_RESPONSE_HOURS_MAX = 168
GUARANTEE_DAYS_MIN = 30
GUARANTEE_DAYS_MAX = 120
PLACEMENT_FEE_BPS_MIN = 500
PLACEMENT_FEE_BPS_MAX = 3000

# --- Requisition -----------------------------------------------------------
DISTANCE_FROM_FACILITY_MILES_MIN = 0
DISTANCE_FROM_FACILITY_MILES_MAX = 500
OPENINGS_TOTAL_MIN = 1
OPENINGS_TOTAL_MAX = 20

# --- Match scoring ---------------------------------------------------------
MATCH_GEO_WEIGHT = 40
MATCH_EXP_WEIGHT = 25
MATCH_EXP_CAP_YEARS = 10
MATCH_SHIFT_WEIGHT = 20
MATCH_SHIFT_PARTIAL = 10
MATCH_COMMUTE_WEIGHT = 15
MATCH_CERT_PENALTY = -20
MATCH_SCORE_MIN = 0
MATCH_SCORE_MAX = 100

# --- Interviews ------------------------------------------------------------
INTERVIEW_MIN_DURATION_MINUTES = 30
INTERVIEW_MAX_DURATION_MINUTES = 240
INTERVIEW_BUFFER_MINUTES = 30
MAX_UNIT_INTERVIEWS_PER_DAY = 6

# --- Deadlines -------------------------------------------------------------
APPLICATION_RESPONSE_DEADLINE_HOURS = 72
COUNTER_EXTENSION_HOURS = 48
MAX_REVISIONS = 2
OFFER_EXPIRY_HOURS = 48

# --- Offers / placements ---------------------------------------------------
START_DATE_MIN_DAYS = 14
START_DATE_MAX_DAYS = 90
HOURS_PER_YEAR = 2080

# --- Subscription flat placement fees (integer cents) ----------------------
BASIC_FEE_CENTS = 2500000
PRO_FEE_CENTS = 2000000
ENTERPRISE_FEE_CENTS = 1500000

# --- SLA report ------------------------------------------------------------
RAPID_OFFER_TARGET_HOURS = 120
