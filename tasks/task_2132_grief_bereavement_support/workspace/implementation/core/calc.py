"""Calculation rules: all rounding is half-up, at the points the PRD pins."""

from decimal import Decimal, ROUND_HALF_UP

from .shape import WEEKDAY_INDEX


def dec(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def rhu(value, places=0):
    """Round half up (away from zero on the .5 boundary) to `places` decimals."""
    quant = Decimal(1).scaleb(-places)
    return dec(value).quantize(quant, rounding=ROUND_HALF_UP)


def money(value):
    """Whole cents, rounded half up."""
    return int(rhu(value, 0))


def num(value, places):
    """Round half up to `places` decimals and return a JSON-friendly float."""
    return float(rhu(value, places))


# ---------------------------------------------------------------- referrals
URGENT_MAX_DAYS = 30
PRIORITY_MAX_DAYS = 180


def screening_band(days_since_death):
    if days_since_death <= URGENT_MAX_DAYS:
        return "URGENT"
    if days_since_death <= PRIORITY_MAX_DAYS:
        return "PRIORITY"
    return "ROUTINE"


# -------------------------------------------------------------- assessments
MAX_RAW = 80
GRIEF_MAX = 40
ISOLATION_MAX = 20
FUNCTION_MAX = 20
W_GRIEF = Decimal("0.5")
W_ISOLATION = Decimal("0.2")
W_FUNCTION = Decimal("0.3")
SUICIDALITY_FLOOR = Decimal("85.00")
RISK_HIGH_MIN = Decimal("70.00")
RISK_MODERATE_MIN = Decimal("40.00")
CADENCE = {"LOW": 90, "MODERATE": 60, "HIGH": 30}


def normalized_score(raw_total):
    return num(dec(raw_total) / dec(MAX_RAW) * dec(100), 2)


def composite_need_index(grief, isolation, functional, suicidality_flag):
    weighted = (W_GRIEF * (dec(grief) / dec(GRIEF_MAX))
                + W_ISOLATION * (dec(isolation) / dec(ISOLATION_MAX))
                + W_FUNCTION * (dec(functional) / dec(FUNCTION_MAX)))
    composite = rhu(dec(100) * weighted, 2)
    if suicidality_flag:
        if composite < SUICIDALITY_FLOOR:
            composite = SUICIDALITY_FLOOR
    return float(composite)


def risk_tier(composite):
    value = dec(composite)
    if value >= RISK_HIGH_MIN:
        return "HIGH"
    if value >= RISK_MODERATE_MIN:
        return "MODERATE"
    return "LOW"


def cadence_days(tier):
    return CADENCE[tier]


def escalate_tier(tier):
    if tier == "LOW":
        return "MODERATE"
    if tier == "MODERATE":
        return "HIGH"
    return "HIGH"


# --------------------------------------------------------- outcome summary
RTM_FACTOR = Decimal("0.15")
PROGRAM_MEAN = Decimal("50.0")
EXPECTED_SESSIONS = 8
ATT_BASE = Decimal("0.6")
ATT_SLOPE = Decimal("0.4")


def raw_delta(latest_score, baseline_score):
    return num(dec(latest_score) - dec(baseline_score), 2)


def rtm_correction(baseline_score):
    return num(RTM_FACTOR * (dec(baseline_score) - PROGRAM_MEAN), 2)


def attendance_ratio_capped(sessions_attended_total):
    ratio = dec(sessions_attended_total) / dec(EXPECTED_SESSIONS)
    if ratio > 1:
        ratio = Decimal(1)
    return float(rhu(ratio, 4))


def attendance_adjusted_delta(raw, correction, ratio):
    weight = ATT_BASE + ATT_SLOPE * dec(ratio)
    return num((dec(raw) - dec(correction)) * weight, 2)


# ------------------------------------------------------------ programme cost
TIER1_MAX_CENTS = 250000
TIER2_MAX_CENTS = 750000
TIER1_BPS = 1200
TIER2_BPS = 1000
TIER3_BPS = 800


def program_cost(direct_cost_cents):
    """Pinned three-step rule: tier from direct cost alone, fee, then total."""
    if direct_cost_cents < TIER1_MAX_CENTS:
        rate = TIER1_BPS
    elif direct_cost_cents < TIER2_MAX_CENTS:
        rate = TIER2_BPS
    else:
        rate = TIER3_BPS
    admin_fee = money(dec(direct_cost_cents) * dec(rate) / dec(10000))
    return admin_fee, direct_cost_cents + admin_fee


# --------------------------------------------------------- counselling queue
URGENCY_WEIGHT = {"ROUTINE": Decimal(10), "PRIORITY": Decimal(25), "URGENT": Decimal(45)}
NEED_FACTOR = Decimal("0.35")
NEED_CAP = Decimal("35.0")
WAIT_POINTS_PER_DAY = Decimal("0.5")
WAIT_CAP = Decimal("20.0")
REENTRY_POINTS = Decimal(5)
REENTRY_CAP = Decimal(10)


def queue_priority(urgency, composite_need_index_value, wait_days, reentry_count):
    urgency_weight = URGENCY_WEIGHT[urgency]
    need = dec(composite_need_index_value) * NEED_FACTOR
    if need > NEED_CAP:
        need = NEED_CAP
    wait = dec(wait_days) * WAIT_POINTS_PER_DAY
    if wait > WAIT_CAP:
        wait = WAIT_CAP
    reentry = REENTRY_POINTS * dec(reentry_count)
    if reentry > REENTRY_CAP:
        reentry = REENTRY_CAP
    return num(urgency_weight + need + wait + reentry, 2)


# ------------------------------------------------------------- match scoring
ENDORSEMENT_WEIGHT = Decimal(40)
TRAINING_WEIGHT = Decimal(30)
HEADROOM_WEIGHT = Decimal(30)
REQUIRED_TRAINING_HOURS = Decimal(16)


def match_score(endorsed, training_hours, active_match_count, max_concurrent_matches):
    endorsement = ENDORSEMENT_WEIGHT * (Decimal(1) if endorsed else Decimal(0))
    ratio = dec(training_hours) / REQUIRED_TRAINING_HOURS
    if ratio > 1:
        ratio = Decimal(1)
    training = TRAINING_WEIGHT * ratio
    headroom = HEADROOM_WEIGHT * (Decimal(1) - dec(active_match_count) / dec(max_concurrent_matches))
    return num(endorsement + training + headroom, 2)


# ------------------------------------------------------------- attendance
def attendance_ratio(sessions_attended, sessions_total):
    return num(dec(sessions_attended) / dec(sessions_total), 4)


# ---------------------------------------------------------- occupation clash
def minutes_collide(a_start, a_duration, b_start, b_duration, buffer_minutes):
    a_end = a_start + a_duration
    b_end = b_start + b_duration
    return (a_start - buffer_minutes) <= b_end and (b_start - buffer_minutes) <= a_end


def weekday_name(d):
    for name, index in WEEKDAY_INDEX.items():
        if index == d.weekday():
            return name
    return None


def dates_intersect_cohort_event(cohort_start, cohort_end, cohort_weekday, event_date):
    if not (cohort_start <= event_date <= cohort_end):
        return False
    return weekday_name(event_date) == cohort_weekday


def dates_intersect_cohorts(a_start, a_end, a_weekday, b_start, b_end, b_weekday):
    if a_weekday != b_weekday:
        return False
    return a_start <= b_end and b_start <= a_end
