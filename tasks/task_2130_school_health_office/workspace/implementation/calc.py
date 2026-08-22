"""Calculation rules (PRD section 3, scaffold 1.3).

Every derived figure is produced here.  Money-style and ratio-style figures use
Decimal with ROUND_HALF_UP, rounded at the pinned point in the arithmetic.
"""
import math
from decimal import Decimal, ROUND_HALF_UP

from store import (db, days, floor_minutes, minute_of_day, minutes,
                   same_utc_day, utc_day_start, weekday_name)

# --- pinned constants ------------------------------------------------------
FULL_TIME_WEEKLY_MINUTES = 2100
CREDENTIAL_WEIGHT = {
    "RN": Decimal("1.00"),
    "LPN": Decimal("0.60"),
}
POSTURE_FULL_MAX = Decimal("750.00")
POSTURE_LIMITED_MAX = Decimal("1500.00")

AVG_DAILY_UNITS = {
    "EPINEPHRINE": Decimal("0.30"),
    "ALBUTEROL": Decimal("1.20"),
    "INSULIN": Decimal("3.00"),
    "METHYLPHENIDATE": Decimal("1.00"),
    "ACETAMINOPHEN": Decimal("2.50"),
}
DAYS_OF_SUPPLY_READY_MIN = Decimal("30.00")
STUDENTS_PER_STOCK_UNIT = 25

ALLERGY_POINTS = {"NONE": 0, "MILD": 5, "MODERATE": 15, "ANAPHYLAXIS": 40}
IMMUNIZATION_POINTS = {"COMPLIANT": 0, "PROVISIONAL": 5, "EXEMPT": 5, "NONCOMPLIANT": 20}
OBSERVED_WINDOW_DAYS = 90
VISIT_POINTS = 6
HIGH_DISPOSITION_POINTS = 12
STOCK_EMERGENCY_POINTS = 8
TIER_ELEVATED_MIN = 25
TIER_CRITICAL_MIN = 60

ACUITY_BASE = {"ROUTINE": 10, "URGENT": 40, "EMERGENT": 70}
COMPLAINT_POINTS = {"INJURY": 10, "ILLNESS": 8, "MEDICATION": 12,
                    "CHRONIC_CARE": 15, "MENTAL_HEALTH": 18, "SCREENING_FOLLOWUP": 2}
RISK_TIER_POINTS = {"ROUTINE": 0, "ELEVATED": 10, "CRITICAL": 20}
ANAPHYLAXIS_BONUS = 15
RISK_UPLIFT_CAP = 25
COVERAGE_PENALTY = {"FULL": 0, "LIMITED": 8, "UNCOVERED": 15}
EMS_REVIEW_MIN = 85

STOCK_PROTOCOL_DOSE = {"EPINEPHRINE": 0.3, "ALBUTEROL": 2}

TRAVEL_BUFFER_MINUTES = 20
MAX_REVISION_ROUNDS = 2
MAX_REOPENS = 1
MAX_SCREENING_CYCLES = 3
REOPEN_WINDOW_MINUTES = 120
VOID_WINDOW_MINUTES = 1440
CONSENT_VALIDITY_DAYS = 30
PLAN_REVIEW_DAYS = 365
RESCREEN_DAYS = 14
REFERRAL_DAYS = 30


def round2(value):
    if value is None:
        return None
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def as_float(value):
    if value is None:
        return None
    return float(value)


# ---------------------------------------------------------------------------
# CoverageAssignment derived status
# ---------------------------------------------------------------------------

def coverage_status(block, clock=None):
    clock = clock or db.now()
    effective_from = block["effective_from"]
    effective_to = block.get("effective_to")
    if clock < effective_from:
        return "SCHEDULED"
    if effective_to is not None and clock >= effective_to:
        return "ENDED"
    return "ACTIVE"


def duration_minutes(block):
    return block["end_minute"] - block["start_minute"]


def nurse_blocks(nurse_id):
    return [b for b in db.coverage_assignments.values() if b["nurse_id"] == nurse_id]


def school_blocks(school_id):
    return [b for b in db.coverage_assignments.values() if b["school_id"] == school_id]


def assigned_school_count(nurse_id):
    schools = set()
    for block in nurse_blocks(nurse_id):
        if coverage_status(block) in ("SCHEDULED", "ACTIVE"):
            schools.add(block["school_id"])
    return len(schools)


def nurse_on_active_coverage(nurse_id, school_id, check_time_of_day=True):
    clock = db.now()
    today = weekday_name(clock)
    mod = minute_of_day(clock)
    for block in db.coverage_assignments.values():
        if block["nurse_id"] != nurse_id or block["school_id"] != school_id:
            continue
        if coverage_status(block, clock) != "ACTIVE":
            continue
        if not check_time_of_day:
            return True
        if block["weekday"] != today:
            continue
        if block["start_minute"] <= mod < block["end_minute"]:
            return True
    return False


# ---------------------------------------------------------------------------
# Student risk scoring
# ---------------------------------------------------------------------------

def intake_risk_score(student):
    allergy = ALLERGY_POINTS.get(student.get("allergy_severity"), 0)
    condition = 10 * len(student.get("chronic_condition_codes") or [])
    immunization = IMMUNIZATION_POINTS.get(student.get("immunization_status"), 0)
    return min(100, allergy + condition + immunization)


def observed_risk_score(student):
    clock = db.now()
    start = clock - days(OBSERVED_WINDOW_DAYS)
    student_id = student["id"]
    visits = [v for v in db.health_visits.values()
              if v["student_id"] == student_id
              and v["status"] in ("DISPOSITIONED", "CLOSED")
              and start <= v["arrival_at"] < clock]
    high = [v for v in visits if v.get("disposition") in ("SEND_HOME", "EMS_TRANSPORT")]
    emergency = 0
    for record in db.administration_records.values():
        if record["status"] != "ADMINISTERED":
            continue
        if record.get("protocol_mode") != "STOCK_EMERGENCY":
            continue
        administered_at = record.get("administered_at")
        if administered_at is None or not (start <= administered_at < clock):
            continue
        visit = db.health_visits.get(record["visit_id"])
        if visit is not None and visit["student_id"] == student_id:
            emergency += 1
    total = (VISIT_POINTS * len(visits) + HIGH_DISPOSITION_POINTS * len(high)
             + STOCK_EMERGENCY_POINTS * emergency)
    return min(100, total)


def effective_risk_score(student):
    return max(student.get("intake_risk_score", 0), student.get("observed_risk_score", 0))


def risk_tier(score):
    if score >= TIER_CRITICAL_MIN:
        return "CRITICAL"
    if score >= TIER_ELEVATED_MIN:
        return "ELEVATED"
    return "ROUTINE"


def active_action_plan(student_id):
    candidates = [p for p in db.action_plans.values()
                  if p["student_id"] == student_id and p["status"] == "ACTIVE"]
    if not candidates:
        return None
    candidates.sort(key=lambda p: (p["effective_from"], p["_seq"]))
    return candidates[-1]


def self_carry_authorized(student_id):
    for plan in db.action_plans.values():
        if plan["student_id"] == student_id and plan["status"] == "ACTIVE" \
                and plan.get("self_carry_requested"):
            return True
    return False


def alert_flags(student):
    flags = []
    if student.get("allergy_severity") == "ANAPHYLAXIS":
        flags.append("ALLERGY_ANAPHYLAXIS")
    if student.get("immunization_status") == "NONCOMPLIANT":
        flags.append("IMMUNIZATION_HOLD")
    if active_action_plan(student["id"]) is None:
        flags.append("NO_ACTIVE_PLAN")
    for screening in db.screenings.values():
        if screening["student_id"] == student["id"] and screening["status"] == "REFERRED":
            flags.append("SCREENING_REFERRAL")
            break
    if self_carry_authorized(student["id"]):
        flags.append("SELF_CARRY")
    return sorted(flags)


# ---------------------------------------------------------------------------
# School derived fields
# ---------------------------------------------------------------------------

def credential_weight(nurse):
    credential = nurse.get("credential")
    if credential in CREDENTIAL_WEIGHT:
        return CREDENTIAL_WEIGHT[credential]
    if credential == "HEALTH_AIDE":
        return Decimal("0.30") if nurse.get("delegation_authorized") else Decimal("0.00")
    return Decimal("0.00")


def enrolled_student_count(school_id):
    return len([s for s in db.students.values()
                if s["school_id"] == school_id and s["enrollment_status"] == "ENROLLED"])


def eligible_stock_student_count(school_id):
    total = 0
    for student in db.students.values():
        if student["school_id"] != school_id or student["enrollment_status"] != "ENROLLED":
            continue
        if student.get("allergy_severity") == "ANAPHYLAXIS" \
                or "ASTHMA" in (student.get("chronic_condition_codes") or []):
            total += 1
    return total


def stock_protocol_requirement(school_id):
    eligible = eligible_stock_student_count(school_id)
    base = int(math.ceil(eligible / float(STUDENTS_PER_STOCK_UNIT)))
    if base <= 2:
        surge = 0
    elif base <= 5:
        surge = 1
    else:
        surge = 2
    return eligible, base, surge, base + surge


def contracted_weekly_minutes(school_id):
    total = 0
    for block in school_blocks(school_id):
        if coverage_status(block) in ("SCHEDULED", "ACTIVE"):
            total += duration_minutes(block)
    return total


def delivered_weekly_minutes(school_id):
    total = Decimal("0")
    for block in school_blocks(school_id):
        if coverage_status(block) != "ACTIVE":
            continue
        nurse = db.nurses.get(block["nurse_id"])
        if nurse is None or nurse.get("employment_status") != "ACTIVE":
            continue
        total += Decimal(duration_minutes(block)) * credential_weight(nurse)
    return total


def coverage_ratio(enrolled, weekly_minutes):
    if weekly_minutes is None:
        return None
    weekly = Decimal(str(weekly_minutes))
    if weekly == 0:
        return None
    # students / (minutes / 2100) == students * 2100 / minutes; the single-
    # expression form keeps the division unrounded until the pinned final round.
    return round2(Decimal(enrolled) * Decimal(FULL_TIME_WEEKLY_MINUTES) / weekly)


def lot_days_of_supply(lot):
    avg = AVG_DAILY_UNITS.get(lot["medication_code"])
    if avg is None or avg == 0:
        return round2(Decimal("0"))
    return round2(Decimal(lot["quantity_on_hand"]) / avg)


def school_days_of_supply(school_id, code):
    clock = db.now()
    total = Decimal("0")
    for lot in db.medication_stock_lots.values():
        if lot["school_id"] != school_id or lot["medication_code"] != code:
            continue
        if lot["status"] != "AVAILABLE":
            continue
        if not lot["expiration_date"] > clock:
            continue
        total += lot_days_of_supply(lot)
    return round2(total)


def stock_protocol_units(school_id, code):
    clock = db.now()
    total = 0
    for lot in db.medication_stock_lots.values():
        if lot["school_id"] != school_id or lot["medication_code"] != code:
            continue
        if lot["status"] != "AVAILABLE" or not lot.get("is_stock_protocol"):
            continue
        if not lot["expiration_date"] > clock:
            continue
        total += lot["quantity_on_hand"]
    return total


def stock_protocol_status(school_id, required_stock_units, epi_days, alb_days):
    epi_units = stock_protocol_units(school_id, "EPINEPHRINE")
    alb_units = stock_protocol_units(school_id, "ALBUTEROL")
    if epi_units == 0 or alb_units == 0:
        return "DEPLETED"
    min_days = min(epi_days, alb_days)
    if epi_units < required_stock_units or min_days < DAYS_OF_SUPPLY_READY_MIN:
        return "DEGRADED"
    return "READY"


def coverage_posture(delivered_ratio, protocol_status):
    if delivered_ratio is None or delivered_ratio > POSTURE_LIMITED_MAX:
        base = "UNCOVERED"
    elif delivered_ratio > POSTURE_FULL_MAX:
        base = "LIMITED"
    else:
        base = "FULL"
    if base == "UNCOVERED":
        return "UNCOVERED"
    if base == "FULL" and protocol_status == "DEPLETED":
        return "LIMITED"
    return base


def occupied_cot_count(school_id):
    return len([v for v in db.health_visits.values()
                if v["school_id"] == school_id
                and v["status"] in ("OPEN", "IN_ASSESSMENT", "REOPENED")])


def school_derived(school):
    """Recompute every derived School field in the pinned order:
    counts -> stock requirement -> days of supply -> protocol status ->
    coverage ratios -> posture."""
    school_id = school["id"]
    enrolled = enrolled_student_count(school_id)
    eligible, base, surge, required = stock_protocol_requirement(school_id)
    epi_days = school_days_of_supply(school_id, "EPINEPHRINE")
    alb_days = school_days_of_supply(school_id, "ALBUTEROL")
    protocol_status = stock_protocol_status(school_id, required, epi_days, alb_days)
    contracted = contracted_weekly_minutes(school_id)
    delivered = delivered_weekly_minutes(school_id)
    contracted_ratio = coverage_ratio(enrolled, contracted)
    delivered_ratio = coverage_ratio(enrolled, delivered)
    posture = coverage_posture(delivered_ratio, protocol_status)
    return {
        "enrolled_student_count": enrolled,
        "eligible_stock_student_count": eligible,
        "base_required_units": base,
        "surge_units": surge,
        "required_stock_units": required,
        "contracted_weekly_minutes": contracted,
        "delivered_weekly_minutes": as_float(round2(delivered)),
        "contracted_students_per_nurse_fte": as_float(contracted_ratio),
        "delivered_students_per_nurse_fte": as_float(delivered_ratio),
        "coverage_posture": posture,
        "epinephrine_days_of_supply": as_float(epi_days),
        "albuterol_days_of_supply": as_float(alb_days),
        "stock_protocol_status": protocol_status,
        "occupied_cot_count": occupied_cot_count(school_id),
    }


def school_posture(school):
    return school_derived(school)["coverage_posture"]


# ---------------------------------------------------------------------------
# MedicationAuthorization derived fields
# ---------------------------------------------------------------------------

def authorization_records(auth_id):
    return [r for r in db.administration_records.values()
            if r.get("authorization_id") == auth_id]


def doses_administered_today(auth):
    clock = db.now()
    start = utc_day_start(clock)
    end = start + days(1)
    total = 0
    for record in authorization_records(auth["id"]):
        if record["status"] != "ADMINISTERED":
            continue
        administered_at = record.get("administered_at")
        if administered_at is not None and start <= administered_at < end:
            total += 1
    return total


def last_administered_at(auth):
    stamps = [r["administered_at"] for r in authorization_records(auth["id"])
              if r["status"] == "ADMINISTERED" and r.get("administered_at") is not None]
    if not stamps:
        return None
    return max(stamps)


def in_validity_window(auth, clock=None):
    clock = clock or db.now()
    return auth["valid_from"] <= clock < auth["valid_until"]


def dispensable(auth):
    return (auth["consent_status"] == "CONSENT_GRANTED"
            and auth["clinical_status"] == "VERIFIED"
            and in_validity_window(auth))


# ---------------------------------------------------------------------------
# HealthVisit derived fields
# ---------------------------------------------------------------------------

def pending_administration_count(visit_id):
    return len([r for r in db.administration_records.values()
                if r["visit_id"] == visit_id and r["status"] == "PREPARED"])


def triage_score(visit, student, school):
    base = ACUITY_BASE.get(visit["acuity"], 0)
    complaint = COMPLAINT_POINTS.get(visit["complaint_code"], 0)
    tier = risk_tier(effective_risk_score(student))
    tier_points = RISK_TIER_POINTS.get(tier, 0)
    bonus = 0
    if student.get("allergy_severity") == "ANAPHYLAXIS" \
            and visit["complaint_code"] in ("ILLNESS", "MEDICATION"):
        bonus = ANAPHYLAXIS_BONUS
    uplift = min(RISK_UPLIFT_CAP, tier_points + bonus)
    penalty = COVERAGE_PENALTY.get(school_posture(school), 0)
    return max(0, min(100, base + complaint + uplift + penalty))


# ---------------------------------------------------------------------------
# Stock lot selection
# ---------------------------------------------------------------------------

def select_lot(school_id, code, units, is_stock_protocol):
    clock = db.now()
    candidates = []
    for lot in db.medication_stock_lots.values():
        if lot["school_id"] != school_id:
            continue
        if lot["medication_code"] != code:
            continue
        if lot["status"] != "AVAILABLE":
            continue
        if not lot["expiration_date"] > clock:
            continue
        if lot["quantity_on_hand"] < units:
            continue
        if bool(lot.get("is_stock_protocol")) != bool(is_stock_protocol):
            continue
        candidates.append(lot)
    if not candidates:
        return None
    candidates.sort(key=lambda l: (l["expiration_date"], l["quantity_on_hand"],
                                   l["created_at"], l["_seq"]))
    return candidates[0]


# ---------------------------------------------------------------------------
# Screening classification
# ---------------------------------------------------------------------------

SCREENING_THRESHOLDS = {
    "VISION": (30, 40),
    "HEARING": (20, 30),
    "SCOLIOSIS": (5, 7),
}


def classify_screening(screening_type, result_value):
    pass_max, refer_min = SCREENING_THRESHOLDS[screening_type]
    if result_value <= pass_max:
        return "PASS"
    if result_value >= refer_min:
        return "REFER"
    return "INCONCLUSIVE"


# ---------------------------------------------------------------------------
# Disclosure redaction and package
# ---------------------------------------------------------------------------

def redaction_level(request_row, student):
    if student.get("privacy_hold") and request_row["requester_type"] != "GUARDIAN":
        return "FULL"
    scope = request_row.get("scope") or []
    if request_row["purpose_code"] in ("ENROLLMENT", "RESEARCH"):
        return "PARTIAL"
    if "MEDICATIONS" in scope and request_row["requester_type"] == "AGENCY":
        return "PARTIAL"
    return "NONE"


def package_item_count(request_row, student, level):
    if level == "FULL":
        return 0
    student_id = student["id"]
    visits = [v for v in db.health_visits.values()
              if v["student_id"] == student_id and v["status"] == "CLOSED"]
    meds = [a for a in db.medication_authorizations.values()
            if a["student_id"] == student_id and a["consent_status"] == "CONSENT_GRANTED"]
    screenings = [s for s in db.screenings.values()
                  if s["student_id"] == student_id
                  and s["status"] in ("COMPLETED", "REFERRED", "CLOSED")]
    plans = [p for p in db.action_plans.values()
             if p["student_id"] == student_id
             and p["status"] in ("ACTIVE", "SUPERSEDED", "EXPIRED")]
    visits_n = len(visits)
    meds_n = len(meds)
    screenings_n = len(screenings)
    plans_n = len(plans)
    if level == "PARTIAL":
        visits_n -= len([v for v in visits if v["complaint_code"] == "MENTAL_HEALTH"])
        meds_n -= len([a for a in meds if a.get("is_controlled")])
    scope = request_row.get("scope") or []
    total = 0
    if "VISITS" in scope:
        total += visits_n
    if "MEDICATIONS" in scope:
        total += meds_n
    if "SCREENINGS" in scope:
        total += screenings_n
    if "ACTION_PLANS" in scope:
        total += plans_n
    return total
