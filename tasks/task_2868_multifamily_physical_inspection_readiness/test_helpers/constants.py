"""Domain constants for the multifamily physical inspection readiness API.

Every literal here is taken from the PRD contract: named policy thresholds,
the deduction multiplier tables, and the canonical instants the test suite
drives the logical clock and the workflow with.
"""

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
# "Before any call the logical clock reads exactly 2026-08-01T00:00:00Z".
INITIAL_CLOCK = "2026-08-01T00:00:00.000Z"

# ---------------------------------------------------------------------------
# Named policy constants
# ---------------------------------------------------------------------------
LIFE_THREATENING_DEADLINE_HOURS = 24
NOTICE_LEAD_HOURS_MIN = 48.00
SWEEP_CLOSURE_RATE_FLOOR = 90.00
SWEEP_MAX_CONCURRENT = 2
INSPECTION_COOLDOWN_BUFFER_HOURS = 72
APPEAL_WINDOW_HOURS = 360
APPEAL_RESUBMIT_LIMIT = 2
REFUSAL_PENALTY_POINTS = 12.00
DEFICIENCY_POINT_CAP = 40.00
PRIORITY_SCORE_CAP = 100.00
CAP_REQUIRED_SCORE_THRESHOLD = 90.00
WATCH_SCORE_THRESHOLD = 60.00
WATCH_OPEN_SEVERE_THRESHOLD = 5
CALENDAR_SCOPE_DAYS = 730
INSPECTION_SCOPE_COUNT = 2
MIN_RECURRENCE_COUNT = 2
FOLLOW_UP_EXTRA_DAYS_WITH_LIFE_THREATENING = 10
FOLLOW_UP_EXTRA_DAYS_WITHOUT_LIFE_THREATENING = 30

# CAP window tiers, upper-inclusive on the current final_score.
CAP_WINDOW_TIERS = (
    (90.00, 60),
    (80.00, 45),
    (60.00, 30),
)
CAP_WINDOW_DAYS_FLOOR = 15

# ---------------------------------------------------------------------------
# Deduction multiplier tables
# ---------------------------------------------------------------------------
SEVERITY_MULTIPLIERS = {
    "LIFE_THREATENING": 3.0,
    "SEVERE": 2.0,
    "MODERATE": 1.0,
    "LOW": 0.5,
}
AREA_MULTIPLIERS = {
    "UNIT": 1.0,
    "INSIDE": 0.8,
    "OUTSIDE": 0.6,
}
RECURRENCE_MULTIPLIER = 1.5
OCCUPANCY_MULTIPLIER = 1.2

# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# ---------------------------------------------------------------------------
# Canonical standard / defect definition literals
# ---------------------------------------------------------------------------
STANDARD_CODE = "NSPIRE-2026"
STANDARD_NAME = "NSPIRE 2026"
ALT_STANDARD_CODE = "ALT-2026"
ALT_STANDARD_NAME = "Alternate 2026"
DRAFT_STANDARD_CODE = "NSPIRE-2027"
DRAFT_STANDARD_NAME = "NSPIRE 2027"

UNIT_WEIGHT_PCT = 50.0
INSIDE_WEIGHT_PCT = 30.0
OUTSIDE_WEIGHT_PCT = 20.0

EFFECTIVE_DATE = "2026-01-01T00:00:00.000Z"
ADOPTED_AT = "2026-01-02T00:00:00.000Z"
ALT_ADOPTED_AT = "2026-01-03T00:00:00.000Z"

# Definition blueprints keyed by code: (name, inspectable_area, severity,
# base_point_value, correction_deadline_hours).
DEFINITION_BLUEPRINTS = {
    "LT_GAS": (
        "Gas leak at range connection",
        "UNIT",
        "LIFE_THREATENING",
        10.0,
        24,
    ),
    "SEV_WINDOW": (
        "Inoperable egress window",
        "UNIT",
        "SEVERE",
        8.0,
        720,
    ),
    "MOD_HANDRAIL": (
        "Loose stairwell handrail",
        "INSIDE",
        "MODERATE",
        6.0,
        720,
    ),
    "LOW_TRASH": (
        "Uncontained trash at the dumpster pad",
        "OUTSIDE",
        "LOW",
        4.0,
        720,
    ),
    "MOD_HEAVY": (
        "Systemic interior finish failure",
        "UNIT",
        "MODERATE",
        40.0,
        720,
    ),
    "MOD_DOOR": (
        "Damaged corridor door closer",
        "INSIDE",
        "MODERATE",
        6.0,
        720,
    ),
    "MOD_FLOOR": (
        "Trip hazard in the dwelling floor",
        "UNIT",
        "MODERATE",
        8.0,
        720,
    ),
    "SEV_DOOR": (
        "Unsecurable entry door",
        "UNIT",
        "SEVERE",
        8.0,
        720,
    ),
}

# ---------------------------------------------------------------------------
# Canonical property literals
# ---------------------------------------------------------------------------
CEDAR_WALK = {
    "name": "Cedar Walk",
    "total_unit_count": 1,
    "capital_reserve_cents": 500000,
    "owner_contact_email": "owner@cedar.example",
}
MAPLE_COURT = {
    "name": "Maple Court",
    "total_unit_count": 4,
    "capital_reserve_cents": 1000000,
    "owner_contact_email": "owner@maple.example",
}
BIRCH_ROW = {
    "name": "Birch Row",
    "total_unit_count": 4,
    "capital_reserve_cents": 1000000,
    "owner_contact_email": "owner@birch.example",
}
ASH_TERRACE = {
    "name": "Ash Terrace",
    "total_unit_count": 2,
    "capital_reserve_cents": 500000,
    "owner_contact_email": "owner@ash.example",
}
ALDER_COURT = {
    "name": "Alder Court",
    "total_unit_count": 30,
    "capital_reserve_cents": 1000000,
    "owner_contact_email": "owner@alder.example",
}
BIRCH_COURT = {
    "name": "Birch Court",
    "total_unit_count": 31,
    "capital_reserve_cents": 1000000,
    "owner_contact_email": "owner@birchcourt.example",
}

# ---------------------------------------------------------------------------
# Canonical inspection workflow instants
# ---------------------------------------------------------------------------
INSPECTION_SCHEDULED_START = "2026-09-10T09:00:00.000Z"
INSPECTION_SCHEDULED_END = "2026-09-10T17:00:00.000Z"
DRAWN_AT = "2026-08-02T00:00:00.000Z"
NOTIFIED_AT = "2026-08-05T09:00:00.000Z"
ACCESS_WINDOW_START = "2026-09-10T09:00:00.000Z"
ACCESS_WINDOW_END = "2026-09-10T17:00:00.000Z"
INSPECTION_STARTED_AT = "2026-09-10T09:00:00.000Z"
ACCESS_RECORDED_AT = "2026-09-10T09:05:00.000Z"
ACCESS_RECORDED_AT_SECOND = "2026-09-10T11:05:00.000Z"

OBSERVED_AT_1 = "2026-09-10T10:00:00.000Z"
OBSERVED_AT_2 = "2026-09-10T10:05:00.000Z"
OBSERVED_AT_3 = "2026-09-10T10:10:00.000Z"
OBSERVED_AT_4 = "2026-09-10T10:15:00.000Z"
OBSERVED_AT_5 = "2026-09-10T10:20:00.000Z"

SCORED_AT = "2026-09-11T09:00:00.000Z"
APPEAL_DEADLINE_AT = "2026-09-26T09:00:00.000Z"
APPEAL_FILED_AT = "2026-09-12T09:00:00.000Z"
APPEAL_DECIDED_AT = "2026-09-13T09:00:00.000Z"
FINALIZED_AT = "2026-09-14T09:00:00.000Z"
CAP_SUBMITTED_AT = "2026-09-15T09:00:00.000Z"
CAP_DECIDED_AT = "2026-09-16T09:00:00.000Z"

CAP_NARRATIVE = "Replace both egress windows"
CAP_COST_CENTS = 400000
CAP_MILESTONE_COUNT = 3
CAP_TARGET_COMPLETION_AT = "2026-10-20T09:00:00.000Z"

FOLLOW_UP_START = "2026-11-02T09:00:00.000Z"
FOLLOW_UP_END = "2026-11-02T17:00:00.000Z"

# ---------------------------------------------------------------------------
# Canonical sweep workflow instants
# ---------------------------------------------------------------------------
SWEEP_WINDOW_START = "2026-08-02T00:00:00.000Z"
SWEEP_WINDOW_END = "2026-08-20T00:00:00.000Z"
SWEEP_STARTED_AT = "2026-08-02T08:00:00.000Z"
SWEEP_OBSERVED_AT_1 = "2026-08-03T09:00:00.000Z"
SWEEP_OBSERVED_AT_2 = "2026-08-03T09:30:00.000Z"
SWEEP_OBSERVED_AT_3 = "2026-08-03T10:00:00.000Z"
LT_CORRECTION_DUE_AT = "2026-08-04T09:00:00.000Z"
WORK_ORDER_COMPLETED_AT = "2026-08-04T09:00:00.000Z"
WORK_ORDER_VERIFIED_AT = "2026-08-05T09:00:00.000Z"

# ---------------------------------------------------------------------------
# Injected history instants
# ---------------------------------------------------------------------------
HISTORY_FINALIZED_OLD = "2024-09-15T00:00:00.000Z"
HISTORY_FINALIZED_MID = "2025-06-15T00:00:00.000Z"
HISTORY_FINALIZED_RECENT = "2026-03-15T00:00:00.000Z"

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------
ADOPTION_STATUSES = ("DRAFT", "ADOPTED", "SUPERSEDED")
INSPECTABLE_AREAS = ("UNIT", "INSIDE", "OUTSIDE")
SEVERITIES = ("LIFE_THREATENING", "SEVERE", "MODERATE", "LOW")
OCCUPANCY_STATUSES = ("OCCUPIED", "VACANT", "DOWN")
READINESS_POSTURES = ("READY", "WATCH", "RESTRICTED", "FROZEN")
PLANNED_AREA_SCOPES = ("UNIT_ONLY", "INSIDE_OUTSIDE", "ALL_AREAS")
SWEEP_STATUSES = ("PLANNED", "IN_PROGRESS", "CLOSED", "ABANDONED")
REPAIR_STATUSES = ("OPEN", "REPAIRED")
VERIFICATION_STATUSES = ("UNVERIFIED", "VERIFIED", "REJECTED", "VOID")
PRIORITY_TIERS = ("ROUTINE", "URGENT")
VERIFICATION_RESULTS = ("PASSED", "FAILED")
INSPECTION_KINDS = ("INITIAL", "FOLLOW_UP")
NOTICE_METHODS = ("POSTED", "MAILED", "POSTED_AND_MAILED", "EMAIL")
ACCESS_RESULTS = ("GRANTED", "REFUSED")
ACCESS_STATUSES = ("NOT_NOTIFIED", "NOTIFIED", "GRANTED", "REFUSED")
SELECTION_STATUSES = ("ACTIVE", "REPLACED")
SELECTION_BASES = ("SAMPLED", "REPLACEMENT")
DEFICIENCY_SOURCES = ("INSPECTION", "SELF_ASSESSMENT")
DEFICIENCY_STATUSES = ("OPEN", "OVERDUE", "CORRECTED", "VERIFIED", "VOIDED")
APPEAL_TYPES = ("TECHNICAL_ERROR", "SCORE_CORRECTION")
APPEAL_STATUSES = ("SUBMITTED", "RETURNED_FOR_INFO", "GRANTED", "DENIED")
APPEAL_DECISIONS = ("GRANTED", "DENIED", "RETURNED_FOR_INFO")
CAP_STATUSES = (
    "SUBMITTED",
    "APPROVED",
    "REJECTED",
    "FOLLOW_UP_SCHEDULED",
    "COMPLETED",
)
CAP_DECISIONS = ("APPROVED", "REJECTED")
RECURRENCE_BASES = ("CALENDAR_SCOPED", "INSPECTION_SCOPED")
CAPITAL_GENERATION_STATUSES = ("ACTIVE", "SUPERSEDED")
