"""Payload factories — one per entity, input fields only (PRD §3)."""
from .constants import TERM_FIXTURE, TEST_DEFAULTS

_email_counter = {"n": 0}


def _unique_email(prefix="user"):
    _email_counter["n"] += 1
    return f"{prefix}{_email_counter['n']}@example.edu"


def create_term_payload(**overrides) -> dict:
    defaults = dict(TERM_FIXTURE)
    defaults.update(overrides)
    return defaults


def create_program_payload(**overrides) -> dict:
    defaults = {
        "code": "BS-CS",
        "title": "BS Computer Science",
        "total_credits_required": TEST_DEFAULTS["TOTAL_CREDITS"],
        "licensure_flag": False,
    }
    defaults.update(overrides)
    return defaults


def create_state_authorization_payload(**overrides) -> dict:
    defaults = {
        "state_code": TEST_DEFAULTS["STATE_CODE"],
        "authorization_status": "AUTHORIZED",
        "effective_from": TEST_DEFAULTS["AUTH_EFFECTIVE_FROM"],
    }
    defaults.update(overrides)
    return defaults


def create_staff_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Sam Staff",
        "email": _unique_email("staff"),
        "staff_type": "ADVISOR",
        "caseload_cap": TEST_DEFAULTS["CASELOAD_CAP"],
    }
    defaults.update(overrides)
    return defaults


def create_applicant_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Pat Prospect",
        "email": _unique_email("prospect"),
        "state_code": TEST_DEFAULTS["STATE_CODE"],
    }
    defaults.update(overrides)
    return defaults


def create_application_payload(applicant_id, term_id, program_id, **overrides) -> dict:
    defaults = {
        "applicant_id": applicant_id,
        "term_id": term_id,
        "program_id": program_id,
    }
    defaults.update(overrides)
    return defaults


def create_tce_payload(**overrides) -> dict:
    defaults = {"accepted_credits": 0, "in_progress_credits": 0}
    defaults.update(overrides)
    return defaults


def create_enrollment_payload(application_id, advisor_id, expected_application_version,
                              **overrides) -> dict:
    defaults = {
        "application_id": application_id,
        "advisor_id": advisor_id,
        "enrollment_intensity": "FULL_TIME",
        "tuition_cents": TEST_DEFAULTS["TUITION_CENTS"],
        "expected_application_version": expected_application_version,
    }
    defaults.update(overrides)
    return defaults


def create_section_payload(**overrides) -> dict:
    defaults = {
        "course_code": "CS-101",
        "capacity": 1,
        "forecast_enrollment": 1,
    }
    defaults.update(overrides)
    return defaults
