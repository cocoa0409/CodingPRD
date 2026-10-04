"""Payload factories — one per request body, input fields only."""
from .constants import TEST_DEFAULTS


def partner_payload(**overrides) -> dict:
    payload = {
        "legal_name": TEST_DEFAULTS["PARTNER_LEGAL_NAME"],
        "industry": TEST_DEFAULTS["PARTNER_INDUSTRY"],
        "billing_email": TEST_DEFAULTS["PARTNER_BILLING_EMAIL"],
        "fee_tier": TEST_DEFAULTS["PARTNER_FEE_TIER"],
    }
    payload.update(overrides)
    return payload


def student_payload(**overrides) -> dict:
    payload = {
        "full_name": TEST_DEFAULTS["STUDENT_FULL_NAME"],
        "email": TEST_DEFAULTS["STUDENT_EMAIL"],
        "date_of_birth": TEST_DEFAULTS["STUDENT_DOB"],
        "education_status": TEST_DEFAULTS["STUDENT_EDUCATION"],
        "household_income_cents": TEST_DEFAULTS["STUDENT_INCOME_CENTS"],
    }
    payload.update(overrides)
    return payload


def cohort_payload(**overrides) -> dict:
    payload = {
        "program_code": TEST_DEFAULTS["COHORT_PROGRAM_CODE"],
        "location_code": TEST_DEFAULTS["COHORT_LOCATION_CODE"],
        "start_date": TEST_DEFAULTS["COHORT_START_DATE"],
        "capacity": 24,
    }
    payload.update(overrides)
    return payload


def agreement_payload(partner_id: str, **overrides) -> dict:
    payload = {
        "partner_id": partner_id,
        "project_scope": TEST_DEFAULTS["AGREEMENT_PROJECT_SCOPE"],
        "supervision_hours_per_week": TEST_DEFAULTS["AGREEMENT_SUPERVISION_HOURS"],
        "slot_count": TEST_DEFAULTS["AGREEMENT_SLOT_COUNT"],
        "fee_tier": TEST_DEFAULTS["PARTNER_FEE_TIER"],
        "start_date": TEST_DEFAULTS["AGREEMENT_START_DATE"],
        "end_date": TEST_DEFAULTS["AGREEMENT_END_DATE"],
    }
    payload.update(overrides)
    return payload


def activation_payload(expected_partner_version: int, **overrides) -> dict:
    payload = {"expected_partner_version": expected_partner_version}
    payload.update(overrides)
    return payload


def eligibility_decision_payload(**overrides) -> dict:
    payload = {"decision": "ELIGIBLE"}
    payload.update(overrides)
    return payload


def enrollment_payload(cohort_id: str, **overrides) -> dict:
    payload = {
        "cohort_id": cohort_id,
        "track_code": TEST_DEFAULTS["COHORT_PROGRAM_CODE"],
    }
    payload.update(overrides)
    return payload


def placement_payload(agreement_id: str, student_id: str, **overrides) -> dict:
    payload = {"agreement_id": agreement_id, "student_id": student_id}
    payload.update(overrides)
    return payload


def interview_payload(**overrides) -> dict:
    payload = {
        "scheduled_for": TEST_DEFAULTS["INTERVIEW_SLOT"],
        "duration_minutes": 45,
        "supervisor_name": TEST_DEFAULTS["SUPERVISOR_NAME"],
    }
    payload.update(overrides)
    return payload


def interview_outcome_payload(**overrides) -> dict:
    payload = {"outcome": "PASSED"}
    payload.update(overrides)
    return payload


def acceptance_payload(**overrides) -> dict:
    payload = {
        "start_date": TEST_DEFAULTS["ACCEPTED_START_DATE"],
        "end_date": TEST_DEFAULTS["ACCEPTED_END_DATE"],
        "hours_per_week": 20,
    }
    payload.update(overrides)
    return payload


def completion_payload(**overrides) -> dict:
    payload = {"outcome": "CONVERTED"}
    payload.update(overrides)
    return payload


def stipend_payload(student_id: str, **overrides) -> dict:
    payload = {
        "student_id": student_id,
        "phase": "L_AND_D",
        "period_start": "2026-09-07",
        "period_end": "2026-09-20",
        "hours_attended": 126,
        "hours_expected": 140,
        "behavior_incidents": 0,
    }
    payload.update(overrides)
    return payload


def satisfaction_payload(placement_id: str, **overrides) -> dict:
    payload = {
        "placement_id": placement_id,
        "supervisor_rating": 4.25,
        "project_rating": 3.15,
        "communication_rating": 2.05,
    }
    payload.update(overrides)
    return payload


def invoice_payload(partner_id: str, placement_id: str, expected_partner_version: int,
                    **overrides) -> dict:
    payload = {
        "partner_id": partner_id,
        "placement_id": placement_id,
        "due_date": "2027-02-01",
        "expected_partner_version": expected_partner_version,
    }
    payload.update(overrides)
    return payload


def invoice_payment_payload(**overrides) -> dict:
    payload = {"amount_paid_cents": 136339, "paid_on": "2026-11-01"}
    payload.update(overrides)
    return payload


def checkpoint_record_payload(**overrides) -> dict:
    payload = {"employment_status": "EMPLOYED", "hourly_wage_cents": 2200}
    payload.update(overrides)
    return payload


def credit_grant_payload(student_id: str, **overrides) -> dict:
    payload = {
        "student_id": student_id,
        "college_partner_name": "Bunker Hill Community College",
        "credit_hours": 48,
    }
    payload.update(overrides)
    return payload


def credit_grant_status_payload(**overrides) -> dict:
    payload = {"status": "GRANTED"}
    payload.update(overrides)
    return payload
