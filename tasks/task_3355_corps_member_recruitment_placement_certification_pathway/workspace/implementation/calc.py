"""The nine declared calculations, implemented exactly as the PRD pins them.

Money is integer cents throughout; the only calculation that passes through
dollars is the institute stipend, which converts back as its final step.
All half-way values resolve with round-half-up.
"""

from decimal import Decimal

from store import (
    APPLICATIONS,
    DISTRICTS,
    MEMBERS,
    MILESTONES,
    PATHWAYS,
    PLACEMENTS,
    REGIONS,
    SCHOOLS,
    now,
)
from util import days_between, dec, dt_date, round_half_up

HIGH_NEED_SUBJECTS = ("MATH", "SCIENCE", "SPED")

# institute_stipend_cents constants
ANNUAL_STIPEND_DOLLARS = Decimal("6510.00")
WEEKS_PER_YEAR = 52
HOURS_PER_WEEK = 40

# certification_deadline_status constants
AT_RISK_WINDOW_DAYS = 14

# readiness_score constants
CERTIFIED_WEIGHT = Decimal("0.5")
PRACTICE_WEIGHT = Decimal("0.3")
COURSEWORK_WEIGHT = Decimal("0.2")
STRONG_TIER_MIN = Decimal("80.00")
QUALIFIED_TIER_MIN = Decimal("50.00")
STRONG_SUPPORT_CREDIT = Decimal("3.0")
QUALIFIED_SUPPORT_CREDIT = Decimal("1.5")
DEVELOPING_SUPPORT_CREDIT = Decimal("0.0")
READINESS_CEILING = Decimal("100.0")

# placement_fee_cents constants
HIGH_NEED_UPLIFT = Decimal("1.15")

# selection_score constants
LEADERSHIP_WEIGHT = Decimal("0.45")
ACHIEVEMENT_WEIGHT = Decimal("0.40")
GPA_WEIGHT = Decimal("0.15")
CAMPUS_TIER_BONUS = Decimal("5.0")
HIGH_NEED_SUBJECT_BONUS = Decimal("7.0")


# --------------------------------------------------------------------------
# selection_score  (provisional reads Applicant.gpa, final reads verified_gpa)
# --------------------------------------------------------------------------
def selection_score(application, applicant, variant):
    gpa_used = application.get("verified_gpa") if variant == "final" else applicant.get("gpa")
    if gpa_used is None:
        gpa_used = 0.0
    gpa_normalized = min(dec(gpa_used), Decimal("4.0")) / Decimal("4.0") * Decimal("100")
    base = (
        dec(applicant["leadership_score"]) * LEADERSHIP_WEIGHT
        + dec(applicant["achievement_score"]) * ACHIEVEMENT_WEIGHT
        + gpa_normalized * GPA_WEIGHT
    )
    if applicant.get("campus_tier") == "PRIORITY":
        base = min(Decimal("100.0"), base + CAMPUS_TIER_BONUS)
    if application.get("subject_area") in HIGH_NEED_SUBJECTS:
        base = min(Decimal("100.0"), base + HIGH_NEED_SUBJECT_BONUS)
    return float(round_half_up(base, 2))


# --------------------------------------------------------------------------
# district_invoice_amount_cents
# --------------------------------------------------------------------------
def district_filled_count(district):
    school_ids = {s["id"] for s in SCHOOLS.values() if s["district_id"] == district["id"]}
    return sum(
        1
        for p in PLACEMENTS.values()
        if p["school_id"] in school_ids and p["status"] in ("CONFIRMED", "ACTIVE")
    )


def district_invoice_amount_cents(district):
    filled = district_filled_count(district)
    unfilled = max(0, district["hiring_commitment_slots"] - filled)
    gross = filled * district["placement_fee_per_member_cents"]
    penalty = unfilled * district["unfilled_slot_penalty_cents"]
    return gross + penalty


def district_forward_looking_invoice_cents(district):
    return district["hiring_commitment_slots"] * district["placement_fee_per_member_cents"]


# --------------------------------------------------------------------------
# institute_stipend_cents
# --------------------------------------------------------------------------
def institute_stipend_cents(practice_teaching_hours):
    weekly_amount = round_half_up(ANNUAL_STIPEND_DOLLARS / Decimal(WEEKS_PER_YEAR), 2)
    whole_weeks = practice_teaching_hours // HOURS_PER_WEEK
    remainder = practice_teaching_hours % HOURS_PER_WEEK
    partial_amount = round_half_up(
        weekly_amount * Decimal(remainder) / Decimal(HOURS_PER_WEEK), 2
    )
    stipend_dollars = Decimal(whole_weeks) * weekly_amount + partial_amount
    return int(round_half_up(stipend_dollars * Decimal(100), 0))


# --------------------------------------------------------------------------
# pathway selection (pinned order: placement region, then application region)
# --------------------------------------------------------------------------
def _earliest_pathway(candidates):
    return min(candidates, key=lambda pw: (pw["created_at"], pw["id"]))


def _placement_region_id(placement):
    school = SCHOOLS.get(placement["school_id"])
    if not school:
        return None
    district = DISTRICTS.get(school["district_id"])
    if not district:
        return None
    return district["region_id"]


def select_pathway(member):
    """The pathway whose region matches the member's CONFIRMED/ACTIVE placement;
    otherwise the earliest-created pathway of the application's preferred region
    (created_at first, lower id string only as the tie-break)."""
    held = [
        p
        for p in PLACEMENTS.values()
        if p["corps_member_id"] == member["id"] and p["status"] in ("CONFIRMED", "ACTIVE")
    ]
    held.sort(key=lambda p: (p["created_at"], p["id"]))
    for placement in held:
        region_id = _placement_region_id(placement)
        if not region_id:
            continue
        candidates = [pw for pw in PATHWAYS.values() if pw["region_id"] == region_id]
        if candidates:
            return _earliest_pathway(candidates)
    application = APPLICATIONS.get(member.get("application_id"))
    if application:
        candidates = [
            pw for pw in PATHWAYS.values() if pw["region_id"] == application["preferred_region_id"]
        ]
        if candidates:
            return _earliest_pathway(candidates)
    return None


# --------------------------------------------------------------------------
# certification_hours_verified / coursework_hours_completed
# --------------------------------------------------------------------------
def member_milestones(member_id):
    return [m for m in MILESTONES.values() if m["corps_member_id"] == member_id]


def certification_hours_verified(member):
    return sum(
        m["required_hours"]
        for m in member_milestones(member["id"])
        if m["progress_status"] == "COMPLETED" and m["verification_status"] == "VERIFIED"
    )


def coursework_hours_completed(member):
    return sum(
        m["required_hours"]
        for m in member_milestones(member["id"])
        if m["milestone_type"] in ("COURSEWORK", "ORIENTATION")
        and m["progress_status"] == "COMPLETED"
    )


# --------------------------------------------------------------------------
# readiness_score
# --------------------------------------------------------------------------
def readiness_score(member):
    milestones = member_milestones(member["id"])
    total_required = sum(m["required_hours"] for m in milestones)
    certified = sum(
        m["required_hours"]
        for m in milestones
        if m["progress_status"] == "COMPLETED" and m["verification_status"] == "VERIFIED"
    )
    if total_required == 0:
        certified_ratio = Decimal("1.0")
    else:
        certified_ratio = min(Decimal("1.0"), Decimal(certified) / Decimal(total_required))

    pathway = select_pathway(member)
    if pathway is None or pathway["required_practice_hours"] <= 0:
        practice_ratio = Decimal("1.0")
    else:
        practice_ratio = min(
            Decimal("1.0"),
            Decimal(member["practice_teaching_hours"]) / Decimal(pathway["required_practice_hours"]),
        )
    if pathway is None or pathway["required_coursework_hours"] <= 0:
        coursework_ratio = Decimal("1.0")
    else:
        coursework_ratio = min(
            Decimal("1.0"),
            Decimal(member["coursework_hours_completed"])
            / Decimal(pathway["required_coursework_hours"]),
        )

    subtotal = round_half_up(
        Decimal("100.0")
        * (
            CERTIFIED_WEIGHT * certified_ratio
            + PRACTICE_WEIGHT * practice_ratio
            + COURSEWORK_WEIGHT * coursework_ratio
        ),
        2,
    )
    if subtotal >= STRONG_TIER_MIN:
        credit = STRONG_SUPPORT_CREDIT
    elif subtotal >= QUALIFIED_TIER_MIN:
        credit = QUALIFIED_SUPPORT_CREDIT
    else:
        credit = DEVELOPING_SUPPORT_CREDIT
    return float(min(READINESS_CEILING, round_half_up(subtotal + credit, 2)))


# --------------------------------------------------------------------------
# certification_deadline_status
# --------------------------------------------------------------------------
def deadline_band(milestone):
    days_remaining = days_between(milestone["due_date"], now())
    if (
        milestone["progress_status"] == "COMPLETED"
        and milestone["verification_status"] == "VERIFIED"
    ):
        band = "SATISFIED"
    elif days_remaining < 0:
        band = "OVERDUE"
    elif days_remaining <= AT_RISK_WINDOW_DAYS:
        band = "AT_RISK"
    else:
        band = "ON_TRACK"
    return days_remaining, band


# --------------------------------------------------------------------------
# employment_eligibility
# --------------------------------------------------------------------------
def employment_eligible(placement):
    if placement["status"] not in ("CONFIRMED", "ACTIVE"):
        return False
    member = MEMBERS.get(placement["corps_member_id"])
    if member is None:
        return False
    if member["service_status"] != "ACTIVE":
        return False
    if member["institute_status"] != "COMPLETED":
        return False
    for milestone in member_milestones(member["id"]):
        _, band = deadline_band(milestone)
        if band == "OVERDUE":
            return False
    pathway = select_pathway(member)
    required = 0
    if pathway is not None:
        required = pathway["required_practice_hours"] + pathway["required_coursework_hours"]
    return member["certification_hours_verified"] >= required


# --------------------------------------------------------------------------
# placement_fee_cents
# --------------------------------------------------------------------------
def placement_fee_cents(placement):
    school = SCHOOLS.get(placement["school_id"])
    district = DISTRICTS.get(school["district_id"]) if school else None
    base = district["placement_fee_per_member_cents"] if district else 0
    if base <= 0:
        region = REGIONS.get(district["region_id"]) if district else None
        base = region["base_placement_fee_cents"] if region else 0
    if placement["subject_area"] in HIGH_NEED_SUBJECTS:
        base = round_half_up(dec(base) * HIGH_NEED_UPLIFT, 0)
    return int(base)


# --------------------------------------------------------------------------
# occupied_classrooms (derived; counts placements whose window is open today)
# --------------------------------------------------------------------------
def school_occupied_classrooms(school):
    today = dt_date(now())
    count = 0
    for placement in PLACEMENTS.values():
        if placement["school_id"] != school["id"]:
            continue
        if placement["status"] not in ("CONFIRMED", "ACTIVE"):
            continue
        if dt_date(placement["term_start_date"]) <= today <= dt_date(placement["term_end_date"]):
            count += 1
    return count
