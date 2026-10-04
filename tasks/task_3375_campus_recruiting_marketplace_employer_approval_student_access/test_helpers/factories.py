"""Payload factories — one per entity, input fields only (PRD §3)."""
import itertools

from .constants import TEST_DEFAULTS

_counters = itertools.count(1)


def _next() -> int:
    return next(_counters)


def create_university_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "name": f"University {n}",
        "primary_domain": f"uni{n}.edu",
    }
    defaults.update(overrides)
    return defaults


def create_student_payload(university_id, **overrides) -> dict:
    n = _next()
    defaults = {
        "university_id": university_id,
        "email": f"student{n}@stateu.edu",
        "full_name": f"Student {n}",
        "major": "CS",
        "graduation_year": 2027,
        "work_authorization": "US_CITIZEN",
    }
    defaults.update(overrides)
    return defaults


def create_employer_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "company_name": f"Company {n}",
        "website_domain": f"company{n}.com",
        "contact_email": f"hr@company{n}.com",
    }
    defaults.update(overrides)
    return defaults


def create_employer_approval_payload(employer_id, university_id, **overrides) -> dict:
    defaults = {
        "employer_id": employer_id,
        "university_id": university_id,
    }
    defaults.update(overrides)
    return defaults


def create_decision_payload(decision, expected_employer_version, **overrides) -> dict:
    defaults = {
        "decision": decision,
        "expected_employer_version": expected_employer_version,
    }
    defaults.update(overrides)
    return defaults


def create_job_posting_payload(employer_id, **overrides) -> dict:
    n = _next()
    defaults = {
        "employer_id": employer_id,
        "title": f"Posting {n}",
        "position_type": "INTERNSHIP",
        "min_graduation_year": 2026,
        "max_graduation_year": 2028,
        "application_deadline": TEST_DEFAULTS["POSTING_DEADLINE"],
    }
    defaults.update(overrides)
    return defaults


def create_career_event_payload(university_id, **overrides) -> dict:
    n = _next()
    defaults = {
        "university_id": university_id,
        "title": f"Career Event {n}",
        "starts_at": TEST_DEFAULTS["EVENT_STARTS_AT"],
        "ends_at": TEST_DEFAULTS["EVENT_ENDS_AT"],
    }
    defaults.update(overrides)
    return defaults


def create_event_session_payload(expected_career_event_version, **overrides) -> dict:
    n = _next()
    defaults = {
        "title": f"Session {n}",
        "mode": "VIRTUAL",
        "starts_at": "2026-10-10T10:00:00Z",
        "ends_at": "2026-10-10T11:00:00Z",
        "signup_deadline": TEST_DEFAULTS["SESSION_SIGNUP_DEADLINE"],
        "capacity": 10,
        "expected_career_event_version": expected_career_event_version,
    }
    defaults.update(overrides)
    return defaults


def create_event_signup_payload(event_session_id, student_id, **overrides) -> dict:
    defaults = {
        "event_session_id": event_session_id,
        "student_id": student_id,
    }
    defaults.update(overrides)
    return defaults


def create_document(doc_type="RESUME", file_uri=None, **overrides) -> dict:
    n = _next()
    doc = {
        "doc_type": doc_type,
        "file_uri": file_uri or f"s3://docs/doc-{n}.pdf",
    }
    doc.update(overrides)
    return doc


def create_application_payload(student_id, job_posting_id, submitted_documents=None,
                               **overrides) -> dict:
    defaults = {
        "student_id": student_id,
        "job_posting_id": job_posting_id,
        "submitted_documents": (
            submitted_documents if submitted_documents is not None else [create_document()]
        ),
    }
    defaults.update(overrides)
    return defaults


def create_interview_payload(**overrides) -> dict:
    defaults = {
        "interviewer_email": "int@acme.com",
        "mode": "VIRTUAL",
        "starts_at": "2026-10-05T10:00:00Z",
        "ends_at": "2026-10-05T11:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_outreach_message_payload(employer_id, student_id, **overrides) -> dict:
    n = _next()
    defaults = {
        "employer_id": employer_id,
        "student_id": student_id,
        "body": f"Opportunity {n}",
    }
    defaults.update(overrides)
    return defaults
