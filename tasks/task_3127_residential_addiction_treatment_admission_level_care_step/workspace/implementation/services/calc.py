"""Pure calculation rules from SCAFFOLD.yaml §1.3."""

from decimal import Decimal, ROUND_HALF_UP

from common import level_rank, round_half_up, tier_rank
from db import STORE
from errors import ApiError

# -- asam_level_placement ----------------------------------------------------
WEIGHTS = {
    "withdrawal_risk": 3,
    "biomedical_conditions": 2,
    "emotional_behavioral": 2,
    "readiness_to_change": 1,
    "relapse_potential": 3,
    "recovery_environment": 1,
}
THRESHOLD_2_1 = 18
THRESHOLD_3_1 = 28
THRESHOLD_3_5 = 36
THRESHOLD_3_7 = 44


def weighted_total(dimension_scores):
    total = 0
    for name, weight in WEIGHTS.items():
        total += weight * int(dimension_scores[name])
    return total


def dimension_sum_level(total_score):
    if total_score >= THRESHOLD_3_7:
        return "ASAM_3_7"
    if total_score >= THRESHOLD_3_5:
        return "ASAM_3_5"
    if total_score >= THRESHOLD_3_1:
        return "ASAM_3_1"
    if total_score >= THRESHOLD_2_1:
        return "ASAM_2_1"
    return "ASAM_1_0"


def single_dimension_floor(dimension_scores):
    withdrawal = int(dimension_scores["withdrawal_risk"])
    relapse = int(dimension_scores["relapse_potential"])
    biomedical = int(dimension_scores["biomedical_conditions"])
    emotional = int(dimension_scores["emotional_behavioral"])
    if withdrawal == 4:
        return "ASAM_3_7"
    if withdrawal == 3 or relapse == 4:
        return "ASAM_3_5"
    if relapse == 3 or biomedical == 4:
        return "ASAM_3_1"
    if emotional == 4:
        return "ASAM_2_1"
    return "ASAM_1_0"


def asam_placement(dimension_scores, placement_basis):
    total_score = weighted_total(dimension_scores)
    sum_level = dimension_sum_level(total_score)
    if placement_basis == "HIGHEST_DIMENSION_FLOOR":
        floor_level = single_dimension_floor(dimension_scores)
        recommended = floor_level if level_rank(floor_level) > level_rank(sum_level) else sum_level
    else:
        recommended = sum_level
    return total_score, recommended


# -- step_down_urgency_score -------------------------------------------------
TIME_WEIGHT = 60
COST_UNIT = 8
TARGET_LEVEL_RANK = 1
CLINICAL_STABLE_BONUS = 15
CLINICAL_ACTIVE_BONUS = 5
CLINICAL_COMPLICATED_PENALTY = 20
TERM_FLOOR = 0


def _clinical_pressure(wm_status):
    if wm_status == "MEDICALLY_STABLE":
        return CLINICAL_STABLE_BONUS
    if wm_status == "ACTIVE":
        return CLINICAL_ACTIVE_BONUS
    if wm_status == "COMPLICATED":
        return -CLINICAL_COMPLICATED_PENALTY
    return 0


def _cost_pressure(granted_level):
    return (level_rank(granted_level) - TARGET_LEVEL_RANK) * COST_UNIT


def _granted_days(authorization):
    """The days granted at approval — the denominator of the persisted variant.

    PRD §3.2: "Because the denominator is the granted days alone, every completed
    concurrent review raises this figure." The running authorized_days is extended by
    a concurrent review, so the original grant is carried separately for this rule.
    """
    value = authorization.get("granted_days")
    if value is None:
        value = authorization.get("authorized_days")
    return int(value or 0)


def urgency_variant_a(authorization, wm_status):
    authorized_days = _granted_days(authorization)
    days_used = int(authorization.get("days_used") or 0)
    if authorized_days == 0:
        time_pressure = Decimal(0)
    else:
        time_pressure = (Decimal(days_used) / Decimal(authorized_days)) * Decimal(TIME_WEIGHT)
    raw = time_pressure + Decimal(_cost_pressure(authorization.get("granted_level"))) + Decimal(_clinical_pressure(wm_status))
    if raw < TERM_FLOOR:
        raw = Decimal(TERM_FLOOR)
    return float(round_half_up(raw, 1))


def urgency_variant_b(authorization, wm_status, review_interval_days):
    # PRD §3.2 computed the extended denominator "as `authorized_days` plus
    # `concurrent_review_count` multiplied by the payer's
    # `concurrent_review_interval_days`" against the 14 + 1 * 7 = 21 worked example,
    # which is the days *granted at approval* plus the reviews — so the base is the
    # original grant, not the running total a review has already widened.
    authorized_days = _granted_days(authorization)
    days_used = int(authorization.get("days_used") or 0)
    reviews = int(authorization.get("concurrent_review_count") or 0)
    extended_days = authorized_days + reviews * int(review_interval_days or 0)
    if extended_days == 0:
        time_pressure = Decimal(0)
    else:
        time_pressure = (Decimal(days_used) / Decimal(extended_days)) * Decimal(TIME_WEIGHT)
    raw = time_pressure + Decimal(_cost_pressure(authorization.get("granted_level"))) + Decimal(_clinical_pressure(wm_status))
    if raw < TERM_FLOOR:
        raw = Decimal(TERM_FLOOR)
    return float(round_half_up(raw, 1))


# -- tiered_compliance_risk_deduction ---------------------------------------
EXPIRED_UNIT = 12
MISSING_UNIT = 5
AGED_CAP = 6
AGED_UNIT = 2
MODERATE_MIN = 10
HI_MIN = 30
PREMIUM_MIN = 60
POSTURE_RESTRICTED_MIN = 45
POSTURE_FROZEN_MIN = 60
DAYS_PER_AGED_UNIT = 30

ACCREDITATION_CLASSES = ["ACCREDITATION_BODY", "STATE_LICENSE", "RECOVERY_HOUSE"]


def compliance_risk_points(facility, now):
    rows = STORE.where("Accreditation", lambda r: r.get("facility_id") == facility["id"])
    expired_rows = [r for r in rows if r.get("status") == "GRANTED" and _at_or_before(r.get("expires_at"), now)]
    expired_count = len(expired_rows)

    granted_classes = {r.get("accreditation_class") for r in rows if r.get("status") == "GRANTED"}
    missing_class_count = sum(1 for cls in ACCREDITATION_CLASSES if cls not in granted_classes)

    longest_days_since_expiry = 0
    if expired_count:
        from common import parse_iso, days_between_floor

        spans = []
        for row in expired_rows:
            expiry = parse_iso(row.get("expires_at"), "expires_at")
            spans.append(days_between_floor(now, expiry))
        longest_days_since_expiry = max(spans) if spans else 0

    aged_units = min(AGED_CAP, max(0, longest_days_since_expiry) // DAYS_PER_AGED_UNIT)
    aged_points = aged_units * AGED_UNIT

    raw = expired_count * EXPIRED_UNIT + missing_class_count * MISSING_UNIT + aged_points

    if raw > PREMIUM_MIN:
        multiplier = Decimal("1.5")
    elif raw > HI_MIN:
        multiplier = Decimal("1.25")
    else:
        multiplier = Decimal("1.0")

    return int(round_half_up(Decimal(raw) * multiplier, 0))


def _at_or_before(instant_str, now):
    if instant_str is None:
        return False
    from common import parse_iso

    return parse_iso(instant_str, "expires_at") <= now


def posture_from_points(points):
    if points >= POSTURE_FROZEN_MIN:
        return "FROZEN"
    if points >= POSTURE_RESTRICTED_MIN:
        return "RESTRICTED"
    return "OPEN"


def accepting_admissions(facility):
    if facility.get("facility_posture") == "FROZEN":
        return False
    if not facility.get("licensed"):
        return False
    return True


# -- medical_clearance_window_remaining --------------------------------------
CLEARANCE_VALIDITY_DAYS = 7


def clearance_windows(expires_at, now):
    from common import hours_exact

    exact = hours_exact(expires_at, now)
    step1 = exact if exact > 0 else Decimal(0)
    step2 = round_half_up(step1, 0)
    hours_remaining = int(step2)
    days_remaining = int(round_half_up(step2 / Decimal(24), 0))
    return hours_remaining, days_remaining


# -- step_down_coverage_resolution ------------------------------------------
BASE_DAILY_CENTS = {
    "ASAM_3_7": 4200,
    "ASAM_3_5": 3600,
    "ASAM_3_1": 2800,
    "ASAM_2_1": 1400,
    "ASAM_1_0": 600,
}


def next_covered_level(payer, granted_level, exclude):
    """First entry of the payer's coverage map below granted_level that is not
    already funded (exclude holds levels already granted/used)."""
    coverage = payer.get("step_down_coverage_map") or {}
    entries = coverage.get(granted_level) or []
    granted_rank = level_rank(granted_level)
    for candidate in entries:
        if level_rank(candidate) < granted_rank and candidate not in exclude:
            return candidate
    return None


def step_down_savings_cents(payer, granted_level, target_level, points):
    gross_daily = BASE_DAILY_CENTS[target_level]
    net_daily = int(round_half_up(Decimal(gross_daily) * (Decimal(1) - Decimal(points) / Decimal(100)), 0))
    return int(round_half_up(Decimal(BASE_DAILY_CENTS[granted_level] - net_daily), 0))


# -- authorization_days_bank -------------------------------------------------
NON_TERMINAL_POSTURES = ["APPROVED", "CONCURRENT_REVIEW_DUE", "EXTENDED", "STEP_DOWN_REQUIRED"]


def whole_days_in_intersection(start, end, span_start, span_end):
    """Count whole days inside [start, end) that also fall inside
    [span_start, span_end); opening inclusive, closing exclusive."""
    lo = start if start > span_start else span_start
    hi = end if end < span_end else span_end
    if hi <= lo:
        return 0
    seconds = (hi - lo).total_seconds()
    return int(seconds // 86400)


# -- weekly_session_requirement ---------------------------------------------
REQUIRED_SESSIONS = {
    "ASAM_1_0": 5,
    "ASAM_2_1": 5,
    "ASAM_3_1": 10,
    "ASAM_3_5": 14,
    "ASAM_3_7": 14,
}
TREATMENT_WEEK_DAYS = 7


def required_sessions(assigned_level):
    return REQUIRED_SESSIONS.get(assigned_level, 5)


def current_treatment_week(admitted_at, now):
    if admitted_at is None:
        return None, None
    from datetime import timedelta

    elapsed = (now - admitted_at).total_seconds()
    index = int(elapsed // (TREATMENT_WEEK_DAYS * 86400))
    if index < 0:
        index = 0
    start = admitted_at + timedelta(days=TREATMENT_WEEK_DAYS * index)
    end = start + timedelta(days=TREATMENT_WEEK_DAYS)
    return start, end


def curriculum_status(episode, attendance_rows, now):
    assigned = episode.get("assigned_level")
    requirement = required_sessions(assigned) if assigned else REQUIRED_SESSIONS["ASAM_1_0"]
    start, end = current_treatment_week(_parse(episode.get("admitted_at")), now)
    attended = 0
    if start is not None and end is not None:
        for row in attendance_rows:
            if row.get("status") != "ATTENDED":
                continue
            scheduled = _parse(row.get("scheduled_at"))
            if scheduled is None:
                continue
            if start <= scheduled < end:
                attended += 1
    compliant = attended >= requirement
    percent = (100 * attended) // requirement if requirement else 0
    return requirement, attended, compliant, percent


def _parse(value):
    if value is None:
        return None
    from common import parse_iso

    return parse_iso(value, "datetime")


# -- attendance_ledger -------------------------------------------------------
SERVICE_BASE_CENTS = {
    "ASAM_3_7": 210,
    "ASAM_3_5": 180,
    "ASAM_3_1": 150,
    "ASAM_2_1": 110,
    "ASAM_1_0": 80,
}
MIN_BILLABLE_MINUTES = 60
MAX_SESSION_CENTS = 900


def session_billing_amount(level_of_care, duration_minutes):
    base = SERVICE_BASE_CENTS.get(level_of_care, 0)
    units = max(1, int(duration_minutes) // MIN_BILLABLE_MINUTES)
    return min(MAX_SESSION_CENTS, base * units)


# -- discharge_readiness_gate ------------------------------------------------
MIN_CREDENTIAL_TIER_FOR_DISCHARGE = "TIER_3_LICENSED"


def open_housing_capacity(facility):
    rows = STORE.where("RecoveryHousing", lambda r: r.get("facility_id") == facility["id"] and r.get("status") == "OPEN")
    return sum(int(r.get("capacity_beds") or 0) for r in rows)


def committed_bed_nights(facility):
    return sum(1 for b in STORE.where("Bed", lambda r: r.get("facility_id") == facility["id"]) if b.get("status") == "OCCUPIED")


def episode_credential_ok(clinician, facility, floor_tier):
    if clinician is None:
        return False
    return tier_rank(clinician.get("credential_tier")) >= tier_rank(floor_tier)


# -- ranked_housing_selection -----------------------------------------------
AFFORDABILITY_TARGET_CENTS = 1000
AFFORDABILITY_CEILING_CENTS = 2000


def ranked_housing_pool(facility, plan, active_plans_by_house):
    pool = []
    for house in STORE.where("RecoveryHousing", lambda r: r.get("facility_id") == facility["id"]):
        if house.get("status") != "OPEN":
            continue
        rate = int(house.get("day_rate_cents") or 0)
        if rate > AFFORDABILITY_CEILING_CENTS:
            continue
        if plan.get("wants_recovery_only_house", True) and not house.get("licensed"):
            continue
        if plan.get("shelter_class") == "RESIDENTIAL" and not house.get("licensed"):
            continue
        used = active_plans_by_house.get(house["id"], 0)
        if int(house.get("capacity_beds") or 0) - used <= 0:
            continue
        pool.append(house)
    pool.sort(key=lambda h: (abs(int(h.get("day_rate_cents") or 0) - AFFORDABILITY_TARGET_CENTS),
                             int(h.get("proximity_rank") or 0),
                             h.get("house_name") or ""))
    return pool


def overlapping_active_count(house_id, window_start, window_end, exclude_plan_id=None):
    from common import parse_iso

    count = 0
    for plan in STORE.where("ContinuingCarePlan", lambda r: r.get("housing_id") == house_id and r.get("status") == "ACTIVE"):
        if exclude_plan_id is not None and plan["id"] == exclude_plan_id:
            continue
        start = parse_iso(plan.get("housing_window_start"), "housing_window_start")
        end = parse_iso(plan.get("housing_window_end"), "housing_window_end")
        if start < window_end and window_start < end:
            count += 1
    return count


# -- alumni_contact_schedule -------------------------------------------------
MIN_INTERVAL_DAYS = 1
MAX_CONTACTS = 24


def alumni_schedule(discharged_at, interval_days, contacts_required):
    from datetime import timedelta

    rows = []
    for attempt in range(1, contacts_required + 1):
        scheduled = discharged_at + timedelta(days=attempt * interval_days)
        if scheduled > discharged_at:
            rows.append((attempt, scheduled))
    return rows