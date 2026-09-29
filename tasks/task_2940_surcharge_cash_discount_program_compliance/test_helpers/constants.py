"""Domain thresholds and numeric constants named by the PRD."""

CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"

# §2.5 — day arithmetic is exact multiples of 24 hours.
SECONDS_PER_DAY = 86_400

# §3.2 — fallback average ticket when the merchant has captured no transactions.
DEFAULT_AVERAGE_TICKET_CENTS = 5000

# §3.3 — the three inputs to the effective cap.
CASH_DISCOUNT_MAX_PCT = 10.0
NETWORK_MAX_SURCHARGE_PCT = 3.0

# §3.4 / §3.5 — separation and notice windows, in days.
RATE_CHANGE_BUFFER_DAYS = 30
NOTICE_PERIOD_DAYS = 30

# §3.10 — exposure scoring.
SUBSTANTIATED_BASE_POINTS = 20
OPEN_CASE_POINTS = 8
SCORE_CEILING = 100
REMEDIATION_EXPOSURE_THRESHOLD = 30
SOURCE_MULTIPLIER = {
    "NETWORK": 1.5,
    "ATTORNEY_GENERAL": 2.0,
    "CARDHOLDER": 1.0,
}
POSTURE_MULTIPLIER = {
    "PERMISSIVE": 0.5,
    "MONITORED": 1.0,
    "RESTRICTIVE": 2.0,
}
RESPONSE_WINDOW_DAYS = {
    "NETWORK": 10,
    "ATTORNEY_GENERAL": 20,
    "CARDHOLDER": 30,
}

# §2.3 — pagination bounds.
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# A well-formed UUID that this service never mints, used to probe the 404 family.
UNMINTED_UUID = "00000000-0000-4000-8000-000000000000"

# Operator identities used across the suite. The four opaque roles carry
# free-form identifiers; two distinct officers are needed for the
# segregation-of-duties rules.
ADMIN_USER_ID = "admin-1"
OFFICER_ONE_USER_ID = "officer-1"
OFFICER_TWO_USER_ID = "officer-2"
AUDITOR_USER_ID = "auditor-1"
REGULATOR_USER_ID = "regulator-1"

# Content hashes are exactly 64 lowercase hexadecimal characters.
CONTENT_HASH_A = "a" * 64
CONTENT_HASH_B = "b" * 64
CONTENT_HASH_C = "c" * 64
CONTENT_HASH_D = "d" * 64
CONTENT_HASH_E = "e" * 64
CONTENT_HASH_F = "f" * 64

# Frequently used instants on the logical clock.
CLOCK_AUG_01 = "2026-08-01T00:00:00Z"
CLOCK_AUG_30_LAST_SECOND = "2026-08-30T23:59:59Z"
CLOCK_AUG_31 = "2026-08-31T00:00:00Z"
CLOCK_SEP_01 = "2026-09-01T00:00:00Z"
CLOCK_SEP_15 = "2026-09-15T00:00:00Z"
CLOCK_OCT_01 = "2026-10-01T00:00:00Z"
CLOCK_DEC_31 = "2026-12-31T00:00:00Z"

# Rendered forms of those instants as the API returns them.
TS_AUG_01 = "2026-08-01T00:00:00.000Z"
TS_AUG_31 = "2026-08-31T00:00:00.000Z"
TS_SEP_01 = "2026-09-01T00:00:00.000Z"
TS_OCT_01 = "2026-10-01T00:00:00.000Z"
TS_DEC_31 = "2026-12-31T00:00:00.000Z"
