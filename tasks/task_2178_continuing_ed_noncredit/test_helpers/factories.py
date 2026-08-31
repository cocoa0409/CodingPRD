"""Payload factories - one per creatable resource, input fields only."""

from .constants import (
    BASE_STIPEND_CENTS,
    COURSE_EXT_101,
    DEFAULT_VOUCHER_EXPIRY,
    ENROLLMENT_CAP_FOR_PAY,
    FALL_CENSUS,
    FALL_END,
    FALL_START,
    FALL_TERM,
    PER_ENROLLMENT_CENTS,
)


def create_course_payload(**overrides) -> dict:
    payload = dict(COURSE_EXT_101)
    payload.update(overrides)
    return payload


def create_offering_payload(course_id: str, **overrides) -> dict:
    payload = {
        "course_id": course_id,
        "scheduling_mode": "TERM",
        "term_code": FALL_TERM,
        "start_date": FALL_START,
        "end_date": FALL_END,
        "census_at": FALL_CENSUS,
        "session_count": 10,
        "min_enrollment": 1,
        "max_enrollment": 10,
        "tuition_cents": 60000,
    }
    payload.update(overrides)
    return payload


def create_learner_payload(**overrides) -> dict:
    payload = {"email": "ada@x.com", "full_name": "Ada Ito", "marketing_opt_in": True}
    payload.update(overrides)
    return payload


def create_instructor_payload(**overrides) -> dict:
    payload = {
        "email": "dana@ext.edu",
        "full_name": "Dana Reyes",
        "credential_level": "SENIOR",
    }
    payload.update(overrides)
    return payload


def create_corporate_account_payload(**overrides) -> dict:
    payload = {"org_name": "ACME Industrial", "billing_email": "ap@acme.example"}
    payload.update(overrides)
    return payload


def create_deposit_payload(amount_cents: int) -> dict:
    return {"amount_cents": amount_cents}


def issue_voucher_payload(face_value_cents: int, expected_version: int, **overrides) -> dict:
    payload = {
        "face_value_cents": face_value_cents,
        "expires_at": DEFAULT_VOUCHER_EXPIRY,
        "expected_corporate_account_version": expected_version,
    }
    payload.update(overrides)
    return payload


def create_registration_payload(learner_id: str, expected_offering_version: int, **overrides) -> dict:
    payload = {
        "learner_id": learner_id,
        "expected_offering_version": expected_offering_version,
    }
    payload.update(overrides)
    return payload


def pay_payload(method: str = "SELF_PAY", voucher_id: str = None) -> dict:
    payload = {"method": method}
    if voucher_id is not None:
        payload["voucher_id"] = voucher_id
    return payload


def create_instructor_contract_payload(offering_id: str, instructor_id: str, **overrides) -> dict:
    payload = {
        "offering_id": offering_id,
        "instructor_id": instructor_id,
        "base_stipend_cents": BASE_STIPEND_CENTS,
        "per_enrollment_cents": PER_ENROLLMENT_CENTS,
        "enrollment_cap_for_pay": ENROLLMENT_CAP_FOR_PAY,
    }
    payload.update(overrides)
    return payload


def create_refund_transfer_payload(registration_id: str, request_type: str = "REFUND", **overrides) -> dict:
    payload = {"registration_id": registration_id, "request_type": request_type}
    payload.update(overrides)
    return payload


def create_petition_payload(learner_id: str, target_course_id: str) -> dict:
    return {"learner_id": learner_id, "target_course_id": target_course_id}


def create_citation_payload(completion_record_id: str, weight: float = 1.0) -> dict:
    return {"completion_record_id": completion_record_id, "weight": weight}
