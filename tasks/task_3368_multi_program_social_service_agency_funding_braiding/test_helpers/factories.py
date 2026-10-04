"""Payload factories — one per entity, input fields only."""
from .constants import TEST_DEFAULTS

DEFAULTS = {
    "FUNDER_NAME": "Diocesan Fund",
    "PROGRAM_NAME": "Housing First",
    "GRANT_CODE": "G-1",
    "CLIENT_NAME": "Ada Vance",
    "COUNTY_CODE": "COOK",
    "GRANT_PERIOD_START": "2026-09-01T00:00:00Z",
    "GRANT_PERIOD_END": "2027-08-31T23:59:59Z",
    "AUTHORIZATION_PERIOD_START": "2026-09-01T00:00:00Z",
    "AUTHORIZATION_PERIOD_END": "2026-10-01T00:00:00Z",
    "ASSESSMENT_DATE": "2026-09-01T00:00:00Z",
    "SERVICE_DATE": "2026-09-02T01:00:00Z",
    "DONATION_DATE": "2026-09-02T00:00:00Z",
}


def create_funder_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["FUNDER_NAME"],
        "funder_type": "DIOCESAN",
        "allow_faith_based_activity": True,
        "requires_time_and_effort_documentation": False,
        "max_admin_rate_pct": TEST_DEFAULTS["MAX_ADMIN_RATE_PCT"],
        "fiscal_year_start_month": 1,
    }
    payload.update(overrides)
    return payload


def create_program_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["PROGRAM_NAME"],
        "service_domain": "HOUSING",
        "faith_based_activity_offered": False,
        "nondiscrimination_attested": True,
        "capacity_slots": TEST_DEFAULTS["CAPACITY_SLOTS"],
        "match_eligible": True,
    }
    payload.update(overrides)
    return payload


def create_grant_payload(funder_id, program_id, **overrides) -> dict:
    payload = {
        "funder_id": funder_id,
        "program_id": program_id,
        "grant_code": DEFAULTS["GRANT_CODE"],
        "total_award_cents": TEST_DEFAULTS["TOTAL_AWARD_CENTS"],
        "admin_rate_pct": TEST_DEFAULTS["ADMIN_RATE_PCT"],
        "allocation_rank": 1,
        "max_in_kind_rate_cents": TEST_DEFAULTS["MAX_IN_KIND_RATE_CENTS"],
        "matching_requirement_pct": 0.0,
        "cost_allocation_basis": "DIRECT_ONLY",
        "restricted_purpose": "HOUSING_ASSISTANCE",
        "period_start": DEFAULTS["GRANT_PERIOD_START"],
        "period_end": DEFAULTS["GRANT_PERIOD_END"],
    }
    payload.update(overrides)
    return payload


def create_client_payload(**overrides) -> dict:
    payload = {
        "full_name": DEFAULTS["CLIENT_NAME"],
        "date_of_birth": "1990-01-01",
        "household_size": TEST_DEFAULTS["HOUSEHOLD_SIZE"],
        "immigration_status": "CITIZEN",
        "county_code": DEFAULTS["COUNTY_CODE"],
    }
    payload.update(overrides)
    return payload


def create_intake_assessment_payload(**overrides) -> dict:
    payload = {
        "assessment_date": DEFAULTS["ASSESSMENT_DATE"],
        "presenting_needs": ["rent arrears"],
        "requested_domains": ["HOUSING"],
    }
    payload.update(overrides)
    return payload


def create_eligibility_screen_payload(program_id, grant_id, **overrides) -> dict:
    payload = {
        "program_id": program_id,
        "grant_id": grant_id,
        "verified_income_cents": TEST_DEFAULTS["VERIFIED_INCOME_CENTS"],
        "household_size_at_screen": TEST_DEFAULTS["HOUSEHOLD_SIZE"],
    }
    payload.update(overrides)
    return payload


def create_enrollment_payload(client_id, program_id, grant_id, **overrides) -> dict:
    payload = {
        "client_id": client_id,
        "program_id": program_id,
        "grant_id": grant_id,
    }
    payload.update(overrides)
    return payload


def create_service_authorization_payload(
    enrollment_id, grant_id, expected_enrollment_version, **overrides
) -> dict:
    payload = {
        "enrollment_id": enrollment_id,
        "grant_id": grant_id,
        "service_code": "HOUSING_RENT_ASSIST",
        "authorized_units": TEST_DEFAULTS["AUTHORIZED_UNITS"],
        "unit_rate_cents": TEST_DEFAULTS["UNIT_RATE_CENTS"],
        "period_start": DEFAULTS["AUTHORIZATION_PERIOD_START"],
        "period_end": DEFAULTS["AUTHORIZATION_PERIOD_END"],
        "expected_enrollment_version": expected_enrollment_version,
    }
    payload.update(overrides)
    return payload


def create_service_delivery_payload(
    service_authorization_id,
    grant_id,
    client_id,
    expected_service_authorization_version,
    **overrides,
) -> dict:
    payload = {
        "service_authorization_id": service_authorization_id,
        "grant_id": grant_id,
        "client_id": client_id,
        "service_date": DEFAULTS["SERVICE_DATE"],
        "units_delivered": 1,
        "unit_rate_cents": TEST_DEFAULTS["UNIT_RATE_CENTS"],
        "expected_service_authorization_version": expected_service_authorization_version,
    }
    payload.update(overrides)
    return payload


def create_in_kind_donation_payload(grant_id, **overrides) -> dict:
    payload = {
        "grant_id": grant_id,
        "donor_type": "PARISH",
        "donor_reference": "PARISH-01",
        "donation_date": DEFAULTS["DONATION_DATE"],
        "hours": 5,
        "valuation_method": "APPRAISAL",
        "rate_cents": TEST_DEFAULTS["MAX_IN_KIND_RATE_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_outcome_report_payload(grant_id, **overrides) -> dict:
    payload = {
        "grant_id": grant_id,
        "measure_code": "HOUSING_PLACEMENTS",
        "reporting_period_start": "2026-09-01T00:00:00Z",
        "reporting_period_end": "2026-09-30T00:00:00Z",
        "numerator": 4,
        "denominator": 10,
    }
    payload.update(overrides)
    return payload
