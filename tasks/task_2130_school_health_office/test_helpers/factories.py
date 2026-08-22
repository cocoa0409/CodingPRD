"""Payload factories — one per creatable record family, input fields only."""

import itertools

from .constants import TEST_DEFAULTS

_code_counter = itertools.count(1)


def unique_building_code(prefix: str = "BLD") -> str:
    """A 2-8 character uppercase alphanumeric building code, unique per process."""
    return f"{prefix}{next(_code_counter):03d}"[:8].upper()


def school_payload(**overrides) -> dict:
    payload = {
        "name": "Test Elementary",
        "building_code": unique_building_code(),
        "cot_capacity": TEST_DEFAULTS["COT_CAPACITY"],
        "emergency_protocol_enabled": True,
    }
    payload.update(overrides)
    return payload


def nurse_payload(**overrides) -> dict:
    payload = {
        "full_name": "Rita Nolan",
        "credential": "RN",
        "weekly_contracted_minutes": TEST_DEFAULTS["NURSE_MINUTES"],
        "delegation_authorized": False,
    }
    payload.update(overrides)
    return payload


def coverage_assignment_payload(nurse_id: str, school_id: str, **overrides) -> dict:
    payload = {
        "nurse_id": nurse_id,
        "school_id": school_id,
        "weekday": "MON",
        "start_minute": TEST_DEFAULTS["BLOCK_START_MINUTE"],
        "end_minute": TEST_DEFAULTS["BLOCK_END_MINUTE"],
        "effective_from": TEST_DEFAULTS["COVERAGE_EFFECTIVE_FROM"],
    }
    payload.update(overrides)
    return payload


def student_payload(school_id: str, **overrides) -> dict:
    payload = {
        "school_id": school_id,
        "full_name": "Ann Reed",
        "grade_level": 3,
        "date_of_birth": "2017-04-11T00:00:00Z",
        "allergy_severity": "NONE",
        "chronic_condition_codes": [],
        "immunization_status": "COMPLIANT",
    }
    payload.update(overrides)
    return payload


def action_plan_payload(student_id: str, expected_student_version: int, **overrides) -> dict:
    payload = {
        "student_id": student_id,
        "condition_code": "ASTHMA",
        "severity_score": 3,
        "requires_stock_epinephrine": False,
        "self_carry_requested": False,
        "effective_from": "2026-08-01T00:00:00Z",
        "expected_student_version": expected_student_version,
    }
    payload.update(overrides)
    return payload


def medication_authorization_payload(student_id: str, **overrides) -> dict:
    payload = {
        "student_id": student_id,
        "medication_code": "ALBUTEROL",
        "route": "INHALED",
        "dose_amount": 2,
        "dose_unit": "PUFF",
        "schedule_type": "SCHEDULED",
        "max_doses_per_day": 2,
        "valid_from": TEST_DEFAULTS["ORDER_VALID_FROM"],
        "valid_until": TEST_DEFAULTS["ORDER_VALID_UNTIL"],
    }
    payload.update(overrides)
    return payload


def stock_lot_payload(school_id: str, **overrides) -> dict:
    payload = {
        "school_id": school_id,
        "medication_code": "ALBUTEROL",
        "lot_number": "LOT-0001",
        "is_stock_protocol": False,
        "initial_quantity": 5,
        "expiration_date": TEST_DEFAULTS["LOT_EXPIRATION"],
    }
    payload.update(overrides)
    return payload


def health_visit_payload(student_id: str, school_id: str, nurse_id: str, **overrides) -> dict:
    payload = {
        "student_id": student_id,
        "school_id": school_id,
        "nurse_id": nurse_id,
        "complaint_code": "ILLNESS",
        "acuity": "ROUTINE",
    }
    payload.update(overrides)
    return payload


def administration_record_payload(visit_id: str, authorization_id: str,
                                  expected_authorization_version: int, **overrides) -> dict:
    payload = {
        "visit_id": visit_id,
        "authorization_id": authorization_id,
        "units": 1,
        "expected_authorization_version": expected_authorization_version,
    }
    payload.update(overrides)
    return payload


def stock_emergency_payload(visit_id: str, medication_code: str = "EPINEPHRINE", **overrides) -> dict:
    payload = {"visit_id": visit_id, "medication_code": medication_code, "units": 1}
    payload.update(overrides)
    return payload


def screening_payload(student_id: str, school_id: str, **overrides) -> dict:
    payload = {
        "student_id": student_id,
        "school_id": school_id,
        "screening_type": "VISION",
        "scheduled_for": "2026-08-03T10:00:00Z",
    }
    payload.update(overrides)
    return payload


def disclosure_request_payload(student_id: str, **overrides) -> dict:
    payload = {
        "student_id": student_id,
        "requester_type": "EXTERNAL_PROVIDER",
        "requester_reference": "Northside Pediatrics",
        "scope": ["VISITS"],
        "purpose_code": "TREATMENT",
    }
    payload.update(overrides)
    return payload
