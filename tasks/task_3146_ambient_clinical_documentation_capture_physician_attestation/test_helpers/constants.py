"""Domain constants: paths, thresholds, calculation constants, logical clock base."""

API_PREFIX = "/ambient-clinical-documentation"
CLOCK_PATH = API_PREFIX + "/_clock/set_current_utc"
TRANSCRIPTION_PATH = API_PREFIX + "/_audio/simulate-transcription"
RETENTION_SWEEP_PATH = API_PREFIX + "/_maintenance/run-retention-sweep"

# Logical clock startup default (PRD section 2.5).
CLOCK_START = "2026-09-01T00:00:00Z"

# Completeness scoring penalties per missing required field (PRD section 3.4).
PENALTY_CRITICAL = 25
PENALTY_MAJOR = 10
PENALTY_MINOR = 5
CRITICAL_CAP = 49
ATTEST_MINIMUM = 80

# Billing (PRD section 3.6).
BILLING_CAP_CENTS = 10000000
MAX_ACTIVE_SUGGESTIONS = 8

# QA composite weights (PRD section 3.7).
W_BASE_ACC = 0.5
W_BASE_COMP = 0.3
W_BASE_TIME = 0.2
W_APPEAL_ACC = 0.7
W_APPEAL_COMP = 0.2
W_APPEAL_TIME = 0.1
MAX_APPEALS = 2

# Speaker confidence decay (PRD section 3.3).
REASSIGNMENT_DECAY = 0.9

# Retention (PRD sections 3.3 and 3.8).
REVOKED_RETENTION_CAP_DAYS = 30

# Temporal buffers (PRD section 3.3).
CAPTURE_GAP_SECONDS = 60

# After-hours charting windows (PRD section 3.8).
AFTER_HOURS_START = "18:00:00Z"
AFTER_HOURS_END = "07:00:00Z"

TEST_DEFAULTS = {
    "SPECIALTY": "CARD",
    "PLANNED_RETENTION_DAYS": 30,
    "CAPTURED_VIA": "ROOM_SIGNAGE",
}
