"""Domain thresholds and canonical fixture literals from the PRD.

Every numeric literal here is quoted directly from PRD §2 / §3 prose.
"""

# ---------------------------------------------------------------------------
# Global constants (PRD §2.4, §2.12, §3.x)
# ---------------------------------------------------------------------------

DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

THRESHOLDS = {
    "MIN_HEARING_NOTICE_DAYS": 10,
    "APPEAL_WINDOW_DAYS": 10,
    "APPEAL_MAX_PER_CASE": 2,
    "ADVISOR_LIMIT_PER_CASE": 2,
    "ATTORNEY_ADVISOR_MIN_RANK": 6,
    "TRAINING_VALID_DAYS": 730,
    "NOTATION_MIN_RANK": 4,
    "INFORMAL_MAX_RANK": 3,
    "REMAND_MAX_HEARING_ROUND": 1,
    "MEETING_MIN_MINUTES": 15,
    "MEETING_MAX_MINUTES": 240,
    "RESPONSE_WINDOW_MIN_DAYS": 5,
    "RESPONSE_WINDOW_MAX_DAYS": 30,
    "RESPONSE_WINDOW_DEFAULT_DAYS": 7,
    "PATTERN_WINDOW_DAYS": 730,
    "REPORTING_WINDOW_DAYS": 365,
    "TRIAGE_ACCEPT_MIN_EVIDENCE_SCORE": 20.00,
    "DEFAULT_ROOM_BUFFER_MINUTES": 30,
    "DEFAULT_SESSIONS_PER_DAY_CAP": 2,
    "PAGINATION_DEFAULT_LIMIT": 10,
    "PAGINATION_MIN_LIMIT": 1,
    "PAGINATION_MAX_LIMIT": 100,
}

# ---------------------------------------------------------------------------
# The sanction ladder (PRD §2.12) — rank -> kind
# ---------------------------------------------------------------------------

LADDER_KIND = {
    1: "WARNING",
    2: "GRADE_PENALTY_ASSIGNMENT",
    3: "GRADE_PENALTY_COURSE",
    4: "TRANSCRIPT_NOTATION_ONLY",
    5: "DISCIPLINARY_PROBATION",
    6: "SUSPENSION_ONE_TERM",
    7: "SUSPENSION_ONE_YEAR",
    8: "EXPULSION_RECOMMENDATION",
}

# rank -> waiting period in days (PRD §3.10 "Eligibility")
LADDER_ELIGIBILITY_DAYS = {4: 365, 5: 365, 6: 730, 7: 1095}

# ---------------------------------------------------------------------------
# Severity arithmetic constants (PRD §3.3, §3.4)
# ---------------------------------------------------------------------------

BASE_POINTS = {
    "PLAGIARISM": 20,
    "UNAUTHORIZED_COLLABORATION": 18,
    "EXAM_CHEATING": 28,
    "FABRICATION_OF_DATA": 32,
    "CONTRACT_CHEATING": 40,
    "FACILITATION": 24,
}

EVIDENCE_KIND_WEIGHT = {
    "SIMILARITY_REPORT": 1.00,
    "PROCTOR_LOG": 0.60,
    "WITNESS_STATEMENT": 0.40,
    "DOCUMENT": 0.20,
}

EVIDENCE_SCORE_CONSTANTS = {
    "EXCLUDED_QUOTE_ALLOWANCE": 5.00,
    "BAND_HIGH_MIN": 40.00,
    "BAND_HIGH_MULTIPLIER": 1.20,
    "BAND_MID_MIN": 20.00,
    "BAND_MID_MULTIPLIER": 1.00,
    "BAND_LOW_MULTIPLIER": 0.70,
    "PAGE_CAP": 20,
    "PAGE_POINT_PER_PAGE": 0.50,
    "DIVERSITY_MULTIPLIER": 10,
    "CORROBORATION_BONUS": 15.00,
    "SCORE_CAP": 100.00,
}

# Severity tier table (PRD §3.4 "Ladder placement, formal variant")
SEVERITY_TIERS = [
    (25.00, 1),
    (40.00, 2),
    (55.00, 3),
    (70.00, 5),
    (85.00, 6),
    (100.00, 7),
]
SEVERITY_TIER_TOP_RANK = 8
SEVERITY_INDEX_CAP = 120.00
EVIDENCE_CONTRIBUTION_WEIGHT = 0.40
ESCALATION_PIVOT_INDEX = 50.00
CROSS_COURSE_POINTS = {0: 0, 1: 4, 2: 10}

# ---------------------------------------------------------------------------
# Canonical fixture literals.
#
# Every numeric expectation in the test suite derives from this seed, so the
# literals below are exactly the ones the PRD's own worked examples use.
# ---------------------------------------------------------------------------

# ENGL-201 / 2026FA gradebook: four weighted components summing to 100.
CANONICAL_GRADE_COMPONENTS = [
    {"code": "ESSAY", "max_points": 200, "weight_pct": 40},
    {"code": "MIDTERM", "max_points": 70, "weight_pct": 30},
    {"code": "PROJECT", "max_points": 90, "weight_pct": 20},
    {"code": "FINAL", "max_points": 180, "weight_pct": 10},
]

# earned points -> baseline_course_grade_pct 79.06 (PRD §3.8 worked example)
CANONICAL_COMPONENT_SCORES = [
    {"code": "ESSAY", "earned_points": 156},
    {"code": "MIDTERM", "earned_points": 68},
    {"code": "PROJECT", "earned_points": 56},
    {"code": "FINAL", "earned_points": 113},
]

CANONICAL_BASELINE_COURSE_GRADE_PCT = 79.06
# Zeroing ESSAY -> 47.86 (delta 31.20); zeroing MIDTERM -> 49.92 (delta 29.14)
CANONICAL_ADJUSTED_ZERO_ESSAY_PCT = 47.86
CANONICAL_DELTA_ZERO_ESSAY_PCT = 31.20
CANONICAL_ADJUSTED_ZERO_MIDTERM_PCT = 49.92
CANONICAL_DELTA_ZERO_MIDTERM_PCT = 29.14

# SEED-A: one SIMILARITY_REPORT, similarity_pct 45.00, page_count 4 -> 60.00
SEED_A_EVIDENCE_SCORE = 60.00
# SEED-B: SEED-A plus one PROCTOR_LOG page_count 1 -> 81.50
SEED_B_EVIDENCE_SCORE = 81.50

TEST_DEFAULTS = {
    "DEPT_ENGL": {
        "code": "ENGL",
        "name": "English",
        "enrolled_student_count": 2000,
        "faculty_headcount": 5,
    },
    "DEPT_HIST": {
        "code": "HIST",
        "name": "History",
        "enrolled_student_count": 1000,
        "faculty_headcount": 4,
    },
    "DEPT_PHIL": {
        "code": "PHIL",
        "name": "Philosophy",
        "enrolled_student_count": 500,
        "faculty_headcount": 3,
    },
    "ROOM_A": {
        "code": "ROOM-A",
        "seat_capacity": 12,
        "buffer_minutes": 30,
        "sessions_per_day_cap": 2,
    },
    "ROOM_B": {
        "code": "ROOM-B",
        "seat_capacity": 20,
        "buffer_minutes": 15,
        "sessions_per_day_cap": 1,
    },
    "COURSE_CODE": "ENGL-201",
    "TERM_CODE": "2026FA",
    "TRAINING_MODULE_CODE": "AI-101",
    "TRAINING_COMPLETED_AT": "2026-01-15T00:00:00Z",
    "INCIDENT_AT": "2026-07-20T00:00:00Z",
    "NARRATIVE": "Essay reuses an uncited source across several paragraphs.",
    "APPEAL_STATEMENT": "The hearing panel disregarded exculpatory evidence entirely.",
}

# A real 64-lowercase-hex sha256 digest for every evidence fixture.
SHA256_A = "1111111111111111111111111111111111111111111111111111111111111111"
SHA256_B = "2222222222222222222222222222222222222222222222222222222222222222"
SHA256_C = "3333333333333333333333333333333333333333333333333333333333333333"
SHA256_D = "4444444444444444444444444444444444444444444444444444444444444444"

# Never minted by any create; used for 404 probes.
UNKNOWN_ID = "00000000-0000-4000-8000-000000000000"
