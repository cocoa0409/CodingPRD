"""Numeric constants, thresholds and small pure recomputations.

Every literal here is transcribed from the requirements document.  The helper
functions reproduce the document's pinned rounding order so a test can state an
expected figure without hard-coding an opaque number.
"""

import math
from decimal import Decimal, ROUND_HALF_UP
from typing import List, Optional

# --------------------------------------------------------------------------
# The logical clock
# --------------------------------------------------------------------------
#: Startup value of the logical clock.
CLOCK_STARTUP = "2026-08-01T00:00:00Z"
CLOCK_STARTUP_DATE = "2026-08-01"

# --------------------------------------------------------------------------
# Pagination
# --------------------------------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# --------------------------------------------------------------------------
# Credit granularity
# --------------------------------------------------------------------------
CREDIT_GRANULARITY = 0.25
MIN_CREDIT_VALUE = 0.25
MAX_CREDIT_VALUE = 2.00
MAX_REQUIRED_CREDITS_TOTAL = 40.00

# --------------------------------------------------------------------------
# Centre seats, staffing and intake posture
# --------------------------------------------------------------------------
RESTRICTED_SEAT_MARGIN_FRACTION = 0.10
RESTRICTED_HEADROOM_THRESHOLD = 1
FROZEN_HEADROOM_THRESHOLD = 0

# --------------------------------------------------------------------------
# Referral priority scoring
# --------------------------------------------------------------------------
DEFICIENCY_CREDIT_CAP = 8.00
BEHAVIOR_INCIDENT_CAP = 5
DAYS_DISENGAGED_CAP = 30
RE_REFERRAL_BUMP = 0.0500

#: pathway -> (deficiency weight, behavior weight, disengagement weight)
PATHWAY_WEIGHTS = {
    "CREDIT_DEFICIENCY": (0.60, 0.20, 0.20),
    "BEHAVIOR": (0.20, 0.60, 0.20),
    "RE_ENGAGEMENT": (0.20, 0.20, 0.60),
}

#: A RESTRICTED centre still seats a referral scoring at least this much.
RESTRICTED_PRIORITY_EXEMPTION = 0.5000

# --------------------------------------------------------------------------
# Offers
# --------------------------------------------------------------------------
DEFAULT_OFFER_VALID_DAYS = 10
PROMOTION_OFFER_VALID_DAYS = 5

# --------------------------------------------------------------------------
# Pacing
# --------------------------------------------------------------------------
ON_PACE_THRESHOLD = 0.900
BEHIND_THRESHOLD = 0.700

# --------------------------------------------------------------------------
# Readiness
# --------------------------------------------------------------------------
ATTENDANCE_WEIGHT = 0.50
PACING_WEIGHT = 0.30
CREDIT_WEIGHT = 0.20
CREDIT_COMPONENT_DENOMINATOR_FLOOR = 0.25

ENGAGEMENT_BONUS_HIGH = 0.0500
ENGAGEMENT_BONUS_HIGH_BASE = 0.8000
ENGAGEMENT_BONUS_HIGH_SESSIONS = 2
ENGAGEMENT_BONUS_LOW = 0.0300
ENGAGEMENT_BONUS_LOW_BASE = 0.6500
ENGAGEMENT_BONUS_LOW_SESSIONS = 1

MIN_ATTENDANCE_FOR_RE_ENTRY = 0.9000
MIN_READINESS_FOR_RE_ENTRY = 0.7500

# --------------------------------------------------------------------------
# Graduation plan posture
# --------------------------------------------------------------------------
ON_TRACK_FRACTION = 0.95
AT_RISK_FRACTION = 0.80

#: grade level -> grade-progress factor
GRADE_PROGRESS_FACTOR = {9: 0.25, 10: 0.50, 11: 0.75, 12: 1.00}

# --------------------------------------------------------------------------
# Cohort accountability
# --------------------------------------------------------------------------
COMPLIANT_GRAD_RATE = 0.8500
WATCH_GRAD_RATE = 0.7000

# --------------------------------------------------------------------------
# Mastery and award gates
# --------------------------------------------------------------------------
DEFAULT_PROCTORED_EXAM_WEIGHT = 0.40
MAX_PROCTORED_EXAM_WEIGHT = 0.60
DEFAULT_MIN_PASSING_PERCENT = 60
COMPETENCY_FULL_CREDIT_MASTERY = 80.00
COMPETENCY_MIN_MASTERY = 70.00

# --------------------------------------------------------------------------
# Proctoring stations and support providers
# --------------------------------------------------------------------------
TURNAROUND_BUFFER_MINUTES = 15
DEFAULT_MAX_CONCURRENT_STUDENTS = 4
MIN_MAX_CONCURRENT_STUDENTS = 1
MAX_MAX_CONCURRENT_STUDENTS = 8
MIN_MINUTES_DELIVERED = 1
MAX_MINUTES_DELIVERED = 480

# --------------------------------------------------------------------------
# Grade points
# --------------------------------------------------------------------------
GRADE_POINTS = {"A": 4.0, "B": 3.0, "C": 2.0, "D": 1.0, "F": 0.0}

#: Literal codes the system stamps on its own.
PROCTOR_INCIDENT_CODE = "PROCTOR_INCIDENT"
INTEGRITY_VOID_REASON = "INTEGRITY_VOID"
PLACEMENT_EXITED_DENIAL_REASON = "PLACEMENT_EXITED"
TRANSCRIPT_SUFFIX = "-AE"

#: Comparison tolerance for every asserted decimal figure.
TOLERANCE = 0.01


# --------------------------------------------------------------------------
# Pure recomputations that reproduce the document's pinned rounding order
# --------------------------------------------------------------------------
def round_half_up(value: float, places: int) -> float:
    """Round half up to ``places`` decimals, the only rounding mode used."""
    quantum = Decimal(1).scaleb(-places)
    return float(Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP))


def floor_to_quarter(value: float) -> float:
    """Floor a credit figure down to a multiple of 0.25."""
    return float(
        (Decimal(str(value)) / Decimal("0.25")).to_integral_value(rounding="ROUND_FLOOR")
        * Decimal("0.25")
    )


def letter_grade(percent: float) -> str:
    """Letter band for a historical row's original percent."""
    if percent >= 90:
        return "A"
    if percent >= 80:
        return "B"
    if percent >= 70:
        return "C"
    if percent >= 60:
        return "D"
    return "F"


def transcript_grade(percent: float) -> str:
    """Letter band for an award's transcript grade code; there is no F band."""
    if percent >= 90:
        return "A"
    if percent >= 80:
        return "B"
    if percent >= 70:
        return "C"
    return "D"


def priority_score(
    pathway: str,
    deficiency_credits: float,
    behavior_incident_count: int,
    days_disengaged: int,
    cites_prior_referral: bool = False,
) -> float:
    """Reproduce the referral priority score, rounding each term before summing."""
    deficiency = min(
        round_half_up(deficiency_credits / DEFICIENCY_CREDIT_CAP, 4), 1.0000
    )
    behavior = min(
        round_half_up(behavior_incident_count / BEHAVIOR_INCIDENT_CAP, 4), 1.0000
    )
    disengagement = min(
        round_half_up(days_disengaged / DAYS_DISENGAGED_CAP, 4), 1.0000
    )
    w_def, w_beh, w_dis = PATHWAY_WEIGHTS[pathway]
    base = round_half_up(
        round_half_up(deficiency * w_def, 4)
        + round_half_up(behavior * w_beh, 4)
        + round_half_up(disengagement * w_dis, 4),
        4,
    )
    if cites_prior_referral:
        return min(round_half_up(base + RE_REFERRAL_BUMP, 4), 1.0000)
    return base


def restricted_seat_margin(seat_capacity: int) -> int:
    """Ten percent of funded capacity, floored to a whole seat."""
    return math.floor(seat_capacity * RESTRICTED_SEAT_MARGIN_FRACTION)


def staffing_headroom(
    certified_teacher_fte: float, max_students_per_teacher: int, active_student_count: int
) -> int:
    """Floor of FTE times the load cap, less the active roster."""
    return (
        math.floor(certified_teacher_fte * max_students_per_teacher)
        - active_student_count
    )


def intake_posture(seats_available: int, headroom: int, margin: int) -> str:
    """First branch that matches wins, in the document's fixed order."""
    if seats_available <= 0 or headroom <= 0:
        return "FROZEN"
    if seats_available <= margin or headroom <= RESTRICTED_HEADROOM_THRESHOLD:
        return "RESTRICTED"
    return "OPEN"


def engagement_bonus(base_score: float, sessions_completed: int) -> float:
    """Two-tier bonus, tiered on the already-rounded base score."""
    if (
        base_score >= ENGAGEMENT_BONUS_HIGH_BASE
        and sessions_completed >= ENGAGEMENT_BONUS_HIGH_SESSIONS
    ):
        return ENGAGEMENT_BONUS_HIGH
    if (
        base_score >= ENGAGEMENT_BONUS_LOW_BASE
        and sessions_completed >= ENGAGEMENT_BONUS_LOW_SESSIONS
    ):
        return ENGAGEMENT_BONUS_LOW
    return 0.0000


def readiness(
    attendance_component: float,
    pacing_component: float,
    credit_component: float,
    sessions_completed: int,
) -> tuple:
    """Return ``(base, bonus, score)`` with the pinned ordering."""
    base = round_half_up(
        attendance_component * ATTENDANCE_WEIGHT
        + pacing_component * PACING_WEIGHT
        + credit_component * CREDIT_WEIGHT,
        4,
    )
    bonus = engagement_bonus(base, sessions_completed)
    score = min(round_half_up(base + bonus, 4), 1.0000)
    return base, bonus, score


def gpa(rows: List[tuple]) -> Optional[float]:
    """GPA from ``(grade_code, credits)`` rows with per-row quality points
    rounded to 3 decimals before summing."""
    quality = 0.0
    credits = 0.0
    for grade_code, row_credits in rows:
        quality += round_half_up(GRADE_POINTS[grade_code] * row_credits, 3)
        credits += row_credits
    if credits == 0:
        return None
    return round_half_up(quality / credits, 2)


def pace_index(
    elapsed_days: int, pacing_days: int, modules_passed: int, total_modules: int
) -> Optional[float]:
    """Actual module fraction over the capped expected fraction."""
    if elapsed_days == 0:
        return None
    expected = min(round_half_up(elapsed_days / pacing_days, 4), 1.0000)
    actual = round_half_up(min(modules_passed, total_modules) / total_modules, 4)
    return round_half_up(actual / expected, 3)


def pacing_flag(index: Optional[float]) -> str:
    if index is None:
        return "NOT_YET_RATED"
    if index >= ON_PACE_THRESHOLD:
        return "ON_PACE"
    if index >= BEHIND_THRESHOLD:
        return "BEHIND"
    return "CRITICAL"


def mastery_pct(
    module_avg_percent: Optional[float],
    proctored_exam_percent: Optional[float],
    proctoring_required: bool,
    proctored_exam_weight: float,
) -> Optional[float]:
    """Blend coursework with the supervised exam when one is available."""
    if module_avg_percent is None:
        return None
    if proctoring_required and proctored_exam_percent is not None:
        return round_half_up(
            module_avg_percent * (1 - proctored_exam_weight)
            + proctored_exam_percent * proctored_exam_weight,
            2,
        )
    return round_half_up(module_avg_percent, 2)


def seat_time_credits(
    seat_hours_logged: float, required_seat_hours: float, credit_value: float
) -> float:
    """Credits under the seat-time policy."""
    fraction = min(round_half_up(seat_hours_logged / required_seat_hours, 4), 1.0000)
    return floor_to_quarter(credit_value * fraction)


def competency_credits(
    mastery: Optional[float],
    credit_value: float,
    modules_passed: int,
    total_modules: int,
) -> float:
    """Credits under the competency policy, in three bands."""
    if mastery is None or mastery < COMPETENCY_MIN_MASTERY:
        return 0.00
    if mastery >= COMPETENCY_FULL_CREDIT_MASTERY:
        return credit_value
    fraction = round_half_up(min(modules_passed, total_modules) / total_modules, 4)
    return floor_to_quarter(credit_value * fraction)


def plan_posture(credits_earned: float, expected_by_grade: float, status: str) -> str:
    """Plan posture in the document's fixed evaluation order."""
    if status == "COMPLETED":
        return "ON_TRACK"
    if credits_earned >= round_half_up(expected_by_grade * ON_TRACK_FRACTION, 2):
        return "ON_TRACK"
    if credits_earned >= round_half_up(expected_by_grade * AT_RISK_FRACTION, 2):
        return "AT_RISK"
    return "OFF_TRACK"


def cohort_flag(adjusted_grad_rate: Optional[float]) -> str:
    if adjusted_grad_rate is None:
        return "NOT_RATED"
    if adjusted_grad_rate >= COMPLIANT_GRAD_RATE:
        return "COMPLIANT"
    if adjusted_grad_rate >= WATCH_GRAD_RATE:
        return "WATCH"
    return "PRIORITY"
