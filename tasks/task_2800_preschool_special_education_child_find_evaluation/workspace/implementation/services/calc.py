"""Pure calculation rules (PRD section 3, SCAFFOLD section 1.3).

All arithmetic is exact decimal; binary float is never used for a rule.
"""
from datetime import date, timedelta
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP

# --- constants -------------------------------------------------------------
AGE_MIN_MONTHS = 33
AGE_MAX_MONTHS = 71
PART_C_PATHWAY_MAX_AGE_MONTHS = 35
EVAL_WINDOW_DAYS = 60
KINDERGARTEN_AGE_YEARS = 5
DELAY_QUALIFY_PCT = Decimal("25.0")
PLAY_BASED_CONFIDENCE_WEIGHT = Decimal("0.9")
REQUIRED_DOMAIN_COUNT = 5
SEVERE_SINGLE_DOMAIN_PCT = Decimal("33.0")
MULTI_DOMAIN_MIN_COUNT = 2
BASE_MINUTES_PER_QUALIFYING_DOMAIN = Decimal("50")
SEVERITY_MULT_MODERATE = Decimal("1.0")
SEVERITY_MULT_SIGNIFICANT = Decimal("1.15")
SEVERITY_MULT_PROFOUND = Decimal("1.4")
SEVERITY_BAND_SIGNIFICANT_PCT = Decimal("33.0")
SEVERITY_BAND_PROFOUND_PCT = Decimal("50.0")
TRAVEL_TIER1_MAX_DIRECT_MINUTES = 300
TRAVEL_TIER1_PCT = Decimal("0.05")
TRAVEL_TIER2_MAX_DIRECT_MINUTES = 600
TRAVEL_TIER2_PCT = Decimal("0.10")
TRAVEL_TIER3_PCT = Decimal("0.15")
TRAVEL_PER_EXTRA_SITE_MINUTES = Decimal("15")
NEAR_CAPACITY_UTILIZATION = Decimal("0.80")
AT_RISK_DAYS = 10
MAX_REVISION_ROUNDS = 2
KINDERGARTEN_CONFERENCE_LEAD_DAYS = 90
EVALUATOR_BUFFER_MINUTES = 30
DISTRICT_CENTER = "DISTRICT_CENTER"

CASE_NON_TERMINAL_STATUSES = (
    "PLANNED",
    "IN_PROGRESS",
    "DOMAINS_COMPLETE",
    "REPORT_DRAFTED",
    "REVISIONS_REQUESTED",
)
COUNTED_PLAN_STATES_PROJECTED = ("DRAFT", "PENDING_PARENT_CONSENT", "ACTIVE")
COUNTED_PLAN_STATES_COMMITTED = ("PENDING_PARENT_CONSENT", "ACTIVE")
SEAT_HOLDING_PLAN_STATES = ("PENDING_PARENT_CONSENT", "ACTIVE")
BOOKED_SLOT_STATES = ("BOOKED", "ATTENDED", "NO_SHOW")

DOMAIN_DISCIPLINE_MAP = {
    "COMMUNICATION": ("SLP", "ECSE_TEACHER"),
    "PHYSICAL_MOTOR": ("OT", "PT"),
    "COGNITIVE": ("SCHOOL_PSYCHOLOGIST", "ECSE_TEACHER"),
    "SOCIAL_EMOTIONAL": ("SOCIAL_WORKER", "SCHOOL_PSYCHOLOGIST"),
}
CHAIR_ELIGIBLE_DISCIPLINES = ("SCHOOL_PSYCHOLOGIST", "ECSE_TEACHER")

VARIANT_STRICT = "STANDARDIZED_STRICT"
VARIANT_INCLUSIVE = "PLAY_BASED_INCLUSIVE"

METHOD_WEIGHTS = {
    VARIANT_STRICT: {"STANDARDIZED": Decimal("1.0")},
    VARIANT_INCLUSIVE: {
        "STANDARDIZED": Decimal("1.0"),
        "PLAY_BASED": PLAY_BASED_CONFIDENCE_WEIGHT,
        "OBSERVATION": PLAY_BASED_CONFIDENCE_WEIGHT,
    },
}


# --- primitives ------------------------------------------------------------
def whole_months(d0, d1):
    months = (d1.year - d0.year) * 12 + (d1.month - d0.month)
    if d1.day < d0.day:
        months -= 1
    return months


def add_years(value, years):
    if value.month == 2 and value.day == 29:
        return date(value.year + years, 3, 1)
    return date(value.year + years, value.month, value.day)


def round_half_up(value, places):
    quantum = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(quantum, rounding=ROUND_HALF_UP)


def ceil5(value):
    ratio = Decimal(value) / Decimal(5)
    return int(ratio.to_integral_value(rounding=ROUND_CEILING)) * 5


def as_number(value):
    """Render an exact decimal as a JSON number without float drift."""
    if value is None:
        return None
    return float(value)


# --- child -----------------------------------------------------------------
def third_birthday(dob):
    return add_years(dob, 3)


def kindergarten_eligibility_date(dob):
    fifth = add_years(dob, KINDERGARTEN_AGE_YEARS)
    cutoff = date(fifth.year, 9, 1)
    if fifth <= cutoff:
        return cutoff
    return date(fifth.year + 1, 9, 1)


# --- referral --------------------------------------------------------------
def referral_age_and_pathway(dob, received_at, part_c_enrolled):
    age_months = whole_months(dob, received_at.date())
    if age_months < AGE_MIN_MONTHS or age_months > AGE_MAX_MONTHS:
        pathway = "AGE_INELIGIBLE"
    elif part_c_enrolled and age_months <= PART_C_PATHWAY_MAX_AGE_MONTHS:
        pathway = "PART_C_TRANSITION_DEADLINE"
    else:
        pathway = "STANDARD_60_DAY"
    return age_months, pathway


def consent_anchored_due_date(consent_granted_at):
    if consent_granted_at is None:
        return None
    return consent_granted_at.date() + timedelta(days=EVAL_WINDOW_DAYS)


def receipt_anchored_due_date(received_at):
    if received_at is None:
        return None
    return received_at.date() + timedelta(days=EVAL_WINDOW_DAYS)


def evaluation_due_date(consent_status, consent_granted_at, pathway, child_third_birthday):
    """PINNED variant: CONSENT_ANCHORED."""
    if consent_status != "GRANTED" or consent_granted_at is None:
        return None
    anchored = consent_anchored_due_date(consent_granted_at)
    if pathway == "PART_C_TRANSITION_DEADLINE" and child_third_birthday is not None:
        return min(anchored, child_third_birthday)
    return anchored


# --- domain assessment ----------------------------------------------------
def pinned_variant(assessment_protocol):
    return VARIANT_STRICT if assessment_protocol == "STANDARDIZED" else VARIANT_INCLUSIVE


def method_weight(variant, method):
    return METHOD_WEIGHTS[variant].get(method)


def percent_delay(chronological_age_months, age_equivalent_months):
    if not chronological_age_months:
        return Decimal("0.0")
    raw = (
        Decimal(100)
        * (Decimal(chronological_age_months) - Decimal(age_equivalent_months))
        / Decimal(chronological_age_months)
    )
    return round_half_up(raw, 1)


def weighted_delay(variant, method, pct_delay):
    weight = method_weight(variant, method)
    if weight is None or pct_delay is None:
        return None
    return round_half_up(Decimal(pct_delay) * weight, 1)


def enters_variant(variant, method):
    return method_weight(variant, method) is not None


# --- composite profile ----------------------------------------------------
def severity_multiplier(pct):
    if pct >= SEVERITY_BAND_PROFOUND_PCT:
        return SEVERITY_MULT_PROFOUND
    if pct >= SEVERITY_BAND_SIGNIFICANT_PCT:
        return SEVERITY_MULT_SIGNIFICANT
    return SEVERITY_MULT_MODERATE


def composite_profile(completed_assessments, variant):
    """completed_assessments: rows with status COMPLETED for one case.

    Returns dict with the aggregates of a single variant plus both
    minute-rounding orders.
    """
    completed_domains = set(a["domain"] for a in completed_assessments)
    completed_domain_count = len(completed_domains)

    entering = [a for a in completed_assessments if enters_variant(variant, a["method"])]
    weighted = {}
    for row in entering:
        value = weighted_delay(variant, row["method"], row["percent_delay"])
        weighted[row["id"]] = value

    qualifying_rows = [
        row
        for row in entering
        if weighted[row["id"]] is not None and weighted[row["id"]] >= DELAY_QUALIFY_PCT
    ]
    qualifying_domain_count = len(set(row["domain"] for row in qualifying_rows))

    max_weighted = None
    for row in entering:
        value = weighted[row["id"]]
        if value is None:
            continue
        if max_weighted is None or value > max_weighted:
            max_weighted = value

    if completed_domain_count < REQUIRED_DOMAIN_COUNT:
        recommendation = "INDETERMINATE"
    elif (
        max_weighted is not None and max_weighted >= SEVERE_SINGLE_DOMAIN_PCT
    ) or qualifying_domain_count >= MULTI_DOMAIN_MIN_COUNT:
        recommendation = "ELIGIBLE_RECOMMENDED"
    else:
        recommendation = "NOT_ELIGIBLE_RECOMMENDED"

    # Representative per distinct qualifying domain: greater weighted delay,
    # tie broken by earlier created_at.
    representative = {}
    for row in qualifying_rows:
        current = representative.get(row["domain"])
        value = weighted[row["id"]]
        if current is None:
            representative[row["domain"]] = (value, row)
            continue
        if value > current[0]:
            representative[row["domain"]] = (value, row)
        elif value == current[0] and (row["created_at"], row["_seq"]) < (
            current[1]["created_at"],
            current[1]["_seq"],
        ):
            representative[row["domain"]] = (value, row)

    per_line_total = 0
    raw_total = Decimal(0)
    for value, _row in representative.values():
        mult = severity_multiplier(value)
        raw = BASE_MINUTES_PER_QUALIFYING_DOMAIN * mult
        raw_total += raw
        per_line_total += ceil5(raw)

    return {
        "completed_domain_count": completed_domain_count,
        "qualifying_domain_count": qualifying_domain_count,
        "max_weighted_percent_delay": max_weighted,
        "composite_eligibility_recommendation": recommendation,
        "per_line_rounded_minutes": per_line_total,
        "sum_then_rounded_minutes": ceil5(raw_total) if representative else 0,
    }


# --- provider capacity ----------------------------------------------------
def travel_tier_pct(direct_minutes):
    if direct_minutes <= TRAVEL_TIER1_MAX_DIRECT_MINUTES:
        return TRAVEL_TIER1_PCT
    if direct_minutes <= TRAVEL_TIER2_MAX_DIRECT_MINUTES:
        return TRAVEL_TIER2_PCT
    return TRAVEL_TIER3_PCT


def provider_minutes(lines):
    """lines: iterable of in-scope STAFFED service line rows."""
    direct = 0
    sites = set()
    for line in lines:
        if line["delivery_model"] == "DIRECT":
            direct += line["weekly_minutes"]
        sites.add(line.get("delivery_site_id") or DISTRICT_CENTER)
    tier_pct = travel_tier_pct(direct)
    extra_sites = max(0, len(sites) - 1)
    travel = ceil5(Decimal(direct) * tier_pct + Decimal(extra_sites) * TRAVEL_PER_EXTRA_SITE_MINUTES)
    return {
        "direct_weekly_service_minutes": direct,
        "travel_overhead_minutes": travel,
        "assigned_weekly_service_minutes": direct + travel,
        "travel_tier_pct": tier_pct,
        "distinct_site_count": len(sites),
    }


def service_capacity_posture(assigned, maximum):
    if assigned >= maximum:
        return "AT_CAPACITY"
    if maximum > 0 and (Decimal(assigned) / Decimal(maximum)) >= NEAR_CAPACITY_UTILIZATION:
        return "NEAR_CAPACITY"
    return "OPEN"


def utilization(assigned, maximum):
    if maximum <= 0:
        return Decimal(0)
    return Decimal(assigned) / Decimal(maximum)


def evaluation_intake_posture(count, maximum):
    return "AT_CAPACITY" if count >= maximum else "OPEN"


# --- screening -------------------------------------------------------------
def window_minutes(start, end):
    return int((end - start).total_seconds() // 60)


def effective_slot_capacity(slot_capacity, slot_length_minutes, start, end):
    return min(slot_capacity, window_minutes(start, end) // slot_length_minutes)


# --- timeline --------------------------------------------------------------
def timeline_compliance(status, due_date, current_date, determined_date):
    if status == "CANCELLED":
        return "ON_TIME"
    if status == "ELIGIBILITY_DETERMINED":
        if due_date is None or determined_date is None:
            return "ON_TIME"
        return "ON_TIME" if determined_date <= due_date else "OVERDUE"
    if due_date is None:
        return "ON_TIME"
    days_remaining = (due_date - current_date).days
    if days_remaining < 0:
        return "OVERDUE"
    if days_remaining <= AT_RISK_DAYS:
        return "AT_RISK"
    return "ON_TIME"


def days_remaining(due_date, current_date):
    if due_date is None:
        return None
    return (due_date - current_date).days
