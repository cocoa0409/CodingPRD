"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "CARRIER_LEGAL_NAME": "Redline Freight LLC",
    "CARRIER_DOT_NUMBER": "DOT-2166-A",
    "CARRIER_OPEN_REQUISITIONS": 5,
    "APPLICANT_FULL_NAME": "Dana Ruiz",
    "APPLICANT_DOB": "1988-04-12",
    "APPLICANT_EMAIL": "dana.ruiz@example.com",
    "APPLICANT_CDL_NUMBER": "CDL-77120",
    "APPLICANT_CDL_STATE": "TX",
    "APPLICANT_CDL_CLASS": "CLASS_A",
    "APPLICANT_EXPERIENCE_MONTHS": 24,
    "EMPLOYER_NAME": "Blue Line Cartage",
    "SCHOOL_NAME": "Prairie CDL Academy",
    "LOCATION_CODE": "DAL-1",
}


def create_carrier_payload(**overrides) -> dict:
    payload = {
        "legal_name": DEFAULTS["CARRIER_LEGAL_NAME"],
        "dot_number": DEFAULTS["CARRIER_DOT_NUMBER"],
        "open_requisitions": DEFAULTS["CARRIER_OPEN_REQUISITIONS"],
        "safety_rating": "SATISFACTORY",
        "mvr_validity_days": 365,
        "annual_review_interval_days": 365,
        "annual_review_grace_days": 30,
        "mvr_point_threshold": 7,
        "rehire_cooldown_days": 180,
        "medical_cert_grace_days": 15,
    }
    payload.update(overrides)
    return payload


def create_driver_applicant_payload(carrier_id: str, **overrides) -> dict:
    payload = {
        "carrier_id": carrier_id,
        "full_name": DEFAULTS["APPLICANT_FULL_NAME"],
        "date_of_birth": DEFAULTS["APPLICANT_DOB"],
        "email": DEFAULTS["APPLICANT_EMAIL"],
        "cdl_number": DEFAULTS["APPLICANT_CDL_NUMBER"],
        "cdl_state": DEFAULTS["APPLICANT_CDL_STATE"],
        "cdl_class": DEFAULTS["APPLICANT_CDL_CLASS"],
        "experience_months": DEFAULTS["APPLICANT_EXPERIENCE_MONTHS"],
    }
    payload.update(overrides)
    return payload


def create_driver_application_payload(applicant_id: str, **overrides) -> dict:
    payload = {"applicant_id": applicant_id, "position_type": "OTR"}
    payload.update(overrides)
    return payload


def create_employment_verification_payload(application_id: str, **overrides) -> dict:
    payload = {
        "application_id": application_id,
        "employer_name": DEFAULTS["EMPLOYER_NAME"],
        "is_dot_regulated": True,
        "employed_from": "2022-01-01",
        "employed_to": "2024-09-01",
    }
    payload.update(overrides)
    return payload


def record_verification_response_payload(**overrides) -> dict:
    payload = {
        "outcome": "VERIFIED",
        "safety_performance_history_received": True,
        "drug_alcohol_violation_reported": False,
    }
    payload.update(overrides)
    return payload


def create_screening_check_payload(application_id: str, check_type: str = "MVR") -> dict:
    return {"application_id": application_id, "check_type": check_type}


def record_screening_result_payload(**overrides) -> dict:
    payload = {
        "issued_on": "2026-07-01",
        "violation_points": 0,
        "serious_violation_count": 0,
        "crash_preventable_count": 0,
    }
    payload.update(overrides)
    return payload


def create_clearinghouse_query_payload(application_id: str, query_type: str = "FULL") -> dict:
    return {"application_id": application_id, "query_type": query_type}


def create_drug_test_order_payload(application_id: str, test_type: str = "PRE_EMPLOYMENT") -> dict:
    return {"application_id": application_id, "test_type": test_type}


def create_road_test_payload(application_id: str, **overrides) -> dict:
    payload = {
        "application_id": application_id,
        "examiner_user_id": "exam-501",
        "scheduled_at": "2026-08-05T14:00:00Z",
        "vehicle_class": "CLASS_A",
    }
    payload.update(overrides)
    return payload


def record_road_test_result_payload(**overrides) -> dict:
    payload = {
        "outcome": "PASSED",
        "score_pretrip": 90,
        "score_skills": 86,
        "score_road": 78,
    }
    payload.update(overrides)
    return payload


def create_orientation_session_payload(carrier_id: str, **overrides) -> dict:
    payload = {
        "carrier_id": carrier_id,
        "starts_at": "2026-08-10T13:00:00Z",
        "ends_at": "2026-08-12T21:00:00Z",
        "capacity": 2,
        "location_code": DEFAULTS["LOCATION_CODE"],
    }
    payload.update(overrides)
    return payload


def create_orientation_enrollment_payload(
    session_id: str, application_id: str, expected_session_version: int
) -> dict:
    return {
        "session_id": session_id,
        "application_id": application_id,
        "expected_session_version": expected_session_version,
    }


def update_dq_document_payload(status: str, expected_dq_file_version: int, **overrides) -> dict:
    payload = {"status": status, "expected_dq_file_version": expected_dq_file_version}
    payload.update(overrides)
    return payload


def create_tuition_agreement_payload(applicant_id: str, **overrides) -> dict:
    payload = {
        "applicant_id": applicant_id,
        "school_name": DEFAULTS["SCHOOL_NAME"],
        "tuition_total_cents": 115205,
        "commitment_months": 12,
    }
    payload.update(overrides)
    return payload


def create_hire_record_payload(application_id: str, expected_carrier_version: int, **overrides) -> dict:
    payload = {
        "application_id": application_id,
        "hired_on": "2026-08-13",
        "expected_carrier_version": expected_carrier_version,
    }
    payload.update(overrides)
    return payload


def terminate_hire_record_payload(**overrides) -> dict:
    payload = {
        "terminated_on": "2026-08-20",
        "termination_type": "VOLUNTARY",
        "rehire_flag": "ELIGIBLE",
    }
    payload.update(overrides)
    return payload
