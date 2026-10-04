"""Payload factories — one per entity, input fields only.

Defaults follow the recurring fixtures used across the PRD workflows: a
"State University" institution, a 2026-01-01..2027-06-30 agreement window,
and a Fall 2026 reporting period.
"""

DEFAULT_INSTITUTION_NAME = "State University"
DEFAULT_OPE_ID = "00123400"
DEFAULT_AGREEMENT_FROM = "2026-01-01"
DEFAULT_AGREEMENT_TO = "2027-06-30"
DEFAULT_TERM_LABEL = "Fall 2026"
DEFAULT_TERM_START = "2026-09-01"
DEFAULT_TERM_END = "2026-12-15"
DEFAULT_OPENS_AT = "2026-11-01"
DEFAULT_DUE_AT = "2026-12-20"


def create_institution_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULT_INSTITUTION_NAME,
        "ope_id": DEFAULT_OPE_ID,
        "users": [
            {"email": "sub@su.edu", "role": "SUBMITTER"},
            {"email": "cert@su.edu", "role": "CERTIFIER"},
        ],
    }
    defaults.update(overrides)
    return defaults


def create_agreement_payload(**overrides) -> dict:
    defaults = {
        "effective_from": DEFAULT_AGREEMENT_FROM,
        "effective_to": DEFAULT_AGREEMENT_TO,
    }
    defaults.update(overrides)
    return defaults


def create_period_payload(**overrides) -> dict:
    defaults = {
        "term_label": DEFAULT_TERM_LABEL,
        "term_start": DEFAULT_TERM_START,
        "term_end": DEFAULT_TERM_END,
        "submission_opens_at": DEFAULT_OPENS_AT,
        "submission_due_at": DEFAULT_DUE_AT,
    }
    defaults.update(overrides)
    return defaults


def enrollment_row(**overrides) -> dict:
    """One enrollment-file row (PRD section 3.3 input fields)."""
    defaults = {
        "student_ref": "S1",
        "full_name": "Ada Lovelace",
        "date_of_birth": "2004-05-12",
        "career_level": "UNDERGRAD",
        "credit_hours": 12.0,
        "term_start": DEFAULT_TERM_START,
        "term_end": DEFAULT_TERM_END,
    }
    defaults.update(overrides)
    return defaults


def create_enrollment_file_payload(institution_id, reporting_period_id,
                                   expected_reporting_period_version,
                                   rows, **overrides) -> dict:
    payload = {
        "institution_id": institution_id,
        "reporting_period_id": reporting_period_id,
        "expected_reporting_period_version": expected_reporting_period_version,
        "rows": rows,
    }
    payload.update(overrides)
    return payload


def create_correction_payload(enrollment_entry_id, **overrides) -> dict:
    payload = {
        "enrollment_entry_id": enrollment_entry_id,
        "reason_code": "REPORTING_ERROR",
    }
    payload.update(overrides)
    return payload


def create_degree_payload(institution_id, student_id, **overrides) -> dict:
    payload = {
        "institution_id": institution_id,
        "student_id": student_id,
        "degree_level": "BACHELOR",
        "degree_title": "BS Computer Science",
        "conferred_on": "2026-05-15",
    }
    payload.update(overrides)
    return payload


def create_requester_payload(**overrides) -> dict:
    defaults = {
        "org_name": "Acme Hiring",
        "requester_kind": "EMPLOYER",
    }
    defaults.update(overrides)
    return defaults


def create_verification_request_payload(student_id, institution_id, **overrides) -> dict:
    payload = {
        "student_id": student_id,
        "institution_id": institution_id,
        "product_type": "DEGREE",
        "purpose": "EMPLOYMENT",
    }
    payload.update(overrides)
    return payload


def create_directive_payload(expected_student_version, **overrides) -> dict:
    payload = {
        "directive_type": "FULL_BLOCK",
        "effective_from": "2026-01-01",
        "expected_student_version": expected_student_version,
    }
    payload.update(overrides)
    return payload


def create_dataset_payload(scope_institution_id, **overrides) -> dict:
    payload = {
        "scope_institution_id": scope_institution_id,
        "cohort_term_start": DEFAULT_TERM_START,
        "cohort_term_end": DEFAULT_TERM_END,
    }
    payload.update(overrides)
    return payload
