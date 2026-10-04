"""Payload factories — input-sourced fields only, one per entity."""
import itertools

from .constants import BASE_EXAM_FEE_CENTS

_counter = itertools.count(1)


def unique_suffix() -> str:
    """A short token so codes stay unique within a single test."""
    return f"{next(_counter):04d}"


def unique_school_code() -> str:
    return f"SC{next(_counter):04d}"


def unique_center_code() -> str:
    return f"{next(_counter):04d}"


def create_school_payload(**overrides) -> dict:
    token = unique_suffix()
    defaults = {
        "name": f"Test High {token}",
        "school_code": f"TS{token}",
        "country_code": "US",
        "center_code": f"9{token}",
        "seat_capacity": 10,
    }
    defaults.update(overrides)
    return defaults


def create_course_audit_payload(school_id, **overrides) -> dict:
    defaults = {
        "school_id": school_id,
        "course_title": "AP Calculus AB",
        "syllabus_hash": f"hash-{unique_suffix()}",
        "submitted_by_user_id": "coordinator-submitter",
    }
    defaults.update(overrides)
    return defaults


def create_student_payload(school_id, **overrides) -> dict:
    token = unique_suffix()
    defaults = {
        "full_name": f"Student {token}",
        "school_id": school_id,
        "student_code": f"ST{token}",
        "grade_level": 12,
    }
    defaults.update(overrides)
    return defaults


def create_exam_order_payload(school_id, course_audit_id, **overrides) -> dict:
    defaults = {
        "school_id": school_id,
        "course_audit_id": course_audit_id,
        "administration_year": 2027,
    }
    defaults.update(overrides)
    return defaults


def create_exam_registration_payload(exam_order_id, student_id, **overrides) -> dict:
    defaults = {
        "exam_order_id": exam_order_id,
        "student_id": student_id,
        "exam_subject": "AP-CALC-AB",
        "registration_tier": "REGULAR",
    }
    defaults.update(overrides)
    return defaults


def create_accommodation_request_payload(student_id, **overrides) -> dict:
    defaults = {
        "student_id": student_id,
        "exam_subject": "AP-CALC-AB",
        "accommodation_type": "EXTENDED_TIME",
        "documentation_completeness": 3,
        "submitted_by_user_id": "coordinator-submitter",
    }
    defaults.update(overrides)
    return defaults


def create_alternate_exam_request_payload(exam_registration_id, **overrides) -> dict:
    defaults = {
        "exam_registration_id": exam_registration_id,
        "alternate_date_utc": "2027-05-10T09:00:00Z",
        "reason_code": "SCHEDULE_CONFLICT",
        "form_code": "ALT-FORM-1",
    }
    defaults.update(overrides)
    return defaults


def create_material_shipment_payload(school_id, exam_order_id, **overrides) -> dict:
    token = unique_suffix()
    defaults = {
        "school_id": school_id,
        "exam_order_id": exam_order_id,
        "carrier_tracking_id": f"TRK-{token}",
        "seal_number": f"SEAL-{token}",
    }
    defaults.update(overrides)
    return defaults


def create_reader_payload(**overrides) -> dict:
    token = unique_suffix()
    defaults = {
        "full_name": f"Reader {token}",
        "subject_expertise": "AP-CALC-AB",
    }
    defaults.update(overrides)
    return defaults


def create_exam_score_payload(exam_registration_id, **overrides) -> dict:
    defaults = {
        "exam_registration_id": exam_registration_id,
        "raw_composite": 96.0,
    }
    defaults.update(overrides)
    return defaults


def create_score_send_payload(exam_score_id, **overrides) -> dict:
    defaults = {
        "exam_score_id": exam_score_id,
        "recipient_type": "COLLEGE",
        "recipient_code": f"C{unique_suffix()}",
        "designation_year": 2027,
    }
    defaults.update(overrides)
    return defaults


def create_irregularity_case_payload(exam_registration_id, school_id, **overrides) -> dict:
    defaults = {
        "exam_registration_id": exam_registration_id,
        "school_id": school_id,
        "irregularity_type": "UNAUTHORIZED_DEVICE",
    }
    defaults.update(overrides)
    return defaults


DEFAULTS = {
    "SEAT_CAPACITY": 10,
    "ADMINISTRATION_YEAR": 2027,
    "BASE_EXAM_FEE_CENTS": BASE_EXAM_FEE_CENTS,
    "SYLLABUS_HASH": "h-default-1",
    "DECISION_NOTES": "syllabus meets the curricular requirements",
}
