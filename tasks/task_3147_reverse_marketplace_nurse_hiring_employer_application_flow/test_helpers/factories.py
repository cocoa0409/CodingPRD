"""Payload factories — one per creatable entity, input fields only."""
import itertools

_COUNTER = itertools.count(1)


def _seq() -> int:
    return next(_COUNTER)


def unique_email(prefix: str = "nurse") -> str:
    return f"{prefix}{_seq()}@example.com"


def unique_license_number(prefix: str = "RN-CA") -> str:
    return f"{prefix}-{10000 + _seq()}"


def create_nurse_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Nurse",
        "email": unique_email(),
        "home_state": "CA",
        "primary_specialty": "ICU",
        "years_experience": 8,
        "desired_shift": "DAY",
        "desired_hourly_rate_cents": 7000,
        "max_commute_miles": 40,
        "current_employer_name": "",
    }
    defaults.update(overrides)
    return defaults


def create_license_verification_payload(nurse_id, **overrides) -> dict:
    defaults = {
        "nurse_id": nurse_id,
        "license_number": unique_license_number(),
        "license_state": "CA",
        "expiry_date": "2028-01-01",
    }
    defaults.update(overrides)
    return defaults


def create_certification_payload(nurse_id, **overrides) -> dict:
    defaults = {
        "nurse_id": nurse_id,
        "cert_code": "ACLS",
        "expires_on": "2027-06-01",
    }
    defaults.update(overrides)
    return defaults


def create_employer_payload(**overrides) -> dict:
    defaults = {
        "legal_name": f"Test Hospital {_seq()}",
        "facility_state": "CA",
        "fee_model": "PER_PLACEMENT",
        "subscription_tier": "BASIC",
        "sla_response_hours": 48,
        "guarantee_days": 60,
        "placement_fee_bps": 2000,
    }
    defaults.update(overrides)
    return defaults


def create_requisition_payload(employer_id, **overrides) -> dict:
    defaults = {
        "employer_id": employer_id,
        "specialty": "ICU",
        "unit_name": "ICU-4West",
        "required_certs": [],
        "facility_state": "CA",
        "distance_from_facility_miles": 20,
        "shift": "DAY",
        "offered_hourly_rate_cents": 8000,
        "openings_total": 2,
    }
    defaults.update(overrides)
    return defaults


def create_application_payload(requisition_id, nurse_id, expected_nurse_version, **overrides) -> dict:
    defaults = {
        "requisition_id": requisition_id,
        "nurse_id": nurse_id,
        "proposed_hourly_rate_cents": 8500,
        "proposed_shift": "DAY",
        "expected_nurse_version": expected_nurse_version,
    }
    defaults.update(overrides)
    return defaults


def create_interview_payload(**overrides) -> dict:
    defaults = {
        "starts_at": "2026-09-02T10:00:00Z",
        "ends_at": "2026-09-02T11:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_offer_payload(expected_requisition_version, **overrides) -> dict:
    defaults = {
        "offered_hourly_rate_cents": 8500,
        # 2026-10-15: satisfies "start_date must fall between 14 and 90 days
        # after the clock's current date at issuance" at every clock the
        # fixtures use (2026-09-01 and 2026-09-02T12:00:00Z).
        "start_date": "2026-10-15",
        "expected_requisition_version": expected_requisition_version,
    }
    defaults.update(overrides)
    return defaults


def create_screening_payload(application_id, **overrides) -> dict:
    defaults = {"application_id": application_id}
    defaults.update(overrides)
    return defaults


def create_document_payload(application_id, **overrides) -> dict:
    defaults = {
        "application_id": application_id,
        "doc_type": "SIGNED_CONTRACT",
    }
    defaults.update(overrides)
    return defaults
