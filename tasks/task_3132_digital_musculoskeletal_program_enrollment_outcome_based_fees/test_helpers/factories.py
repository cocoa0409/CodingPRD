"""Payload factories — one per entity, input fields only."""
from .constants import TEST_DEFAULTS

DEFAULTS = {
    "LEGAL_NAME": "Halewood Utilities",
    "CLIENT_TYPE": "HEALTH_PLAN",
    "FULL_NAME": "Dana Whitfield",
    "LICENSE_NUMBER": "PT-88123",
    "MEMBER_FULL_NAME": "Ilse Marchetti",
    "EXTERNAL_MEMBER_REF": "HW-0001",
    "DATE_OF_BIRTH": "1980-05-05T00:00:00Z",
    "CONDITION_CODE": "KNEE_OA",
    "BASELINE_PAIN": 6.5,
    "BASELINE_FUNCTION": 53.0,
}


def create_client_payload(**overrides) -> dict:
    defaults = {
        "legal_name": DEFAULTS["LEGAL_NAME"],
        "client_type": DEFAULTS["CLIENT_TYPE"],
    }
    defaults.update(overrides)
    return defaults


def create_program_track_payload(track_code="ACUTE", base_fee_per_member_cents=9000,
                                 **overrides) -> dict:
    defaults = {
        "track_code": track_code,
        "base_fee_per_member_cents": base_fee_per_member_cents,
        "expected_sessions_per_week": 3,
        "pain_reduction_target_points": 2.0,
        "function_gain_target_points": 15.0,
        "min_adherence_rate": TEST_DEFAULTS["MIN_ADHERENCE_RATE"],
        "severity_weights": dict(TEST_DEFAULTS["SEVERITY_WEIGHTS"]),
    }
    defaults.update(overrides)
    return defaults


def create_eligibility_file_payload(client_account_id: str, **overrides) -> dict:
    defaults = {
        "client_account_id": client_account_id,
        "file_period": TEST_DEFAULTS["FILE_PERIOD"],
        "roster_format": TEST_DEFAULTS["ROSTER_FORMAT"],
    }
    defaults.update(overrides)
    return defaults


def create_member_payload(client_account_id: str, eligibility_file_id: str,
                          **overrides) -> dict:
    defaults = {
        "client_account_id": client_account_id,
        "eligibility_file_id": eligibility_file_id,
        "external_member_ref": DEFAULTS["EXTERNAL_MEMBER_REF"],
        "full_name": DEFAULTS["MEMBER_FULL_NAME"],
        "date_of_birth": DEFAULTS["DATE_OF_BIRTH"],
        "musculo_condition_code": DEFAULTS["CONDITION_CODE"],
        "baseline_pain_score": DEFAULTS["BASELINE_PAIN"],
        "baseline_function_score": DEFAULTS["BASELINE_FUNCTION"],
    }
    defaults.update(overrides)
    return defaults


def create_enrollment_payload(member_id: str, **overrides) -> dict:
    defaults = {"member_id": member_id}
    defaults.update(overrides)
    return defaults


def create_clinical_review_payload(enrollment_id: str, reviewer_id: str, **overrides) -> dict:
    defaults = {
        "enrollment_id": enrollment_id,
        "reviewer_id": reviewer_id,
        "review_notes": "Clinical note",
    }
    defaults.update(overrides)
    return defaults


def conduct_review_payload(reviewed_track_id: str, review_decision="APPROVE", **overrides) -> dict:
    defaults = {
        "review_decision": review_decision,
        "reviewed_track_id": reviewed_track_id,
    }
    defaults.update(overrides)
    return defaults


def approve_transition_payload(approving_clinician_id: str,
                               expected_eligibility_file_version=None, **overrides) -> dict:
    defaults = {"approving_clinician_id": approving_clinician_id}
    if expected_eligibility_file_version is not None:
        defaults["expected_eligibility_file_version"] = expected_eligibility_file_version
    defaults.update(overrides)
    return defaults


def deny_transition_payload(approving_clinician_id: str, **overrides) -> dict:
    defaults = {"approving_clinician_id": approving_clinician_id}
    defaults.update(overrides)
    return defaults


def create_session_payload(**overrides) -> dict:
    defaults = {
        "session_date": "2026-09-08T09:00:00Z",
        "session_week": 1,
        "recorded_via": "SENSOR",
        "planned_reps": TEST_DEFAULTS["PLANNED_REPS"],
        "planned_minutes": TEST_DEFAULTS["PLANNED_MINUTES"],
    }
    defaults.update(overrides)
    return defaults


def complete_session_payload(completed_denominator_units=1,
                             pain_score_after=TEST_DEFAULTS["PAIN_SCORE_AFTER"],
                             **overrides) -> dict:
    defaults = {
        "completed_denominator_units": completed_denominator_units,
        "pain_score_after": pain_score_after,
    }
    defaults.update(overrides)
    return defaults


def create_outreach_payload(enrollment_id: str, contact_week=1, channel="PUSH",
                            **overrides) -> dict:
    defaults = {
        "enrollment_id": enrollment_id,
        "contact_week": contact_week,
        "channel": channel,
    }
    defaults.update(overrides)
    return defaults


def create_clinician_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["FULL_NAME"],
        "discipline": "PHYSICAL_THERAPIST",
        "license_number": DEFAULTS["LICENSE_NUMBER"],
        "weekly_capacity_slots": TEST_DEFAULTS["WEEKLY_CAPACITY_SLOTS"],
    }
    defaults.update(overrides)
    return defaults


def create_appointment_payload(enrollment_id: str, clinician_id: str, **overrides) -> dict:
    defaults = {
        "enrollment_id": enrollment_id,
        "clinician_id": clinician_id,
        "appointment_date": "2026-09-08T00:00:00Z",
        "start_minute": 540,
        "duration_minutes": 60,
        "slot_type": "INITIAL_CONSULT",
    }
    defaults.update(overrides)
    return defaults


def create_measurement_payload(enrollment_id: str, **overrides) -> dict:
    defaults = {
        "enrollment_id": enrollment_id,
        "measurement_week": 4,
        "pain_score": 5.0,
        "function_score": 65.0,
    }
    defaults.update(overrides)
    return defaults


def create_claim_line_payload(enrollment_id: str, **overrides) -> dict:
    defaults = {
        "enrollment_id": enrollment_id,
        "claim_service_date": "2026-09-14T00:00:00Z",
        "claim_service_week": 2,
        "claim_severity": "HIGH",
        "amount_cents": 250000,
        "claim_source": "MEDICAL",
    }
    defaults.update(overrides)
    return defaults


def create_invoice_payload(client_account_id: str, **overrides) -> dict:
    defaults = {
        "client_account_id": client_account_id,
        "billing_period": TEST_DEFAULTS["FILE_PERIOD"],
    }
    defaults.update(overrides)
    return defaults