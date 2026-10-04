"""Domain thresholds and fixture defaults drawn from the PRD's stated rules."""

# ------------------------------------------------------------------ ASAM scale
# Weighted total bounds (PRD §3.1).
WEIGHT_WITHDRAWAL_RISK = 3
WEIGHT_BIOMEDICAL_CONDITIONS = 2
WEIGHT_EMOTIONAL_BEHAVIORAL = 2
WEIGHT_READINESS_TO_CHANGE = 1
WEIGHT_RELAPSE_POTENTIAL = 3
WEIGHT_RECOVERY_ENVIRONMENT = 1

MAX_DIMENSION_SCORE = 4
MAX_TOTAL_SCORE = 48

# Dimension-sum placement bands, descending (PRD §3.1).
THRESHOLD_3_7 = 44
THRESHOLD_3_5 = 36
THRESHOLD_3_1 = 28
THRESHOLD_2_1 = 18

# ------------------------------------------------------- compliance risk ledger
# Raw accumulation units (PRD §2.6).
EXPIRED_UNIT = 12
MISSING_UNIT = 5
AGED_CAP = 6
AGED_UNIT = 2
DAYS_PER_AGED_UNIT = 30

# Strictly-greater-than tier boundaries (PRD §2.6).
MODERATE_MIN = 10
HI_MIN = 30
PREMIUM_MIN = 60
TIER_MULTIPLIER_BASE = 1.0
TIER_MULTIPLIER_MODERATE = 1.0
TIER_MULTIPLIER_HI = 1.25
TIER_MULTIPLIER_PREMIUM = 1.5

# Facility posture bands, inclusive at both cut points (PRD §2.6).
POSTURE_RESTRICTED_MIN = 45
POSTURE_FROZEN_MIN = 60

# ---------------------------------------------------------- step-down pressure
TIME_WEIGHT = 60
COST_UNIT = 8
TARGET_LEVEL_RANK = 1
CLINICAL_STABLE_BONUS = 15
CLINICAL_ACTIVE_BONUS = 5
CLINICAL_COMPLICATED_PENALTY = 20

# ------------------------------------------------------------- clearance window
CLEARANCE_VALIDITY_DAYS = 7
HOURS_PER_DAY = 24

# ------------------------------------------------------------ seating / billing
BASE_DAILY_CENTS = {
    "ASAM_3_7": 4200,
    "ASAM_3_5": 3600,
    "ASAM_3_1": 2800,
    "ASAM_2_1": 1400,
    "ASAM_1_0": 600,
}
SERVICE_BASE_CENTS = {
    "ASAM_3_7": 210,
    "ASAM_3_5": 180,
    "ASAM_3_1": 150,
    "ASAM_2_1": 110,
    "ASAM_1_0": 80,
}
MIN_BILLABLE_MINUTES = 60
MAX_SESSION_CENTS = 900

# --------------------------------------------------------------- curriculum cap
REQUIRED_SESSIONS_PER_WEEK = {
    "ASAM_1_0": 5,
    "ASAM_2_1": 5,
    "ASAM_3_1": 10,
    "ASAM_3_5": 14,
    "ASAM_3_7": 14,
}
TREATMENT_WEEK_DAYS = 7

# ------------------------------------------------------------ housing selection
AFFORDABILITY_TARGET_CENTS = 1000
AFFORDABILITY_CEILING_CENTS = 2000

# ------------------------------------------------------------------ alumni gate
MIN_ALUMNI_INTERVAL_DAYS = 1
MAX_ALUMNI_INTERVAL_DAYS = 90
MAX_ALUMNI_CONTACTS = 24

# ---------------------------------------------------------------------- ceilings
MAX_STEP_DOWNS_PER_EPISODE = 2
MAX_CHANGES_PER_PAYER = 5
MIN_CREDENTIAL_TIER_FOR_DISCHARGE = "TIER_3_LICENSED"

# ------------------------------------------------------------------- pagination
DEFAULT_PAGE_LIMIT = 10
MAX_PAGE_LIMIT = 100

# ---------------------------------------------------------------------- fixtures
# The logical clock never falls back to wall time and its startup default sits
# before every fixture date (PRD §2.11).
CLOCK_DEFAULT = "2026-09-01T00:00:00Z"

# A calendar of instants the fixtures and boundary tests move between.
CLOCK_2026_09_01 = "2026-09-01T00:00:00Z"
CLOCK_2026_09_02 = "2026-09-02T00:00:00Z"
CLOCK_2026_09_05 = "2026-09-05T00:00:00Z"
CLOCK_2026_09_07 = "2026-09-07T00:00:00Z"
CLOCK_2026_09_08 = "2026-09-08T00:00:00Z"
CLOCK_2026_09_09 = "2026-09-09T00:00:00Z"
CLOCK_2026_09_10 = "2026-09-10T00:00:00Z"
CLOCK_2026_09_14 = "2026-09-14T00:00:00Z"
CLOCK_2026_09_15 = "2026-09-15T00:00:00Z"
CLOCK_2026_09_20 = "2026-09-20T00:00:00Z"

CREDENTIAL_EFFECTIVE_AT = "2026-01-01T00:00:00Z"
CREDENTIAL_EXPIRES_AT = "2027-01-01T00:00:00Z"

# The same instants rendered as the server must stamp them. PRD §2.11: "Timestamps
# are ISO 8601 UTC with three fractional digits throughout", so a stored or returned
# instant always carries the `.000` before the `Z` while a request-body literal need
# not. Assertions on a response field use the *_ISO form.
CLOCK_DEFAULT_ISO = "2026-09-01T00:00:00.000Z"
CLOCK_2026_09_01_ISO = "2026-09-01T00:00:00.000Z"
CLOCK_2026_09_02_ISO = "2026-09-02T00:00:00.000Z"
CLOCK_2026_09_05_ISO = "2026-09-05T00:00:00.000Z"
CLOCK_2026_09_07_ISO = "2026-09-07T00:00:00.000Z"
CLOCK_2026_09_08_ISO = "2026-09-08T00:00:00.000Z"
CLOCK_2026_09_09_ISO = "2026-09-09T00:00:00.000Z"
CLOCK_2026_09_10_ISO = "2026-09-10T00:00:00.000Z"
CLOCK_2026_09_15_ISO = "2026-09-15T00:00:00.000Z"

# Fixture defaults for the standard Minnesota site.
FACILITY_NAME = "Cascade Ridge Recovery Center"
FACILITY_STATE = "MN"
BED_LABEL_35 = "MN-B-01"
BED_LABEL_31 = "MN-B-02"
BED_LABEL_21 = "MN-B-03"
CLEANING_HOURS_35 = 24
CLEANING_HOURS_31 = 48
CLEANING_HOURS_21 = 48
SERVICE_CODE_RES = "RES_GROUP"
SERVICE_CODE_IOP = "IOP_GROUP"
PAYER_NAME = "Northlight Health Plan"

# The payer's grant table, coverage map, review cadence and credential floors.
PAYER_INITIAL_DAYS = {"ASAM_3_5": 14, "ASAM_3_1": 10, "ASAM_2_1": 8}
PAYER_STEP_DOWN_COVERAGE = {
    "ASAM_3_5": ["ASAM_3_1", "ASAM_2_1", "ASAM_1_0"],
    "ASAM_3_1": ["ASAM_2_1", "ASAM_1_0"],
    "ASAM_2_1": ["ASAM_1_0"],
    "ASAM_1_0": [],
}
PAYER_REVIEW_INTERVAL_DAYS = 7
PAYER_CREDENTIAL_FLOORS = {
    "ASAM_3_5": "TIER_3_LICENSED",
    "ASAM_3_1": "TIER_3_LICENSED",
    "ASAM_2_1": "TIER_2_COUNSELOR",
    "ASAM_1_0": "TIER_1_SUPPORT",
}

# A dimension scorecard whose weighted total is 40, placing at ASAM_3_5.
# 4*3 + 2*2 + 2*2 + 4*1 + 4*3 + 4*1 = 12 + 4 + 4 + 4 + 12 + 4 = 40.
SCORES_ASAM_3_5 = {
    "withdrawal_risk": 4,
    "biomedical_conditions": 2,
    "emotional_behavioral": 2,
    "readiness_to_change": 4,
    "relapse_potential": 4,
    "recovery_environment": 4,
}

PATIENT_REF = "PT-8001"
