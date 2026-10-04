"""Payload factories — one per writable endpoint, input fields only."""
from typing import Optional

from .constants import (
    AUDIT_SCHEDULED_DATE,
    DEFAULT_DATE_OF_BIRTH,
    DEFAULT_TOTAL_SCORED_ITEMS,
    DOC_EXPIRY_VALID,
    SESSION_END_TIME,
    SESSION_START_TIME,
    TEST_DATE,
)


def create_test_center_payload(
    name: str = "Test Center",
    facility_seat_capacity: int = 20,
    equipment_list: Optional[list] = None,
    **overrides,
) -> dict:
    payload = {
        "name": name,
        "facility_seat_capacity": facility_seat_capacity,
        "equipment_list": equipment_list if equipment_list is not None else ["computers"],
    }
    payload.update(overrides)
    return payload


def create_audit_payload(
    scheduled_date: str = AUDIT_SCHEDULED_DATE,
    audit_type: str = "ANNOUNCED",
    **overrides,
) -> dict:
    payload = {"scheduled_date": scheduled_date, "audit_type": audit_type}
    payload.update(overrides)
    return payload


def complete_audit_payload(
    facility_findings: int = 1,
    staffing_findings: int = 1,
    equipment_findings: int = 2,
    high_severity_findings: int = 0,
    **overrides,
) -> dict:
    payload = {
        "facility_findings": facility_findings,
        "staffing_findings": staffing_findings,
        "equipment_findings": equipment_findings,
        "high_severity_findings": high_severity_findings,
    }
    payload.update(overrides)
    return payload


def create_staff_payload(
    full_name: str = "Staff Member",
    staff_role: str = "PROCTOR",
    certification_level: str = "BASIC",
    **overrides,
) -> dict:
    payload = {
        "full_name": full_name,
        "staff_role": staff_role,
        "certification_level": certification_level,
    }
    payload.update(overrides)
    return payload


def create_session_payload(
    test_date: str = TEST_DATE,
    start_time: str = SESSION_START_TIME,
    end_time: str = SESSION_END_TIME,
    room_label: str = "R1",
    total_seats: int = 5,
    reserved_accommodation_seats: int = 0,
    **overrides,
) -> dict:
    payload = {
        "test_date": test_date,
        "start_time": start_time,
        "end_time": end_time,
        "room_label": room_label,
        "total_seats": total_seats,
        "reserved_accommodation_seats": reserved_accommodation_seats,
    }
    payload.update(overrides)
    return payload


def create_examinee_payload(
    full_name: str = "Ex Aminee",
    date_of_birth: str = DEFAULT_DATE_OF_BIRTH,
    id_document_type: str = "PASSPORT",
    id_document_number: str = "P0001",
    id_document_expiry: str = DOC_EXPIRY_VALID,
    **overrides,
) -> dict:
    payload = {
        "full_name": full_name,
        "date_of_birth": date_of_birth,
        "id_document_type": id_document_type,
        "id_document_number": id_document_number,
        "id_document_expiry": id_document_expiry,
    }
    payload.update(overrides)
    return payload


def create_accommodation_request_payload(
    accommodation_type: str = "EXTENDED_TIME", **overrides
) -> dict:
    payload = {"accommodation_type": accommodation_type}
    payload.update(overrides)
    return payload


def decide_accommodation_payload(decision: str = "APPROVED", **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def create_registration_payload(
    examinee_id: str, expected_session_version: int, **overrides
) -> dict:
    payload = {
        "examinee_id": examinee_id,
        "expected_session_version": expected_session_version,
    }
    payload.update(overrides)
    return payload


def create_check_in_payload(
    id_document_number: str,
    id_document_expiry: str,
    biometric_sample: str = "bio-sample",
    **overrides,
) -> dict:
    payload = {
        "id_document_number": id_document_number,
        "id_document_expiry": id_document_expiry,
        "biometric_sample": biometric_sample,
    }
    payload.update(overrides)
    return payload


def create_irregularity_payload(
    registration_id: str,
    category: str = "SEATING_VIOLATION",
    severity: str = "LOW",
    narrative: str = "Observed irregularity.",
    **overrides,
) -> dict:
    payload = {
        "registration_id": registration_id,
        "category": category,
        "severity": severity,
        "narrative": narrative,
    }
    payload.update(overrides)
    return payload


def resolve_irregularity_payload(resolution: str = "DISMISSED", **overrides) -> dict:
    payload = {"resolution": resolution}
    payload.update(overrides)
    return payload


def create_score_entry_payload(
    section_raws=None,
    prior_best_scaled_score: int = 30,
    matched_responses_count: int = 0,
    total_scored_items: int = DEFAULT_TOTAL_SCORED_ITEMS,
    same_form: bool = True,
    adjacent_seated: bool = False,
    **overrides,
) -> dict:
    payload = {
        "section_raws": section_raws if section_raws is not None else [10, 10, 10],
        "prior_best_scaled_score": prior_best_scaled_score,
        "matched_responses_count": matched_responses_count,
        "total_scored_items": total_scored_items,
        "same_form": same_form,
        "adjacent_seated": adjacent_seated,
    }
    payload.update(overrides)
    return payload


def run_analysis_payload(session_id: str, **overrides) -> dict:
    payload = {"session_id": session_id}
    payload.update(overrides)
    return payload


def respond_case_payload(response_text: str = "Written response.", **overrides) -> dict:
    payload = {"response_text": response_text}
    payload.update(overrides)
    return payload


def adjudicate_case_payload(
    outcome: str = "UPHELD",
    rationale: str = "Adjudication rationale.",
    expected_case_version: int = 1,
    **overrides,
) -> dict:
    payload = {
        "outcome": outcome,
        "rationale": rationale,
        "expected_case_version": expected_case_version,
    }
    payload.update(overrides)
    return payload


def create_score_report_payload(institution_code: str = "MIT2026", **overrides) -> dict:
    payload = {"institution_code": institution_code}
    payload.update(overrides)
    return payload


def set_clock_payload(to_iso8601: str, **overrides) -> dict:
    payload = {"to_iso8601": to_iso8601}
    payload.update(overrides)
    return payload
