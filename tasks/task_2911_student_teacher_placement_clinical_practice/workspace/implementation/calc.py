"""Pure calculations (PRD 2.7, 3.2, 3.4, 3.6, 3.7, 3.8, 3.9)."""

from decimal import Decimal, ROUND_HALF_UP

EXAM_PASS_SCORE = 240
EXAM_POINTS = 40
CLEARANCE_POINTS = 35
COURSEWORK_POINTS_CAP = 25
REQUIRED_CREDITS = 30
READINESS_THRESHOLD = 90

TRAINING_VALID_DAYS = 730
TURNAROUND_PAD_DAYS = 14
COMMUTE_CEILING_MILES = 45

CASELOAD_CAP_BY_EMPLOYMENT = {"FULL_TIME": 24, "ADJUNCT": 10}
STAGE_BASE_POINTS = {"PROPOSED": 1, "ACTIVE": 2, "REMOVAL_PENDING": 3}

MILEAGE_RATE_CENTS = 67
TRIPS_PER_WEEK = 5
COMPLETION_PREMIUM_CENTS = 2500
WEEKS_CREDITED_FLOOR = 4

MIN_CYCLE_DENOMINATOR = 3
ASSESSMENT_CUT_SCORE = 70
RUBRIC_SCALE = 20
RUBRIC_WEIGHTS = (
    ("task_planning", Decimal("0.30")),
    ("task_instruction", Decimal("0.35")),
    ("task_assessment", Decimal("0.20")),
    ("task_professionalism", Decimal("0.15")),
)

STATE_REPORT_GRACE_DAYS = 45
RESUBMISSION_GRACE_DAYS = 7
MAX_REROUTES_PER_REQUEST = 2
MAX_RESCHEDULES_PER_CYCLE = 2
MAX_ASSESSMENT_ATTEMPTS = 2
MAX_ROUTING_ROUNDS = 3


def round_half_up_int(value):
    """Round half up (away from zero) to a whole unit."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_places(value, places):
    exp = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(exp, rounding=ROUND_HALF_UP)


def manhattan(x1, y1, x2, y2):
    return abs(int(x1) - int(x2)) + abs(int(y1) - int(y2))


# --- readiness -------------------------------------------------------------

def coursework_points(total_credits):
    """Rounded to whole points BEFORE the 25-point cap is applied."""
    raw = (Decimal(str(total_credits)) * Decimal(COURSEWORK_POINTS_CAP)
           / Decimal(REQUIRED_CREDITS))
    points = round_half_up_int(raw)
    return min(points, COURSEWORK_POINTS_CAP)


def readiness_components(counted_items):
    exam = 0
    clearance = 0
    credits = Decimal("0")
    for item in counted_items:
        if item["item_type"] == "CONTENT_EXAM":
            score = item.get("exam_score")
            if score is not None and int(score) >= EXAM_PASS_SCORE:
                exam = EXAM_POINTS
        elif item["item_type"] == "BACKGROUND_CLEARANCE":
            clearance = CLEARANCE_POINTS
        elif item["item_type"] == "COURSEWORK_BLOCK":
            value = item.get("credits")
            if value is not None:
                credits += Decimal(str(value))
    coursework = coursework_points(credits)
    return exam, clearance, coursework


def readiness_status(score, clearance, previous_status):
    if score >= READINESS_THRESHOLD and clearance == CLEARANCE_POINTS:
        return "READY"
    if previous_status == "READY":
        return "LAPSED"
    return "NOT_READY"


# --- caseload --------------------------------------------------------------

def distance_surcharge(miles):
    if miles <= 15:
        return 0
    if miles <= 40:
        return 1
    return 2


def stage_points(placement_status, travel_miles):
    base = STAGE_BASE_POINTS.get(placement_status)
    if base is None:
        return 0
    return base + distance_surcharge(travel_miles)


def max_caseload_points(employment_type, override):
    ceiling = CASELOAD_CAP_BY_EMPLOYMENT[employment_type]
    if override is not None:
        return min(ceiling, int(override))
    return ceiling


# --- stipend and travel ----------------------------------------------------

def longevity_multiplier(consecutive_terms_hosted):
    terms = int(consecutive_terms_hosted or 0)
    if terms >= 3:
        return Decimal("1.10")
    if terms >= 1:
        return Decimal("1.05")
    return Decimal("1.00")


def weekly_stipend_cents(rate_cents_per_week, consecutive_terms_hosted):
    """Rounded to whole cents BEFORE multiplication by credited weeks."""
    raw = Decimal(int(rate_cents_per_week)) * longevity_multiplier(
        consecutive_terms_hosted)
    return round_half_up_int(raw)


def final_weeks_credited(start_date, settlement_date, weeks_scheduled):
    whole_weeks = (settlement_date - start_date).days // 7
    return max(WEEKS_CREDITED_FLOOR, min(int(weeks_scheduled), whole_weeks))


def gross_stipend_cents(weekly_cents, weeks_credited, premium_cents):
    return int(weekly_cents) * int(weeks_credited) + int(premium_cents)


def travel_allowance_percent(subtotal_cents):
    if subtotal_cents <= 50000:
        return Decimal("8")
    if subtotal_cents <= 150000:
        return Decimal("5")
    return Decimal("3")


def travel_reimbursement_cents(commute_miles, weeks_credited, enabled):
    if not enabled:
        return 0
    billable_miles = int(commute_miles) * 2 * TRIPS_PER_WEEK * int(weeks_credited)
    subtotal = billable_miles * MILEAGE_RATE_CENTS
    percent = travel_allowance_percent(subtotal)
    allowance = round_half_up_int(Decimal(subtotal) * percent / Decimal(100))
    return subtotal + allowance


# --- observation compliance and rubric ------------------------------------

def compliance_ratio(counted_total, completed_total):
    denominator = max(MIN_CYCLE_DENOMINATOR, int(counted_total))
    ratio = Decimal(int(completed_total)) / Decimal(denominator)
    return round_half_up_places(ratio, 4)


def rubric_dimension_points(raw_score, weight):
    return round_half_up_int(
        Decimal(str(raw_score)) * weight * Decimal(RUBRIC_SCALE))


def assessment_total_score(scores):
    total = 0
    for name, weight in RUBRIC_WEIGHTS:
        total += rubric_dimension_points(scores[name], weight)
    return total
