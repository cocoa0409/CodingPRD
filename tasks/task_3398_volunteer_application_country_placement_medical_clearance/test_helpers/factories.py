"""Payload factories — one per creatable resource, input fields only.

Defaults are internally consistent with the canonical fixture instants in
constants.py: openings depart after the cohort window, issue deadlines sit
before it, and interviews are scheduled shortly after the clock start.
"""

import itertools

from .constants import (
    COHORT_END_DATE,
    COHORT_NAME,
    COHORT_START_DATE,
    INTERVIEW_END,
    INTERVIEW_START,
    OPENING_DEPARTURE_DATE,
    OPENING_ISSUE_DEADLINE,
)

_email_counter = itertools.count(1)
_country_counter = itertools.count(1)
_opening_counter = itertools.count(1)
_cohort_counter = itertools.count(1)


def create_applicant_payload(**overrides) -> dict:
    n = next(_email_counter)
    defaults = {
        "full_name": "Ana Ruiz",
        "email": f"applicant-{n}@example.org",
        "date_of_birth": "1995-05-20T00:00:00Z",
        "citizenship_country": "US",
        "skills": ["TEACHING_ENGLISH"],
    }
    defaults.update(overrides)
    return defaults


def create_country_program_payload(**overrides) -> dict:
    n = next(_country_counter)
    defaults = {
        "country_code": f"P{n:02d}",
        "name": f"Program {n}",
        "medical_support_tier": 3,
        "required_language": "Spanish",
        "language_threshold_score": 2.5,
        "training_capacity": 10,
    }
    defaults.update(overrides)
    return defaults


def create_assignment_opening_payload(country_program_id: str, **overrides) -> dict:
    n = next(_opening_counter)
    defaults = {
        "country_program_id": country_program_id,
        "sector": "EDUCATION",
        "title": f"Assignment Opening {n}",
        "required_skills": ["TEACHING_ENGLISH"],
        "seats_total": 2,
        "departure_date": OPENING_DEPARTURE_DATE,
        "invitation_issue_deadline": OPENING_ISSUE_DEADLINE,
    }
    defaults.update(overrides)
    return defaults


def create_application_payload(applicant_id: str, **overrides) -> dict:
    defaults = {
        "applicant_id": applicant_id,
        "sector_preferences": ["EDUCATION"],
    }
    defaults.update(overrides)
    return defaults


def create_interview_payload(**overrides) -> dict:
    defaults = {
        "interviewer_id": "officer-1",
        "scheduled_start": INTERVIEW_START,
        "scheduled_end": INTERVIEW_END,
    }
    defaults.update(overrides)
    return defaults


def complete_interview_payload(**overrides) -> dict:
    """Default scores 4.0/3.0/3.0/3.0 -> overall 3.30, RECOMMEND."""
    defaults = {
        "motivation_score": 4.0,
        "adaptability_score": 3.0,
        "skill_competency_score": 3.0,
        "cross_cultural_score": 3.0,
    }
    defaults.update(overrides)
    return defaults


def create_invitation_payload(application_id: str, assignment_opening_id: str,
                              expected_assignment_opening_version: int, **overrides) -> dict:
    defaults = {
        "application_id": application_id,
        "assignment_opening_id": assignment_opening_id,
        "expected_assignment_opening_version": expected_assignment_opening_version,
    }
    defaults.update(overrides)
    return defaults


def create_medical_clearance_payload(application_id: str, **overrides) -> dict:
    defaults = {
        "application_id": application_id,
        "conditions": [],
        "dental_status": "CLEAR",
    }
    defaults.update(overrides)
    return defaults


def resubmit_medical_clearance_payload(**overrides) -> dict:
    defaults = {
        "conditions": [],
        "dental_status": "CLEAR",
    }
    defaults.update(overrides)
    return defaults


def determine_medical_payload(**overrides) -> dict:
    defaults = {"determination": "CLEARED"}
    defaults.update(overrides)
    return defaults


def adjudicate_background_payload(**overrides) -> dict:
    defaults = {"outcome": "CLEAR"}
    defaults.update(overrides)
    return defaults


def determine_suitability_payload(**overrides) -> dict:
    defaults = {"outcome": "FAVORABLE"}
    defaults.update(overrides)
    return defaults


def create_training_cohort_payload(country_program_id: str, **overrides) -> dict:
    n = next(_cohort_counter)
    defaults = {
        "country_program_id": country_program_id,
        "name": f"{COHORT_NAME}-{n}",
        "start_date": COHORT_START_DATE,
        "end_date": COHORT_END_DATE,
        "capacity": 5,
    }
    defaults.update(overrides)
    return defaults


def create_training_enrollment_payload(application_id: str, training_cohort_id: str,
                                       **overrides) -> dict:
    defaults = {
        "application_id": application_id,
        "training_cohort_id": training_cohort_id,
    }
    defaults.update(overrides)
    return defaults


def assess_enrollment_payload(**overrides) -> dict:
    """Default scores pass any language_threshold_score <= 3.0 and the 2.5
    technical/cultural minimums."""
    defaults = {
        "language_score": 3.0,
        "technical_score": 3.0,
        "cultural_score": 3.0,
    }
    defaults.update(overrides)
    return defaults


def create_service_event_payload(**overrides) -> dict:
    defaults = {
        "event_type": "MEDICAL_CARE",
        "severity": "ROUTINE",
        "description": "Routine checkup at regional office",
        "occurred_at": "2027-01-04T08:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def early_terminate_payload(**overrides) -> dict:
    defaults = {"reason": "FAMILY"}
    defaults.update(overrides)
    return defaults


def create_site_placement_payload(**overrides) -> dict:
    defaults = {
        "host_community_name": "Huascar Valley",
        "counterpart_org_name": "Andes Education NGO",
    }
    defaults.update(overrides)
    return defaults


def review_site_placement_payload(**overrides) -> dict:
    defaults = {
        "counterpart_agreement_signed": True,
        "has_running_water": True,
        "structurally_sound": True,
        "secure_locks": True,
        "decision": "CONFIRM",
    }
    defaults.update(overrides)
    return defaults
