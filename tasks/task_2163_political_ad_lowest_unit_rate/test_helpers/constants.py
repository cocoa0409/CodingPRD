"""Numeric constants the PRD pins for this domain."""

# Before the clock is ever set it reads exactly this instant.
CLOCK_EPOCH = "2026-08-01T00:00:00Z"

# The unit of political airtime is the thirty-second unit.
UNIT_SECONDS = 30

DAYPART_MULTIPLIER = {
    "MORNING": 0.60,
    "DAYTIME": 0.45,
    "EARLY_NEWS": 1.00,
    "PRIME": 2.25,
    "LATE_NIGHT": 0.35,
}

# spot_count band -> discount fraction
VOLUME_DISCOUNT_TIERS = [
    (1, 4, 0.00),
    (5, 9, 0.05),
    (10, 19, 0.125),
    (20, None, 0.20),
]

# gross_charge_cents band -> agency commission fraction
AGENCY_COMMISSION_TIERS = [
    (0, 49999, 0.00),
    (50000, 249999, 0.02),
    (250000, None, 0.035),
]

THRESHOLDS = {
    "MAX_REVIEW_ROUNDS": 3,
    "DISCLOSURE_MIN_SECONDS": 4,
    "CANDIDATE_SEPARATION_BUFFER_SECONDS": 900,
    "POSTURE_RESTRICTED_THRESHOLD": 1,
    "POSTURE_FROZEN_THRESHOLD": 2,
    "EO_REQUEST_WINDOW_DAYS": 7,
    "EO_RESPONSE_DEADLINE_HOURS": 24,
    "COMPLAINT_RESPONSE_DEADLINE_HOURS": 240,
    "CURE_PERIOD_HOURS": 720,
    "NET_TERM_DAYS": 30,
    "LUC_WINDOW_DAYS_GENERAL": 60,
    "LUC_WINDOW_DAYS_OTHER": 45,
}

TEST_DEFAULTS = {
    "CLOCK": "2026-08-05T09:00:00Z",
    "STATION_DEADLINE_HOURS": 24,
    "STATION_DAILY_CAP_SECONDS": 300,
    "POSTED_RATE_EARLY_NEWS": 100000,
    "POSTED_RATE_MORNING": 12345,
    "ELECTION_DATE": "2026-09-15",
    "AIR_DATE": "2026-08-20",
    "DISCLOSURE_DURATION_SECONDS": 5,
    "ISSUE_LEGAL_NAME": "Empire Growth Fund",
    "CANDIDATE_LEGAL_NAME": "Rivera For Senate",
}

# A syntactically valid UUID that never names a persisted row.
UNKNOWN_UUID = "00000000-0000-0000-0000-000000000000"
