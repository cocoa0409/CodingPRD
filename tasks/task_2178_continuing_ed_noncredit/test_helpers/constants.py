"""Domain thresholds and reusable test data drawn from the PRD's stated numbers."""

# Pricing resolution (PRD section 3.5)
LOYALTY_DISCOUNT_PCT = {"NEW": 0.00, "RETURNING": 0.05, "LOYAL": 0.10, "CHAMPION": 0.15}
FEE_TIER_BREAKPOINTS_CENTS = [0, 25000, 75000]
FEE_TIER_PCT = [0.06, 0.04, 0.025]
FEE_MIN_CENTS = 500
FEE_MAX_CENTS = 4000

# Program revenue (PRD section 3.6)
INSTITUTIONAL_OVERHEAD_RATE = 0.185
PLATFORM_FEE_PER_REG_CENTS = 250

# Refunds and transfers (PRD section 3.9)
POLICY_TIER_DAYS = [14, 7, 1]
POLICY_TIER_PCT = [1.00, 0.75, 0.50, 0.00]
PRO_RATA_MAX_REFUND_PCT = 0.90
TRANSFER_FEE_CENTS = 2500

# Instructor pay (PRD section 3.8)
CREDENTIAL_MULTIPLIER = {"ADJUNCT": 1.00, "SENIOR": 1.15, "MASTER": 1.30}
KILL_FEE_PCT = 0.25

# Completion (PRD section 3.7)
MIN_ATTENDANCE_RATIO = 0.80
LOYALTY_THRESHOLDS = {"RETURNING": 1, "LOYAL": 4, "CHAMPION": 8}

# Credit for prior learning (PRD section 3.10)
CEU_TO_CREDIT_DIVISOR = 3.0
CPL_MAX_PCT_OF_COURSE = 0.75
CPL_ROUND_STEP = 0.5
RECENCY_DECAY_YEARS = 5
RECENCY_DECAY_FACTOR = 0.5
MAX_CPL_REVISION_ROUNDS = 2

# Seats and load (PRD sections 3.5)
WAITLIST_CAP = 5
MAX_CONCURRENT_CEU = 4.0

# Logical clock (PRD section 2.5)
CLOCK_EPOCH = "2026-08-01T00:00:00Z"

# Pagination (PRD section 2.3)
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100

# ---- Catalog fixtures used across the suite -----------------------------

COURSE_EXT_101 = {
    "course_code": "EXT-101",
    "title": "Foundations of Project Delivery",
    "ceu_units": 1.2,
    "contact_hours": 12,
    "list_price_cents": 60000,
    "delivery_mode": "ONLINE_SYNC",
    "cpl_credit_units": 3.0,
}

COURSE_EXT_050 = {
    "course_code": "EXT-050",
    "title": "Micro Credential Primer",
    "ceu_units": 0.5,
    "contact_hours": 5,
    "list_price_cents": 25000,
    "delivery_mode": "ONLINE_ASYNC",
    "cpl_credit_units": 1.0,
}

COURSE_EXT_150 = {
    "course_code": "EXT-150",
    "title": "Applied Delivery Lab",
    "ceu_units": 1.5,
    "contact_hours": 15,
    "list_price_cents": 45000,
    "delivery_mode": "IN_PERSON",
    "cpl_credit_units": 2.0,
}

COURSE_EXT_201 = {
    "course_code": "EXT-201",
    "title": "Advanced Delivery Practice",
    "ceu_units": 1.5,
    "contact_hours": 15,
    "list_price_cents": 90000,
    "delivery_mode": "ONLINE_SYNC",
    "cpl_credit_units": 3.0,
}

COURSE_EXT_300 = {
    "course_code": "EXT-300",
    "title": "Capstone Practicum",
    "ceu_units": 3.0,
    "contact_hours": 30,
    "list_price_cents": 120000,
    "delivery_mode": "ONLINE_SYNC",
    "cpl_credit_units": 6.0,
}

# Standard fall term window used by most scenarios.
FALL_START = "2026-09-15T00:00:00Z"
FALL_END = "2026-11-15T00:00:00Z"
FALL_CENSUS = "2026-09-01T00:00:00Z"
FALL_TERM = "2026FA"

SPRING_START = "2027-01-15T00:00:00Z"
SPRING_END = "2027-03-15T00:00:00Z"
SPRING_CENSUS = "2027-01-05T00:00:00Z"
SPRING_TERM = "2027SP"

DEFAULT_VOUCHER_EXPIRY = "2027-06-30T00:00:00Z"

# Standard contract commercial terms.
BASE_STIPEND_CENTS = 250000
PER_ENROLLMENT_CENTS = 12345
ENROLLMENT_CAP_FOR_PAY = 8

# Total due for a NEW-tier learner on a 60000-cent section:
# subtotal 60000 -> 4% band -> fee 2400 -> total 62400.
STANDARD_TOTAL_DUE_CENTS = 62400
STANDARD_PROCESSING_FEE_CENTS = 2400
