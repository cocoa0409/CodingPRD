"""Cascades, derived-counter refreshes and the logical clock's system events."""

from datetime import timedelta

import calc
from store import (
    DISTRICTS,
    MEMBERS,
    MILESTONES,
    PATHWAYS,
    PLACEMENTS,
    REGIONS,
    SCHOOLS,
    now,
    stamp,
    touch,
)
from util import iso, parse_dt

MILESTONE_ORDER = ("COURSEWORK", "PRACTICUM", "ORIENTATION", "EXAM")


# --------------------------------------------------------------------------
# Derived-field refreshes. Each refresh is a mutation: it refreshes the owning
# resource's updated_at and increments its version by exactly one.
# --------------------------------------------------------------------------
def refresh_member(member):
    member["certification_hours_verified"] = calc.certification_hours_verified(member)
    member["coursework_hours_completed"] = calc.coursework_hours_completed(member)
    member["readiness_score"] = calc.readiness_score(member)
    member["institute_stipend_cents"] = calc.institute_stipend_cents(
        member["practice_teaching_hours"]
    )
    touch(member)
    return member


def refresh_district(district):
    district["committed_placement_count"] = calc.district_filled_count(district)
    district["invoice_amount_cents"] = calc.district_invoice_amount_cents(district)
    touch(district)
    return district


def refresh_school(school):
    school["occupied_classrooms"] = calc.school_occupied_classrooms(school)
    touch(school)
    return school


def refresh_placement_eligibility(placement):
    placement["employment_eligible"] = calc.employment_eligible(placement)
    touch(placement)
    return placement


def refresh_member_placements(member):
    """Re-evaluate employment_eligible on every CONFIRMED / ACTIVE placement."""
    for placement in PLACEMENTS.values():
        if placement["corps_member_id"] == member["id"] and placement["status"] in (
            "CONFIRMED",
            "ACTIVE",
        ):
            refresh_placement_eligibility(placement)


def overlapping_occupied_count(school, term_start, term_end, exclude_id=None):
    """Placements at the school whose status is CONFIRMED / ACTIVE and whose closed
    term interval overlaps the candidate interval. Both ends are inclusive, so two
    windows sharing exactly one endpoint overlap."""
    count = 0
    for placement in PLACEMENTS.values():
        if placement["school_id"] != school["id"]:
            continue
        if exclude_id is not None and placement["id"] == exclude_id:
            continue
        if placement["status"] not in ("CONFIRMED", "ACTIVE"):
            continue
        if placement["term_start_date"] <= term_end and term_start <= placement["term_end_date"]:
            count += 1
    return count


def district_of_school(school):
    return DISTRICTS.get(school["district_id"]) if school else None


def school_of_placement(placement):
    return SCHOOLS.get(placement["school_id"])


def district_of_placement(placement):
    return district_of_school(school_of_placement(placement))


def region_of_district(district):
    return REGIONS.get(district["region_id"]) if district else None


# --------------------------------------------------------------------------
# Certification milestone synthesis
# --------------------------------------------------------------------------
def milestone_hours_for(pathway, milestone_type):
    if milestone_type == "PRACTICUM":
        return pathway["required_practice_hours"]
    if milestone_type in ("COURSEWORK", "ORIENTATION"):
        return pathway["required_coursework_hours"]
    return 0


def milestone_due_date(region, pathway):
    return parse_dt(region["term_start_date"]) - timedelta(days=pathway["deadline_days_before_term"])


def build_milestone(member, pathway, milestone_type, required_hours, due_date, synthesized):
    region = REGIONS.get(pathway["region_id"])
    record = {
        "corps_member_id": member["id"],
        "pathway_id": pathway["id"],
        "milestone_type": milestone_type,
        "required_hours": required_hours,
        "due_date": iso(due_date if due_date is not None else milestone_due_date(region, pathway)),
        "progress_status": "PENDING",
        "verification_status": "UNVERIFIED",
        "completed_at": None,
        "completed_by_user_id": None,
        "verified_by_user_id": None,
        "deadline_status": None,
        "days_remaining": 0,
        "synthesized": synthesized,
    }
    stamp(record)
    MILESTONES[record["id"]] = record
    return record


def synthesize_milestones(member, preferred_region_id):
    """One milestone per (pathway, milestone_type) pair, in the fixed order
    COURSEWORK, PRACTICUM, ORIENTATION, EXAM. Each synthesized milestone
    recomputes the member's verified hours and readiness, advancing the
    member's version once per milestone."""
    pathways = [pw for pw in PATHWAYS.values() if pw["region_id"] == preferred_region_id]
    pathways.sort(key=lambda pw: (pw["created_at"], pw["id"]))
    created = []
    for pathway in pathways:
        for milestone_type in MILESTONE_ORDER:
            record = build_milestone(
                member,
                pathway,
                milestone_type,
                milestone_hours_for(pathway, milestone_type),
                None,
                True,
            )
            created.append(record)
            refresh_member(member)
    return created


_TYPE_ORDER = {name: index for index, name in enumerate(MILESTONE_ORDER)}


def order_member_milestones(rows):
    """Synthesized milestones read in the canonical type order; milestones created
    directly by an officer are appended in created_at ascending order."""
    synthesized = [m for m in rows if m.get("synthesized")]
    direct = [m for m in rows if not m.get("synthesized")]
    synthesized.sort(key=lambda m: (_TYPE_ORDER.get(m["milestone_type"], 99), m["created_at"], m["id"]))
    direct.sort(key=lambda m: (m["created_at"], m["id"]))
    return synthesized + direct


def synthesize_member(application, region):
    """Hop 1 of the offer-acceptance cascade."""
    member = {
        "application_id": application["id"],
        "cohort_year": parse_dt(region["term_start_date"]).year if region is not None else now().year,
        "institute_status": "ENROLLED",
        "service_status": "ACTIVE",
        "practice_teaching_hours": 0,
        "coursework_hours_completed": 0,
        "certification_hours_verified": 0,
        "readiness_score": 0.0,
        "institute_stipend_cents": 0,
        "service_started_at": None,
        "leave_started_at": None,
        "exit_reason": None,
    }
    stamp(member)
    MEMBERS[member["id"]] = member
    synthesize_milestones(member, application["preferred_region_id"])
    return member


# --------------------------------------------------------------------------
# System events driven by the logical clock
# --------------------------------------------------------------------------
def _complete_placement_at_term_end(placement):
    placement["status"] = "COMPLETED"
    placement["employment_eligible"] = False
    touch(placement)
    school = school_of_placement(placement)
    district = district_of_school(school)
    if school is not None:
        refresh_school(school)
    if district is not None:
        refresh_district(district)


def _expire_district(district):
    district["agreement_status"] = "EXPIRED"
    touch(district)


def settle_clock_effects():
    """Apply the two clock-driven system transitions before handling a request."""
    current = now()
    for placement in list(PLACEMENTS.values()):
        if placement["status"] == "ACTIVE" and current >= parse_dt(placement["term_end_date"]):
            _complete_placement_at_term_end(placement)
    for district in list(DISTRICTS.values()):
        if district["agreement_status"] == "ACTIVE":
            region = REGIONS.get(district["region_id"])
            if region is not None and current >= parse_dt(region["term_start_date"]):
                _expire_district(district)
