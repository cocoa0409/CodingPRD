"""The eleven calculations of PRD 3 / SCAFFOLD calculations[].

Money is an integer count of cents; every ratio is integer basis points floored
toward zero (PRD 2.5). The only half-up rounding in the system is the per-entry
savings match (PRD 3.8).
"""

from decimal import Decimal, ROUND_HALF_UP

import store

# ------------------------------------------------------------------- constants
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"
NOTIFICATION_DUE_HOURS = 24
PENDING_SCREENING_TTL_HOURS = 72
MEDIATION_COOLDOWN_HOURS = 72
AFTERCARE_PLAN_HOURS = 72
AFTERCARE_CONTACTS_REQUIRED = 3
MAX_MEDIATION_ROUNDS = 3
MAX_EXTENSIONS = 2
CASE_CLOSE_LAG_HOURS = 168
NOON_CUTOFF_UTC_HOUR = 12

DECAY_PCT_PER_WEEK = 10
ELEVATED_THRESHOLD = 30
CRITICAL_THRESHOLD = 60
INDICATOR_WEIGHTS = {
    "THIRD_PARTY_CONTROL": 30,
    "QUOTA_DEBT": 25,
    "COMMERCIAL_SEX": 40,
    "DOCUMENT_WITHHELD": 20,
    "RECRUITER_PRESENT": 15,
    "CURFEW_ENFORCED": 10,
}
INDICATOR_CODES = tuple(INDICATOR_WEIGHTS.keys())
BASIC_NEEDS_CODES = ("FOOD", "HYGIENE_KIT", "CLOTHING", "TRANSIT_PASS", "MEDICAL_REFERRAL")
ENGAGEMENT_STAGES = ("FIRST_CONTACT", "RAPPORT_BUILDING", "SERVICE_OFFER", "TRUST_ESTABLISHED")

RESTRICTED_UTILIZATION_BP = 9000
FROZEN_OVERDUE_COUNT = 2
RESTRICTED_PRIORITY_FLOOR = 60

ADULT_AGE = 18
AGE_WEIGHT = 4
RISK_CAP = 40
ENGAGEMENT_CAP = 20
ENGAGEMENT_STEP = 5
EXPOSURE_BASE = 15
CRITICAL_BUMP = 10

MATCH_CAP_CENTS = 50000
DAYS_PER_SAVINGS_MONTH = 30
HAIRCUT_RATIO_BP = 7500
NOTICE_LEAD_DAYS = 30

ADOPTION_RATIO_BP = 5000
ADOPTION_MIN_SUPPORT = 2

BED_HOLDING_ADMISSION_STATUSES = ("ACTIVE", "EXTENDED", "DISCHARGE_SCHEDULED")
NON_TERMINAL_ADMISSION_STATUSES = (
    "PENDING_SCREENING",
    "WAITLISTED",
    "ACTIVE",
    "EXTENDED",
    "DISCHARGE_SCHEDULED",
)
OPEN_NOTIFICATION_STATUSES = ("PENDING", "ATTEMPTED", "OVERDUE")
RESOLVED_NOTIFICATION_STATUSES = ("CONTACTED", "WAIVED", "LAW_ENFORCEMENT_REPORTED")
OPEN_TENANCY_STATUSES = ("PLACED", "NOTICE_GIVEN")


def floor_div(numerator, denominator):
    """Division truncated toward zero (all operands here are non-negative)."""
    if denominator == 0:
        return 0
    return numerator // denominator


def round_half_up(numerator, denominator):
    """Whole cents, rounded half up (PRD 3.8)."""
    return int(
        (Decimal(numerator) / Decimal(denominator)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    )


# ------------------------------------------------------- 1. youth_age_years
def age_years(youth, clock=None):
    """PRD 2.5: whole years from date_of_birth to the logical clock; the birthday
    itself counts as the new age because the month-day comparison is inclusive."""
    clock = clock or store.now()
    dob = youth["date_of_birth"]
    had_birthday = (clock.month, clock.day) >= (dob.month, dob.day)
    return clock.year - dob.year - (0 if had_birthday else 1)


# --------------------------------------------- 2. admission_billable_nights
def projected_billable_nights(admitted_at, planned_discharge_at):
    """Forward-looking figure: pure calendar arithmetic, clock times ignored."""
    if admitted_at is None or planned_discharge_at is None:
        return None
    return store.day_span(admitted_at, planned_discharge_at)


def final_billable_nights(admitted_at, discharged_at):
    """Chronological-actual figure: plus one night when the discharge hour is >= 12."""
    base = store.day_span(admitted_at, discharged_at)
    if discharged_at.hour >= NOON_CUTOFF_UTC_HOUR:
        base += 1
    return base


# ------------------------------------------------- 3. trafficking_risk_score
def raw_indicator_value(codes):
    return sum(INDICATOR_WEIGHTS[c] for c in set(codes))


def screening_score(codes):
    """Undecayed snapshot of exactly one indicator set, capped at 100."""
    return min(100, raw_indicator_value(codes))


def tier_for(score):
    if score >= CRITICAL_THRESHOLD:
        return "CRITICAL"
    if score >= ELEVATED_THRESHOLD:
        return "ELEVATED"
    return "LOW"


def outreach_history_score(youth_id, clock=None):
    """Decaying history score: per-contact contribution floored BEFORE summation."""
    clock = clock or store.now()
    total = 0
    contacts = store.ordered(
        [c for c in store.outreach_contacts.values() if c["youth_id"] == youth_id]
    )
    for contact in contacts:
        seconds = (clock - contact["contacted_at"]).total_seconds()
        age_days = int(seconds // 86400)
        if age_days < 0:
            age_days = 0
        weeks = age_days // 7
        decay_pct = max(0, 100 - DECAY_PCT_PER_WEEK * weeks)
        total += floor_div(raw_indicator_value(contact["indicator_flags"]) * decay_pct, 100)
    return min(100, total)


# ---------------------------------------------------- 4. savings_match_award
def match_component(entry_type, amount_cents, rate_bp):
    if entry_type == "DEPOSIT":
        return round_half_up(amount_cents * rate_bp, 10000)
    if entry_type == "REVERSAL":
        return -round_half_up(amount_cents * rate_bp, 10000)
    return 0


def signed_amount(entry_type, amount_cents):
    return amount_cents if entry_type == "DEPOSIT" else -amount_cents


def placement_entries(placement_id):
    return store.ordered(
        [e for e in store.savings_entries.values() if e["placement_id"] == placement_id]
    )


def savings_totals(placement_id):
    """(match_awarded_cents, savings_balance_cents) over every entry, no filter."""
    entries = placement_entries(placement_id)
    raw_match = sum(e["match_component_cents"] for e in entries)
    match_awarded = min(MATCH_CAP_CENTS, max(0, raw_match))
    balance = sum(e["signed_amount_cents"] for e in entries) + match_awarded
    return match_awarded, balance


def lifetime_deposited_cents(youth_id):
    placement_ids = {
        p["id"] for p in store.tlp_placements.values() if p["youth_id"] == youth_id
    }
    total = 0
    for entry in store.savings_entries.values():
        if entry["placement_id"] not in placement_ids:
            continue
        if entry["entry_type"] == "DEPOSIT":
            total += entry["amount_cents"]
        elif entry["entry_type"] == "REVERSAL":
            total -= entry["amount_cents"]
    return total


def deposit_headroom(placement_id):
    """Sum of DEPOSIT amounts less the sum of prior REVERSAL amounts (PRD 3.8)."""
    total = 0
    for entry in placement_entries(placement_id):
        if entry["entry_type"] == "DEPOSIT":
            total += entry["amount_cents"]
        elif entry["entry_type"] == "REVERSAL":
            total -= entry["amount_cents"]
    return total


# -------------------------------------------------------- 5. required_savings
def days_elapsed(placement, clock=None):
    """Whole 24-hour days between placed_at and the logical clock, floored."""
    clock = clock or store.now()
    seconds = (clock - placement["placed_at"]).total_seconds()
    value = int(seconds // 86400)
    return value if value > 0 else 0


def required_savings_cents(placement, program, elapsed_days):
    months = floor_div(elapsed_days, DAYS_PER_SAVINGS_MONTH)
    monthly = floor_div(
        placement["documented_monthly_income_cents"] * program["required_savings_rate_bp"], 10000
    )
    return monthly * months


def review_outcome(balance_cents, required_cents):
    if balance_cents >= required_cents:
        return "IN_COMPLIANCE"
    if balance_cents >= floor_div(required_cents, 2):
        return "SAVINGS_DEFICIENT"
    return "PROBATION"


# -------------------------------------------------- 6. tlp_duration_allowance
def duration_allowance(placement, elapsed_days):
    """The pinned three-step evaluation of PRD 3.7."""
    base = placement["base_allowance_days"]
    consumed_ratio_bp = floor_div(elapsed_days * 10000, base)
    hours = placement["life_skills_credit_hours"]
    if hours >= 60:
        milestone = 90
    elif hours >= 40:
        milestone = 60
    elif hours >= 20:
        milestone = 30
    else:
        milestone = 0
    if consumed_ratio_bp >= HAIRCUT_RATIO_BP:
        earned_bonus_days = floor_div(milestone, 2)
    else:
        earned_bonus_days = milestone
    return consumed_ratio_bp, earned_bonus_days, base + earned_bonus_days


# ------------------------------------------------ 7. admission_priority_score
def priority_score(youth, clock=None):
    """Frozen onto the Admission at request time; never revised afterwards."""
    age_component = max(0, ADULT_AGE - age_years(youth, clock)) * AGE_WEIGHT
    risk_component = min(RISK_CAP, youth["trafficking_risk_score"])
    engagement_component = min(ENGAGEMENT_CAP, youth["engagement_contact_count"] * ENGAGEMENT_STEP)
    nights = youth["cumulative_shelter_nights"]
    if nights == 0:
        exposure_component = EXPOSURE_BASE
    else:
        exposure_component = max(0, EXPOSURE_BASE - nights)
    subtotal = age_component + risk_component + engagement_component + exposure_component
    if youth["trafficking_risk_tier"] == "CRITICAL":
        subtotal += CRITICAL_BUMP
    return min(100, subtotal)


# ---------------------------------------------------------- 8. program_posture
def program_counters(program):
    """The four counters that feed the posture (PRD 2.6), all recounted from the
    underlying records so that a client can never assert a compliance figure."""
    program_id = program["id"]
    if program["program_type"] == "EMERGENCY_SHELTER":
        occupied = sum(
            1
            for a in store.admissions.values()
            if a["program_id"] == program_id and a["status"] in BED_HOLDING_ADMISSION_STATUSES
        )
    else:
        occupied = sum(
            1
            for p in store.tlp_placements.values()
            if p["program_id"] == program_id and p["tenancy_status"] in OPEN_TENANCY_STATUSES
        )
    waitlisted = sum(
        1
        for a in store.admissions.values()
        if a["program_id"] == program_id and a["status"] == "WAITLISTED"
    )
    overdue = 0
    for notification in store.guardian_notifications.values():
        if notification["status"] != "OVERDUE":
            continue
        admission = store.admissions.get(notification["admission_id"])
        if admission is not None and admission["program_id"] == program_id:
            overdue += 1
    utilization_bp = floor_div(occupied * 10000, program["licensed_bed_capacity"])
    return occupied, waitlisted, overdue, utilization_bp


def posture_for(occupied, overdue, utilization_bp, capacity):
    """Three clauses evaluated from the top down, the first match winning."""
    if occupied >= capacity or overdue >= FROZEN_OVERDUE_COUNT:
        return "FROZEN"
    if utilization_bp >= RESTRICTED_UTILIZATION_BP or overdue == 1:
        return "RESTRICTED"
    return "OPEN"


def beds_full(program):
    """True when the program's FROZEN posture arises from beds being full."""
    return program["occupied_beds"] >= program["licensed_bed_capacity"]


# ------------------------------------------------------ 9. youth_risk_posture
def latest_screening(youth_id):
    """The youth's SafetyScreening row with the greatest created_at."""
    rows = store.ordered(
        [s for s in store.safety_screenings.values() if s["youth_id"] == youth_id]
    )
    return rows[-1] if rows else None


def youth_notifications(youth_id):
    """Every GuardianNotification reachable through any of the youth's admissions."""
    admission_ids = {
        a["id"] for a in store.admissions.values() if a["youth_id"] == youth_id
    }
    return store.ordered(
        [
            n
            for n in store.guardian_notifications.values()
            if n["admission_id"] in admission_ids
        ]
    )


def has_open_obligation(youth_id):
    return any(
        n["status"] in OPEN_NOTIFICATION_STATUSES for n in youth_notifications(youth_id)
    )


def risk_posture_for(youth):
    screening = latest_screening(youth["id"])
    if screening is not None and screening["status"] == "ESCALATED":
        return "FROZEN"
    if has_open_obligation(youth["id"]) or youth["trafficking_risk_tier"] == "CRITICAL":
        return "RESTRICTED"
    return "OPEN"


def vote_eligible(youth):
    """PRD 3.1: true exactly when status is SHELTERED or TLP_ENROLLED and the youth
    has at least one outreach encounter."""
    return youth["status"] in ("SHELTERED", "TLP_ENROLLED") and youth["engagement_contact_count"] >= 1


def is_resident(youth_id, program_id):
    """PRD 3.9 residency test used by the electorate."""
    for admission in store.admissions.values():
        if (
            admission["youth_id"] == youth_id
            and admission["program_id"] == program_id
            and admission["status"] in BED_HOLDING_ADMISSION_STATUSES
        ):
            return True
    for placement in store.tlp_placements.values():
        if (
            placement["youth_id"] == youth_id
            and placement["program_id"] == program_id
            and placement["tenancy_status"] in OPEN_TENANCY_STATUSES
        ):
            return True
    return False


# ------------------------------------------------ 10. governance_adoption_tally
def proposal_tally(proposal):
    support = 0
    oppose = 0
    for vote in store.governance_votes.values():
        if vote["proposal_id"] != proposal["id"] or vote["status"] != "COUNTED":
            continue
        if vote["stance"] == "SUPPORT":
            support += 1
        else:
            oppose += 1
    return support, oppose


def electorate_size(program_id):
    return sum(
        1
        for youth in store.youths.values()
        if youth["governance_vote_eligible"] and is_resident(youth["id"], program_id)
    )


# ----------------------------------------------- 11. federal_compliance_report
def compliance_report(program):
    program_id = program["id"]
    discharged = store.ordered(
        [
            a
            for a in store.admissions.values()
            if a["program_id"] == program_id and a["status"] == "DISCHARGED"
        ]
    )
    discharged_count = len(discharged)
    billable_nights_total = sum((a["final_billable_nights"] or 0) for a in discharged)
    over_limit = sum(
        1
        for a in discharged
        if (a["final_billable_nights"] or 0) > program["max_stay_nights"]
    )
    positive = sum(1 for a in discharged if a["outcome_positive"] is True)
    if discharged_count == 0:
        positive_rate_bp = 0
        average_stay_nights_bp = 0
    else:
        positive_rate_bp = floor_div(positive * 10000, discharged_count)
        average_stay_nights_bp = floor_div(billable_nights_total * 100, discharged_count)
    waived = 0
    reported = 0
    for notification in store.guardian_notifications.values():
        admission = store.admissions.get(notification["admission_id"])
        if admission is None or admission["program_id"] != program_id:
            continue
        if notification["status"] == "WAIVED":
            waived += 1
        elif notification["status"] == "LAW_ENFORCEMENT_REPORTED":
            reported += 1
    return {
        "licensed_bed_capacity": program["licensed_bed_capacity"],
        "occupied_beds": program["occupied_beds"],
        "waitlisted_count": program["waitlisted_count"],
        "utilization_bp": program["utilization_bp"],
        "posture": program["posture"],
        "bed_capacity_compliant": program["occupied_beds"] <= program["licensed_bed_capacity"],
        "discharged_count": discharged_count,
        "billable_nights_total": billable_nights_total,
        "average_stay_nights_bp": average_stay_nights_bp,
        "over_limit_admission_count": over_limit,
        "positive_outcome_count": positive,
        "positive_outcome_rate_bp": positive_rate_bp,
        "overdue_notification_count": program["overdue_notification_count"],
        "waived_notification_count": waived,
        "runaway_report_count": reported,
    }
