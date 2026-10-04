"""Payload factories — one per resource, input fields only."""
from typing import Dict, Optional

from .constants import TEST_DEFAULTS as D

_email_counter = {"n": 0}


def unique_email(prefix: str = "applicant") -> str:
    """A fresh applicant email; the API treats email as the uniqueness key."""
    _email_counter["n"] += 1
    return f"{prefix}{_email_counter['n']}@x.edu"


def create_region_payload(**overrides) -> dict:
    payload = {
        "region_code": D["REGION_CODE"],
        "name": D["REGION_NAME"],
        "state_code": D["STATE_CODE"],
        "term_start_date": D["TERM_START_DATE"],
        "base_placement_fee_cents": D["BASE_PLACEMENT_FEE_CENTS"],
        "max_corps_members": D["MAX_CORPS_MEMBERS"],
    }
    payload.update(overrides)
    return payload


def create_partner_district_payload(region_id: str, **overrides) -> dict:
    payload = {
        "region_id": region_id,
        "name": D["DISTRICT_NAME"],
        "hiring_commitment_slots": D["HIRING_COMMITMENT_SLOTS"],
        "placement_fee_per_member_cents": D["PLACEMENT_FEE_PER_MEMBER_CENTS"],
        "unfilled_slot_penalty_cents": D["UNFILLED_SLOT_PENALTY_CENTS"],
        "fee_budget_cents": D["FEE_BUDGET_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_partner_school_payload(district_id: str, expected_district_version: int, **overrides) -> dict:
    payload = {
        "district_id": district_id,
        "name": D["SCHOOL_NAME"],
        "grade_band": D["SCHOOL_GRADE_BAND"],
        "subject_needs": list(D["SCHOOL_SUBJECT_NEEDS"]),
        "classroom_capacity": D["CLASSROOM_CAPACITY"],
        "expected_district_version": expected_district_version,
    }
    payload.update(overrides)
    return payload


def create_applicant_payload(**overrides) -> dict:
    payload = {
        "full_name": D["APPLICANT_NAME"],
        "email": unique_email(),
        "campus_name": D["CAMPUS_NAME"],
        "campus_tier": D["CAMPUS_TIER"],
        "graduation_year": D["GRADUATION_YEAR"],
        "leadership_score": D["LEADERSHIP_SCORE"],
        "achievement_score": D["ACHIEVEMENT_SCORE"],
        "gpa": D["GPA"],
    }
    payload.update(overrides)
    return payload


def create_application_payload(applicant_id: str, preferred_region_id: str, **overrides) -> dict:
    payload = {
        "applicant_id": applicant_id,
        "preferred_region_id": preferred_region_id,
        "subject_area": D["SUBJECT_AREA"],
        "grade_preference": D["GRADE_PREFERENCE"],
    }
    payload.update(overrides)
    return payload


def create_certification_pathway_payload(region_id: str, **overrides) -> dict:
    payload = {
        "region_id": region_id,
        "state_code": D["STATE_CODE"],
        "certification_track": "ALTERNATIVE_EMERGENCY",
        "required_coursework_hours": D["PATHWAY_COURSEWORK_HOURS"],
        "required_practice_hours": D["PATHWAY_PRACTICE_HOURS"],
        "deadline_days_before_term": D["PATHWAY_DEADLINE_DAYS"],
        "coursework_fee_cents": D["PATHWAY_FEE_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_placement_payload(
    corps_member_id: str,
    school_id: str,
    expected_corps_member_version: int,
    **overrides,
) -> dict:
    payload = {
        "corps_member_id": corps_member_id,
        "school_id": school_id,
        "subject_area": D["SUBJECT_AREA"],
        "grade_band": D["GRADE_PREFERENCE"],
        "term_start_date": D["TERM_WINDOW_START"],
        "term_end_date": D["TERM_WINDOW_END"],
        "expected_corps_member_version": expected_corps_member_version,
    }
    payload.update(overrides)
    return payload


def create_certification_milestone_payload(
    corps_member_id: str,
    pathway_id: str,
    expected_corps_member_version: int,
    **overrides,
) -> dict:
    payload = {
        "corps_member_id": corps_member_id,
        "pathway_id": pathway_id,
        "milestone_type": "EXAM",
        "required_hours": 10,
        "expected_corps_member_version": expected_corps_member_version,
    }
    payload.update(overrides)
    return payload


def create_support_record_payload(corps_member_id: str, **overrides) -> dict:
    payload = {
        "corps_member_id": corps_member_id,
        "record_type": "COACHING",
        "coach_user_id": "coach_lee",
        "session_start": "2026-09-10T14:00:00Z",
        "session_end": "2026-09-10T15:00:00Z",
        "effectiveness_score": 4,
        "notes": "first observation",
    }
    payload.update(overrides)
    return payload


def create_evaluation_payload(corps_member_id: str, **overrides) -> dict:
    payload = create_support_record_payload(corps_member_id)
    payload.update(
        {
            "record_type": "EVALUATION",
            "session_start": "2026-09-10T14:00:00Z",
            "session_end": "2026-09-10T15:00:00Z",
            "effectiveness_score": 4,
            "notes": "formal evaluation",
        }
    )
    payload.update(overrides)
    return payload
