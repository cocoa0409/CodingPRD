"""Canonical literals and PRD-declared thresholds used across the suite.

Every value here is transcribed from the PRD; nothing is invented.
"""

API_PREFIX = "/pdn"

# --- Logical clock (PRD 2.5) ---------------------------------------------
#: The clock reads this instant before any client moves it.
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"
#: Monday 06:00Z of ISO week 32 of 2026 - the instant the design recipes park on.
CLOCK_WEEK32_MONDAY_06 = "2026-08-03T06:00:00Z"
#: Bounds of the ISO week window containing CLOCK_WEEK32_MONDAY_06.
WEEK32_START = "2026-08-03T00:00:00Z"
WEEK32_END = "2026-08-10T00:00:00Z"
#: Monday 06:00Z of the following ISO week.
CLOCK_WEEK33_MONDAY_06 = "2026-08-10T06:00:00Z"

# --- Pagination (PRD 2.3) ------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# --- Numeric conventions (PRD 2.9) ---------------------------------------
HOURS_DECIMAL_PLACES = 2
RATIO_DECIMAL_PLACES = 4
MINUTES_PER_BILLING_UNIT = 15

# --- Billing edits (PRD 3.7) --------------------------------------------
GRACE_MINUTES = 15
LATE_START_THRESHOLD_MINUTES = 7
EVV_VERIFICATION_WINDOW_MINUTES = 60
DEDUCTION_PCT_TIER_LOW = 5
DEDUCTION_PCT_TIER_MID = 10
DEDUCTION_PCT_TIER_HIGH = 15
STRICT_RULESET_SURCHARGE_PCT = 5
TIER_LOW_MAX_GROSS_UNITS = 8
TIER_MID_MAX_GROSS_UNITS = 16

# --- Resource overlap (PRD 3.5) -----------------------------------------
REST_BUFFER_MINUTES = 60
DEFAULT_CONCURRENT_NURSE_LIMIT = 1
MAX_CONCURRENT_NURSE_LIMIT = 3

# --- Supervisory cadence (PRD 3.4) --------------------------------------
CADENCE_DAYS_VENT = 14
CADENCE_DAYS_TRACH = 30
CADENCE_DAYS_BASE = 60

# --- Renewal gate (PRD 3.9) ---------------------------------------------
MIN_RENEWAL_UTILIZATION_RATIO = 0.5

# --- Canonical fixture literals -----------------------------------------
PAYER_NAME = "Sunrise MCO"
PAYER_WEEKLY_HOUR_CAP = 84.0
PAYER_REDUCTION_NOTICE_DAYS = 10
PAYER_APPEAL_WINDOW_DAYS = 30

PATIENT_NAME = "Mia Reyes"
PATIENT_DOB = "2019-04-12"
PATIENT_ADDRESS = "88 Larkspur Lane, Tempe AZ"

POC_REQUESTED_HOURS = 56.0
POC_EFFECTIVE_START = "2026-08-03"
POC_EFFECTIVE_END = "2026-11-01"
POC_PHYSICIAN_NAME = "Dr. Alan Reyes"
POC_PHYSICIAN_NPI = "1234567893"

AUTH_APPROVED_HOURS = 40.0
AUTH_EFFECTIVE_START = "2026-08-03T00:00:00Z"
AUTH_EFFECTIVE_END = "2026-11-01T00:00:00Z"

NURSE_FULL_NAME = "Nora Vance"
NURSE_LICENSE_NUMBER = "RN-100001"
NURSE_LICENSE_EXPIRES_ON = "2027-06-30"
NURSE_MAX_WEEKLY_HOURS = 48.0
NURSE_HOME_ZIP = "85281"

COMPETENCY_VALIDATED_ON = "2026-06-01"
COMPETENCY_EXPIRES_ON = "2027-07-01"

#: A syntactically valid UUID that never identifies a row.
UNKNOWN_UUID = "00000000-0000-4000-8000-000000000000"
