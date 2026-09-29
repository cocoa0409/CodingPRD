"""Numeric constants, thresholds and pure-python mirrors of the contract math.

Every value here is taken from the contract text, not invented: thresholds,
weights, tier boundaries and caps.  The small helper functions reproduce the
contract's rounding discipline (round half up, at the pinned rounding sites)
so tests can state expected integers derived the same way the contract derives
them, while every headline figure in a test is still asserted as a literal.
"""
from decimal import Decimal, ROUND_HALF_UP

# ─── Clock ────────────────────────────────────────────
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

# ─── Readiness scoring ────────────────────────────────
EXAM_PASSING_SCORE = 240
EXAM_WEIGHT_POINTS = 40
CLEARANCE_WEIGHT_POINTS = 35
COURSEWORK_WEIGHT_POINTS = 25
REQUIRED_COURSEWORK_CREDITS = 30
READY_THRESHOLD = 90

# ─── Geometry ─────────────────────────────────────────
MAX_PROGRAM_COMMUTE_MILES = 45
NEAR_MILES_MAX = 15
MID_MILES_MAX = 40

# ─── Supervisor caseload ──────────────────────────────
STAGE_BASE_POINTS = {"PROPOSED": 1, "ACTIVE": 2, "REMOVAL_PENDING": 3}
CASELOAD_CAP_BY_EMPLOYMENT = {"FULL_TIME": 24, "ADJUNCT": 10}

# ─── Teacher scheduling ───────────────────────────────
TURNAROUND_BUFFER_DAYS = 14
TRAINING_VALID_DAYS = 730

# ─── Stipend ──────────────────────────────────────────
# No bonus with zero consecutive terms hosted, 5 percent with one or two,
# 10 percent with three or more.
LONGEVITY_BONUS_NONE = Decimal("0")
LONGEVITY_BONUS_MID_PCT = Decimal("0.05")
LONGEVITY_BONUS_HIGH_PCT = Decimal("0.10")
COMPLETION_PREMIUM_CENTS = 2500
MIN_CREDITED_WEEKS = 4

# ─── Travel ───────────────────────────────────────────
MILEAGE_RATE_CENTS_PER_MILE = 67
WEEKLY_TRIPS = 5
TIER_1_SUBTOTAL_MAX_CENTS = 50000
TIER_2_SUBTOTAL_MAX_CENTS = 150000
TIER_1_PCT = Decimal("0.08")
TIER_2_PCT = Decimal("0.05")
TIER_3_PCT = Decimal("0.03")

# ─── Observation / assessment ─────────────────────────
MIN_REQUIRED_CYCLES = 3
ASSESSMENT_SUBMIT_MIN_RATIO = 0.5
COMPLETION_MIN_RATIO = 1.0
RUBRIC_SCALE = 20
WEIGHT_TASK_PLANNING = Decimal("0.3")
WEIGHT_INSTRUCTION = Decimal("0.35")
WEIGHT_ASSESSMENT = Decimal("0.2")
WEIGHT_PROFESSIONALISM = Decimal("0.15")
CUT_SCORE = 70
MAX_ASSESSMENT_ATTEMPTS = 2
RETURN_GRACE_DAYS = 7

# ─── Reporting ────────────────────────────────────────
STATE_REPORT_GRACE_DAYS = 45

# ─── Pagination ───────────────────────────────────────
DEFAULT_PAGE = 1
DEFAULT_PAGE_SIZE = 10
MAX_PAGE_SIZE = 100


def round_half_up(value) -> int:
    """Round a decimal value to a whole number, halves away from zero."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def manhattan_miles(x1: int, y1: int, x2: int, y2: int) -> int:
    """Grid distance: absolute x difference plus absolute y difference."""
    return abs(x1 - x2) + abs(y1 - y2)


def distance_surcharge(miles: int) -> int:
    """0 points at or under 15 miles, 1 point from 16 to 40, 2 points beyond."""
    if miles <= NEAR_MILES_MAX:
        return 0
    if miles <= MID_MILES_MAX:
        return 1
    return 2


def caseload_points_for(stage: str, miles: int) -> int:
    """Stage base points plus the distance surcharge for one placement."""
    return STAGE_BASE_POINTS[stage] + distance_surcharge(miles)


def coursework_points(credits) -> int:
    """Credits scaled to 25 points, rounded before the 25-point cap applies."""
    scaled = round_half_up(Decimal(str(credits)) * COURSEWORK_WEIGHT_POINTS
                           / REQUIRED_COURSEWORK_CREDITS)
    return min(scaled, COURSEWORK_WEIGHT_POINTS)


def longevity_bonus_pct(consecutive_terms_hosted: int) -> Decimal:
    """Zero terms earn nothing, one or two earn 5 percent, three or more 10."""
    if consecutive_terms_hosted == 0:
        return LONGEVITY_BONUS_NONE
    if consecutive_terms_hosted <= 2:
        return LONGEVITY_BONUS_MID_PCT
    return LONGEVITY_BONUS_HIGH_PCT


def weekly_stipend_cents(rate_cents: int, consecutive_terms_hosted: int) -> int:
    """Base weekly rate lifted by the longevity bonus, rounded to whole cents."""
    pct = longevity_bonus_pct(consecutive_terms_hosted)
    return round_half_up(Decimal(rate_cents) * (Decimal(1) + pct))


def travel_allowance_pct(subtotal_cents: int) -> Decimal:
    """Tier percentage selected from the pre-allowance subtotal."""
    if subtotal_cents <= TIER_1_SUBTOTAL_MAX_CENTS:
        return TIER_1_PCT
    if subtotal_cents <= TIER_2_SUBTOTAL_MAX_CENTS:
        return TIER_2_PCT
    return TIER_3_PCT


def travel_reimbursement_cents(commute_miles: int, weeks: int) -> int:
    """Billable miles, then subtotal, then the tier allowance on that subtotal."""
    miles = commute_miles * 2 * WEEKLY_TRIPS * weeks
    subtotal = miles * MILEAGE_RATE_CENTS_PER_MILE
    allowance = round_half_up(Decimal(subtotal) * travel_allowance_pct(subtotal))
    return subtotal + allowance


def rubric_total(planning, instruction, assessment, professionalism) -> int:
    """Each weighted dimension rounded to a whole number before summing."""
    parts = [
        (Decimal(str(planning)), WEIGHT_TASK_PLANNING),
        (Decimal(str(instruction)), WEIGHT_INSTRUCTION),
        (Decimal(str(assessment)), WEIGHT_ASSESSMENT),
        (Decimal(str(professionalism)), WEIGHT_PROFESSIONALISM),
    ]
    return sum(round_half_up(raw * weight * RUBRIC_SCALE) for raw, weight in parts)
