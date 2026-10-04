"""Payload factories — one per creatable resource, input fields only."""
from .constants import (
    COUNSELOR_USER_ID,
    ELIGIBLE_DOB,
    ELIGIBLE_HOUSEHOLD_SIZE,
    ELIGIBLE_INCOME_CENTS,
)


def create_applicant_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Student",
        "date_of_birth": ELIGIBLE_DOB,
        "home_region_code": "R-NORTH",
        "desired_trade_code": "WELDING",
    }
    defaults.update(overrides)
    return defaults


def create_application_payload(applicant_id, expected_applicant_version,
                               **overrides) -> dict:
    defaults = {
        "applicant_id": applicant_id,
        "household_size": ELIGIBLE_HOUSEHOLD_SIZE,
        "annual_income_cents": ELIGIBLE_INCOME_CENTS,
        "barrier_flags": ["FOSTER_CARE"],
        "expected_applicant_version": expected_applicant_version,
    }
    defaults.update(overrides)
    return defaults


def create_center_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Center",
        "region_code": "R-NORTH",
        "total_beds": 2,
    }
    defaults.update(overrides)
    return defaults


def create_trade_program_payload(center_id, **overrides) -> dict:
    defaults = {
        "center_id": center_id,
        "trade_code": "WELDING",
        "capacity": 5,
    }
    defaults.update(overrides)
    return defaults


def create_enrollment_payload(applicant_id, trade_program_id, **overrides) -> dict:
    defaults = {
        "applicant_id": applicant_id,
        "trade_program_id": trade_program_id,
        "residential_track": False,
    }
    defaults.update(overrides)
    return defaults


def create_dormitory_assignment_payload(enrollment_id, **overrides) -> dict:
    defaults = {
        "enrollment_id": enrollment_id,
        "move_in_date": "2026-09-01",
    }
    defaults.update(overrides)
    return defaults


def create_conduct_incident_payload(enrollment_id, **overrides) -> dict:
    defaults = {
        "enrollment_id": enrollment_id,
        "infraction_code": "THEFT",
        "occurred_at": "2026-08-20",
    }
    defaults.update(overrides)
    return defaults


def create_credential_payload(enrollment_id, **overrides) -> dict:
    defaults = {
        "enrollment_id": enrollment_id,
        "credential_type": "HSE",
    }
    defaults.update(overrides)
    return defaults


def create_employer_agreement_payload(**overrides) -> dict:
    defaults = {
        "employer_name": "Test Employer LLC",
        "trade_code": "WELDING",
        "region_code": "R-NORTH",
        "slot_count": 2,
        "hourly_wage_floor_cents": 100000,
        "effective_start": "2026-01-01",
        "effective_end": "2026-12-31",
    }
    defaults.update(overrides)
    return defaults


def create_wbl_placement_payload(enrollment_id, employer_agreement_id,
                                 **overrides) -> dict:
    defaults = {
        "enrollment_id": enrollment_id,
        "employer_agreement_id": employer_agreement_id,
        "supervisor_id": "sup-1",
        "hourly_wage_cents": 120000,
    }
    defaults.update(overrides)
    return defaults


def create_operator_contract_payload(center_id, **overrides) -> dict:
    defaults = {
        "center_id": center_id,
        "operator_name": "Test Operator Co",
        "contract_code": "K-DEFAULT",
    }
    defaults.update(overrides)
    return defaults


def center_assignment_payload(expected_applicant_version, **overrides) -> dict:
    defaults = {
        "expected_applicant_version": expected_applicant_version,
        "residential_track": False,
    }
    defaults.update(overrides)
    return defaults


DEFAULT_COUNSELOR_ID = COUNSELOR_USER_ID
