"""Domain thresholds and pinned numeric constants taken from the PRD narrative."""

# Screening bands (PRD 3.1) — both bounds inclusive.
SCREENING = {
    "URGENT_MAX_DAYS": 30,
    "PRIORITY_MAX_DAYS": 180,
}

# Risk tiering from the composite need index (PRD 3.2) — inclusive lower bounds.
RISK = {
    "HIGH_MIN": 70.00,
    "MODERATE_MIN": 40.00,
    "SUICIDALITY_FLOOR": 85.00,
}

# Composite need index weights (PRD 3.2).
NEED_WEIGHTS = {
    "GRIEF_SEVERITY": 0.5,
    "GRIEF_SEVERITY_MAX": 40,
    "FUNCTIONAL_IMPAIRMENT": 0.3,
    "FUNCTIONAL_IMPAIRMENT_MAX": 20,
    "ISOLATION_INDEX": 0.2,
    "ISOLATION_INDEX_MAX": 20,
}

# Assessment sub-score ranges (PRD 3.2).
ASSESSMENT_RANGES = {
    "GRIEF_SEVERITY_MAX": 40,
    "ISOLATION_INDEX_MAX": 20,
    "FUNCTIONAL_IMPAIRMENT_MAX": 20,
    "NORMALIZED_DENOMINATOR": 80,
}

# Outreach cadence in days by tier (PRD 3.2).
CADENCE_DAYS = {"LOW": 90, "MODERATE": 60, "HIGH": 30}

# Anniversary cadence plan offsets in days from date_of_death (PRD 3.8).
OUTREACH_OFFSET_DAYS = {
    "ONE_MONTH": 30,
    "THREE_MONTH": 90,
    "SIX_MONTH": 180,
    "FIRST_ANNIVERSARY": 365,
}

# Outcome measurement constants (PRD 3.2).
OUTCOME = {
    "PROGRAM_MEAN": 50.0,
    "RTM_FACTOR": 0.15,
    "FULL_COURSE_SESSIONS": 8,
    "ATTENDANCE_BASE_WEIGHT": 0.6,
    "ATTENDANCE_SCALE_WEIGHT": 0.4,
}

# Indirect-fee tier table on direct cost alone (PRD 3.3).
INDIRECT_TIERS = {
    "LOW_BAND_MAX_EXCLUSIVE": 250_000,
    "MID_BAND_MAX_EXCLUSIVE": 750_000,
    "LOW_BAND_BPS": 1200,
    "MID_BAND_BPS": 1000,
    "HIGH_BAND_BPS": 800,
    "BPS_DIVISOR": 10_000,
}

# Enrollment hold window and viability (PRD 3.4).
ENROLLMENT = {
    "HOLD_HOURS": 72,
    "ATTENDANCE_RATIO_DECIMALS": 4,
}

# Counselling queue priority weights (PRD 3.5).
QUEUE_PRIORITY = {
    "URGENCY_ROUTINE": 10,
    "URGENCY_PRIORITY": 25,
    "URGENCY_URGENT": 45,
    "NEED_FACTOR": 0.35,
    "NEED_CAP": 35,
    "WAIT_PER_DAY": 0.5,
    "WAIT_CAP": 20,
    "REENTRY_PER_EVENT": 5,
    "REENTRY_CAP": 10,
    "REENTRY_ESCALATION_THRESHOLD": 2,
}

# Volunteer training and certification (PRD 3.6).
VOLUNTEER = {
    "CERT_HOURS": 16,
    "CERT_VALID_DAYS": 365,
    "HIGH_RISK_MIN_HOURS": 24,
    "CORE_MODULES": ["CORE_LISTENING", "CORE_SAFETY"],
    "DEFAULT_MAX_CONCURRENT_MATCHES": 3,
}

# Companion match score components (PRD 3.6).
MATCH_SCORE = {
    "ENDORSEMENT_POINTS": 40,
    "TRAINING_POINTS": 30,
    "HEADROOM_POINTS": 30,
}

# RSVP window (PRD 3.7).
INVITATION = {"RSVP_LEAD_DAYS": 3}

# Anniversary outreach silence deadline (PRD 3.8).
OUTREACH = {"NO_RESPONSE_DAYS": 21}

# Grant defaults (PRD 3.9).
GRANT = {"DEFAULT_INDIRECT_RATE_BPS": 1200}

# Meeting spaces (PRD 3.3).
MEETING_SPACE = {"DEFAULT_TURNOVER_BUFFER_MINUTES": 30}

# Pagination (PRD 2.3).
PAGINATION = {"DEFAULT_LIMIT": 10, "MIN_LIMIT": 1, "MAX_LIMIT": 100, "DEFAULT_OFFSET": 0}

# The logical clock reads this instant before any operator repositions it (PRD 2.4).
DEFAULT_LOGICAL_CLOCK = "2026-08-01T00:00:00Z"

# The instant most scenarios pin the logical clock to.
BASE_CLOCK = "2026-09-01T00:00:00Z"
BASE_CLOCK_DATE = "2026-09-01"

# Well-formed UUIDs that are never minted by the server.
UNUSED_UUIDS = {
    "referral": "11111111-1111-4111-8111-111111111111",
    "cohort": "22222222-2222-4222-8222-222222222222",
    "enrollment": "33333333-3333-4333-8333-333333333333",
    "space": "44444444-4444-4444-8444-444444444444",
    "counseling_referral": "55555555-5555-4555-8555-555555555555",
    "companion": "66666666-6666-4666-8666-666666666666",
    "match": "77777777-7777-4777-8777-777777777777",
    "event": "88888888-8888-4888-8888-888888888888",
    "invitation": "99999999-9999-4999-8999-999999999999",
    "grant": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    "allocation": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
    "report": "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
    "outreach": "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
    "counselor": "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee",
    "participant": "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2",
}
