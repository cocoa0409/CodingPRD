"""Domain thresholds and canonical test literals taken from the PRD."""

# The logical clock's value at startup.
CLOCK_STARTUP_UTC = "2026-08-01T00:00:00.000Z"

# Instant every fixture pins the clock to before building its scenario.
BASE_CLOCK_UTC = "2026-09-01T00:00:00.000Z"

SECONDS_PER_DAY = 86_400
SECONDS_PER_HOUR = 3_600

# Program policy defaults (PRD §3.1).
PROGRAM_POLICY_DEFAULTS = {
    "mastery_threshold_pct": 80.00,
    "units_per_credit_hour": 3.0,
    "sap_min_units_per_term": 12,
    "required_unit_total": 120,
    "irr_tolerance_pct": 5.00,
    "irr_min_paired_reviews": 3,
    "irr_suspend_rate_pct": 70.00,
    "attempt_cooloff_hours": 48,
    "attempts_before_endorsement": 3,
    "critical_dimension_min_ratio": 0.70,
    "cadence_gate_overdue_days": 7,
    "blueprint_notice_days": 14,
    "aid_earned_pct_full_threshold": 0.6000,
    "aid_min_credit_equivalency": 1,
}

# Pagination contract (PRD §2.3).
PAGINATION = {"default_limit": 10, "min_limit": 1, "max_limit": 100, "default_offset": 0}

# Decimal scales pinned per field (PRD §2.7).
DECIMAL_SCALES = {
    "mastery_threshold_pct": 2,
    "earned_pct": 4,
    "units_per_credit_hour": 1,
    "unit_value": 2,
    "critical_dimension_min_ratio": 2,
    "weight": 4,
    "score": 2,
    "weighted_score_pct": 2,
    "translated_credit_hours": 1,
    "cumulative_credit_equivalency": 1,
    "credit_equivalency_variance": 1,
    "line_credit_hours": 2,
    "line_credit_hour_sum": 2,
    "rounding_residual_credit_hours": 2,
}

# Canonical scenario literals reused by the composite fixtures.
TEST_DEFAULTS = {
    "PROGRAM_CODE": "CBE-BSIT",
    "PROGRAM_TITLE": "BS Information Technology",
    "COMPETENCY_CODE": "IT-101",
    "COMPETENCY_TITLE": "Relational Data Modeling",
    "COMPETENCY_UNIT_VALUE": 4,
    "COMPETENCY_LEVEL": "FOUNDATION",
    "STUDENT_NAME": "Ada Learner",
    "STUDENT_EMAIL": "ada@example.edu",
    "TERM_START_UTC": "2026-09-01T00:00:00.000Z",
    "TERM_END_UTC": "2026-12-01T00:00:00.000Z",
    "TUITION_CENTS": 375_000,
    "MENTOR_NAME": "Mentor Meg",
    "MENTOR_EMAIL": "meg@example.edu",
    "MENTOR_MAX_CASELOAD": 5,
    "MENTOR_CADENCE_DAYS": 14,
    "EVALUATOR_NAME": "Eve Reader",
    "EVALUATOR_EMAIL": "eve@example.edu",
    "EVALUATOR_CERTIFICATION_LEVEL": "SENIOR",
    "ARTIFACT_HASH": "sha256:aaaa",
    "CLIENT_FINGERPRINT": "fp-ada-1",
    "AID_SCHEDULED_CENTS": 200_000,
}

# A syntactically valid identifier that no row will ever carry.
PHANTOM_UUID = "00000000-0000-4000-8000-000000000000"

# The single-dimension rubric every simple scenario publishes.
SINGLE_DIMENSION_RUBRIC = [
    {"code": "D1", "weight": 1.0000, "max_score": 100, "critical": False}
]
