"""Payload factories — one per entity, input fields only."""
import itertools

_counter = itertools.count(1)


def _seq() -> int:
    return next(_counter)


def create_institution_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "name": f"Test Institution {n}",
        "residency_region": "US",
    }
    defaults.update(overrides)
    return defaults


def create_lms_integration_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "provider": "CANVAS",
        "external_key": f"ext-key-{n}",
    }
    defaults.update(overrides)
    return defaults


def create_instructor_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "email": f"instructor{n}@example.edu",
        "full_name": f"Professor {n}",
    }
    defaults.update(overrides)
    return defaults


def create_student_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "external_lms_id": f"lms-student-{n}",
        "email": f"student{n}@example.edu",
        "full_name": f"Student {n}",
        "home_region": "US",
    }
    defaults.update(overrides)
    return defaults


def create_assignment_payload(instructor_id: str, **overrides) -> dict:
    n = _seq()
    defaults = {
        "instructor_id": instructor_id,
        "title": f"Assignment {n}",
        "due_at": "2027-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_submission_payload(student_id: str, content_text: str, **overrides) -> dict:
    defaults = {
        "student_id": student_id,
        "content_text": content_text,
    }
    defaults.update(overrides)
    return defaults


def create_source_document_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "source_type": "INTERNET",
        "uri": f"https://sources.example/{n}",
        "region": "US",
    }
    defaults.update(overrides)
    return defaults


def create_match_fragment_payload(submission_id: str, source_document_id: str, **overrides) -> dict:
    defaults = {
        "submission_id": submission_id,
        "source_document_id": source_document_id,
        "matched_word_count": 5,
        "match_category": "DIRECT_QUOTE",
        "offset_start": 0,
    }
    defaults.update(overrides)
    return defaults


def create_retention_policy_payload(**overrides) -> dict:
    defaults = {
        "region": "US",
        "applies_to": "SUBMISSIONS",
        "retention_start": "2026-01-01T00:00:00Z",
        "retention_end": "2026-06-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_grade_entry_payload(**overrides) -> dict:
    defaults = {
        "score_points": 50,
    }
    defaults.update(overrides)
    return defaults


def words(n: int) -> str:
    """Exactly n whitespace-separated tokens (PRD §3.4 word_count semantics)."""
    return " ".join(["w"] * n)
