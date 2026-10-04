"""Domain thresholds and literal values the PRD pins."""

# ─── Selection score ──────────────────────────────────
LEADERSHIP_WEIGHT = 0.45
ACHIEVEMENT_WEIGHT = 0.40
GPA_WEIGHT = 0.15
CAMPUS_TIER_BONUS = 5.0
HIGH_NEED_SUBJECT_BONUS = 7.0
STRONG_BAND_MIN = 85.00
QUALIFIED_BAND_MIN = 70.00
SELECT_BAND_MIN = 85.00
HIGH_NEED_SUBJECTS = ("MATH", "SCIENCE", "SPED")

# ─── Selection pipeline ───────────────────────────────
LEADERSHIP_FLOOR = 40.0
REVISION_CEILING = 3
RESUBMISSION_WINDOW_DAYS = 30
OFFER_WINDOW_DAYS = 14

# ─── Institute ────────────────────────────────────────
ANNUAL_STIPEND_DOLLARS = 6510.00
WEEKS_PER_YEAR = 52
HOURS_PER_WEEK = 40
PRACTICE_HOURS_CEILING = 480
INSTITUTE_COMPLETION_FLOOR = 120

# ─── Readiness ────────────────────────────────────────
CERTIFIED_WEIGHT = 0.5
PRACTICE_WEIGHT = 0.3
COURSEWORK_WEIGHT = 0.2
READINESS_STRONG_MIN = 80.00
READINESS_QUALIFIED_MIN = 50.00
STRONG_SUPPORT_CREDIT = 3.0
QUALIFIED_SUPPORT_CREDIT = 1.5
DEVELOPING_SUPPORT_CREDIT = 0.0
READINESS_CEILING = 100.0
ACTIVATION_READINESS_MIN = 60.0

# ─── Deadlines ────────────────────────────────────────
AT_RISK_WINDOW_DAYS = 14

# ─── Placement fees ───────────────────────────────────
HIGH_NEED_UPLIFT = 1.15

# ─── Logical clock ────────────────────────────────────
CLOCK_STARTUP_INSTANT = "2026-09-01T00:00:00Z"

# ─── Test defaults (recurring fixture values) ─────────
TEST_DEFAULTS = {
    "REGION_CODE": "GULF-COAST",
    "REGION_NAME": "Gulf Coast",
    "STATE_CODE": "TX",
    "TERM_START_DATE": "2026-12-01T00:00:00Z",
    "BASE_PLACEMENT_FEE_CENTS": 300000,
    "MAX_CORPS_MEMBERS": 10,
    "PATHWAY_COURSEWORK_HOURS": 60,
    "PATHWAY_PRACTICE_HOURS": 120,
    "PATHWAY_DEADLINE_DAYS": 30,
    "PATHWAY_FEE_CENTS": 250000,
    "DISTRICT_NAME": "Bayou ISD",
    "HIRING_COMMITMENT_SLOTS": 4,
    "PLACEMENT_FEE_PER_MEMBER_CENTS": 350000,
    "UNFILLED_SLOT_PENALTY_CENTS": 120000,
    "FEE_BUDGET_CENTS": 2000000,
    "SCHOOL_NAME": "Bayou High",
    "SCHOOL_GRADE_BAND": "HIGH",
    "SCHOOL_SUBJECT_NEEDS": ["MATH", "SCIENCE"],
    "CLASSROOM_CAPACITY": 1,
    "APPLICANT_NAME": "Ada Rivera",
    "APPLICANT_EMAIL": "ada@x.edu",
    "CAMPUS_NAME": "State U",
    "CAMPUS_TIER": "STANDARD",
    "GRADUATION_YEAR": 2026,
    "LEADERSHIP_SCORE": 80.0,
    "ACHIEVEMENT_SCORE": 85.0,
    "GPA": 4.0,
    "VERIFIED_GPA": 4.0,
    "SUBJECT_AREA": "MATH",
    "GRADE_PREFERENCE": "HIGH",
    "TERM_WINDOW_START": "2026-12-01T00:00:00Z",
    "TERM_WINDOW_END": "2027-05-31T00:00:00Z",
}

# Reviewer / officer operator ids. Decision and verification operators must
# differ from the reviewer and completer respectively (segregation of duties).
OPERATORS = {
    "REVIEWER": "sm_reviewer",
    "DECIDER": "sm_decider",
    "REVIEWER_2": "sm_reviewer_2",
    "DECIDER_2": "sm_decider_2",
    "COMPLETER": "co_completer",
    "VERIFIER": "co_verifier",
    "COACH": "coach_lee",
}
