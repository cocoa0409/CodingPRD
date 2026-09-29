"""
Business constants for the Early Intervention Service Coordination API.

Every value here is a literal the PRD states explicitly. Tests must reference
these names rather than repeating magic numbers, so that a single edit tracks a
contract change.
"""

# ─── Statutory timeline ───────────────────────────────────────────────
STATUTORY_TIMELINE_DAYS = 45
MAX_FAMILY_UNAVAILABLE_DAYS_PER_ASSESSMENT = 120

# ─── Sliding scale: federal poverty level ─────────────────────────────
FPL_BASE_CENTS = 1_580_000
FPL_PER_ADDITIONAL_MEMBER_CENTS = 555_000

# Inclusive upper bounds on fpl_percent for each tier.
TIER_0_CEILING_PERCENT = 250.0
TIER_1_CEILING_PERCENT = 400.0
TIER_2_CEILING_PERCENT = 600.0

TIER_RATES = {
    "TIER_0": 0.00,
    "TIER_1": 0.05,
    "TIER_2": 0.10,
    "TIER_3": 0.15,
}

TIER_MONTHLY_CAP_CENTS = {
    "TIER_0": 0,
    "TIER_1": 12_000,
    "TIER_2": 30_000,
    "TIER_3": 60_000,
}

INSURANCE_OFFSET_RATE = 0.60

# Service types whose lines never contribute to the family fee.
FAMILY_FEE_EXEMPT_SERVICE_TYPES = ("SERVICE_COORDINATION", "EVALUATION_ASSESSMENT")

# ─── Weighted caseload standard ───────────────────────────────────────
PRE_PLAN_STAGE_POINTS = 1.50
ACTIVE_STAGE_POINTS = 1.00
INTERPRETER_ADD_POINTS = 0.50
TRANSITION_WINDOW_ADD_POINTS = 0.75
MULTI_SERVICE_ADD_POINTS = 0.50
MULTI_SERVICE_LINE_THRESHOLD = 4
TRANSITION_WINDOW_DAYS = 180
MIN_CASE_WEIGHT_POINTS = 1.00
MAX_CASE_WEIGHT_POINTS = 3.00
NEAR_CAP_RATIO = 0.9000
MIN_MAX_WEIGHTED_CASELOAD_POINTS = 1.00
MAX_MAX_WEIGHTED_CASELOAD_POINTS = 40.00

# ─── Visits, units, makeups ───────────────────────────────────────────
MINUTES_PER_UNIT = 15
MAX_VISIT_MINUTES = 240
CROSS_SETTING_BUFFER_MINUTES = 30
MAKEUP_AT_RISK_THRESHOLD_UNITS = 4
MAKEUP_WINDOW_DAYS = 30

# ─── Transition to preschool ──────────────────────────────────────────
TRANSITION_WINDOW_OPEN_DAYS = 270
MINIMUM_LEAD_DAYS = 90
EARLIEST_LEAD_DAYS = 270

# ─── Monthly family contact ───────────────────────────────────────────
QUALIFYING_CONTACT_METHODS = ("HOME_VISIT", "PHONE", "VIDEO")
GRACE_DAY_OF_MONTH = 20

# ─── Exit child outcomes ──────────────────────────────────────────────
AGE_EXPECTED_RATING = 6
MINIMUM_COMPARABLE_DURATION_DAYS = 180
MIN_OUTCOME_RATING = 1
MAX_OUTCOME_RATING = 7

# ─── Settings ─────────────────────────────────────────────────────────
SETTING_CODES = (
    "HOME",
    "COMMUNITY_CHILDCARE",
    "COMMUNITY_OTHER",
    "CLINIC",
    "PROGRAM_OFFICE",
)
NATURAL_SETTING_CODES = ("HOME", "COMMUNITY_CHILDCARE", "COMMUNITY_OTHER")
NON_NATURAL_SETTING_CODES = ("CLINIC", "PROGRAM_OFFICE")
MIN_JUSTIFICATION_LENGTH = 20

# ─── Developmental domains ────────────────────────────────────────────
ALL_DOMAINS = [
    "PHYSICAL",
    "COGNITIVE",
    "COMMUNICATION",
    "SOCIAL_EMOTIONAL",
    "ADAPTIVE",
]

# ─── Pagination ───────────────────────────────────────────────────────
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_EFFECTIVE_LIMIT = 100
MAX_SYNTACTIC_LIMIT = 200
MIN_OFFSET = 0

# ─── Logical clock ────────────────────────────────────────────────────
# The clock reads exactly this instant until an administrator sets it.
INITIAL_LOGICAL_CLOCK = "2026-08-01T00:00:00Z"

# ─── Rounding precision per field ─────────────────────────────────────
FPL_PERCENT_DECIMALS = 1
CASE_WEIGHT_DECIMALS = 2
UTILIZATION_RATIO_DECIMALS = 4

# ─── Enumerations used by test payloads ───────────────────────────────
REFERRAL_SOURCES = (
    "PHYSICIAN",
    "HOSPITAL",
    "PARENT",
    "CHILD_CARE",
    "SOCIAL_SERVICES",
    "PUBLIC_HEALTH",
    "EARLY_HEAD_START",
    "OTHER",
)

SERVICE_TYPES = (
    "SPEECH_THERAPY",
    "OCCUPATIONAL_THERAPY",
    "PHYSICAL_THERAPY",
    "DEVELOPMENTAL_INSTRUCTION",
    "SOCIAL_WORK",
    "SERVICE_COORDINATION",
    "EVALUATION_ASSESSMENT",
)

ASSESSMENT_TYPES = (
    "INITIAL_EVALUATION",
    "FAMILY_ASSESSMENT",
    "SUPPLEMENTAL_EVALUATION",
)
