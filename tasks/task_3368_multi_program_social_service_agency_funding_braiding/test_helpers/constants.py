"""Domain thresholds and test defaults derived from the PRD's rules.

Every value here is stated in PRD prose (the logical clock start, the burn
posture thresholds, the IRS volunteer hour rate, the minimum denominator and
the duplicate-service allowance).
"""

# PRD §2.5 — the logical clock reads this on startup.
CLOCK_START = "2026-09-01T00:00:00Z"

# PRD §2.12 — inclusive posture thresholds on burn_ratio.
THROTTLE_THRESHOLD = 0.85
FREEZE_THRESHOLD = 1.0
BURN_RATIO_SCALE = 6

# PRD §3.4 — verification expires this many days after screened_at.
VERIFICATION_EXPIRY_DAYS = 180

# PRD §3.7 — only one row per client, per service code, per calendar day.
ALLOWED_ROWS_PER_DAY = 1

# PRD §3.8 — the IRS volunteer hour rate is $33.90.
IRS_VOLUNTEER_HOUR_RATE_CENTS = 3390
INKIND_ROLLING_WINDOW_DAYS = 7
INKIND_MAX_HOURS_PER_WINDOW = 40

# PRD §3.9 — the reporting universe floor.
MIN_DENOMINATOR = 5
RATE_SCALE = 2

# PRD §2.3 — pagination defaults.
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0

# PRD §2.8 — funder types whose programs must carry the attestation.
ATTESTATION_REQUIRED_FUNDER_TYPES = ["FEDERAL", "STATE"]

# PRD §2.7 — the four operations guarded by the confidentiality rule.
CONFIDENTIALITY_GUARDED_OPERATIONS = [
    "open_eligibility_screen",
    "determine_eligibility_screen",
    "create_enrollment",
    "read_client",
]

# PRD §2.9 — the two endpoints that accept a version field.
OCC_GUARDED_OPERATIONS = {
    "POST /api/service-authorizations": "expected_enrollment_version",
    "POST /api/service-deliveries": "expected_service_authorization_version",
}

TEST_DEFAULTS = {
    "CLOCK": CLOCK_START,
    "TOTAL_AWARD_CENTS": 200_000,
    "ADMIN_RATE_PCT": 0.10,
    "MAX_ADMIN_RATE_PCT": 0.25,
    "MAX_IN_KIND_RATE_CENTS": 3000,
    "MATCHING_REQUIREMENT_PCT": 0.25,
    "UNIT_RATE_CENTS": 5000,
    "AUTHORIZED_UNITS": 20,
    "VERIFIED_INCOME_CENTS": 120_000,
    "HOUSEHOLD_SIZE": 2,
    "CAPACITY_SLOTS": 3,
}
