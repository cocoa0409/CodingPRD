"""Calculation rules: proration schedules, labor coverage, remedy split,
complaint pattern score, training credits, liability factor."""
from decimal import Decimal, ROUND_HALF_UP

from services.helpers import add_months

# Schedule percentage by completed years (integer pct)
def pct_standard(y):
    return max(20, 100 - 10 * max(0, y - 1))


def pct_enhanced(y):
    return max(50, 100 - 5 * max(0, y - 5))


def pct_enhanced_plus(y):
    return max(80, 100 - 2 * max(0, y - 10))


SCHEDULE_FN = {
    "STANDARD": pct_standard,
    "ENHANCED": pct_enhanced,
    "ENHANCED_PLUS": pct_enhanced_plus,
}

TIER_SCHEDULE = {"BRONZE": "STANDARD", "SILVER": "ENHANCED", "GOLD": "ENHANCED_PLUS"}

TIER_RANK = {"BRONZE": 1, "SILVER": 2, "GOLD": 3}

TIER_MIN_CREDITS = {"BRONZE": 4, "SILVER": 8, "GOLD": 12}

TIER_RULES = {
    "BRONZE": {"labor_years": 2, "labor_cap_cents": 200000},
    "SILVER": {"labor_years": 5, "labor_cap_cents": 500000},
    "GOLD": {"labor_years": 10, "labor_cap_cents": 1000000},
}

DETERMINATION_SHARE = {
    "MANUFACTURER_DEFECT": Decimal("1.0"),
    "MIXED": Decimal("0.5"),
    "INSTALLATION_ERROR": Decimal("0.0"),
}

WORKMANSHIP_DELTA = {
    "MANUFACTURER_DEFECT": 0,
    "MIXED": -4,
    "INSTALLATION_ERROR": -10,
}

DECERT_THRESHOLD = 60

SUSPEND_THRESHOLD = 5
REVOKE_LIFETIME = 8


def round_half_up_cents(value):
    """value: Decimal -> int cents, ROUND_HALF_UP."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def liability_factor(filing_workmanship_score):
    if filing_workmanship_score >= 80:
        return Decimal("1.00")
    if filing_workmanship_score >= 61:
        return Decimal("1.10")
    return Decimal("1.25")


def training_credit_total(db, contractor_id, evaluation_date):
    """Sum of credits over COMPLETED enrollments whose validity window
    covers the evaluation date (inclusive boundary)."""
    total = 0
    for en in db.training_enrollments.values():
        if en["contractor_id"] != contractor_id:
            continue
        if en["status"] != "COMPLETED":
            continue
        course = db.training_courses.get(en["course_id"])
        if course is None:
            continue
        completed = _to_date(en["completed_at"])
        if add_months(completed, course["validity_months"]) >= evaluation_date:
            total += course["credits"]
    return total


def _to_date(s):
    from datetime import date
    return date.fromisoformat(s)


def complaint_weighted_score(db, contractor_id, clock_dt):
    """Weighted trailing-24-month score over SUBSTANTIATED complaints,
    aging from each complaint's filed_at."""
    score = 0
    for c in db.complaints.values():
        if c["contractor_id"] != contractor_id or c["status"] != "SUBSTANTIATED":
            continue
        from services.helpers import parse_clock
        filed = parse_clock(c["filed_at"])
        days = (clock_dt - filed).days
        months = days // 30
        if months <= 6:
            w = 3
        elif months <= 12:
            w = 2
        elif months <= 24:
            w = 1
        else:
            w = 0
        score += w
    return score
