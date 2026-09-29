"""Every calculation from PRD Section 2.7 / 2.8 and SCAFFOLD `calculations`.

All arithmetic runs through decimal.Decimal with ROUND_HALF_UP. Money is whole
cents (integers), consequence scores and freeboard carry 2 decimal places and
acre-foot volumes carry 3.
"""

from decimal import Decimal

from common import add_days, add_months, dec, dfloor, rhu, rhu_int, whole_days_between

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

HAZARD_CLASSES = ("UNCLASSIFIED", "LOW", "SIGNIFICANT", "HIGH")
CERTIFIABLE_CLASSES = ("LOW", "SIGNIFICANT", "HIGH")
OWNER_TYPES = ("PRIVATE", "MUNICIPAL", "UTILITY", "IRRIGATION_DISTRICT")
DELINQUENCY_STATUSES = ("CURRENT", "DELINQUENT")
SAFETY_STATUSES = ("UNRATED", "SATISFACTORY", "CONDITIONALLY_SATISFACTORY", "POOR", "UNSATISFACTORY")
CONDITION_RATINGS = ("SATISFACTORY", "CONDITIONALLY_SATISFACTORY", "POOR", "UNSATISFACTORY")
REGULATORY_STATUSES = ("REGISTERED", "UNDER_ENFORCEMENT", "STATE_INTERVENTION", "REMOVAL_PERMITTED", "BREACHED")
ASSESSMENT_STATUSES = ("DRAFT", "CERTIFIED", "SUPERSEDED")
INSPECTION_TYPES = ("PERIODIC", "FOLLOW_UP", "HIGH_WATER")
INSPECTION_STATUSES = ("SCHEDULED", "SUBMITTED", "ACCEPTED", "RETURNED")
DEFICIENCY_SOURCES = ("INSPECTION", "SYSTEM_EAP", "SYSTEM_EXERCISE")
ENGINEER_DEFICIENCY_CATEGORIES = ("SPILLWAY_CAPACITY", "SEEPAGE", "EROSION", "STRUCTURAL", "OPERATIONAL")
SYSTEM_DEFICIENCY_CATEGORIES = ("EAP_MISSING", "EAP_EXERCISE")
DEFICIENCY_CATEGORIES = ENGINEER_DEFICIENCY_CATEGORIES + SYSTEM_DEFICIENCY_CATEGORIES
SEVERITIES = ("MINOR", "MODERATE", "SERIOUS", "CRITICAL")
DEFICIENCY_STATUSES = ("OPEN", "ORDERED", "REMEDIATION_SUBMITTED", "ESCALATED", "CLOSED_VERIFIED")
ORDER_TYPES = ("NOTICE_OF_DEFICIENCY", "COMPLIANCE_ORDER", "EMERGENCY_ORDER")
ORDER_STATUSES = ("ISSUED", "RESPONSE_FILED", "SATISFIED", "DEFAULTED", "REFERRED_FOR_ENFORCEMENT")
EAP_STATUSES = ("DRAFT", "SUBMITTED", "APPROVED", "REVISION_REQUIRED", "SUPERSEDED", "EXPIRED")
LATEST_EAP_STATUSES = ("NONE",) + EAP_STATUSES
EXERCISE_TYPES = ("TABLETOP", "FUNCTIONAL", "FULL_SCALE")
EXERCISE_OUTCOMES = ("ACCEPTED", "DEFICIENT")
PERMIT_TYPES = ("CONSTRUCTION", "REPAIR", "REMOVAL")
PERMIT_STATUSES = ("SUBMITTED", "UNDER_ENGINEERING_REVIEW", "ISSUED", "DENIED", "RETURNED_FOR_REVISION")
EVENT_STATUSES = ("MONITORING", "EMERGENCY", "STOOD_DOWN")
ALERT_LEVELS = ("NORMAL", "WATCH", "CRITICAL", "OVERTOPPING")
DRAWDOWN_STATUSES = ("REQUESTED", "COORDINATED", "ACTIVE", "COMPLETED", "CANCELLED")
POSITIVE_LEDGER_TYPES = ("PERMIT_REVIEW_FEE", "ANNUAL_REGISTRATION_FEE", "CIVIL_PENALTY")
NEGATIVE_LEDGER_TYPES = ("PAYMENT_RECEIVED", "PENALTY_ABATEMENT", "FEE_VOID")
LEDGER_TYPES = POSITIVE_LEDGER_TYPES + NEGATIVE_LEDGER_TYPES
INTERVENTION_TYPES = ("ABANDONMENT_TAKEOVER", "EMERGENCY_REPAIR", "BREACH_ORDER")
LICENSE_STATUSES = ("ACTIVE", "EXPIRED")

# ---------------------------------------------------------------------------
# Hazard-class dial (PRD Section 2.8). UNCLASSIFIED behaves as LOW everywhere.
# ---------------------------------------------------------------------------

INSPECTION_INTERVAL_MONTHS = {"HIGH": 12, "SIGNIFICANT": 24, "LOW": 60, "UNCLASSIFIED": 60}
EAP_REQUIRED = {"HIGH": True, "SIGNIFICANT": True, "LOW": False, "UNCLASSIFIED": False}
MIN_NOTIFICATION_CONTACTS = {"HIGH": 8, "SIGNIFICANT": 4, "LOW": 1, "UNCLASSIFIED": 1}
EAP_VALIDITY_MONTHS = {"HIGH": 36, "SIGNIFICANT": 60, "LOW": None, "UNCLASSIFIED": None}
MIN_EXERCISE_PARTICIPANTS = {"HIGH": 6, "SIGNIFICANT": 4, "LOW": 2, "UNCLASSIFIED": 2}
PERMITTED_EXERCISE_FORMATS = {
    "HIGH": ("FUNCTIONAL", "FULL_SCALE"),
    "SIGNIFICANT": ("TABLETOP", "FUNCTIONAL", "FULL_SCALE"),
    "LOW": ("TABLETOP", "FUNCTIONAL", "FULL_SCALE"),
    "UNCLASSIFIED": ("TABLETOP", "FUNCTIONAL", "FULL_SCALE"),
}
MIN_HIGH_HAZARD_BOND_CENTS = 25000000
FINANCIAL_ASSURANCE_FLOOR_CENTS = {
    "HIGH": MIN_HIGH_HAZARD_BOND_CENTS, "SIGNIFICANT": 0, "LOW": 0, "UNCLASSIFIED": 0,
}
REMEDIATION_COMPRESSION_FACTOR = {
    "HIGH": Decimal("0.5"), "SIGNIFICANT": Decimal("0.75"),
    "LOW": Decimal("1.0"), "UNCLASSIFIED": Decimal("1.0"),
}
PENALTY_HAZARD_FACTOR = {
    "HIGH": Decimal("1.6"), "SIGNIFICANT": Decimal("1.25"),
    "LOW": Decimal("1.0"), "UNCLASSIFIED": Decimal("1.0"),
}
PERMIT_REVIEW_FEE_UPLIFT = {
    "HIGH": Decimal("1.25"), "SIGNIFICANT": Decimal("1.10"),
    "LOW": Decimal("1.0"), "UNCLASSIFIED": Decimal("1.0"),
}

DELINQUENCY_THRESHOLD_CENTS = 25000

# ---------------------------------------------------------------------------
# 1. breach_consequence_score  (two variants: screening / certified)
# ---------------------------------------------------------------------------

POP_WEIGHT = Decimal("2.0")
POP_CAP = Decimal("60")
STRUCTURE_WEIGHT = Decimal("1.5")
STRUCTURE_CAP = Decimal("20")
INFRA_WEIGHT = Decimal("5.0")
INFRA_CAP = Decimal("15")
ECON_DIVISOR = Decimal("100")
ECON_CAP = Decimal("5")


def travel_time_multiplier(minutes):
    m = dec(minutes)
    if m < Decimal("30"):
        return Decimal("1.5")
    if m < Decimal("120"):
        return Decimal("1.0")
    return Decimal("0.6")


def consequence_score(population_at_risk, habitable_structures, critical_facilities,
                      breach_travel_time_minutes, inundation_area_acres, variant):
    """variant is 'screening' (multiplier forced to 1.0, economic term forced to 0)
    or 'certified' (travel-time multiplier applied, economic term included)."""
    if variant == "screening":
        multiplier = Decimal("1.0")
        econ = Decimal("0")
    else:
        multiplier = travel_time_multiplier(breach_travel_time_minutes)
        econ = min(ECON_CAP, dfloor(dec(inundation_area_acres) / ECON_DIVISOR))
    population_component = min(POP_CAP, dec(population_at_risk) * POP_WEIGHT * multiplier)
    structure_component = min(STRUCTURE_CAP, dec(habitable_structures) * STRUCTURE_WEIGHT)
    infrastructure_component = min(INFRA_CAP, dec(critical_facilities) * INFRA_WEIGHT)
    total = population_component + structure_component + infrastructure_component + econ
    return rhu(total, 2)


# ---------------------------------------------------------------------------
# 2. hazard_classification
# ---------------------------------------------------------------------------

HIGH_POPULATION_THRESHOLD = 25
HIGH_SCORE_THRESHOLD = Decimal("45.00")
SIGNIFICANT_SCORE_THRESHOLD = Decimal("15.00")


def hazard_classification(score, population_at_risk):
    par = int(population_at_risk)
    s = dec(score)
    if par >= HIGH_POPULATION_THRESHOLD:
        return "HIGH"
    if s >= HIGH_SCORE_THRESHOLD:
        return "HIGH"
    if s >= SIGNIFICANT_SCORE_THRESHOLD:
        return "SIGNIFICANT"
    if par >= 1:
        return "SIGNIFICANT"
    return "LOW"


# ---------------------------------------------------------------------------
# 3. inspection_due_schedule
# ---------------------------------------------------------------------------

def next_inspection_due(baseline_instant, hazard_class):
    return add_months(baseline_instant, INSPECTION_INTERVAL_MONTHS[hazard_class])


# ---------------------------------------------------------------------------
# 4. remediation_deadline
# ---------------------------------------------------------------------------

BASE_RESPONSE_DAYS = {"MINOR": 180, "MODERATE": 90, "SERIOUS": 45, "CRITICAL": 10}
MIN_RESPONSE_DAYS = 5
MAX_RESPONSE_DAYS = 365
EMERGENCY_ORDER_MAX_DAYS = 5
DAILY_PENALTY_BASE_CENTS = {"MINOR": 2000, "MODERATE": 5000, "SERIOUS": 12500, "CRITICAL": 25000}
REFERRAL_DAYS = 30


def effective_response_days(severity, hazard_class, requested_response_days, order_type):
    base = BASE_RESPONSE_DAYS[severity]
    factor = REMEDIATION_COMPRESSION_FACTOR[hazard_class]
    allowed = int(dfloor(dec(base) * factor))
    allowed = max(MIN_RESPONSE_DAYS, min(MAX_RESPONSE_DAYS, allowed))
    effective = min(int(requested_response_days), allowed)
    if order_type == "EMERGENCY_ORDER":
        effective = min(effective, EMERGENCY_ORDER_MAX_DAYS)
    return effective


def compliance_deadline(issued_at, effective_days):
    return add_days(issued_at, effective_days)


def daily_penalty_rate_cents(severity, hazard_class):
    return rhu_int(dec(DAILY_PENALTY_BASE_CENTS[severity]) * PENALTY_HAZARD_FACTOR[hazard_class])


# ---------------------------------------------------------------------------
# 5. civil_penalty_accrual  (provisional preview / final assessment)
# ---------------------------------------------------------------------------

PENALTY_TIER_1_FACTOR = Decimal("1.0")
PENALTY_TIER_2_FACTOR = Decimal("1.15")
PENALTY_TIER_3_FACTOR = Decimal("1.3225")
PENALTY_CAP_CENTS = 5000000
GOOD_FAITH_ABATEMENT_RATE = Decimal("0.25")


def overdue_days(clock, compliance_deadline_at):
    return whole_days_between(clock, compliance_deadline_at)


def _day_factor(day_index):
    if day_index <= 7:
        return PENALTY_TIER_1_FACTOR
    if day_index <= 30:
        return PENALTY_TIER_2_FACTOR
    return PENALTY_TIER_3_FACTOR


def accrued_penalty_cents(rate_cents, days):
    total = 0
    rate = dec(rate_cents)
    for day in range(1, int(days) + 1):
        total += rhu_int(rate * _day_factor(day))
    return total


def provisional_penalty_cents(rate_cents, days):
    """Preview variant: uncapped, no abatement."""
    return accrued_penalty_cents(rate_cents, days)


def final_penalty_cents(rate_cents, days, response_filed):
    """Final variant: cap first, then the good-faith abatement."""
    total = accrued_penalty_cents(rate_cents, days)
    total = min(total, PENALTY_CAP_CENTS)
    if response_filed:
        total = total - rhu_int(dec(total) * GOOD_FAITH_ABATEMENT_RATE)
    return total


# ---------------------------------------------------------------------------
# 6. permit_fee_schedule
# ---------------------------------------------------------------------------

BASE_FEE_TIERS = (
    (5000000, 25000),
    (50000000, 100000),
    (500000000, 350000),
)
TOP_BASE_FEE_CENTS = 900000
REVIEW_FEE_PCT = {
    "CONSTRUCTION": Decimal("0.0075"),
    "REPAIR": Decimal("0.005"),
    "REMOVAL": Decimal("0.0035"),
}
REVIEW_FEE_CAP_CENTS = 750000
DELINQUENCY_SURCHARGE_RATE = Decimal("0.15")
VOLUME_CREDIT_RATE = Decimal("0.10")
VOLUME_CREDIT_THRESHOLD_CENTS = 500000


def base_fee_cents(estimated_project_cost_cents):
    cost = int(estimated_project_cost_cents)
    for upper, fee in BASE_FEE_TIERS:
        if cost < upper:
            return fee
    return TOP_BASE_FEE_CENTS


def permit_fees(estimated_project_cost_cents, permit_type, hazard_class, owner_delinquent):
    base = base_fee_cents(estimated_project_cost_cents)
    uplift = PERMIT_REVIEW_FEE_UPLIFT[hazard_class]
    review = rhu_int(dec(estimated_project_cost_cents) * REVIEW_FEE_PCT[permit_type] * uplift)
    review = min(REVIEW_FEE_CAP_CENTS, review)
    subtotal = base + review
    surcharge = rhu_int(dec(subtotal) * DELINQUENCY_SURCHARGE_RATE) if owner_delinquent else 0
    pre_credit = subtotal + surcharge
    if pre_credit >= VOLUME_CREDIT_THRESHOLD_CENTS:
        credit = rhu_int(dec(pre_credit) * VOLUME_CREDIT_RATE)
    else:
        credit = 0
    total = pre_credit - credit
    return {
        "base_fee_cents": base,
        "engineering_review_fee_cents": review,
        "delinquency_surcharge_cents": surcharge,
        "volume_credit_cents": credit,
        "total_fee_cents": total,
    }


# ---------------------------------------------------------------------------
# 7/8. exercise currency and grading
# ---------------------------------------------------------------------------

EXERCISE_CURRENCY_DAYS = 365


def grade_exercise(hazard_class, notification_test_passed, participant_count, exercise_type):
    """Fixed evaluation order: notification test, then participation, then format."""
    if not notification_test_passed:
        return "DEFICIENT", "NOTIFICATION_TEST_FAILED"
    if int(participant_count) < MIN_EXERCISE_PARTICIPANTS[hazard_class]:
        return "DEFICIENT", "INSUFFICIENT_PARTICIPANTS"
    if exercise_type not in PERMITTED_EXERCISE_FORMATS[hazard_class]:
        return "DEFICIENT", "EXERCISE_TYPE_NOT_PERMITTED"
    return "ACCEPTED", None


# ---------------------------------------------------------------------------
# 10. engineer_visit_conflict
# ---------------------------------------------------------------------------

VISIT_BUFFER_MINUTES = 120


def windows_conflict(new_start, new_end, existing_start, existing_end):
    from datetime import timedelta
    buffer_delta = timedelta(minutes=VISIT_BUFFER_MINUTES)
    return new_start < (existing_end + buffer_delta) and existing_start < (new_end + buffer_delta)


# ---------------------------------------------------------------------------
# 11. reading_freeboard_and_alert
# ---------------------------------------------------------------------------

OVERTOPPING_FREEBOARD_FT = Decimal("0.0")
CRITICAL_FREEBOARD_FT = Decimal("1.0")
WATCH_FREEBOARD_FT = Decimal("3.0")


def freeboard_ft(crest_elevation_ft, pool_elevation_ft):
    return rhu(dec(crest_elevation_ft) - dec(pool_elevation_ft), 2)


def alert_level(freeboard):
    fb = dec(freeboard)
    if fb <= OVERTOPPING_FREEBOARD_FT:
        return "OVERTOPPING"
    if fb <= CRITICAL_FREEBOARD_FT:
        return "CRITICAL"
    if fb <= WATCH_FREEBOARD_FT:
        return "WATCH"
    return "NORMAL"


# ---------------------------------------------------------------------------
# 12. drawdown_volume_conservation
# ---------------------------------------------------------------------------

CFS_HOURS_TO_ACRE_FEET = Decimal("0.0826446")


def window_hours(window_start, window_end):
    seconds = dec((window_end - window_start).total_seconds())
    return seconds / dec(3600)


def planned_release_acre_ft(requested_release_cfs, window_start, window_end):
    hours = window_hours(window_start, window_end)
    return rhu(dec(requested_release_cfs) * hours * CFS_HOURS_TO_ACRE_FEET, 3)


def available_storage_acre_ft(gross_storage_acre_ft, committed_acre_ft):
    return rhu(dec(gross_storage_acre_ft) - dec(committed_acre_ft), 3)


def rhu_committed(value):
    """Committed acre-foot volumes are reported at 3 decimal places."""
    return rhu(value, 3)
